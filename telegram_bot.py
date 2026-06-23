# -*- coding: utf-8 -*-
"""
Bot do Telegram — arquivo para iniciar o robo (Run ▶).

1. Rode run_project.py antes (prepara ambiente).
2. Configure TELEGRAM_BOT_TOKEN no .env.
3. Clique em Run neste arquivo.
"""
from __future__ import annotations

import atexit
import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

import requests

from src.bot_processor import (
    apply_parse_result,
    build_missing_fields_message,
    build_preview,
    get_default_workbook,
    process_command,
    sale_id_from_parse_result,
)
from src.parser import parse_message, _parse_pt_date, _is_service_delivery_finalized, should_replace_pending_preview, _extract_total_value, _currency_candidates, enrich_with_last_sale_context, recalculate_payments_for_total, parse_money_value, _extract_customer, apply_multi_field_corrections, apply_preview_corrections, extract_supplemental_sale_id, _extract_target_sale_id_for_updates, extract_sale_ids_list_for_updates
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


def _lock_path() -> Path:
    return Path(__file__).resolve().parent / ".telegram_bot.lock"


def _acquire_single_instance_lock() -> None:
    """Evita rodar duas instancias do bot ao mesmo tempo (causa previas/erros duplicados)."""
    from src.bootstrap import stop_old_bot_instances

    stop_old_bot_instances(prefix="Telegram")

    lock_path = _lock_path()
    lock_path.write_text(str(os.getpid()), encoding="utf-8")

    def _cleanup() -> None:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_cleanup)

HELP_TEXT = """👋 *Olá! Eu sou o assistente da sua planilha.*

⚙️ *Como funciona*
🎙️ Você manda *áudio* ou *texto*
📋 Eu mostro uma *prévia* com os dados
✅ Você confirma com *SIM* ou *OK*
💾 Pronto — salvo na planilha!

🔹🔹🔹

🆕 *Exemplo 1 — registrar uma venda nova*

É a primeira vez dessa venda. Fale o *nome do cliente* e siga este roteiro — campo por campo:

👤 Cliente: _nome do cliente_
📦 Produto: _o que foi vendido_
📅 Data da venda: _hoje ou a data_
💰 Valor total: _valor do pedido_
   Pago: _entrada_ | Pendente: _o que falta_
🔎 Status: _pendente ou pago_
📅 Data de entrega: _quando entrega_

💬 *Na prática, pode falar assim:*
_"Vendi um letreiro para a Lucia hoje por 2200. Deu 700 de entrada, falta 1500 pro dia 25. Entrega na quarta."_

💡 Ao salvar, a planilha gera o 🧾 *ID VENDA* (ex.: 012). Guarde esse código para as próximas mensagens.

🔹🔹🔹

📂 *Exemplo 2 — venda que já está na planilha*

A venda já foi salva. Agora use o 🧾 *ID VENDA*:

👤 Cliente: _já cadastrado_
🧾 ID VENDA: _012_
💰 Valor total: _já na planilha_
   Pago: _atualizado_ | Pendente: _atualizado_
🔎 Status: _pendente → pago_
📅 Data de entrega: _já cadastrada_

💬 *Cliente pagou o que faltava:*
_"ID VENDA 012 recebeu o saldo de 1500 hoje."_

💬 *Cliente quitou tudo:*
_"ID VENDA 012 pagou tudo hoje."_

🔹🔹🔹

🔧 *Exemplo 3 — algo aconteceu depois da venda*

Com o 🧾 *ID VENDA* em mãos, você também pode avisar:

💬 *Gasto com material:*
_"Gastei 350 de tinta na ID VENDA 012."_

💬 *Mudança na entrega:*
_"A entrega da ID VENDA 012 ficou para sexta."_

💬 *Vários de uma vez (entrega ou pagamento):*
_"Foi entregue cliente id 004, 005 e 008"_
_"ID VENDA 004, 005, 010 pagou"_
_(mostra prévia do lote → confirme com *SIM*)_

🔹🔹🔹

🚚 *Entrega em atraso (amarelo na planilha)*
O bot usa sempre a *data de hoje*. Se a entrega era dia 21 e hoje é 23, e ainda está *amarela*, ele cobra:
✅ *SIM* → verde na planilha | ❌ *NÃO* → continua amarelo

🔹🔹🔹

⚡ *Botões rápidos*
📋 *Prévia* — vendas, pendências e entregas
📊 *Resumo* — totais da planilha
💹 *Status* — situação financeira

✅ *Depois da prévia*
👍 Está certo → responda *SIM* ou *OK*
✏️ Precisa ajustar → mande só o que mudou:
`Cliente: Lucia, Valor: 2200, Entrada: 700`"""

