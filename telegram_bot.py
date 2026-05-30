# -*- coding: utf-8 -*-
"""
Bot do Telegram que atualiza a mesma planilha do aplicativo.
Use @BotFather no Telegram para criar o bot e obter o token.
Configure TELEGRAM_BOT_TOKEN no .env e rode: python telegram_bot.py
"""
from __future__ import annotations

import atexit
import argparse
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import requests

from src.bot_processor import (
    apply_parse_result,
    build_preview,
    get_default_workbook,
    process_command,
    sale_id_from_parse_result,
)
from src.parser import parse_message, _parse_pt_date, _is_service_delivery_finalized, should_replace_pending_preview, _extract_total_value, _currency_candidates, enrich_with_last_sale_context, recalculate_payments_for_total, parse_money_value, _extract_customer
from src.transcription import TranscriptionError, transcribe_audio

# Carregar .env
def _load_dotenv() -> None:
    for base in (Path(__file__).resolve().parent, Path.cwd()):
        env_file = base / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip()
                    if v.startswith('"') and v.endswith('"') or v.startswith("'") and v.endswith("'"):
                        v = v[1:-1]
                    # Se o arquivo tiver chaves repetidas, queremos que a última
                    # prevaleça (evita problema de TELEGRAM_BOT_TOKEN ficar vazio).
                    os.environ[k] = v
            break


_load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _acquire_single_instance_lock() -> None:
    """Evita rodar duas instâncias do bot ao mesmo tempo (causa prévias/erros duplicados)."""
    lock_path = Path(__file__).resolve().parent / ".telegram_bot.lock"
    try:
        # Criação exclusiva: falha se já existir
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        os.close(fd)
    except FileExistsError:
        print("[Telegram] Ja existe uma instancia do bot em execucao. Feche a outra janela e tente novamente.")
        raise SystemExit(2)

    def _cleanup() -> None:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_cleanup)

HELP_TEXT = """Olá! Eu sou o assistente da sua planilha.

Pode me mandar *áudio* ou *texto*. Eu entendo a mensagem, mostro uma prévia e só salvo quando você confirmar.

*Comandos rápidos*
• *Resumo* - mostra os totais da planilha
• *Prévia* - mostra vendas, pendências e entregas
• *Status* - mostra a situação financeira

*Exemplos do que você pode falar*
• Vendi uma placa para o cliente 004 por 1547,27 e ele pagou tudo.
• Cliente 004 comprou um banner de 3000, deu 500 de entrada e o restante dia 30.
• ID VENDA 1001 pagou 1547,27 hoje.
• Gastei 200 de material para ID VENDA 1001.

Se a prévia estiver correta, responda *SIM* ou *OK*.
Para corrigir, envie: Valor: 1547,27, Cliente: 004 ou Produto: Fachada."""

# Teclado de menu (botões que aparecem abaixo do campo de digitação)
MAIN_MENU_KEYBOARD = {
    "keyboard": [
        ["Prévia", "Resumo", "Status"],
        ["Ajuda", "Reiniciar"],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}

def _maybe_build_text_image_png(text: str) -> str | None:
    """
    Gera uma imagem (PNG) com o texto para facilitar visualização no Telegram.
    Retorna o caminho do arquivo temporário, ou None se não for possível.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:
        return None

    raw = (text or "").strip()
    if not raw:
        return None

    # Normaliza bullets e remove markdown básico para ficar legível na imagem
    lines_in = [
        ln.replace("*", "").replace("📄", "").replace("📋", "").rstrip()
        for ln in raw.splitlines()
    ]

    max_width = 980
    padding = 28
    bg = (2, 6, 23)          # #020617
    card = (15, 23, 42)      # #0f172a
    ink = (226, 232, 240)    # #e2e8f0
    soft = (148, 163, 184)   # #94a3b8

    font = ImageFont.load_default()

    def wrap_line(s: str) -> list[str]:
        s = (s or "").strip()
        if not s:
            return [""]
        words = s.split()
        out: list[str] = []
        cur = ""
        for w in words:
            nxt = (cur + " " + w).strip()
            if ImageDraw.Draw(Image.new("RGB", (10, 10))).textlength(nxt, font=font) <= (max_width - 2 * padding):
                cur = nxt
            else:
                if cur:
                    out.append(cur)
                cur = w
        out.append(cur)
        return out

    wrapped: list[str] = []
    for ln in lines_in:
        for wln in wrap_line(ln):
            wrapped.append(wln)

    # Calcula altura
    line_h = int(font.getbbox("Ag")[3] - font.getbbox("Ag")[1]) + 8
    title = "Resumo da planilha"
    height = padding + 40 + 18 + (len(wrapped) * line_h) + padding

    img = Image.new("RGB", (max_width, max(240, height)), bg)
    draw = ImageDraw.Draw(img)

    # Card
    card_x0, card_y0 = padding, padding
    card_x1, card_y1 = max_width - padding, img.height - padding
    draw.rounded_rectangle((card_x0, card_y0, card_x1, card_y1), radius=18, fill=card)

    # Título
    draw.text((card_x0 + 18, card_y0 + 14), title, fill=ink, font=font)
    y = card_y0 + 44
    for ln in wrapped:
        color = soft if (not ln.strip() or ln.strip().lower().startswith("nenhuma")) else ink
        draw.text((card_x0 + 18, y), ln, fill=color, font=font)
        y += line_h

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.close()
    img.save(tmp.name, format="PNG", optimize=True)
    return tmp.name


def _maybe_build_status_table_image(workbook_path: str) -> str | None:
    """
    Gera imagem estilo "TOTAL DOS LUCROS MENSAIS E ANUAIS" com valores dinâmicos.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
        from src.excel_store import SpreadsheetService, SHEET_SALES, SHEET_MATERIAL, SHEET_FIXED, DATA_START_ROW
    except Exception:
        return None

    try:
        svc = SpreadsheetService(workbook_path)
        wb = svc._open_workbook(data_only=True)
        try:
            ws_sales = wb[svc._resolve_sheet_name(wb, SHEET_SALES)]
            ws_mat = wb[svc._resolve_sheet_name(wb, SHEET_MATERIAL)]
            ws_fix = wb[svc._resolve_sheet_name(wb, SHEET_FIXED)]

            sales_cols = svc._sales_columns(ws_sales)
            col_id = sales_cols.get("id venda")
            col_paid = sales_cols.get("total de vendas (pago)")
            col_pending = sales_cols.get("valor (pendente)")

            total_paid = 0.0
            total_pending = 0.0
            for row in range(DATA_START_ROW, min(ws_sales.max_row + 1, svc.MAX_DATA_ROW)):
                if col_id and ws_sales[f"{col_id}{row}"].value in (None, ""):
                    continue
                if col_paid:
                    total_paid += svc._to_float(ws_sales[f"{col_paid}{row}"].value)
                if col_pending:
                    total_pending += svc._to_float(ws_sales[f"{col_pending}{row}"].value)

            mat_cols = svc._material_columns(ws_mat)
            col_mat_desc = mat_cols.get("descricao")
            col_mat_val = mat_cols.get("valor")
            total_mat = 0.0
            for row in range(DATA_START_ROW, min(ws_mat.max_row + 1, svc.MAX_DATA_ROW)):
                if col_mat_desc and ws_mat[f"{col_mat_desc}{row}"].value in (None, ""):
                    continue
                if col_mat_val:
                    total_mat += svc._to_float(ws_mat[f"{col_mat_val}{row}"].value)

            total_fix = 0.0
            for row in range(DATA_START_ROW, min(ws_fix.max_row + 1, svc.MAX_DATA_ROW)):
                total_fix += svc._to_float(ws_fix[f"D{row}"].value)
        finally:
            wb.close()
    except Exception:
        return None

    total_sales = round(total_paid + total_pending, 2)
    lucro = round(total_sales - total_mat - total_fix, 2)

    def _brl(v: float) -> str:
        txt = f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {txt}"

    def _load_font(size: int, bold: bool = False):
        candidates = (
            [
                r"C:\Windows\Fonts\segoeuib.ttf",
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\calibrib.ttf",
            ]
            if bold
            else [
                r"C:\Windows\Fonts\segoeui.ttf",
                r"C:\Windows\Fonts\arial.ttf",
                r"C:\Windows\Fonts\calibri.ttf",
            ]
        )
        for fp in candidates:
            try:
                return ImageFont.truetype(fp, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    font_title = _load_font(26, bold=True)
    font_meta = _load_font(17, bold=False)
    font_label = _load_font(17, bold=False)
    font_value = _load_font(24, bold=True)

    # Grade 2x3: mais legível no Telegram do que 6 colunas em uma única faixa
    kpi = [
        ("Total de vendas (geral)", _brl(total_sales), False),
        ("Vendas pagas", _brl(total_paid), False),
        ("Valor pendente", _brl(total_pending), False),
        ("Compras matéria-prima", _brl(total_mat), False),
        ("Gastos fixos", _brl(total_fix), False),
        ("Lucro estimado", _brl(lucro), True),
    ]

    outer_bg = (241, 245, 249)
    card_bg = (255, 255, 255)
    title_bar = (12, 74, 110)
    border_soft = (207, 221, 232)
    label_muted = (75, 85, 99)
    ink = (17, 24, 39)
    green_profit = (5, 122, 85)
    red_loss = (185, 28, 28)
    cell_zebra = (249, 252, 255)
    cell_lucro_bg = (236, 253, 245)

    pad = 22
    card_w = 900
    title_h = 54
    meta_h = 30
    gap = 14
    cols = 2
    rows = 3
    inner_w = card_w - pad * 2
    cell_w = (inner_w - gap) // 2
    cell_h = 96

    card_h = pad + title_h + 8 + meta_h + 12 + rows * cell_h + (rows - 1) * gap + pad
    img_w = card_w + pad * 2
    img_h = card_h + pad * 2

    img = Image.new("RGB", (img_w, img_h), outer_bg)
    draw = ImageDraw.Draw(img)

    cx0 = pad
    cy0 = pad
    cx1 = cx0 + card_w
    cy1 = cy0 + card_h
    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=18, fill=card_bg, outline=border_soft, width=1)

    bar_y1 = cy0 + title_h + 6
    draw.rounded_rectangle((cx0, cy0, cx1, bar_y1), radius=18, fill=title_bar)
    draw.rectangle((cx0, cy0 + 16, cx1, bar_y1), fill=title_bar)

    title = "TOTAL DOS LUCROS MENSAIS E ANUAIS"
    tw = draw.textlength(title, font=font_title)
    draw.text((cx0 + (card_w - tw) / 2, cy0 + 14), title, fill=(255, 255, 255), font=font_title)
    draw.text(
        (cx0 + pad, bar_y1 + 6),
        "Resumo calculado a partir da planilha • atualizado ao vivo",
        fill=label_muted,
        font=font_meta,
    )

    y0 = bar_y1 + meta_h + 12
    x0 = cx0 + pad

    measure = ImageDraw.Draw(Image.new("RGB", (20, 20)))

    def _vlen(s: str, fnt) -> int:
        try:
            return int(measure.textlength(s, font=fnt))
        except Exception:
            return len(s) * 10

    for i, (lbl, val, is_lucro) in enumerate(kpi):
        r, c = divmod(i, cols)
        x = x0 + c * (cell_w + gap)
        y = y0 + r * (cell_h + gap)
        fill = cell_lucro_bg if is_lucro else (cell_zebra if (r + c) % 2 == 0 else (255, 255, 255))
        draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=12, fill=fill, outline=border_soft, width=1)
        if is_lucro:
            border_lucro = green_profit if lucro >= 0 else red_loss
            draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=12, outline=border_lucro, width=2)

        draw.text((x + 16, y + 14), lbl, fill=label_muted, font=font_label)
        val_color = green_profit if is_lucro and lucro >= 0 else (red_loss if is_lucro and lucro < 0 else ink)
        vw = _vlen(val, font_value)
        draw.text((x + cell_w - 16 - vw, y + 44), val, fill=val_color, font=font_value)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.close()
    img.save(tmp.name, format="PNG", optimize=True)
    return tmp.name


