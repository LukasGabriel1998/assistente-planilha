# -*- coding: utf-8 -*-
"""Saúde do robô: detecta queda de rede/API e avisa o grupo admin."""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .runtime_paths import runtime_file

_LOCK = threading.Lock()
_NAME = "bot_health.json"

_SendFn = Callable[[str], bool]
_send_fn: _SendFn | None = None
_bot_label = "Robô"

_consecutive_failures = 0
_outage_started_at: float | None = None
_alerted_down = False
_last_ok_at: float | None = None
_last_error: str = ""

_outbound_failures = 0
_outbound_alerted = False
_started_at: float | None = None


def configure_sender(send_fn: _SendFn) -> None:
    global _send_fn
    _send_fn = send_fn


def configure_bot_label(label: str) -> None:
    global _bot_label
    text = (label or "").strip()
    _bot_label = text or "Robô"


def bot_label() -> str:
    return _bot_label


def _path(project_dir: Path) -> Path:
    return runtime_file(project_dir, _NAME)


def _load(project_dir: Path) -> dict[str, Any]:
    path = _path(project_dir)
    if not path.is_file():
        return {"pending": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"pending": []}
    if not isinstance(raw, dict):
        return {"pending": []}
    pending = raw.get("pending")
    if not isinstance(pending, list):
        pending = []
    return {"pending": pending}


