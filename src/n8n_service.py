# -*- coding: utf-8 -*-
"""
Serviço HTTP para integração com n8n (WhatsApp, Telegram, etc.).
Reutiliza parser, prévia e gravação da planilha do bot Telegram.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from .bot_processor import (
    SUMMARY_KEYWORDS,
    STATUS_KEYWORDS,
    PREVIEW_KEYWORDS,
    apply_parse_result,
    build_preview,
    get_default_workbook,
    process_command,
)
from .parser import ParseResult, apply_multi_field_corrections, parse_message
from .transcription import TranscriptionError, transcribe_audio

CONFIRM_WORDS = frozenset(
    {"sim", "confirmar", "ok", "confirmo", "pode salvar", "salvar", "s"}
)
CANCEL_WORDS = frozenset({"não", "nao", "cancelar", "cancela", "n"})

_sessions: dict[str, dict[str, Any]] = {}


def _is_short_read_command(text: str) -> bool:
    cmd_strip = text.lower().strip()
    keywords = SUMMARY_KEYWORDS + STATUS_KEYWORDS + PREVIEW_KEYWORDS
    return any(cmd_strip.startswith(kw) for kw in keywords)


def _apply_field_correction(parse_result: ParseResult, text: str) -> bool:
    """Correções pontuais na prévia (cliente, produto, valor, id venda)."""
    return apply_multi_field_corrections(text, parse_result.command, parse_result)


def _parse_result_summary(parse_result: ParseResult) -> dict[str, Any]:
    cmd = parse_result.command
    return {
        "intent": parse_result.intent,
        "missing_fields": list(parse_result.missing_fields),
        "customer": getattr(cmd, "customer", None),
        "sale_id": getattr(cmd, "sale_id", None),
        "total_value": getattr(cmd, "total_value", None),
        "product_id": getattr(cmd, "product_id", None),
    }


def handle_message(
    conversation_id: str,
    text: str,
    *,
    channel: str = "n8n",
    action: str | None = None,
) -> dict[str, Any]:
    """
    Processa mensagem vinda do n8n.

    action: None | confirm | cancel (opcional; se omitido, detecta SIM/NÃO no texto)
    """
    conv = (conversation_id or "default").strip()
    raw = (text or "").strip()
    origin = f"n8n:{channel}" if channel else "n8n"
    lower = raw.lower()

    workbook = get_default_workbook()
    if not workbook:
        return {
            "ok": False,
            "conversation_id": conv,
            "reply": "Planilha nao encontrada. Configure WORKBOOK_PATH no .env.",
            "needs_confirmation": False,
            "applied": False,
        }

    act = (action or "").strip().lower()
    if act == "cancel" or (lower in CANCEL_WORDS and conv in _sessions):
        _sessions.pop(conv, None)
        return {
            "ok": True,
            "conversation_id": conv,
            "reply": "Cancelado. Pode enviar os dados de novo quando quiser.",
            "needs_confirmation": False,
            "applied": False,
            "cancelled": True,
        }

    if act == "confirm" or (lower in CONFIRM_WORDS and conv in _sessions):
        pending = _sessions.pop(conv, None)
        if not pending:
            return {
                "ok": True,
                "conversation_id": conv,
                "reply": "Nao ha previa pendente para confirmar.",
                "needs_confirmation": False,
                "applied": False,
            }
        batch = pending.get("batch_parse_results")
        if batch:
            replies: list[str] = []
            for pr in batch:
                replies.append(
                    apply_parse_result(
                        pr,
                        origin=pending.get("origin", origin),
                        original_text=pending.get("original_text", raw),
                        chat_id=conv,
                    )
                )
            return {
                "ok": True,
                "conversation_id": conv,
                "reply": "\n\n".join(replies),
                "needs_confirmation": False,
                "applied": True,
                "batch": True,
            }
        pr: ParseResult = pending["parse_result"]
        reply = apply_parse_result(
            pr,
            origin=pending.get("origin", origin),
            original_text=pending.get("original_text", raw),
            chat_id=conv,
        )
        return {
            "ok": True,
            "conversation_id": conv,
            "reply": reply,
            "needs_confirmation": False,
            "applied": True,
            "parse_summary": _parse_result_summary(pr),
        }

    if conv in _sessions and raw:
        pending = _sessions[conv]
        if _apply_field_correction(pending["parse_result"], raw):
            preview = build_preview(pending["parse_result"])
            return {
                "ok": True,
                "conversation_id": conv,
                "reply": preview,
                "needs_confirmation": True,
                "preview": preview,
                "applied": False,
                "parse_summary": _parse_result_summary(pending["parse_result"]),
            }
        return {
            "ok": True,
            "conversation_id": conv,
            "reply": (
                "Ha uma previa pendente. Responda SIM para salvar, NAO para cancelar, "
                "ou envie correcao (ex.: Cliente: Ana, Valor: 1500)."
            ),
            "needs_confirmation": True,
            "applied": False,
        }

    if not raw:
        return {
            "ok": False,
            "conversation_id": conv,
            "reply": "Mensagem vazia.",
            "needs_confirmation": False,
            "applied": False,
        }

    if _is_short_read_command(raw):
        reply = process_command(raw, origin=origin)
        return {
            "ok": True,
            "conversation_id": conv,
            "reply": reply,
            "needs_confirmation": False,
            "applied": True,
            "read_only": True,
        }

    parse_result = parse_message(raw, reference_date=date.today())

    if parse_result.missing_fields:
        missing_set = set(parse_result.missing_fields)
        if missing_set <= {"ID Cliente", "ID VENDA"} and parse_result.intent in (
            "sale",
            "mixed_update",
            "refund",
            "status_update",
            "delivery_update",
            "delivery_finalize",
            "material_update",
            "sale_delete",
        ):
            preview = build_preview(parse_result)
            extra = ""
            if "ID Cliente" in missing_set:
                extra = "\n\nFaltou apenas o ID Cliente. Envie ex.: cliente id 004."
            elif "ID VENDA" in missing_set:
                extra = "\n\nFaltou apenas o ID VENDA. Envie ex.: id venda 002."
            _sessions[conv] = {
                "parse_result": parse_result,
                "original_text": raw,
                "origin": origin,
            }
            return {
                "ok": True,
                "conversation_id": conv,
                "reply": preview + extra,
                "needs_confirmation": True,
                "preview": preview,
                "applied": False,
                "parse_summary": _parse_result_summary(parse_result),
            }
        return {
            "ok": False,
            "conversation_id": conv,
            "reply": "Faltam dados: " + ", ".join(parse_result.missing_fields),
            "needs_confirmation": False,
            "applied": False,
            "missing_fields": parse_result.missing_fields,
        }

    preview = build_preview(parse_result)
    _sessions[conv] = {
        "parse_result": parse_result,
        "original_text": raw,
        "origin": origin,
    }
    return {
        "ok": True,
        "conversation_id": conv,
        "reply": preview,
        "needs_confirmation": True,
        "preview": preview,
        "applied": False,
        "parse_summary": _parse_result_summary(parse_result),
    }


def transcribe_audio_file(audio_path: str, model_size: str | None = None) -> dict[str, Any]:
    import os

    size = (model_size or os.getenv("WHISPER_MODEL", "small")).strip() or "small"
    try:
        text = transcribe_audio(audio_path, model_size=size)
        return {"ok": True, "text": text}
    except TranscriptionError as exc:
        return {"ok": False, "error": str(exc)}


def clear_session(conversation_id: str) -> bool:
    return _sessions.pop((conversation_id or "").strip(), None) is not None


def health_info() -> dict[str, Any]:
    from pathlib import Path

    wb = get_default_workbook()
    return {
        "ok": True,
        "workbook_path": wb,
        "workbook_exists": bool(wb and Path(wb).is_file()),
        "pending_sessions": len(_sessions),
    }