def _maybe_build_sales_snippet_image(
    workbook_path: str,
    *,
    sale_id: str | None = None,
    limit: int = 7,
    title_main: str = "TOTAL DE VENDAS - Visão atual",
    meta_line: str | None = None,
) -> str | None:
    """
    Gera um "mini-dashboard" da aba de Vendas (clientes, pagos/pendentes, datas).
    Visual alinhado ao card do Status (faixa azul + card branco + tipografia).
    Usado no botão Prévia — não confundir com o resumo financeiro (lucro) do Status.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
        from src.excel_store import SpreadsheetService, SHEET_SALES, DATA_START_ROW
    except Exception:
        return None

    try:
        svc = SpreadsheetService(workbook_path)
        wb = svc._open_workbook(data_only=True)
        try:
            ws = wb[svc._resolve_sheet_name(wb, SHEET_SALES)]
            cols = svc._sales_columns(ws)
            # Ordem e labels fixos para ficar consistente/legível.
            display_cols = [
                ("data de venda", "Data da venda"),
                ("data de entrega", "Data entrega"),
                ("id cliente", "ID Cliente"),
                ("id produto", "Produto"),
                ("total de vendas (pago)", "Pago"),
                ("valor (pendente)", "Pendente"),
                ("id venda", "ID VENDA"),
                ("status de valor", "Status"),
            ]
            col_pairs = [(cols.get(key), label, key) for key, label in display_cols if cols.get(key)]
            col_letters = [c for c, _label, _key in col_pairs]
            if not col_letters:
                return None

            # Determina linhas de dados existentes (baseado em ID VENDA).
            id_col = cols.get("id venda")
            data_rows: list[int] = []
            if id_col:
                for r in range(DATA_START_ROW, min(ws.max_row + 1, svc.MAX_DATA_ROW)):
                    if ws[f"{id_col}{r}"].value not in (None, ""):
                        data_rows.append(r)
            if not data_rows:
                return None

            # Linha para destacar (se informar sale_id); senão destaca a última.
            highlight_row = data_rows[-1]
            if sale_id and id_col:
                for r in reversed(data_rows[-250:]):
                    if str(ws[f"{id_col}{r}"].value or "").strip() == str(sale_id).strip():
                        highlight_row = r
                        break

            # Pega as últimas N linhas e garante que a destacada esteja incluída.
            last_rows = data_rows[-max(limit, 3):]
            if highlight_row not in last_rows:
                last_rows = (last_rows + [highlight_row])[-max(limit, 3):]

            # Cabeçalho: normalmente fica na linha anterior ao início dos dados.
            headers = [label for _c, label, _key in col_pairs]

            def _cell_txt(c: str, key: str, r: int) -> str:
                v = ws[f"{c}{r}"].value
                if v in (None, ""):
                    return ""
                if key in ("total de vendas (pago)", "valor (pendente)"):
                    num = svc._to_float(v)
                    txt = f"{float(num):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    return f"R$ {txt}"
                if hasattr(v, "strftime"):
                    try:
                        return v.strftime("%d/%m/%Y")
                    except Exception:
                        pass
                return str(v)

            rows_txt = [[_cell_txt(c, key, r) for c, _label, key in col_pairs] for r in last_rows]
        finally:
            wb.close()
    except Exception:
        return None

    # Renderização visual premium
    def _load_font(size: int, bold: bool = False):
        candidates = []
        if bold:
            candidates = [
                "C:\\Windows\\Fonts\\segoeuib.ttf",
                "C:\\Windows\\Fonts\\arialbd.ttf",
                "C:\\Windows\\Fonts\\calibrib.ttf",
            ]
        else:
            candidates = [
                "C:\\Windows\\Fonts\\segoeui.ttf",
                "C:\\Windows\\Fonts\\arial.ttf",
                "C:\\Windows\\Fonts\\calibri.ttf",
            ]
        for fp in candidates:
            try:
                return ImageFont.truetype(fp, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    font_body = _load_font(24, bold=False)
    font_header = _load_font(22, bold=True)
    font_title = _load_font(30, bold=True)
    font_meta = _load_font(20, bold=False)

    pad = 22
    card_pad = 18
    cell_pad_x = 12
    cell_pad_y = 10
    outer_bg = (241, 245, 249)
    card_bg = (255, 255, 255)
    title_bar = (12, 74, 110)
    header_bg = (230, 243, 251)
    header_ink = (10, 45, 70)
    grid = (207, 221, 232)
    ink = (20, 23, 28)
    muted = (75, 85, 99)
    red_pending = (185, 28, 28)
    zebra = (249, 252, 255)
    highlight_bg = (255, 246, 214)
    status_pago_bg = (220, 252, 231)
    status_pend_bg = (254, 249, 195)

    # Medição de texto
    measure_draw = ImageDraw.Draw(Image.new("RGB", (20, 20)))

    def tlen(s: str, font_obj) -> int:
        try:
            return int(measure_draw.textlength(s, font=font_obj))
        except Exception:
            return max(1, len(s)) * 8

    def _truncate(text: str, max_width: int, font_obj) -> str:
        text = str(text or "")
        if tlen(text, font_obj) <= max_width:
            return text
        suffix = "..."
        while text and tlen(text + suffix, font_obj) > max_width:
            text = text[:-1]
        return (text + suffix) if text else suffix

    col_widths: list[int] = []
    for ci in range(len(headers)):
        maxw = tlen(headers[ci], font_header)
        for rr in rows_txt:
            maxw = max(maxw, tlen(rr[ci], font_body))
        cap = 360 if ci == 3 else 230
        floor = 115 if ci in (0, 1, 6, 7) else 140
        col_widths.append(max(floor, min(cap, maxw + cell_pad_x * 2)))

    row_h = (font_body.getbbox("Ag")[3] - font_body.getbbox("Ag")[1]) + (cell_pad_y * 2) + 2
    title_h = 58
    meta_h = 36
    table_w = sum(col_widths)
    table_h = row_h * (1 + len(rows_txt))
    card_w = table_w + card_pad * 2
    card_h = title_h + meta_h + table_h + card_pad * 2 + 12
    img_w = card_w + pad * 2
    img_h = card_h + pad * 2

    img = Image.new("RGB", (img_w, img_h), outer_bg)
    draw = ImageDraw.Draw(img)

    # Card principal
    card_x0 = pad
    card_y0 = pad
    card_x1 = img_w - pad
    card_y1 = img_h - pad
    draw.rounded_rectangle((card_x0, card_y0, card_x1, card_y1), radius=18, fill=card_bg, outline=grid, width=1)

    # Barra de título
    bar_y1 = card_y0 + title_h + 8
    draw.rounded_rectangle((card_x0, card_y0, card_x1, bar_y1), radius=18, fill=title_bar)
    # Corrige cantos inferiores da barra para ficar reta
    draw.rectangle((card_x0, card_y0 + 18, card_x1, bar_y1), fill=title_bar)

    tw_title = draw.textlength(title_main, font=font_title)
    draw.text(
        (card_x0 + (card_w - tw_title) / 2, card_y0 + 14),
        title_main,
        fill=(255, 255, 255),
        font=font_title,
    )

    # Meta (Prévia: foco em pendências/entregas; fallback: últimas linhas)
    meta_text = meta_line or (
        f"Mostrando {len(rows_txt)} linha(s) mais recentes • Atualizado ao vivo"
    )
    tw_meta = draw.textlength(meta_text, font=font_meta)
    draw.text(
        (card_x0 + (card_w - tw_meta) / 2, bar_y1 + 8),
        meta_text,
        fill=muted,
        font=font_meta,
    )

    x0 = card_x0 + card_pad
    y0 = bar_y1 + meta_h + 8

    def _row_has_pending(rvals: list[str]) -> bool:
        """Amarelo na linha inteira só quando há pendência real (valor ou status)."""
        try:
            pi = headers.index("Pendente")
            pt = rvals[pi]
            if pt.startswith("R$"):
                raw = pt.replace("R$", "").strip().replace(".", "").replace(",", ".")
                if float(raw) > 0.01:
                    return True
        except Exception:
            pass
        try:
            si = headers.index("Status")
            if "pendente" in (rvals[si] or "").strip().lower():
                return True
        except Exception:
            pass
        return False

    # Header
    x = x0
    for ci, h in enumerate(headers):
        w = col_widths[ci]
        draw.rectangle((x, y0, x + w, y0 + row_h), fill=header_bg, outline=grid, width=1)
        draw.text((x + cell_pad_x, y0 + cell_pad_y), _truncate(h, w - 2 * cell_pad_x, font_header), fill=header_ink, font=font_header)
        x += w

    # Rows (fundo amarelo só com pendência; pago + R$ 0 pendente = zebra branco como as demais)
    for ri, rvals in enumerate(rows_txt, start=1):
        y = y0 + (row_h * ri)
        x = x0
        pending_row = _row_has_pending(rvals)
        for ci, txt in enumerate(rvals):
            w = col_widths[ci]
            is_money_col = headers[ci] in ("Pago", "Pendente")
            base_fill = highlight_bg if pending_row else (zebra if (ri % 2 == 0) else (255, 255, 255))
            if headers[ci] == "Status":
                sl = (txt or "").strip().lower()
                if sl == "pago" or (sl.startswith("pago") and "pendente" not in sl):
                    cell_fill = status_pago_bg
                elif "pendente" in sl:
                    cell_fill = status_pend_bg
                else:
                    cell_fill = base_fill
            else:
                cell_fill = base_fill
            draw.rectangle(
                (x, y, x + w, y + row_h),
                fill=cell_fill,
                outline=grid,
                width=1,
            )
            text_value = _truncate(txt, w - 2 * cell_pad_x, font_body)
            cell_ink = ink
            if headers[ci] == "Pendente" and text_value.startswith("R$"):
                try:
                    raw = (
                        text_value.replace("R$", "")
                        .strip()
                        .replace(".", "")
                        .replace(",", ".")
                    )
                    if float(raw) > 0.01:
                        cell_ink = red_pending
                except Exception:
                    pass
            if is_money_col:
                tw = tlen(text_value, font_body)
                tx = x + w - cell_pad_x - tw
            else:
                tx = x + cell_pad_x
            draw.text((tx, y + cell_pad_y), text_value, fill=cell_ink, font=font_body)
            x += w

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.close()
    img.save(tmp.name, format="PNG", optimize=True)
    return tmp.name


def send_photo(chat_id: int | str, image_path: str, caption: str = "") -> bool:
    """Envia uma foto para o chat (sendPhoto)."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    try:
        with open(image_path, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": str(chat_id)}
            if caption:
                data["caption"] = caption[:1024]
            r = requests.post(f"{BASE_URL}/sendPhoto", data=data, files=files, timeout=30)
            return r.status_code == 200
    except Exception as e:
        print(f"[Telegram] Erro ao enviar foto: {e}")
        return False


def send_message(
    chat_id: int | str,
    text: str,
    parse_mode: str | None = None,
    reply_markup: dict | None = None,
) -> bool:
    """Envia mensagem de texto para o chat."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    text = (text or "")[:4096]
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=15)
        return r.status_code == 200
    except Exception as e:
        print(f"[Telegram] Erro ao enviar: {e}")
        return False


def download_telegram_voice(file_id: str) -> str:
    """Baixa o áudio de uma mensagem de voz do Telegram; retorna caminho do arquivo temporário (.ogg)."""
    r = requests.get(f"{BASE_URL}/getFile", params={"file_id": file_id}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError("getFile falhou")
    file_path = data.get("result", {}).get("file_path")
    if not file_path:
        raise RuntimeError("file_path nao retornado")
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    audio_r = requests.get(url, timeout=60)
    audio_r.raise_for_status()
    suffix = ".ogg" if "ogg" in (file_path or "").lower() else ".oga"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(audio_r.content)
    tmp.close()
    return tmp.name


def get_updates(offset: int | None = None) -> list[dict]:
    """Long polling: busca novas mensagens (timeout 30s)."""
    if not TELEGRAM_BOT_TOKEN:
        return []
    params = {"timeout": 30}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=35)
        if r.status_code != 200:
            return []
        data = r.json()
        if not data.get("ok"):
            return []
        return data.get("result", [])
    except Exception as e:
        print(f"[Telegram] Erro getUpdates: {e}")
        return []


def run_polling() -> None:
    """Loop principal: processa mensagens e responde."""
    _acquire_single_instance_lock()
    if not TELEGRAM_BOT_TOKEN:
        print("[Telegram] Configure TELEGRAM_BOT_TOKEN no .env (token do @BotFather).")
        return

    print("[Telegram] Bot iniciado. Aguardando mensagens... (Ctrl+C para parar)")
    next_offset = None
    seen_update_ids: set[int] = set()
    seen_message_keys: set[tuple[int | str, int]] = set()
    # Prévia pendente por chat: só salva na planilha após o usuário confirmar (SIM)
    pending_preview: dict = {}
    pending_delivery: dict[int | str, dict] = {}
    # Cache simples por chat: se o usuário enviar texto sem "ID Cliente"
    # (ex.: ele escreve a transcrição mas não repete o id), usamos o último
    # ID Cliente extraído com sucesso para destravar a prévia.
    last_customer_by_chat: dict[int | str, str] = {}
    last_sale_id_by_chat: dict[int | str, str] = {}
    last_reminder_check = 0.0

    while True:
        updates = get_updates(offset=next_offset)
        for update in updates:
            uid = update.get("update_id", 0)
            if isinstance(uid, int) and uid in seen_update_ids:
                continue
            if isinstance(uid, int):
                seen_update_ids.add(uid)
                # Evitar crescimento infinito (mantém só os últimos ~2000)
                if len(seen_update_ids) > 2000:
                    for old in sorted(seen_update_ids)[:500]:
                        seen_update_ids.discard(old)
            next_offset = uid + 1
            msg = update.get("message") or update.get("edited_message")
            if not msg:
                continue
            chat_id = msg.get("chat", {}).get("id")
            message_id = msg.get("message_id")
            if chat_id and isinstance(message_id, int):
                key = (chat_id, message_id)
                if key in seen_message_keys:
                    continue
                seen_message_keys.add(key)
                if len(seen_message_keys) > 4000:
                    # Remove a parte mais antiga (ordenação estável pelo tuple)
                    for old in sorted(seen_message_keys)[:1000]:
                        seen_message_keys.discard(old)
            text = (msg.get("text") or "").strip()
            from_voice = False

            # Áudio: baixar, transcrever e usar o texto como se fosse mensagem digitada
            if not text and msg.get("voice"):
                voice = msg["voice"]
                file_id = voice.get("file_id")
                if file_id:
                    try:
                        audio_path = download_telegram_voice(file_id)
                        try:
                            whisper_model = os.getenv("WHISPER_MODEL", "small")
                            text = transcribe_audio(audio_path, model_size=whisper_model)
                            from_voice = True
                            send_message(
                                chat_id,
                                "🎤 *Áudio entendido!*\n\n"
                                f"{text}\n\n"
                                "Agora vou montar a prévia do lançamento. Confira os campos e responda *SIM* para salvar, "
                                "ou envie a correção por texto.",
                                parse_mode="Markdown",
                                reply_markup=MAIN_MENU_KEYBOARD,
                            )
                        finally:
                            try:
                                Path(audio_path).unlink(missing_ok=True)
                            except Exception:
                                pass
                    except TranscriptionError as e:
                        send_message(chat_id, f"Não consegui transcrever o áudio: {e}")
                        continue
                    except Exception as e:
                        send_message(chat_id, f"Erro ao processar o áudio: {e}")
                        print(f"[Telegram] Erro áudio: {e}")
                        continue

            if not chat_id:
                continue

            if not text:
                send_message(
                    chat_id,
                    "Envie um texto (ex.: vendi placa para o João por 2000), um áudio, ou toque em Resumo.",
                    reply_markup=MAIN_MENU_KEYBOARD,
                )
                continue

            # Comandos especiais do Telegram: boas-vindas e ajuda (limpam prévia pendente) + menu
            if text in ("/start", "/help") or text.strip().lower() in ("ajuda", "start"):
                pending_preview.pop(chat_id, None)
                send_message(
                    chat_id,
                    HELP_TEXT,
                    parse_mode="Markdown",
                    reply_markup=MAIN_MENU_KEYBOARD,
                )
                continue

            # Reiniciar: cancela qualquer prévia pendente e volta ao zero
            if "reiniciar" in text.strip().lower() and len(text.strip()) <= 15:
                pending_preview.pop(chat_id, None)
                pending_delivery.pop(chat_id, None)
                send_message(
                    chat_id,
                    "Reiniciado. Pode enviar um novo comando, áudio ou tocar em Resumo.",
                    reply_markup=MAIN_MENU_KEYBOARD,
                )
                continue

            user = msg.get("from", {})
            username = user.get("username") or user.get("first_name") or "?"
            print(f"[Telegram] Mensagem de {username} ({chat_id}): {text[:60]!r}")

            try:
                # Finalizar serviço
                if text.strip().lower().startswith("finalizar") and "id venda" in text.strip().lower():
                    import re
                    from src.excel_store import SpreadsheetService
                    sale_digits = re.findall(r"\d+", text)
                    if sale_digits:
                        sale_id = sale_digits[-1].zfill(3) if len(sale_digits[-1]) <= 3 else sale_digits[-1]
                        workbook_path = os.getenv("WORKBOOK_PATH", "").strip()
                        if not workbook_path:
                            from src.workbook_paths import default_workbook_path
                            workbook_path = default_workbook_path([Path.cwd(), Path.cwd().parent])
                        svc = SpreadsheetService(workbook_path)
                        ok = svc.finalize_service(sale_id)
                        send_message(chat_id, "Finalizado e marcado na planilha." if ok else "Não achei esse ID VENDA na planilha.")
                        continue

                # Confirmação da prévia: salvar na planilha
                confirm_words = ("sim", "confirmar", "ok", "confirmo", "pode salvar", "salvar")
                if text.strip().lower() in confirm_words and chat_id in pending_preview:
                    pending = pending_preview.pop(chat_id)
                    # Fluxo em lote: múltiplos updates (ex.: "cliente id 003 e id 002 pagou")
                    batch_results = pending.get("batch_parse_results")
                    if batch_results:
                        applied = 0
                        replies: list[str] = []
                        for pr in batch_results:
                            try:
                                reply_item = apply_parse_result(
                                    pr,
                                    origin=pending.get("origin", "telegram"),
                                    original_text=pending.get("original_text", ""),
                                    chat_id=str(chat_id),
                                )
                                replies.append(reply_item)
                                applied += 1
                            except Exception as e:
                                replies.append(f"Falha em um item do lote: {e}")
                        msg_out = f"Atualização em lote concluída: {applied}/{len(batch_results)} item(ns).\n\n" + "\n".join(replies[:6])
                        send_message(chat_id, msg_out)
                        continue
                    parse_result = pending["parse_result"]
                    original_text = pending.get("original_text", "")
                    origin = pending.get("origin", "telegram")
                    cmd = parse_result.command
                    # Se ainda faltar ID Cliente, não salva: pede o ID e recoloca a prévia pendente.
                    # Para atualização de status e atualização de entrega, nao exigimos cmd.customer.
                    if parse_result.intent not in ("status_update", "delivery_update", "delivery_finalize", "payment_update"):
                        if "ID Cliente" in parse_result.missing_fields or not (cmd.customer or "").strip():
                            pending_preview[chat_id] = pending
                            send_message(
                                chat_id,
                                "Faltou o *ID Cliente* para salvar.\nEnvie por exemplo: `cliente id 004`.",
                                parse_mode="Markdown",
                            )
                            continue
                    # Se ainda faltar ID VENDA, não salva: pede o ID e recoloca a prévia pendente.
                    if "ID VENDA" in parse_result.missing_fields:
                        pending_preview[chat_id] = pending
                        send_message(
                            chat_id,
                            "Faltou o *ID VENDA* para salvar.\nEnvie por exemplo: `id venda 002`.",
                            parse_mode="Markdown",
                        )
                        continue
                    # Se não informou data de entrega e for um fluxo de venda (tem valor/parcelas),
                    # e não houver pendência de pagamento, perguntar a data.
                    pending_amount = 0.0
                    for p in cmd.payments:
                        if (p.status or "").strip().lower() != "pago":
                            pending_amount += float(p.value or 0.0)
                    needs_delivery_date = (
                        parse_result.intent not in ("status_update", "payment_update", "delivery_update", "delivery_finalize")
                        and cmd.service_due_date is None
                        and (cmd.total_value or 0.0) > 0.01
                        and pending_amount <= 0.01
                    )
                    if needs_delivery_date:
                        pending_delivery[chat_id] = pending
                        send_message(
                            chat_id,
                            "Qual a *Data de Entrega* deste serviço? (ex.: 20/03, 20/03/2026 ou *hoje*)\n"
                            "Se já foi entregue, pode responder por exemplo: *foi finalizado hoje*.",
                            parse_mode="Markdown",
                        )
                        continue

                    reply = apply_parse_result(
                        parse_result,
                        origin=origin,
                        original_text=original_text,
                        chat_id=str(chat_id),
                    )
                    remembered = sale_id_from_parse_result(parse_result)
                    if remembered:
                        last_sale_id_by_chat[chat_id] = remembered
                    send_message(chat_id, reply, parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)
                    # Enviar imagem atualizada da aba de vendas para facilitar visualização.
                    workbook_path = os.getenv("WORKBOOK_PATH", "").strip()
                    if not workbook_path:
                        from src.workbook_paths import default_workbook_path
                        workbook_path = default_workbook_path([Path.cwd(), Path.cwd().parent])
                    if workbook_path:
                        img_path = _maybe_build_sales_snippet_image(
                            workbook_path,
                            sale_id=getattr(parse_result.status_update_command, "sale_id", None)
                            if getattr(parse_result, "intent", "") == "status_update"
                            else getattr(parse_result.command, "sale_id", None),
                        )
                        if img_path:
                            try:
                                send_photo(chat_id, img_path)
                            finally:
                                try:
                                    Path(img_path).unlink(missing_ok=True)
                                except Exception:
                                    pass
                    print(f"[Telegram] Planilha atualizada para {chat_id}")
                    continue

                # Cancelar prévia
                cancel_words = ("não", "nao", "cancelar", "cancela")
                if text.strip().lower() in cancel_words and chat_id in pending_preview:
                    pending_preview.pop(chat_id, None)
                    send_message(chat_id, "❌ Cancelado. Pode enviar os dados de novo quando quiser.", reply_markup=MAIN_MENU_KEYBOARD)
                    continue

                # Correção pontual da prévia (Cliente/Produto/Valor) antes de confirmar
                if chat_id in pending_preview and text.strip():
                    if should_replace_pending_preview(text):
                        pending_preview.pop(chat_id, None)
                    else:
                        lower = text.strip().lower()
                        pending = pending_preview.get(chat_id)
                        if pending:
                            parse_result = pending["parse_result"]
                            cmd = parse_result.command
                            updated = False
                            # Atualizar cliente
                            if lower.startswith("cliente"):
                                import re
                                _, _, rest = text.partition(":")
                                if not rest:
                                    rest = text.split("cliente", 1)[-1]
                                new_name = rest.strip(" :-")
                                if new_name:
                                    # Aceita formatos como "cliente id 004" e guarda só o número.
                                    m_id = re.search(r"\d+", new_name)
                                    if m_id:
                                        digits = m_id.group(0)
                                        digits = digits.zfill(3) if len(digits) <= 3 else digits
                                        cmd.customer = digits
                                    else:
                                        cmd.customer = new_name
                                    updated = True
                            # Atualizar ID VENDA
                            if not updated and ("id venda" in lower or lower.startswith("venda")):
                                import re
                                m_id = re.search(r"\d+", text)
                                if m_id:
                                    digits = m_id.group(0)
                                    digits = digits.zfill(3) if len(digits) <= 3 else digits
                                    cmd.sale_id = digits
                                    updated = True
                            # Atualizar produto
                            if not updated and ("produto" in lower):
                                _, _, rest = text.partition(":")
                                if not rest:
                                    rest = text.split("produto", 1)[-1]
                                new_prod = rest.strip(" :-")
                                if new_prod:
                                    cmd.product_id = new_prod
                                    parse_result.command.description = new_prod
                                    updated = True
                            # Atualizar valor total
                            if not updated and ("valor" in lower):
                                _, _, rest = text.partition(":")
                                value_text = (rest or text).strip()
                                parsed_value = parse_money_value(value_text)
                                if parsed_value is None:
                                    parsed_value = _extract_total_value(text, _currency_candidates(text))
                                if parsed_value is not None and parsed_value > 0:
                                    cmd.total_value = parsed_value
                                    recalculate_payments_for_total(cmd)
                                    updated = True
                            if not updated:
                                from src.parser import apply_preview_corrections
                                updated = apply_preview_corrections(text, cmd)
                            if updated:
                                # Se pagamento mudou na mensagem, recalcular entrada/saldo.
                                if any(tok in lower for tok in ("pagou", "paguei", "entrada", "metade", "restante", "saldo")):
                                    fresh = parse_message(text, reference_date=date.today())
                                    if fresh.intent == parse_result.intent and not fresh.missing_fields:
                                        pending["parse_result"] = fresh
                                        pending["original_text"] = text
                                        parse_result = fresh
                                # Se o usuário forneceu o ID Cliente, remover da lista de missing.
                                if (cmd.customer or "").strip() and "ID Cliente" in parse_result.missing_fields:
                                    parse_result.missing_fields = [
                                        f for f in parse_result.missing_fields if f != "ID Cliente"
                                    ]
                                # Se o usuário forneceu o ID VENDA, remover da lista de missing.
                                if getattr(cmd, "sale_id", None) and "ID VENDA" in parse_result.missing_fields:
                                    parse_result.missing_fields = [
                                        f for f in parse_result.missing_fields if f != "ID VENDA"
                                    ]
                                pending["parse_result"] = parse_result
                                preview_text = build_preview(parse_result)
                                send_message(chat_id, preview_text, parse_mode="Markdown")
                                continue

                # Resposta de data de entrega pendente
                if chat_id in pending_delivery:
                    try:
                        pending = pending_delivery.get(chat_id)
                        if not pending:
                            continue
                        raw = text.strip()
                        parsed = _parse_pt_date(raw, date.today(), full_text=raw)
                        if parsed is None:
                            from datetime import datetime
                            for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d/%m"):
                                try:
                                    dt = datetime.strptime(raw, fmt)
                                    if fmt == "%d/%m":
                                        dt = dt.replace(year=date.today().year)
                                    parsed = dt.date()
                                    break
                                except Exception:
                                    continue
                        if parsed is None:
                            raise ValueError("Data inválida.")
                        parse_result = pending["parse_result"]
                        parse_result.command.service_due_date = parsed
                        if _is_service_delivery_finalized(raw):
                            parse_result.command.service_status = "finalizado"
                        reply = apply_parse_result(
                            parse_result,
                            origin=pending.get("origin", "telegram"),
                            original_text=pending.get("original_text", ""),
                            chat_id=str(chat_id),
                        )
                        if _is_service_delivery_finalized(raw):
                            sale_id = getattr(parse_result.command, "sale_id", None)
                            if sale_id:
                                workbook_path = get_default_workbook()
                                if workbook_path:
                                    from src.excel_store import SpreadsheetService
                                    SpreadsheetService(workbook_path).finalize_service(str(sale_id))
                        send_message(chat_id, reply, parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)
                        pending_delivery.pop(chat_id, None)
                        continue
                    except Exception:
                        # Se a resposta não for uma data válida, segue sem data de entrega.
                        pending = pending_delivery.pop(chat_id, None)
                        if pending:
                            parse_result = pending["parse_result"]
                            reply = apply_parse_result(
                                parse_result,
                                origin=pending.get("origin", "telegram"),
                                original_text=pending.get("original_text", ""),
                                chat_id=str(chat_id),
                            )
                            send_message(
                                chat_id,
                                "Não entendi a data, então vou salvar sem Data de Entrega.",
                            )
                            send_message(chat_id, reply, parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)
                        continue

                # Atualizar status baseado em ID do cliente (ex.: "Cliente ID 002 pagou")
                # Isso evita depender de "ID VENDA" em mensagens curtas.
                try:
                    import re
                    lower = text.strip().lower()
                    # Ignora se for criação de venda (para não confundir "cliente ... pagou" dentro de venda).
                    sale_tokens = ("vendi", "fechei", "fechamos", "acabei de fazer uma venda", "fiz uma venda", "fiz um", "comprou")
                    # Se tiver valor (ex.: "cliente id 005 pagou 2500"), é pagamento parcial:
                    # deixa seguir para o parser normal (payment_update) em vez de marcar como pago total.
                    nums = [int(n) for n in re.findall(r"\b\d{1,6}\b", lower)]
                    has_amount = any(n >= 100 for n in nums)
                    if (
                        "cliente" in lower
                        and ("pagou" in lower or "pago" in lower)
                        and not any(tok in lower for tok in sale_tokens)
                        and not has_amount
                    ):
                        # Suporta variações como:
                        # "Cliente ID 002, 003 e 004 pagou"
                        # "cliente ID 002,003, 004 pagou"
                        ids: list[str] = []
                        m_cluster = re.search(
                            r"cliente\s*(?:id)?\s*[:\-]?\s*([0-9,\seE]+?)\s*(?:pagou|pago)\b",
                            lower,
                        )
                        if m_cluster:
                            raw_cluster = m_cluster.group(1)
                            ids = re.findall(r"\d{1,6}", raw_cluster)
                        if not ids:
                            # Fallback: padrões "id 002 e id 003"
                            ids = re.findall(r"\bid\s*[:\-]?\s*(\d{1,6})\b", lower)
                        if not ids:
                            # Fallback final: primeiro número após "cliente"
                            m = re.search(r"(?:cliente\s*(?:id)?\s*[:\-]?\s*)(\d{1,6})", lower)
                            if m:
                                ids = [m.group(1)]
                        if ids:
                            normalized_ids: list[str] = []
                            for raw_id in ids:
                                cid = raw_id.zfill(3) if len(raw_id) <= 3 else raw_id
                                if cid not in normalized_ids:
                                    normalized_ids.append(cid)

                            workbook_path = get_default_workbook()

                            if workbook_path and Path(workbook_path).exists():
                                from src.excel_store import SpreadsheetService
                                svc = SpreadsheetService(workbook_path)
                                batch_results = []
                                not_found = []
                                for cliente_id in normalized_ids:
                                    # Prioridade 1: interpretar os IDs informados como ID VENDA.
                                    # (Ex.: "Cliente ID 002, 003 e 004 pagou" na prática marca ID VENDA 002/003/004.)
                                    target_sale_id = None
                                    sale_rows = svc.get_pending_sale_by_sale_id(
                                        cliente_id,
                                        max_rows_scan=500,
                                        include_paid=True,
                                    )
                                    if sale_rows:
                                        target_sale_id = sale_rows[0].get("sale_id")
                                    else:
                                        # Prioridade 2 (fallback): interpretar como ID de cliente (aba ID Cliente).
                                        pend_rows = svc.get_pending_sales_by_customer(
                                            cliente_id,
                                            max_rows_scan=500,
                                            include_paid=True,
                                        )
                                        if pend_rows:
                                            target_sale_id = pend_rows[0].get("sale_id")
                                    if target_sale_id:
                                        pr = parse_message(
                                            f"ID VENDA {target_sale_id} pagou",
                                            reference_date=date.today(),
                                        )
                                        batch_results.append(pr)
                                    else:
                                        not_found.append(cliente_id)

                                if batch_results:
                                    if len(batch_results) == 1:
                                        parse_result = batch_results[0]
                                        preview_text = build_preview(parse_result)
                                        if not_found:
                                            preview_text += (
                                                f"\n\nIDs sem pendência/não encontrados: {', '.join(not_found)}"
                                            )
                                        send_message(chat_id, preview_text, parse_mode="Markdown")
                                        pending_preview[chat_id] = {
                                            "parse_result": parse_result,
                                            "original_text": text,
                                            "origin": "telegram",
                                        }
                                    else:
                                        parts = []
                                        for idx, pr in enumerate(batch_results, start=1):
                                            parts.append(f"Item {idx}:\n{build_preview(pr)}")
                                        if not_found:
                                            parts.append("IDs sem pendência: " + ", ".join(not_found))
                                        parts.append("\nResponda *SIM* para confirmar o lote ou *NÃO* para cancelar.")
                                        send_message(chat_id, "\n\n".join(parts[:8]), parse_mode="Markdown")
                                        pending_preview[chat_id] = {
                                            "batch_parse_results": batch_results,
                                            "original_text": text,
                                            "origin": "telegram",
                                        }
                                    continue

                                send_message(chat_id, f"Não achei pendência para os IDs informados ({', '.join(normalized_ids)}).")
                                continue
                except Exception as e:
                    # Não interrompe o fluxo normal.
                    print(f"[Telegram] Erro ao interpretar 'cliente pagou': {e}")

                # Comandos curtos (Resumo/Status/Prévia/Planilha): não usam prévia
                cmd_lower = text.lower()
                short_cmd_keywords = (
                    "resumo",
                    "status",
                    "planilha",
                    "prévia",
                    "previa",
                )
                cmd_strip = cmd_lower.strip()
                if any(cmd_strip.startswith(kw) for kw in short_cmd_keywords):
                    pending_preview.pop(chat_id, None)
                    reply = process_command(text, origin="telegram")
                    send_message(chat_id, reply, parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)
                    # Para Status/Resumo/Planilha/Prévia, também envia uma imagem (facilita visualização).
                    if cmd_strip.startswith(("status", "resumo", "planilha", "prévia", "previa")):
                        workbook_path = os.getenv("WORKBOOK_PATH", "").strip()
                        if not workbook_path:
                            from src.workbook_paths import default_workbook_path
                            workbook_path = default_workbook_path([Path.cwd(), Path.cwd().parent])
                        img_path = None
                        if workbook_path:
                            # Status/Resumo/Planilha: card financeiro (lucros). Prévia: tabela de vendas (clientes/pendências).
                            if cmd_strip.startswith(("prévia", "previa")):
                                img_path = _maybe_build_sales_snippet_image(
                                    workbook_path,
                                    title_main="TOTAL DE VENDAS - Visão atual",
                                    meta_line="Pendências e entregas • Atualizado ao vivo com base na planilha",
                                )
                            else:
                                img_path = _maybe_build_status_table_image(workbook_path)
                        if not img_path:
                            img_path = _maybe_build_text_image_png(reply)
                        if img_path:
                            try:
                                send_photo(chat_id, img_path)
                            finally:
                                try:
                                    Path(img_path).unlink(missing_ok=True)
                                except Exception:
                                    pass
                    continue

                # Interpretar mensagem: se tiver dados completos, mostrar prévia; senão, pedir o que falta
                parse_text = enrich_with_last_sale_context(text, last_sale_id_by_chat.get(chat_id))
                if parse_text != text:
                    print(f"[Telegram] Contexto: último ID VENDA {last_sale_id_by_chat.get(chat_id)} aplicado no chat {chat_id}")
                parse_result = parse_message(parse_text, reference_date=date.today())

                # Atualiza cache quando conseguir extrair cliente.
                parsed_customer = (getattr(parse_result.command, "customer", "") or "").strip()
                explicit_customer = (_extract_customer(text) or _extract_customer(parse_text) or "").strip()
                if explicit_customer:
                    parse_result.command.customer = explicit_customer
                    parse_result.missing_fields = [
                        f for f in parse_result.missing_fields if f != "ID Cliente"
                    ]
                    parsed_customer = explicit_customer
                if parsed_customer and parsed_customer != "-":
                    last_customer_by_chat[chat_id] = parsed_customer

                # Fallback: se faltou somente "ID Cliente", tente preencher com o último conhecido.
                if "ID Cliente" in parse_result.missing_fields:
                    cached_customer = None if should_replace_pending_preview(text) else last_customer_by_chat.get(chat_id)
                    if cached_customer:
                        parse_result.command.customer = cached_customer
                        parse_result.missing_fields = [
                            f for f in parse_result.missing_fields if f != "ID Cliente"
                        ]
                        print(f"[Telegram] Fallback de 'ID Cliente' usado no chat {chat_id}: {cached_customer}")

                # Fallback: atualização de entrega/status logo após outra ação ("para ele", "entrega hoje").
                if "ID VENDA" in parse_result.missing_fields and parse_result.intent in (
                    "status_update",
                    "delivery_update",
                    "delivery_finalize",
                    "payment_update",
                ):
                    cached_sale_id = last_sale_id_by_chat.get(chat_id)
                    if cached_sale_id:
                        cmd.sale_id = cached_sale_id
                        parse_result.missing_fields = [
                            f for f in parse_result.missing_fields if f != "ID VENDA"
                        ]
                        print(f"[Telegram] Fallback de 'ID VENDA' usado no chat {chat_id}: {cached_sale_id}")

                remembered_sale = sale_id_from_parse_result(parse_result)
                if remembered_sale:
                    last_sale_id_by_chat[chat_id] = remembered_sale

                # Inferencia: quando for gasto de material e faltar "ID VENDA",
                # tente localizar a venda pendente pelo "ID Cliente" informado.
                # Isso preserva o sentido:
                # - Você pode falar "cliente id 002" (ID Cliente)
                # - O robô encontra o ID VENDA correspondente e lança em "Compras Matéria-Prima".
                cmd = parse_result.command
                if "ID VENDA" in parse_result.missing_fields:
                    try:
                        material_cost = getattr(cmd, "material_cost", None)
                        is_material_expense = bool(material_cost and float(material_cost) > 0 and (cmd.total_value or 0.0) <= 0.01 and not cmd.payments)
                        if is_material_expense:
                            customer_id = (getattr(cmd, "customer", "") or "").strip()
                            if customer_id:
                                workbook_path = os.getenv("WORKBOOK_PATH", "").strip()
                                if not workbook_path:
                                    from src.workbook_paths import default_workbook_path
                                    workbook_path = default_workbook_path([Path.cwd(), Path.cwd().parent])
                                if workbook_path and Path(workbook_path).exists():
                                    from src.excel_store import SpreadsheetService
                                    svc = SpreadsheetService(workbook_path)
                                    sale_rows = svc.get_pending_sales_by_customer(
                                        customer_id, max_rows_scan=500, include_paid=True
                                    )
                                    if not sale_rows:
                                        # Alguns fluxos podem mandar o numero como "ID VENDA" em vez de "ID Cliente".
                                        sale_rows = svc.get_pending_sale_by_sale_id(
                                            customer_id, max_rows_scan=500, include_paid=True
                                        )
                                    if sale_rows:
                                        inferred_sale_id = sale_rows[0].get("sale_id")
                                        if inferred_sale_id:
                                            cmd.sale_id = inferred_sale_id
                                            # Se ainda nao houver material_allocations, crie agora para vincular no Excel.
                                            if not getattr(cmd, "material_allocations", None):
                                                from src.models import MaterialAllocation
                                                alloc_date = getattr(cmd, "material_date", None) or date.today()
                                                cmd.material_allocations = [
                                                    MaterialAllocation(
                                                        sale_id=str(inferred_sale_id).strip(),
                                                        amount=float(material_cost),
                                                        material_date=alloc_date,
                                                    )
                                                ]
                                            cmd.description = f"Material da venda {inferred_sale_id}"
                                            parse_result.missing_fields = [
                                                f for f in parse_result.missing_fields if f != "ID VENDA"
                                            ]
                                            print(f"[Telegram] Inferido ID VENDA {inferred_sale_id} a partir do ID Cliente {customer_id} (chat {chat_id}).")
                    except Exception as e:
                        print(f"[Telegram] Falha na inferencia de ID VENDA: {e}")

                if parse_result.missing_fields:
                    missing_set = set(parse_result.missing_fields)

                    # Mostra prévia mesmo sem ID Cliente, para o usuário validar os demais campos.
                    if missing_set == {"ID Cliente"} and parse_result.intent in (
                        "sale",
                        "mixed_update",
                        "refund",
                        "status_update",
                        "delivery_update",
                        "delivery_finalize",
                        "material_update",
                    ):
                        preview_text = build_preview(parse_result)
                        send_message(
                            chat_id,
                            preview_text
                            + "\n\nFaltou apenas o *ID Cliente*.\n"
                            + "Envie por exemplo: `cliente id 004`.",
                            parse_mode="Markdown",
                        )
                        pending_preview[chat_id] = {
                            "parse_result": parse_result,
                            "original_text": text,
                            "origin": "audio" if from_voice else "telegram",
                        }
                        continue

                    if missing_set == {"ID VENDA"} and parse_result.intent in (
                        "sale",
                        "mixed_update",
                        "refund",
                        "status_update",
                        "delivery_update",
                        "delivery_finalize",
                        "material_update",
                    ):
                        preview_text = build_preview(parse_result)
                        send_message(
                            chat_id,
                            preview_text
                            + "\n\nFaltou apenas o *ID VENDA* para vincular na planilha.\n"
                            + "Envie por exemplo: `id venda 002`.",
                            parse_mode="Markdown",
                        )
                        pending_preview[chat_id] = {
                            "parse_result": parse_result,
                            "original_text": text,
                            "origin": "audio" if from_voice else "telegram",
                        }
                        continue

                    if chat_id in pending_preview:
                        send_message(
                            chat_id,
                            "Para *confirmar* a prévia responda SIM. Para *cancelar* responda NÃO. "
                            "Ou envie os dados corrigidos (ex.: Cliente é X, produto Y, valor Z).",
                            parse_mode="Markdown",
                        )
                    else:
                        send_message(
                            chat_id,
                            "Faltam dados: " + ", ".join(parse_result.missing_fields) + ". Revise e tente de novo.",
                        )
                    continue

                # Dados completos: mostrar prévia e guardar até o usuário confirmar
                if parse_result.intent in (
                    "sale",
                    "mixed_update",
                    "refund",
                    "status_update",
                    "delivery_update",
                    "delivery_finalize",
                    "material_update",
                ):
                    preview_text = build_preview(parse_result)
                    send_message(chat_id, preview_text, parse_mode="Markdown")
                    pending_preview[chat_id] = {
                        "parse_result": parse_result,
                        "original_text": text,
                        "origin": "audio" if from_voice else "telegram",
                    }
                    remembered = sale_id_from_parse_result(parse_result)
                    if remembered:
                        last_sale_id_by_chat[chat_id] = remembered
                    continue

                # Outros casos (ex.: só texto que não é venda/estorno): processar direto
                reply = process_command(text, origin="telegram")
                send_message(chat_id, reply, parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)
            except Exception as e:
                reply = f"⚠️ Não consegui processar essa mensagem: {e}"
                send_message(chat_id, reply, reply_markup=MAIN_MENU_KEYBOARD)
                print(f"[Telegram] Erro ao processar: {e}")

        if not updates:
            time.sleep(0.5)

        # Checagem de lembretes (a cada ~10 minutos)
        if time.time() - last_reminder_check >= 600:
            last_reminder_check = time.time()
            try:
                from src.excel_store import SpreadsheetService
                from src.workbook_paths import default_workbook_path
                from pathlib import Path
                wb_path = os.getenv("WORKBOOK_PATH", "").strip()
                if not wb_path:
                    wb_path = default_workbook_path([Path.cwd(), Path.cwd().parent])
                if wb_path and Path(wb_path).exists():
                    svc = SpreadsheetService(wb_path)
                    wb = svc._open_workbook(data_only=True)
                    try:
                        due = svc.list_due_reminders(wb, date.today())
                    finally:
                        wb.close()
                    admin_chat = os.getenv("ADMIN_CHAT_ID", "").strip()
                    for item in due[:20]:
                        sale_id = item.get("id venda") or item.get("id venda".lower()) or ""
                        cliente = item.get("cliente", "")
                        desc = item.get("descricao", "")
                        pending_amount = item.get("pending_amount_num", None)
                        total_amount = item.get("total_amount_num", None)

                        def _format_currency_pt(value: float) -> str:
                            txt = f"{float(value):,.2f}"
                            # pt-BR: separador decimal vírgula e milhares ponto
                            txt = txt.replace(",", "X").replace(".", ",").replace("X", ".")
                            return f"R$ {txt}"

                        value_line = ""
                        try:
                            if pending_amount is not None and float(pending_amount or 0.0) > 0.01:
                                value_line = f"Valor pendente: {_format_currency_pt(float(pending_amount))}\n"
                            elif total_amount is not None:
                                value_line = f"Valor total: {_format_currency_pt(float(total_amount))}\n"
                        except Exception:
                            value_line = ""

                        msg_txt = (
                            f"⏰ *Lembrete de entrega hoje*\n"
                            f"ID VENDA: {sale_id}\n"
                            f"Cliente: {cliente}\n"
                            f"Descricao: {desc}\n\n"
                            f"{value_line}"
                            f"Se já finalizou, envie: FINALIZAR ID VENDA {sale_id}"
                        )
                        chat_target = (item.get("chat id") or "").strip()
                        if chat_target:
                            send_message(chat_target, msg_txt, parse_mode="Markdown")
                        if admin_chat:
                            send_message(admin_chat, msg_txt, parse_mode="Markdown")
            except Exception:
                pass


def _run_local_test(args: argparse.Namespace) -> None:
    """
    Modo de teste para validar parser + preview + escrita na planilha
    sem depender de TELEGRAM_BOT_TOKEN nem do Telegram em si.
    """
    if args.workbook:
        os.environ["WORKBOOK_PATH"] = args.workbook

    text = args.test_message or ""
    if not text.strip():
        raise SystemExit("Informe --test-message com um texto para testar.")

    # Mantemos a mesma lógica do bot.
    parse_result = parse_message(text, reference_date=date.today())

    if parse_result.missing_fields:
        print("Missing fields:", ", ".join(parse_result.missing_fields))
        return

    if parse_result.intent in (
        "sale",
        "mixed_update",
        "refund",
        "status_update",
        "delivery_update",
        "delivery_finalize",
        "material_update",
    ):
        preview_text = build_preview(parse_result)
        print(preview_text)

    if args.apply:
        reply = apply_parse_result(
            parse_result,
            origin=args.origin,
            original_text=text,
            chat_id=args.chat_id,
        )
        print("\n--- Apply result ---")
        print(reply)


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram bot (planilha) com modo local de teste.")
    parser.add_argument("--test-message", dest="test_message", default="", help="Texto para simular uma mensagem do Telegram.")
    parser.add_argument("--apply", action="store_true", help="Aplica a escrita na planilha durante o modo de teste.")
    parser.add_argument("--workbook", dest="workbook", default="", help="Sobrescreve WORKBOOK_PATH no modo de teste.")
    parser.add_argument("--origin", dest="origin", default="local-test", help="Origem usada no log durante o modo de teste.")
    parser.add_argument("--chat-id", dest="chat_id", default="local-test", help="Chat ID usado para lembretes (modo teste).")
    args, _unknown = parser.parse_known_args()

    if args.test_message:
        # Windows console pode estar em cp1252 e falhar ao imprimir emojis (prévia usa emoji).
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[call-arg]
        return _run_local_test(args)

    try:
        run_polling()
    except KeyboardInterrupt:
        # Encerramento amigável no Ctrl+C (sem traceback assustando o usuário).
        print("\n[Telegram] Bot encerrado por Ctrl+C.")
        return


if __name__ == "__main__":
    main()
