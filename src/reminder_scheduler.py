# -*- coding: utf-8 -*-
"""Agenda de lembretes: início às 6h e repetição a cada 2h no dia da entrega."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_START_HOUR = 6
DEFAULT_END_HOUR = 22
DEFAULT_INTERVAL_HOURS = 2


def reminder_start_hour() -> int:
    return int(os.getenv("REMINDER_START_HOUR", str(DEFAULT_START_HOUR)))


def reminder_end_hour() -> int:
    return int(os.getenv("REMINDER_END_HOUR", str(DEFAULT_END_HOUR)))


def reminder_interval_hours() -> int:
    return int(os.getenv("REMINDER_INTERVAL_HOURS", str(DEFAULT_INTERVAL_HOURS)))


def current_reminder_slot(now: datetime | None = None) -> tuple[date, int] | None:
    """
    Retorna (dia, hora_do_slot) se estivermos em uma janela de lembrete.
    Ex.: das 6h às 7h59 -> (hoje, 6); das 8h às 9h59 -> (hoje, 8).
  """
    now = now or datetime.now()
    hour = now.hour
    start = reminder_start_hour()
    end = reminder_end_hour()
    interval = max(1, reminder_interval_hours())
    if hour < start or hour > end:
        return None
    slot_hour = start + ((hour - start) // interval) * interval
    if slot_hour > end:
        return None
    return now.date(), slot_hour


def reminder_state_path() -> Path:
    custom = os.getenv("REMINDER_STATE_PATH", "").strip()
    if custom:
        return Path(custom)
    return Path.cwd() / ".reminder_slots_sent.json"


class ReminderSlotTracker:
    """Evita reenviar o mesmo lembrete no mesmo slot (entrega ou cobrança)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or reminder_state_path()
        self._sent: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._sent = {str(x) for x in data}
        except Exception:
            self._sent = set()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(sorted(self._sent), ensure_ascii=False, indent=0),
                encoding="utf-8",
            )
        except Exception:
            pass

    @staticmethod
    def _key(kind: str, sale_id: str, day: date, slot_hour: int) -> str:
        return f"{kind}:{sale_id}:{day.isoformat()}:{slot_hour}"

    def was_sent(self, kind: str, sale_id: str, day: date, slot_hour: int) -> bool:
        return self._key(kind, sale_id, day, slot_hour) in self._sent

    def mark_sent(self, kind: str, sale_id: str, day: date, slot_hour: int) -> None:
        self._sent.add(self._key(kind, sale_id, day, slot_hour))
        self._prune_old(day)
        self._save()

    def _prune_old(self, today: date) -> None:
        cutoff = today - timedelta(days=7)
        kept: set[str] = set()
        for key in self._sent:
            parts = key.split(":")
            if len(parts) < 4:
                continue
            try:
                key_day = date.fromisoformat(parts[2])
            except ValueError:
                continue
            if key_day >= cutoff:
                kept.add(key)
        self._sent = kept