def _save(project_dir: Path, data: dict[str, Any]) -> None:
    _path(project_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _enqueue(project_dir: Path, text: str) -> None:
    with _LOCK:
        data = _load(project_dir)
        pending = data.setdefault("pending", [])
        pending.append({"text": text, "at": time.time()})
        if len(pending) > 30:
            data["pending"] = pending[-30:]
        _save(project_dir, data)


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    mins, sec = divmod(seconds, 60)
    if mins < 60:
        return f"{mins} min" if sec < 15 else f"{mins} min {sec}s"
    hours, mins = divmod(mins, 60)
    return f"{hours}h {mins}min"


@lru_cache(maxsize=1)
def _local_tz() -> ZoneInfo:
    tz_name = (
        os.getenv("BOT_TIMEZONE")
        or os.getenv("TIMEZONE")
        or os.getenv("GOOGLE_CALENDAR_TIMEZONE")
        or "America/Sao_Paulo"
    ).strip()
    try:
        return ZoneInfo(tz_name or "America/Sao_Paulo")
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def _now_label() -> str:
    return datetime.now(_local_tz()).strftime("%d/%m %H:%M:%S")


def _sanitize_error(error: Exception | str) -> str:
    err = str(error or "").strip()
    if "bot" in err.lower() and "api.telegram.org" in err.lower():
        err = "falha de rede/DNS ao contato com api.telegram.org"
    elif len(err) > 180:
        err = err[:177] + "..."
    return err or "desconhecido"


def _with_bot_header(text: str) -> str:
    return f"🤖 *{bot_label()}*\n\n{text}"


def fail_threshold() -> int:
    try:
        return max(1, int(os.getenv("BOT_HEALTH_FAIL_THRESHOLD", "3") or "3"))
    except ValueError:
        return 3


def outbound_fail_threshold() -> int:
    try:
        return max(1, int(os.getenv("BOT_HEALTH_OUTBOUND_FAIL_THRESHOLD", "2") or "2"))
    except ValueError:
        return 2


def alerts_enabled() -> bool:
    raw = (os.getenv("BOT_HEALTH_ALERTS", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def try_send(text: str, *, project_dir: Path | None = None) -> bool:
    if not alerts_enabled():
        return False
    fn = _send_fn
    ok = False
    payload = _with_bot_header(text)
    if fn is not None:
        try:
            ok = bool(fn(payload))
        except Exception:
            ok = False
    if not ok and project_dir is not None:
        _enqueue(project_dir, payload)
    return ok


def flush_pending(project_dir: Path) -> int:
    if not alerts_enabled():
        return 0
    fn = _send_fn
    if fn is None:
        return 0
    with _LOCK:
        data = _load(project_dir)
        pending = list(data.get("pending") or [])
        data["pending"] = []
        _save(project_dir, data)
    sent = 0
    for item in pending:
        text = str((item or {}).get("text") or "").strip()
        if not text:
            continue
        try:
            if fn(text):
                sent += 1
            else:
                _enqueue(project_dir, text)
                break
        except Exception:
            _enqueue(project_dir, text)
            break
        time.sleep(0.15)
    return sent


def record_poll_ok(project_dir: Path) -> None:
    global _consecutive_failures, _outage_started_at, _alerted_down, _last_ok_at, _last_error
    global _outbound_failures, _outbound_alerted
    recovered = False
    downtime = 0.0
    failures = 0
    with _LOCK:
        now = time.time()
        recovered = _alerted_down or (_consecutive_failures >= fail_threshold())
        if _outage_started_at is not None:
            downtime = now - _outage_started_at
        failures = _consecutive_failures
        _consecutive_failures = 0
        _outage_started_at = None
        was_alerted = _alerted_down
        _alerted_down = False
        _last_ok_at = now
        _last_error = ""
        _outbound_failures = 0
        _outbound_alerted = False

    flush_pending(project_dir)
    if recovered and was_alerted:
        try_send(
            "✅ *Rede restabelecida*\n\n"
            f"Voltou a falar com o Telegram às *{_now_label()}*.\n"
            f"• Queda durou: *{_fmt_duration(downtime)}*\n"
            f"• Falhas seguidas no polling: *{failures}*\n\n"
            "_Mensagens e planilha devem voltar ao normal._",
            project_dir=project_dir,
        )


def record_poll_error(project_dir: Path, error: Exception | str) -> float:
    global _consecutive_failures, _outage_started_at, _alerted_down, _last_error
    err = _sanitize_error(error)

    with _LOCK:
        _consecutive_failures += 1
        _last_error = err
        if _outage_started_at is None:
            _outage_started_at = time.time()
        count = _consecutive_failures
        started = _outage_started_at
        already = _alerted_down

    wait = min(60.0, float(2 ** min(count, 5)))

    threshold = fail_threshold()
    if count >= threshold and not already:
        with _LOCK:
            _alerted_down = True
        elapsed = time.time() - (started or time.time())
        try_send(
            "🚨 *Alerta — não consigo receber mensagens*\n\n"
            f"O polling do Telegram falhou desde *{_ts_label(started)}* "
            f"_(há {_fmt_duration(elapsed)})_.\n\n"
            f"• Falhas seguidas: *{count}*\n"
            f"• Motivo: `{err}`\n\n"
            "_Quando a rede voltar, aviso aqui automaticamente._",
            project_dir=project_dir,
        )
    elif count > 0 and count % 20 == 0:
        try_send(
            "⚠️ *Ainda sem rede (polling)*\n\n"
            f"Continuo sem contato com o Telegram "
            f"({_fmt_duration(time.time() - (started or time.time()))}, "
            f"{count} falhas).\n"
            f"• Motivo: `{err}`",
            project_dir=project_dir,
        )
    return wait


def record_outbound_error(
    project_dir: Path,
    error: Exception | str,
    *,
    context: str = "enviar resposta ao usuário",
) -> None:
    global _outbound_failures, _outbound_alerted
    err = _sanitize_error(error)
    ctx = (context or "enviar mensagem").strip()

    with _LOCK:
        _outbound_failures += 1
        count = _outbound_failures
        already = _outbound_alerted

    threshold = outbound_fail_threshold()
    if count < threshold or already:
        return

    with _LOCK:
        _outbound_alerted = True

    try_send(
        "🚨 *Alerta — não consigo responder no chat*\n\n"
        f"Recebi mensagens, mas falhei ao *{ctx}* às *{_now_label()}*.\n\n"
        f"• Falhas seguidas ao enviar: *{count}*\n"
        f"• Motivo: `{err}`\n\n"
        "_Provável instabilidade de rede/DNS. Quando normalizar, aviso a recuperação._",
        project_dir=project_dir,
    )


def record_outbound_ok() -> None:
    global _outbound_failures, _outbound_alerted
    with _LOCK:
        _outbound_failures = 0
        _outbound_alerted = False


def record_startup() -> None:
    global _started_at
    with _LOCK:
        if _started_at is None:
            _started_at = time.time()


def _ago_label(ts: float | None) -> str:
    if ts is None:
        return "—"
    delta = max(0, int(time.time() - ts))
    if delta < 5:
        return "agora"
    return f"há {_fmt_duration(delta)}"


def _ts_label(ts: float | None) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts, tz=_local_tz()).strftime("%d/%m %H:%M:%S")


def format_status_report(*, spreadsheet_line: str = "") -> str:
    with _LOCK:
        failures = _consecutive_failures
        outage_started = _outage_started_at
        alerted = _alerted_down
        last_ok = _last_ok_at
        last_err = _last_error
        outbound_failures = _outbound_failures
        outbound_alerted = _outbound_alerted
        started = _started_at

    threshold = fail_threshold()
    outbound_threshold = outbound_fail_threshold()
    alerts_on = alerts_enabled()

    if alerted or failures >= threshold:
        poll_icon = "🔴"
        poll_state = "sem contato com o Telegram"
    elif failures > 0:
        poll_icon = "🟡"
        poll_state = "instável (tentando reconectar)"
    else:
        poll_icon = "🟢"
        poll_state = "conectado"

    lines = [
        f"📊 *Status — {bot_label()}*",
        "",
        f"{poll_icon} *Telegram (polling):* {poll_state}",
    ]

    if last_ok is not None and not (alerted or failures >= threshold):
        lines.append(f"• Último OK: *{_ts_label(last_ok)}* ({_ago_label(last_ok)})")
    elif outage_started is not None and (alerted or failures >= threshold):
        lines.append(
            f"• Sem polling desde: *{_ts_label(outage_started)}* ({_ago_label(outage_started)})"
        )
    elif last_ok is not None:
        lines.append(f"• Último OK: *{_ts_label(last_ok)}* ({_ago_label(last_ok)})")

    if failures > 0:
        lines.append(f"• Falhas seguidas no polling: *{failures}*")
    if last_err and (failures > 0 or alerted):
        lines.append(f"• Último erro: `{last_err}`")

    if outbound_alerted or outbound_failures >= outbound_threshold:
        lines.append("")
        lines.append("🔴 *Envio de mensagens:* com falhas recentes")
        lines.append(f"• Falhas seguidas ao enviar: *{outbound_failures}*")
    elif outbound_failures > 0:
        lines.append("")
        lines.append(f"🟡 *Envio de mensagens:* {outbound_failures} falha(s) recente(s)")

    if spreadsheet_line:
        lines.append("")
        lines.append(spreadsheet_line)

    lines.append("")
    if started is not None:
        lines.append(f"⏱ *Uptime:* {_fmt_duration(time.time() - started)}")
    lines.append(
        f"🔔 *Alertas:* {'ligados' if alerts_on else 'desligados'}"
        f" (polling ≥{threshold}, envio ≥{outbound_threshold})"
    )
    lines.append("")
    lines.append("_Atualize com_ `/status` _a qualquer momento._")
    return "\n".join(lines)


def notify_startup(project_dir: Path, *, bot_username: str = "") -> None:
    record_startup()
    if bot_label() == "Robô" and bot_username:
        configure_bot_label(f"@{bot_username.lstrip('@')}")
    flush_pending(project_dir)
    raw = (os.getenv("BOT_HEALTH_NOTIFY_ONLINE", "0") or "0").strip().lower()
    if raw not in {"1", "true", "yes", "on"} or not alerts_enabled():
        return
    try_send(
        "🟢 *Bot online*\n\n"
        f"Iniciado às *{_now_label()}*.\n"
        "_Alertas de queda de rede e falha ao responder estão ativos._",
        project_dir=project_dir,
    )


_last_event_at: dict[str, float] = {}


def notify_event(
    project_dir: Path,
    title: str,
    detail: str = "",
    *,
    cooldown_sec: float = 300.0,
    key: str = "",
) -> None:
    event_key = key or title
    now = time.time()
    with _LOCK:
        last = _last_event_at.get(event_key, 0.0)
        if now - last < cooldown_sec:
            return
        _last_event_at[event_key] = now
    body = f"📣 *{title}*\n\n_{_now_label()}_"
    if detail:
        body += f"\n\n{detail}"
    try_send(body, project_dir=project_dir)


def _truncate_text(text: str, limit: int = 200) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def _format_traceback(exc: Exception | str) -> str:
    if isinstance(exc, BaseException):
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        tb = str(exc)
    lines = [line.rstrip() for line in tb.strip().splitlines() if line.strip()]
    if len(lines) > 8:
        lines = ["..."] + lines[-7:]
    return "\n".join(lines)


def notify_processing_error(
    project_dir: Path,
    error: Exception | str,
    *,
    user_name: str = "",
    chat_id: int | str | None = None,
    message_text: str = "",
    context: str = "processar mensagem",
    cooldown_sec: float = 90.0,
) -> None:
    if not alerts_enabled():
        return

    err_text = _sanitize_error(error)
    who = (user_name or "Usuário").strip() or "Usuário"
    ctx = (context or "processar mensagem").strip()
    event_key = f"user_err:{chat_id or 'unknown'}:{type(error).__name__ if isinstance(error, BaseException) else 'err'}"
    now = time.time()
    with _LOCK:
        last = _last_event_at.get(event_key, 0.0)
        if now - last < cooldown_sec:
            return
        _last_event_at[event_key] = now

    lines = [
        "🐛 *Erro ao atender usuário*",
        "",
        f"• Quando: *{_now_label()}*",
        f"• Usuário: *{who}*",
    ]
    if chat_id is not None:
        lines.append(f"• Chat ID: `{chat_id}`")
    lines.append(f"• Ao: {ctx}")
    if message_text.strip():
        lines.append(f"• Mensagem: _{_truncate_text(message_text)}_")
    lines.extend(
        [
            "",
            f"• Erro: `{err_text}`",
        ]
    )
    tb = _format_traceback(error)
    if tb and tb != err_text:
        lines.append("")
        lines.append("_Detalhe técnico:_")
        for line in tb.splitlines()[-5:]:
            safe = line.replace("`", "'")[:140]
            if safe:
                lines.append(f"`{safe}`")
    lines.append("")
    lines.append("_O usuário já recebeu aviso no chat dele._")
    try_send("\n".join(lines), project_dir=project_dir)
