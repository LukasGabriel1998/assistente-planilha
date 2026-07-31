# -*- coding: utf-8 -*-
"""Estado persistente da troca de senha liberada pelo admin."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .runtime_paths import runtime_file

_LOCK = threading.Lock()
_NAME = "password_resets.json"


def _path(project_dir: Path) -> Path:
    return runtime_file(project_dir, _NAME)


def load_all(project_dir: Path) -> dict[str, Any]:
    path = _path(project_dir)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def save_all(project_dir: Path, data: dict[str, Any]) -> None:
    _path(project_dir).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get(project_dir: Path, chat_id: int | str) -> dict[str, Any] | None:
    with _LOCK:
        data = load_all(project_dir)
    item = data.get(str(chat_id))
    return item if isinstance(item, dict) else None


def set_state(project_dir: Path, chat_id: int | str, state: dict[str, Any]) -> None:
    with _LOCK:
        data = load_all(project_dir)
        data[str(chat_id)] = state
        save_all(project_dir, data)


def clear(project_dir: Path, chat_id: int | str) -> None:
    with _LOCK:
        data = load_all(project_dir)
        if str(chat_id) in data:
            del data[str(chat_id)]
            save_all(project_dir, data)
