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
    process_command,
)
from src.parser import parse_message
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

HELP_TEXT = """Olá! Eu atualizo a planilha com vendas, estornos e status.

📝 **Texto ou 🎤 áudio** – tanto faz: você pode *escrever* ou *gravar um áudio*. Eu interpreto do mesmo jeito e mostro uma prévia antes de salvar.

📋 **Resumo da planilha**
*Resumo* ou *Status* ou *Planilha*

💰 **Registrar venda** (texto ou áudio)
Exemplo (igual ao app):
• Hoje vendi uma placa para a cliente Ana Flores por 3000, ela pagou metade agora e o restante dia 15

🔁 **Atualizar venda existente por ID VENDA** (texto ou áudio)
Exemplo (igual ao app):
• Depois voce pode falar: ID VENDA 1001, ja pagou tudo, atualiza para pago

🔄 **Estorno**
Exemplo:
• Estorno da venda 123

✏️ **Status / Quitação**
Exemplos:
• Cliente João pagou o saldo
• ID VENDA 1001, ja pagou tudo, atualiza para pago

Antes de salvar mostro uma *prévia*. Quer alterar? Envie a correção. Tudo certo? Responda *SIM* ou *OK* para salvar na planilha."""

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

    labels = [
        "Total Vendas",
        "total de vendas (pago)",
        "Valor (pendente)",
        "Total Compras Materia Prima",
        "Gastos Fixos",
        "Lucro",
    ]
    values = [_brl(total_sales), _brl(total_paid), _brl(total_pending), _brl(total_mat), _brl(total_fix), _brl(lucro)]

    # Layout parecido com a área da planilha mostrada pelo usuário
    col_widths = [190, 230, 210, 290, 170, 160]
    title_h = 54
    head_h = 44
    val_h = 48
    pad = 12
    width = sum(col_widths) + (pad * 2)
    height = title_h + head_h + val_h + (pad * 2)

    img = Image.new("RGB", (width, height), (246, 249, 252))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    navy = (9, 47, 99)
    header_bg = (210, 228, 237)
    border = (65, 88, 112)
    black = (26, 26, 26)
    green = (0, 153, 76)

    # Título
    draw.rectangle((pad, pad, width - pad, pad + title_h), fill=navy, outline=border, width=1)
    title = "TOTAL DOS LUCROS MENSAIS E ANUAIS"
    tw = draw.textlength(title, font=font)
    draw.text((int((width - tw) / 2), pad + 18), title, fill=(255, 255, 255), font=font)

    y_head = pad + title_h
    y_val = y_head + head_h
    x = pad
    for idx, w in enumerate(col_widths):
        draw.rectangle((x, y_head, x + w, y_head + head_h), fill=header_bg, outline=border, width=1)
        draw.rectangle((x, y_val, x + w, y_val + val_h), fill=(255, 255, 255), outline=border, width=1)
        draw.text((x + 8, y_head + 13), labels[idx], fill=black, font=font)
        val_color = green if idx == len(col_widths) - 1 else black
        draw.text((x + 8, y_val + 15), values[idx], fill=val_color, font=font)
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
                                "🎤 *Interpretação do áudio:*\n\n" + text + "\n\n"
                                "Abaixo mostro o que será salvo. Confira e responda *SIM* para confirmar "
                                "ou envie a *correção* por texto.",
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
                    # Para atualização de status, nao exigimos cmd.customer (o ID Cliente nao vem no texto sintetizado).
                    if parse_result.intent != "status_update":
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
                    if (cmd.service_due_date is None) and ((cmd.total_value or 0.0) > 0.01) and (pending_amount <= 0.01):
                        pending_delivery[chat_id] = pending
                        send_message(
                            chat_id,
                            "Qual a *Data de Entrega* deste serviço? (ex.: 20/03 ou 20/03/2026)\n"
                            "Responda somente com a data.",
                            parse_mode="Markdown",
                        )
                        continue

                    reply = apply_parse_result(
                        parse_result,
                        origin=origin,
                        original_text=original_text,
                        chat_id=str(chat_id),
                    )
                    send_message(chat_id, reply)
                    print(f"[Telegram] Planilha atualizada para {chat_id}")
                    continue

                # Cancelar prévia
                cancel_words = ("não", "nao", "cancelar", "cancela")
                if text.strip().lower() in cancel_words and chat_id in pending_preview:
                    pending_preview.pop(chat_id, None)
                    send_message(chat_id, "Cancelado. Pode enviar os dados de novo quando quiser.")
                    continue

                # Correção pontual da prévia (Cliente/Produto/Valor) antes de confirmar
                if chat_id in pending_preview and text.strip():
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
                            import re

                            m = re.search(r"(\\d{1,3}(?:[\\.\\s]\\d{3})*(?:,\\d{1,2})?|\\d+(?:,\\d{1,2})?)", text)
                            if m:
                                raw = m.group(1)
                                raw_norm = raw.replace(".", "").replace(" ", "").replace(",", ".")
                                try:
                                    new_total = float(raw_norm)
                                    cmd.total_value = new_total
                                    updated = True
                                except Exception:
                                    pass
                        if updated:
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
                        from datetime import datetime
                        pending = pending_delivery.get(chat_id)
                        if not pending:
                            continue
                        raw = text.strip()
                        parsed = None
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
                        reply = apply_parse_result(
                            parse_result,
                            origin=pending.get("origin", "telegram"),
                            original_text=pending.get("original_text", ""),
                            chat_id=str(chat_id),
                        )
                        send_message(chat_id, reply)
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
                            send_message(chat_id, reply)
                        continue

                # Atualizar status baseado em ID do cliente (ex.: "Cliente ID 002 pagou")
                # Isso evita depender de "ID VENDA" em mensagens curtas.
                try:
                    import re
                    lower = text.strip().lower()
                    # Ignora se for criação de venda (para não confundir "cliente ... pagou" dentro de venda).
                    sale_tokens = ("vendi", "fechei", "fechamos", "acabei de fazer uma venda", "fiz uma venda", "fiz um", "comprou")
                    if (
                        "cliente" in lower
                        and ("pagou" in lower or "pago" in lower)
                        and not any(tok in lower for tok in sale_tokens)
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

                            workbook_path = os.getenv("WORKBOOK_PATH", "").strip()
                            if not workbook_path:
                                from src.workbook_paths import default_workbook_path
                                workbook_path = default_workbook_path([Path.cwd(), Path.cwd().parent])

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
                    send_message(chat_id, reply)
                    # Para Status/Resumo/Planilha, também envia uma imagem do resumo (facilita visualização).
                    if cmd_strip.startswith(("status", "resumo", "planilha")):
                        workbook_path = os.getenv("WORKBOOK_PATH", "").strip()
                        if not workbook_path:
                            from src.workbook_paths import default_workbook_path
                            workbook_path = default_workbook_path([Path.cwd(), Path.cwd().parent])
                        img_path = _maybe_build_status_table_image(workbook_path) if workbook_path else None
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
                parse_result = parse_message(text, reference_date=date.today())

                # Atualiza cache quando conseguir extrair cliente.
                parsed_customer = (getattr(parse_result.command, "customer", "") or "").strip()
                if parsed_customer and parsed_customer != "-":
                    last_customer_by_chat[chat_id] = parsed_customer

                # Fallback: se faltou somente "ID Cliente", tente preencher com o último conhecido.
                if "ID Cliente" in parse_result.missing_fields:
                    cached_customer = last_customer_by_chat.get(chat_id)
                    if cached_customer:
                        parse_result.command.customer = cached_customer
                        parse_result.missing_fields = [
                            f for f in parse_result.missing_fields if f != "ID Cliente"
                        ]
                        print(f"[Telegram] Fallback de 'ID Cliente' usado no chat {chat_id}: {cached_customer}")

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
                    if missing_set == {"ID Cliente"} and parse_result.intent in ("sale", "mixed_update", "refund", "status_update"):
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

                    if missing_set == {"ID VENDA"} and parse_result.intent in ("sale", "mixed_update", "refund", "status_update"):
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
                if parse_result.intent in ("sale", "mixed_update", "refund", "status_update"):
                    preview_text = build_preview(parse_result)
                    send_message(chat_id, preview_text, parse_mode="Markdown")
                    pending_preview[chat_id] = {
                        "parse_result": parse_result,
                        "original_text": text,
                        "origin": "audio" if from_voice else "telegram",
                    }
                    continue

                # Outros casos (ex.: só texto que não é venda/estorno): processar direto
                reply = process_command(text, origin="telegram")
                send_message(chat_id, reply)
            except Exception as e:
                reply = f"Erro: {e}"
                send_message(chat_id, reply)
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

    if parse_result.intent in ("sale", "mixed_update", "refund", "status_update"):
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