# Teclado de menu (botões que aparecem abaixo do campo de digitação)
MAIN_MENU_KEYBOARD = {
    "keyboard": [
        ["Prévia", "Resumo", "Status"],
        ["Ajuda", "Reiniciar"],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}

_FONT_CACHE: dict[tuple[int, bool], object] = {}


def _load_telegram_font(size: int, bold: bool = False):
    """Carrega fonte uma vez e reutiliza (acelera geração de imagens)."""
    from PIL import ImageFont  # type: ignore

    key = (size, bold)
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
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
            font = ImageFont.truetype(fp, size=size)
            _FONT_CACHE[key] = font
            return font
        except Exception:
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _save_telegram_image(img) -> str:
    """Salva imagem em JPEG (mais rápido e leve para enviar no Telegram)."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    tmp.close()
    img.save(tmp.name, format="JPEG", quality=88, optimize=False)
    return tmp.name


def send_chat_action(chat_id: int | str, action: str = "typing") -> None:
    """Indica no Telegram que o bot está processando (melhora percepção de velocidade)."""
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            f"{BASE_URL}/sendChatAction",
            json={"chat_id": str(chat_id), "action": action},
            timeout=5,
        )
    except Exception:
        pass


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

    return _save_telegram_image(img)


def _maybe_build_status_table_image(
    workbook_path: str,
    wb=None,
    svc=None,
) -> str | None:
    """
    Gera imagem estilo "TOTAL DOS LUCROS MENSAIS E ANUAIS" com valores dinâmicos.
    """
    try:
        from PIL import Image, ImageDraw  # type: ignore
        from src.excel_store import SpreadsheetService, SHEET_SALES, SHEET_MATERIAL, SHEET_FIXED, DATA_START_ROW
    except Exception:
        return None

    try:
        own_wb = wb is None
        if own_wb:
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

            sales_end = svc._effective_data_end_row(ws_sales, col_id) if col_id else svc._scan_row_cap(ws_sales)
            total_paid = svc._sum_column_range(ws_sales, col_paid, DATA_START_ROW, sales_end)
            total_pending = svc._sum_column_range(ws_sales, col_pending, DATA_START_ROW, sales_end)

            mat_cols = svc._material_columns(ws_mat)
            col_mat_desc = mat_cols.get("descricao")
            col_mat_val = mat_cols.get("valor")
            mat_end = svc._effective_data_end_row(ws_mat, col_mat_desc) if col_mat_desc else svc._scan_row_cap(ws_mat)
            total_mat = svc._sum_column_range(ws_mat, col_mat_val, DATA_START_ROW, mat_end)

            fix_end = svc._scan_row_cap(ws_fix)
            total_fix = svc._sum_column_range(ws_fix, "D", DATA_START_ROW, fix_end)
        finally:
            if own_wb:
                wb.close()
    except Exception:
        return None

    total_sales = round(total_paid + total_pending, 2)
    lucro = round(total_sales - total_mat - total_fix, 2)

    def _brl(v: float) -> str:
        txt = f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {txt}"

    font_title = _load_telegram_font(26, bold=True)
    font_meta = _load_telegram_font(17, bold=False)
    font_label = _load_telegram_font(17, bold=False)
    font_value = _load_telegram_font(24, bold=True)

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

    return _save_telegram_image(img)


def _maybe_build_sales_snippet_image(
    workbook_path: str,
    *,
    wb=None,
    svc=None,
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
        own_wb = wb is None
        if own_wb:
            svc = SpreadsheetService(workbook_path)
            wb = svc._open_workbook(data_only=False)
        try:
            ws = wb[svc._resolve_sheet_name(wb, SHEET_SALES)]
            cols = svc._sales_columns(ws)
            # Ordem e labels fixos para ficar consistente/legível.
            display_cols = [
                ("data de venda", "Data da venda"),
                ("data de entrega", "Data entrega"),
                ("cliente", "Cliente"),
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
                sales_end = svc._effective_data_end_row(ws, id_col)
                if getattr(ws, "read_only", False):
                    from openpyxl.utils import column_index_from_string

                    col_idx = column_index_from_string(id_col)
                    for row in ws.iter_rows(
                        min_row=DATA_START_ROW,
                        max_row=sales_end,
                        min_col=col_idx,
                        max_col=col_idx,
                    ):
                        if row[0].value not in (None, ""):
                            data_rows.append(row[0].row)
                else:
                    for r in range(DATA_START_ROW, sales_end + 1):
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
            delivery_cell_states: list[bool | None] = []
            for r in last_rows:
                delivery_col = cols.get("data de entrega")
                state: bool | None = None
                if delivery_col:
                    cell = ws[f"{delivery_col}{r}"]
                    if svc._cell_fill_matches(cell, "FFF59D"):
                        state = True
                    elif svc._cell_fill_matches(cell, "C8E6C9"):
                        state = False
                delivery_cell_states.append(state)
        finally:
            if own_wb:
                wb.close()
    except Exception:
        return None

    if not rows_txt:
        return None

    # Renderização visual premium
    font_body = _load_telegram_font(24, bold=False)
    font_header = _load_telegram_font(22, bold=True)
    font_title = _load_telegram_font(30, bold=True)
    font_meta = _load_telegram_font(20, bold=False)

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
    delivery_done_bg = (200, 230, 201)

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

    # Rows: Status = pagamento; Data entrega = entrega (amarelo até confirmar entrega).
    for ri, rvals in enumerate(rows_txt, start=1):
        y = y0 + (row_h * ri)
        x = x0
        pending_row = _row_has_pending(rvals)
        delivery_state = delivery_cell_states[ri - 1] if ri - 1 < len(delivery_cell_states) else None
        for ci, txt in enumerate(rvals):
            w = col_widths[ci]
            is_money_col = headers[ci] in ("Pago", "Pendente")
            base_fill = highlight_bg if pending_row else (zebra if (ri % 2 == 0) else (255, 255, 255))
            if headers[ci] == "Data entrega":
                if delivery_state is True:
                    cell_fill = status_pend_bg
                elif delivery_state is False:
                    cell_fill = delivery_done_bg
                else:
                    cell_fill = base_fill
            elif headers[ci] == "Status":
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

    return _save_telegram_image(img)


def send_photo(
    chat_id: int | str,
    image_path: str,
    caption: str = "",
    parse_mode: str | None = None,
    reply_markup: dict | None = None,
) -> bool:
    """Envia uma foto para o chat (sendPhoto), com legenda opcional."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    try:
        with open(image_path, "rb") as f:
            files = {"photo": f}
            data: dict[str, str] = {"chat_id": str(chat_id)}
            if caption:
                data["caption"] = caption[:1024]
            if parse_mode:
                data["parse_mode"] = parse_mode
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)
            r = requests.post(f"{BASE_URL}/sendPhoto", data=data, files=files, timeout=30)
            return r.status_code == 200
    except Exception as e:
        print(f"[Telegram] Erro ao enviar foto: {e}")
        return False


def send_reply(
    chat_id: int | str,
    text: str,
    *,
    parse_mode: str | None = None,
    reply_markup: dict | None = None,
    image_path: str | None = None,
) -> bool:
    """Envia texto ou foto com legenda (uma única mensagem quando há imagem)."""
    if image_path:
        return send_photo(
            chat_id,
            image_path,
            caption=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    return send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)


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


def _audio_download_read_timeout(*, file_size: int = 0, duration_sec: int = 0) -> int:
    """Timeout de leitura do download — escala com tamanho e duração do áudio."""
    try:
        env_max = int(os.getenv("TELEGRAM_AUDIO_DOWNLOAD_TIMEOUT", "600") or 600)
    except ValueError:
        env_max = 600
    env_max = max(120, min(env_max, 900))
    by_size = 60 + (max(file_size, 0) // 2048)
    by_duration = max(duration_sec, 0) * 4
    return min(env_max, max(180, by_size, by_duration))


def _audio_processing_wait_message(duration_sec: int) -> str:
    if duration_sec >= 120:
        wait_hint = "cerca de 2 a 4 minutos"
    elif duration_sec >= 60:
        wait_hint = "cerca de 1 a 2 minutos"
    elif duration_sec >= 30:
        wait_hint = "30 segundos a 1 minuto"
    else:
        wait_hint = "alguns segundos"
    duration_line = f" ({duration_sec}s)" if duration_sec > 0 else ""
    return (
        f"⏳ *Processando áudio...*{duration_line}\n"
        f"Pode levar {wait_hint}. Aguarde — não envie outra mensagem ainda."
    )


def _spreadsheet_saving_wait_message(intent: str = "", *, batch: bool = False) -> str:
    if batch:
        return (
            "⏳ *Salvando na planilha...*\n"
            "Atualizando vários registros. Aguarde um instante."
        )
    intent = (intent or "").strip().lower()
    action_labels = {
        "sale": "a venda",
        "material_update": "o material",
        "status_update": "o status da venda",
        "payment_update": "o pagamento",
        "delivery_update": "a data de entrega",
        "delivery_finalize": "a entrega",
        "sale_delete": "a exclusão",
        "refund": "o estorno",
        "mixed_update": "a atualização",
    }
    action = action_labels.get(intent, "o lançamento")
    return (
        "⏳ *Salvando na planilha...*\n"
        f"Registrando {action}. Aguarde um instante."
    )


def _notify_spreadsheet_saving(chat_id: int | str, intent: str = "", *, batch: bool = False) -> None:
    send_message(
        chat_id,
        _spreadsheet_saving_wait_message(intent, batch=batch),
        parse_mode="Markdown",
    )
    send_chat_action(chat_id, "typing")


def _requests_get_with_retry(
    url: str,
    *,
    params: dict | None = None,
    timeout: float | tuple[float, float] = (15, 120),
    max_attempts: int = 3,
    label: str = "requisicao",
) -> requests.Response:
    """GET com retentativas em falhas de rede/timeout (comum em áudios longos)."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            wait_s = min(2 ** attempt, 8)
            print(f"[Telegram] {label} falhou (tentativa {attempt}/{max_attempts}): {exc}. Retentando em {wait_s}s...")
            time.sleep(wait_s)
    raise RuntimeError(
        f"Falha ao conectar com o Telegram apos {max_attempts} tentativas ({label}). "
        "Verifique sua internet e tente enviar o audio novamente."
    ) from last_exc


def download_telegram_voice(
    file_id: str,
    *,
    duration_sec: int = 0,
    hinted_file_size: int = 0,
) -> str:
    """Baixa o áudio de uma mensagem de voz do Telegram; retorna caminho do arquivo temporário (.ogg)."""
    r = _requests_get_with_retry(
        f"{BASE_URL}/getFile",
        params={"file_id": file_id},
        timeout=(15, 60),
        label="getFile",
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError("getFile falhou")
    result = data.get("result", {}) or {}
    file_path = result.get("file_path")
    if not file_path:
        raise RuntimeError("file_path nao retornado")
    file_size = int(result.get("file_size") or hinted_file_size or 0)
    download_read_timeout = _audio_download_read_timeout(
        file_size=file_size,
        duration_sec=duration_sec,
    )
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    audio_r = _requests_get_with_retry(
        url,
        timeout=(20, download_read_timeout),
        label="download do audio",
    )
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


def _format_currency_pt(value: float) -> str:
    txt = f"{float(value):,.2f}"
    txt = txt.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {txt}"


def _build_scheduled_reminder_message(item: dict) -> tuple[str, list[str]]:
    """Monta texto do lembrete e lista de tipos enviados (entrega/cobranca)."""
    sale_id = item.get("id venda") or ""
    cliente = item.get("cliente", "")
    desc = item.get("descricao", "")
    pending_amount = float(item.get("pending_amount_num") or 0.0)
    needs_delivery = bool(item.get("needs_delivery_reminder"))
    needs_payment = bool(item.get("needs_payment_reminder"))
    kinds: list[str] = []
    if needs_delivery:
        kinds.append("entrega")
    if needs_payment:
        kinds.append("cobranca")

    if needs_delivery and needs_payment:
        header = "⏰ *Lembrete do dia — entrega e cobrança*"
    elif needs_payment:
        header = "💰 *Cobrança — valor pendente hoje*"
    else:
        header = "🚚 *Lembrete de entrega hoje*"

    lines = [
        header,
        "",
        f"🧾 ID VENDA: *{sale_id}*",
        f"👤 Cliente: *{cliente}*",
        f"📦 Produto: *{desc}*",
        "",
    ]
    if needs_delivery:
        lines.append("🚚 *Entrega:* ainda não marcada como entregue.")
        lines.append(f"Quando entregar, envie: `FINALIZAR ID VENDA {sale_id}`")
        lines.append("")
    elif needs_payment and item.get("service_finalized"):
        lines.append("✅ *Entrega:* já marcada como entregue.")
        lines.append("")

    if needs_payment:
        lines.append(f"💰 *Pendente:* {_format_currency_pt(pending_amount)} — receber hoje.")
        lines.append(f"Quando receber, envie: `ID VENDA {sale_id} pagou`")

    return "\n".join(lines), kinds


def _build_overdue_delivery_message(item: dict) -> str:
    sale_id = item.get("id venda") or ""
    cliente = item.get("cliente", "") or "-"
    desc = item.get("descricao", "") or "-"
    delivery_txt = item.get("data entrega") or "-"
    today_txt = item.get("reference_today") or date.today().strftime("%d/%m/%Y")
    days = int(item.get("days_overdue") or 0)
    if days <= 1:
        days_txt = "1 dia"
    else:
        days_txt = f"{days} dias"
    return (
        "🚚 *Confirme a entrega — planilha pendente*\n\n"
        f"📆 *Hoje:* {today_txt}\n"
        f"A *Data de Entrega* de *{cliente}* (ID VENDA *{sale_id}*) era *{delivery_txt}* "
        f"— já passou há {days_txt} — e ainda está *amarela* (não entregue).\n\n"
        f"📦 Produto: *{desc}*\n\n"
        "⚠️ *O que aconteceu? Preciso que você confirme:*\n"
        "✅ *Já entregou?* → responda *SIM* (marco *verde* na planilha)\n"
        f"   ou envie: `ID VENDA {sale_id} foi entregue`\n"
        "❌ *Ainda não entregou?* → responda *NÃO*\n\n"
        "_Enquanto estiver amarelo e a data tiver passado, continuo cobrando._"
    )


def _register_overdue_pending(
    pending_overdue_delivery: dict,
    chat_id: int | str,
    sale_id: str,
    customer: str,
) -> None:
    bucket = pending_overdue_delivery.setdefault(chat_id, {})
    bucket[str(sale_id).strip()] = {"customer": customer or ""}


def _resolve_overdue_sale_id(text: str, bucket: dict[str, dict]) -> str | None:
    if not bucket:
        return None
    hinted = _extract_target_sale_id_for_updates(text or "")
    if hinted:
        hint = str(hinted).strip()
        for key in bucket:
            if key == hint or key.lstrip("0") == hint.lstrip("0"):
                return key
    if len(bucket) == 1:
        return next(iter(bucket))
    digits = re.findall(r"\b\d{2,4}\b", text or "")
    for raw in digits:
        for candidate in (raw, raw.zfill(3)):
            if candidate in bucket:
                return candidate
    return None


def _try_handle_overdue_delivery_reply(
    chat_id: int | str,
    text: str,
    pending_overdue_delivery: dict,
    pending_preview: dict | None = None,
) -> bool:
    bucket = pending_overdue_delivery.get(chat_id)
    if not bucket or not (text or "").strip():
        return False
    lower = text.strip().lower()
    preview_confirm = ("sim", "confirmar", "ok", "confirmo", "pode salvar", "salvar")
    if pending_preview is not None and chat_id in pending_preview and lower in preview_confirm:
        return False

    negative = any(
        tok in lower
        for tok in ("nao", "não", "ainda nao", "ainda não", "ainda nao entreg", "ainda não entreg")
    )
    positive = any(
        tok in lower
        for tok in (
            "sim",
            "ok",
            "confirmo",
            "pode atualizar",
            "pode marcar",
            "foi entregue",
            "foi entreg",
            "ja entregue",
            "já entregue",
            "entregue",
            "entregou",
            "finalizado",
            "finalizada",
        )
    )
    if not negative and not positive:
        return False

    if positive:
        multi_ids = extract_sale_ids_list_for_updates(text)
        targets = [sid for sid in multi_ids if sid in bucket]
        if len(targets) > 1:
            wb_path = _workbook_path_for_bot()
            if not wb_path:
                send_message(chat_id, "Planilha não encontrada.")
                return True
            try:
                from src.excel_store import SpreadsheetService

                svc = SpreadsheetService(wb_path)
                _notify_spreadsheet_saving(chat_id, "delivery_finalize", batch=True)
                ok_ids: list[str] = []
                fail_ids: list[str] = []
                for sid in targets:
                    if svc.finalize_service(sid):
                        ok_ids.append(sid)
                        bucket.pop(sid, None)
                    else:
                        fail_ids.append(sid)
                if not bucket:
                    pending_overdue_delivery.pop(chat_id, None)
                lines = []
                if ok_ids:
                    lines.append(
                        f"✅ *Entregas confirmadas:* {', '.join(f'*{s}*' for s in ok_ids)} — verde na planilha."
                    )
                if fail_ids:
                    lines.append(f"⚠️ Não achei na planilha: {', '.join(fail_ids)}")
                send_message(
                    chat_id,
                    "\n".join(lines) or "Nenhuma entrega atualizada.",
                    parse_mode="Markdown",
                    reply_markup=MAIN_MENU_KEYBOARD,
                )
            except Exception as exc:
                send_message(chat_id, f"Erro ao atualizar: {exc}", reply_markup=MAIN_MENU_KEYBOARD)
            return True

    sale_id = _resolve_overdue_sale_id(text, bucket)
    if not sale_id:
        lines = [
            "Você tem *várias entregas* amarelas aguardando confirmação:",
            "",
        ]
        for sid, info in sorted(bucket.items()):
            nome = info.get("customer") or "-"
            lines.append(f"• ID VENDA *{sid}* — {nome}")
        lines.extend(
            [
                "",
                "Responda, por exemplo:",
                "`SIM ID VENDA 002` — já entregue",
                "`NÃO ID VENDA 003` — ainda não entregue",
            ]
        )
        send_message(chat_id, "\n".join(lines), parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)
        return True

    if negative and not positive:
        send_message(
            chat_id,
            f"Ok, ID VENDA *{sale_id}* continua *amarelo* (não entregue).\n"
            f"Quando entregar, responda *SIM* ou `ID VENDA {sale_id} foi entregue`.",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return True

    wb_path = _workbook_path_for_bot()
    if not wb_path:
        send_message(chat_id, "Planilha não encontrada.")
        return True
    try:
        from src.excel_store import SpreadsheetService

        svc = SpreadsheetService(wb_path)
        _notify_spreadsheet_saving(chat_id, "delivery_finalize")
        ok = svc.finalize_service(sale_id)
        bucket.pop(sale_id, None)
        if not bucket:
            pending_overdue_delivery.pop(chat_id, None)
        if ok:
            send_message(
                chat_id,
                f"✅ *Entrega confirmada!*\n\nID VENDA *{sale_id}* marcado como entregue — *verde* na planilha.",
                parse_mode="Markdown",
                reply_markup=MAIN_MENU_KEYBOARD,
            )
        else:
            send_message(
                chat_id,
                f"Não achei ID VENDA *{sale_id}* na planilha.",
                parse_mode="Markdown",
                reply_markup=MAIN_MENU_KEYBOARD,
            )
    except Exception as exc:
        send_message(chat_id, f"Erro ao atualizar: {exc}", reply_markup=MAIN_MENU_KEYBOARD)
    return True


def _workbook_path_for_bot() -> str:
    wb_path = os.getenv("WORKBOOK_PATH", "").strip()
    if not wb_path:
        from src.workbook_paths import default_workbook_path
        wb_path = default_workbook_path([Path.cwd(), Path.cwd().parent])
    return wb_path or ""


def _build_dashboard_reply(cmd_strip: str) -> tuple[str, str | None]:
    """
    Gera texto + imagem abrindo a planilha uma única vez (Prévia/Status/Resumo).
    Retorna (legenda, caminho_imagem).
    """
    from src.excel_store import SpreadsheetService

    workbook_path = _workbook_path_for_bot()
    if not workbook_path or not Path(workbook_path).exists():
        return process_command(cmd_strip, origin="telegram"), None

    svc = SpreadsheetService(workbook_path)
    wb = svc._open_workbook(data_only=False)
    img_path: str | None = None
    try:
        if cmd_strip.startswith(("prévia", "previa")):
            reply = svc.get_sales_preview(wb=wb)
            img_path = _maybe_build_sales_snippet_image(
                workbook_path,
                wb=wb,
                svc=svc,
                title_main="TOTAL DE VENDAS - Visão atual",
                meta_line="Pendências e entregas • Atualizado ao vivo com base na planilha",
            )
        elif cmd_strip.startswith(("status", "resumo", "planilha")):
            reply = svc.get_planilha_summary(wb=wb)
            img_path = _maybe_build_status_table_image(workbook_path, wb=wb, svc=svc)
        else:
            return process_command(cmd_strip, origin="telegram"), None
    finally:
        wb.close()

    if not img_path:
        img_path = _maybe_build_text_image_png(reply)
        if img_path:
            return "", img_path
    return reply, img_path


def _send_batch_update_preview(
    chat_id: int | str,
    batch_results: list,
    *,
    original_text: str,
    pending_preview: dict,
    not_found: list[str] | None = None,
) -> None:
    from src.bot_processor import build_preview

    missing = not_found or []
    if len(batch_results) == 1:
        parse_result = batch_results[0]
        preview_text = build_preview(parse_result)
        if missing:
            preview_text += f"\n\nIDs não encontrados: {', '.join(missing)}"
        send_message(chat_id, preview_text, parse_mode="Markdown")
        pending_preview[chat_id] = {
            "parse_result": parse_result,
            "original_text": original_text,
            "origin": "telegram",
        }
        return

    parts: list[str] = []
    for idx, pr in enumerate(batch_results, start=1):
        parts.append(f"*Item {idx}:*\n{build_preview(pr)}")
    if missing:
        parts.append(f"IDs não encontrados: {', '.join(missing)}")
    parts.append("\nResponda *SIM* para confirmar o lote ou *NÃO* para cancelar.")
    send_message(chat_id, "\n\n".join(parts[:8]), parse_mode="Markdown")
    pending_preview[chat_id] = {
        "batch_parse_results": batch_results,
        "original_text": original_text,
        "origin": "telegram",
    }


def _try_handle_batch_sale_updates(
    chat_id: int | str,
    text: str,
    pending_preview: dict,
) -> bool:
    """Vários ID VENDA na mesma mensagem — entrega ou pagamento total."""
    lower = text.strip().lower()
    sale_tokens = (
        "vendi",
        "fechei",
        "fechamos",
        "acabei de fazer uma venda",
        "fiz uma venda",
        "fiz um",
        "comprou",
    )
    if any(tok in lower for tok in sale_tokens):
        return False

    ids = extract_sale_ids_list_for_updates(text)
    if len(ids) < 2:
        return False

    nums = [int(n) for n in re.findall(r"\b\d{1,6}\b", lower)]
    has_amount = any(n >= 100 for n in nums)

    is_payment = ("pagou" in lower or "pago" in lower or "quitou" in lower) and not has_amount
    is_delivery = (
        _is_service_delivery_finalized(text)
        or bool(re.search(r"\b(?:foi\s+)?entreg", lower))
        or "finaliz" in lower
        or bool(re.search(r"\batualiz\w+.*entreg", lower))
    ) and not is_payment

    if not is_payment and not is_delivery:
        return False

    workbook_path = _workbook_path_for_bot()
    if not workbook_path or not Path(workbook_path).exists():
        return False

    batch_results: list = []
    not_found: list[str] = []
    today = date.today()

    if is_delivery:
        for sale_id in ids:
            pr = parse_message(f"ID VENDA {sale_id} foi entregue hoje", reference_date=today)
            if pr.missing_fields:
                not_found.append(sale_id)
            else:
                batch_results.append(pr)
        kind = "entrega"
    else:
        from src.excel_store import SpreadsheetService

        svc = SpreadsheetService(workbook_path)
        for cliente_id in ids:
            target_sale_id = None
            sale_rows = svc.get_pending_sale_by_sale_id(
                cliente_id, max_rows_scan=500, include_paid=True
            )
            if sale_rows:
                target_sale_id = sale_rows[0].get("sale_id")
            else:
                pend_rows = svc.get_pending_sales_by_customer(
                    cliente_id, max_rows_scan=500, include_paid=True
                )
                if pend_rows:
                    target_sale_id = pend_rows[0].get("sale_id")
            if target_sale_id:
                pr = parse_message(f"ID VENDA {target_sale_id} pagou", reference_date=today)
                batch_results.append(pr)
            else:
                not_found.append(cliente_id)
        kind = "pagamento"

    if not batch_results:
        send_message(
            chat_id,
            f"Não consegui montar o lote de {kind} para os IDs: {', '.join(ids)}.",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return True

    _send_batch_update_preview(
        chat_id,
        batch_results,
        original_text=text,
        pending_preview=pending_preview,
        not_found=not_found,
    )
    return True


def _process_scheduled_reminders(tracker) -> None:
    """Envia lembretes no dia da entrega: a partir das 6h, a cada 2h."""
    from src.excel_store import SpreadsheetService
    from src.reminder_scheduler import current_reminder_slot
    from src.workbook_paths import default_workbook_path

    slot = current_reminder_slot()
    if not slot:
        return
    today, slot_hour = slot

    wb_path = os.getenv("WORKBOOK_PATH", "").strip()
    if not wb_path:
        wb_path = default_workbook_path([Path.cwd(), Path.cwd().parent])
    if not wb_path or not Path(wb_path).exists():
        return

    svc = SpreadsheetService(wb_path)
    wb = svc._open_workbook(data_only=True)
    try:
        due = svc.list_due_reminders(wb, today)
    finally:
        wb.close()

    if not due:
        return

    admin_chat = os.getenv("ADMIN_CHAT_ID", "").strip()
    for item in due[:20]:
        sale_id = str(item.get("id venda") or "").strip()
        if not sale_id:
            continue

        send_delivery = bool(item.get("needs_delivery_reminder")) and not tracker.was_sent(
            "entrega", sale_id, today, slot_hour
        )
        send_payment = bool(item.get("needs_payment_reminder")) and not tracker.was_sent(
            "cobranca", sale_id, today, slot_hour
        )
        if not send_delivery and not send_payment:
            continue

        preview_item = dict(item)
        preview_item["needs_delivery_reminder"] = send_delivery
        preview_item["needs_payment_reminder"] = send_payment
        msg_txt, kinds = _build_scheduled_reminder_message(preview_item)
        if not kinds:
            continue

        chat_target = (item.get("chat id") or "").strip()
        sent = False
        if chat_target:
            sent = send_message(chat_target, msg_txt, parse_mode="Markdown")
        if admin_chat:
            send_message(admin_chat, msg_txt, parse_mode="Markdown")
            sent = True
        if not sent:
            continue

        for kind in kinds:
            tracker_key = "entrega" if kind == "entrega" else "cobranca"
            tracker.mark_sent(tracker_key, sale_id, today, slot_hour)
        print(
            f"[Telegram] Lembrete enviado ID VENDA {sale_id} "
            f"({', '.join(kinds)}) slot {slot_hour:02d}h"
        )


def _process_overdue_deliveries(tracker, pending_overdue_delivery: dict) -> None:
    """
    Cobra entregas amarelas cuja data já passou em relação a hoje (date.today()).
    Roda a cada ~1 min; na subida do bot já verifica na hora.
    """
    from src.excel_store import SpreadsheetService
    from src.reminder_scheduler import overdue_reminder_slot

    now = datetime.now()
    today, slot_hour = overdue_reminder_slot(now)

    wb_path = _workbook_path_for_bot()
    if not wb_path or not Path(wb_path).exists():
        return

    svc = SpreadsheetService(wb_path)
    wb = svc._open_workbook(data_only=False)
    try:
        overdue = svc.list_overdue_deliveries(wb, today)
    finally:
        wb.close()

    if not overdue:
        return

    print(
        f"[Telegram] {len(overdue)} entrega(s) amarela(s) com data passada "
        f"(referência hoje: {today.strftime('%d/%m/%Y')})"
    )

    admin_chat = os.getenv("ADMIN_CHAT_ID", "").strip()
    for item in overdue[:15]:
        sale_id = str(item.get("id venda") or "").strip()
        if not sale_id or tracker.was_sent("atraso", sale_id, today, slot_hour):
            continue

        msg_txt = _build_overdue_delivery_message(item)
        chat_target = (item.get("chat id") or "").strip()
        sent = False
        if chat_target:
            if send_message(chat_target, msg_txt, parse_mode="Markdown"):
                _register_overdue_pending(
                    pending_overdue_delivery,
                    chat_target,
                    sale_id,
                    str(item.get("cliente") or ""),
                )
                sent = True
        if admin_chat:
            send_message(admin_chat, msg_txt, parse_mode="Markdown")
            _register_overdue_pending(
                pending_overdue_delivery,
                admin_chat,
                sale_id,
                str(item.get("cliente") or ""),
            )
            sent = True
        if not sent:
            continue

        tracker.mark_sent("atraso", sale_id, today, slot_hour)
        print(
            f"[Telegram] Cobrança entrega amarela ID VENDA {sale_id} slot {slot_hour:02d}h"
        )


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
    # Cache simples por chat: último nome de Cliente informado com sucesso.
    last_customer_by_chat: dict[int | str, str] = {}
    last_sale_id_by_chat: dict[int | str, str] = {}
    pending_overdue_delivery: dict[int | str, dict] = {}
    last_reminder_check = 0.0
    from src.reminder_scheduler import ReminderSlotTracker

    reminder_tracker = ReminderSlotTracker()

    print(
        f"[Telegram] Verificação inicial de entregas amarelas "
        f"(data de hoje: {date.today().strftime('%d/%m/%Y')})..."
    )
    try:
        _process_overdue_deliveries(reminder_tracker, pending_overdue_delivery)
    except Exception as e:
        print(f"[Telegram] Erro na verificação inicial de entregas: {e}")

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
            voice_payload = msg.get("voice") or msg.get("audio")
            if not text and voice_payload:
                file_id = voice_payload.get("file_id")
                if file_id:
                    try:
                        duration_sec = int(voice_payload.get("duration") or 0)
                        hinted_size = int(voice_payload.get("file_size") or 0)
                        send_message(
                            chat_id,
                            _audio_processing_wait_message(duration_sec),
                            parse_mode="Markdown",
                        )
                        send_chat_action(chat_id, "typing")
                        audio_path = download_telegram_voice(
                            file_id,
                            duration_sec=duration_sec,
                            hinted_file_size=hinted_size,
                        )
                        try:
                            whisper_model = os.getenv("WHISPER_MODEL", "small")
                            if duration_sec >= 60:
                                print(
                                    f"[Telegram] Transcrevendo audio longo ({duration_sec}s) "
                                    f"com modelo {whisper_model}..."
                                )
                            text = transcribe_audio(audio_path, model_size=whisper_model)
                            from_voice = True
                            preview_text = text
                            if len(preview_text) > 3500:
                                preview_text = preview_text[:3500] + "\n\n… _(texto truncado na exibição)_"
                            send_message(
                                chat_id,
                                "🎤 *Áudio entendido!*\n\n"
                                f"{preview_text}\n\n"
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
                        err = str(e).lower()
                        if "timeout" in err or "timed out" in err:
                            hint = (
                                "A conexão com o Telegram demorou demais para baixar o áudio.\n"
                                "Tente de novo com internet estável, ou envie um áudio mais curto / digite o texto."
                            )
                        else:
                            hint = str(e)
                        send_message(chat_id, f"Erro ao processar o áudio: {hint}")
                        print(f"[Telegram] Erro áudio: {e}")
                        continue

            if not chat_id:
                continue

            if text and _try_handle_overdue_delivery_reply(
                chat_id, text, pending_overdue_delivery, pending_preview
            ):
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
                pending_overdue_delivery.pop(chat_id, None)
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
                        _notify_spreadsheet_saving(chat_id, batch=True)
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
                    # Se ainda faltar Cliente (nome), não salva em fluxos de venda nova.
                    # Para atualização de status, entrega, material etc., usa-se o ID VENDA.
                    if parse_result.intent not in (
                        "status_update",
                        "delivery_update",
                        "delivery_finalize",
                        "payment_update",
                        "sale_delete",
                        "material_update",
                    ):
                        if "Cliente" in parse_result.missing_fields or not (cmd.customer or "").strip():
                            pending_preview[chat_id] = pending
                            send_message(
                                chat_id,
                                "Faltou o *Cliente* para salvar.\nEnvie por exemplo: `Cliente: Macdonald`.",
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
                        parse_result.intent not in ("status_update", "payment_update", "delivery_update", "delivery_finalize", "sale_delete")
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

                    _notify_spreadsheet_saving(chat_id, getattr(parse_result, "intent", ""))
                    reply = apply_parse_result(
                        parse_result,
                        origin=origin,
                        original_text=original_text,
                        chat_id=str(chat_id),
                    )
                    remembered = sale_id_from_parse_result(parse_result)
                    if remembered:
                        last_sale_id_by_chat[chat_id] = remembered
                    send_chat_action(chat_id, "upload_photo")
                    workbook_path = os.getenv("WORKBOOK_PATH", "").strip()
                    if not workbook_path:
                        from src.workbook_paths import default_workbook_path
                        workbook_path = default_workbook_path([Path.cwd(), Path.cwd().parent])
                    img_path = None
                    if workbook_path:
                        img_path = _maybe_build_sales_snippet_image(
                            workbook_path,
                            sale_id=getattr(parse_result.status_update_command, "sale_id", None)
                            if getattr(parse_result, "intent", "") == "status_update"
                            else getattr(parse_result.command, "sale_id", None),
                        )
                    try:
                        send_reply(
                            chat_id,
                            reply,
                            parse_mode="Markdown",
                            reply_markup=MAIN_MENU_KEYBOARD,
                            image_path=img_path,
                        )
                    finally:
                        if img_path:
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
                            repl = parse_message(text, reference_date=date.today())
                            if (
                                repl.intent == "sale_delete"
                                and repl.delete_command
                                and repl.delete_command.sale_id
                                and not repl.missing_fields
                            ):
                                pending_preview[chat_id] = {
                                    "parse_result": repl,
                                    "original_text": text,
                                    "origin": pending.get("origin", "telegram"),
                                }
                                send_message(chat_id, build_preview(repl), parse_mode="Markdown")
                                continue
                        if pending:
                            parse_result = pending["parse_result"]
                            cmd = parse_result.command
                            updated = apply_multi_field_corrections(
                                text, cmd, parse_result, reference_date=date.today()
                            )
                            if not updated:
                                updated = apply_preview_corrections(text, cmd)
                            if not updated and "ID VENDA" in parse_result.missing_fields:
                                supplemental_id = extract_supplemental_sale_id(text)
                                if supplemental_id:
                                    cmd.sale_id = supplemental_id
                                    dc = getattr(parse_result, "delete_command", None)
                                    if dc is not None:
                                        dc.sale_id = supplemental_id
                                    parse_result.missing_fields = [
                                        f for f in parse_result.missing_fields if f != "ID VENDA"
                                    ]
                                    updated = True
                            if updated:
                                if (cmd.customer or "").strip() and "Cliente" in parse_result.missing_fields:
                                    parse_result.missing_fields = [
                                        f for f in parse_result.missing_fields if f != "Cliente"
                                    ]
                                # Se o usuário forneceu o ID VENDA, remover da lista de missing.
                                if getattr(cmd, "sale_id", None) and "ID VENDA" in parse_result.missing_fields:
                                    parse_result.missing_fields = [
                                        f for f in parse_result.missing_fields if f != "ID VENDA"
                                    ]
                                dc = getattr(parse_result, "delete_command", None)
                                if dc is not None and getattr(cmd, "sale_id", None):
                                    dc.sale_id = str(cmd.sale_id).strip()
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
                        _notify_spreadsheet_saving(chat_id, getattr(parse_result, "intent", "sale"))
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
                            _notify_spreadsheet_saving(chat_id, getattr(parse_result, "intent", "sale"))
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

                # Lote: vários ID VENDA — entrega ou pagamento na mesma mensagem
                if _try_handle_batch_sale_updates(chat_id, text, pending_preview):
                    continue

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
                    if cmd_strip.startswith(("status", "resumo", "planilha", "prévia", "previa")):
                        send_chat_action(chat_id, "upload_photo")
                        caption, img_path = _build_dashboard_reply(cmd_strip)
                    else:
                        caption = process_command(text, origin="telegram")
                        img_path = None
                    try:
                        send_reply(
                            chat_id,
                            caption,
                            parse_mode="Markdown",
                            reply_markup=MAIN_MENU_KEYBOARD,
                            image_path=img_path,
                        )
                    finally:
                        if img_path:
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
                        f for f in parse_result.missing_fields if f != "Cliente"
                    ]
                    parsed_customer = explicit_customer
                if parsed_customer and parsed_customer != "-":
                    last_customer_by_chat[chat_id] = parsed_customer

                # Fallback: se faltou somente "Cliente", tente preencher com o último nome conhecido.
                if "Cliente" in parse_result.missing_fields:
                    cached_customer = None if should_replace_pending_preview(text) else last_customer_by_chat.get(chat_id)
                    if cached_customer:
                        parse_result.command.customer = cached_customer
                        parse_result.missing_fields = [
                            f for f in parse_result.missing_fields if f != "Cliente"
                        ]
                        print(f"[Telegram] Fallback de 'Cliente' usado no chat {chat_id}: {cached_customer}")

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

                # Inferência: gasto de material sem ID VENDA explícito — tenta achar a venda na planilha.
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
                                    customer_digits = re.sub(r"\D", "", customer_id)
                                    is_numeric_ref = bool(customer_digits) and customer_id.strip().isdigit()
                                    if is_numeric_ref:
                                        sale_rows = svc.get_pending_sale_by_sale_id(
                                            customer_id, max_rows_scan=500, include_paid=True
                                        )
                                    else:
                                        sale_rows = svc.get_pending_sales_by_customer(
                                            customer_id, max_rows_scan=500, include_paid=True
                                        )
                                    if not sale_rows and customer_digits:
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
                                            print(f"[Telegram] Inferido ID VENDA {inferred_sale_id} (chat {chat_id}).")
                    except Exception as e:
                        print(f"[Telegram] Falha na inferencia de ID VENDA: {e}")

                if parse_result.missing_fields:
                    missing_set = set(parse_result.missing_fields)

                    # Mostra prévia mesmo sem Cliente, para o usuário validar os demais campos.
                    if missing_set == {"Cliente"} and parse_result.intent in (
                        "sale",
                        "mixed_update",
                        "refund",
                        "status_update",
                        "delivery_update",
                        "delivery_finalize",
                        "material_update",
                        "sale_delete",
                    ):
                        preview_text = build_preview(parse_result)
                        send_message(
                            chat_id,
                            preview_text
                            + "\n\nFaltou apenas o *Cliente* (nome).\n"
                            + "Envie por exemplo: `Cliente: Macdonald`.",
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
                        "sale_delete",
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
                            build_missing_fields_message(
                                parse_result.missing_fields,
                                parse_result.intent,
                            ),
                            parse_mode="Markdown",
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
                    "sale_delete",
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

        # Lembretes: checagem a cada ~1 min; envio às 6h e a cada 2h no dia da entrega.
        if time.time() - last_reminder_check >= 60:
            last_reminder_check = time.time()
            try:
                _process_scheduled_reminders(reminder_tracker)
                _process_overdue_deliveries(reminder_tracker, pending_overdue_delivery)
            except Exception as e:
                print(f"[Telegram] Erro nos lembretes: {e}")


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
        "sale_delete",
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
    print("[Telegram] Iniciando bot...", flush=True)
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
        print("\n[Telegram] Bot encerrado por Ctrl+C.", flush=True)
        return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Telegram] Bot encerrado por Ctrl+C.", flush=True)
    except Exception as exc:
        print(f"\n[Telegram] Erro ao iniciar o bot: {exc}", flush=True)
        raise SystemExit(1) from exc
