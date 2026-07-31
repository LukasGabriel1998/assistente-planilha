# -*- coding: utf-8 -*-
"""Caixa de entrada do admin — pedidos de troca de senha."""
from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from .runtime_paths import runtime_file

_LOCK = threading.Lock()
_INBOX_NAME = "admin_inbox.json"

ItemType = str
ItemStatus = str


def _inbox_path(project_dir: Path) -> Path:
    return runtime_file(project_dir, _INBOX_NAME)


def _empty() -> dict[str, Any]:
    return {"items": []}


def load_inbox(project_dir: Path) -> dict[str, Any]:
    path = _inbox_path(project_dir)
    if not path.is_file():
        return _empty()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty()
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        return _empty()
    return raw


def save_inbox(project_dir: Path, data: dict[str, Any]) -> None:
    _inbox_path(project_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def close_open_for_chat(
    project_dir: Path,
    chat_id: int | str,
    item_type: ItemType,
    *,
    status: ItemStatus = "superseded",
) -> int:
    closed = 0
    with _LOCK:
        data = load_inbox(project_dir)
        for item in data["items"]:
            if not isinstance(item, dict):
                continue
            if item.get("status") != "open":
                continue
            if item.get("type") != item_type:
                continue
            if str(item.get("chat_id")) != str(chat_id):
                continue
            item["status"] = status
            item["done_at"] = time.time()
            closed += 1
        if closed:
            save_inbox(project_dir, data)
    return closed


def add_item(
    project_dir: Path,
    *,
    item_type: ItemType,
    chat_id: int | str,
    user_name: str = "",
    username: str = "",
    text: str = "",
) -> dict[str, Any]:
    if item_type == "password_help":
        close_open_for_chat(project_dir, chat_id, "password_help")
    item = {
        "id": secrets.token_hex(4),
        "type": item_type,
        "chat_id": chat_id,
        "user_name": (user_name or "").strip(),
        "username": (username or "").strip(),
        "text": (text or "").strip(),
        "created_at": time.time(),
        "status": "open",
    }
    with _LOCK:
        data = load_inbox(project_dir)
        data["items"].append(item)
        save_inbox(project_dir, data)
    return item


def set_status(
    project_dir: Path,
    item_id: str,
    status: ItemStatus,
    **extra: Any,
) -> dict[str, Any] | None:
    with _LOCK:
        data = load_inbox(project_dir)
        for item in data["items"]:
            if isinstance(item, dict) and str(item.get("id")) == str(item_id):
                item["status"] = status
                item["done_at"] = time.time()
                for key, value in extra.items():
                    item[key] = value
                save_inbox(project_dir, data)
                return item
    return None


def get_item(project_dir: Path, item_id: str) -> dict[str, Any] | None:
    with _LOCK:
        data = load_inbox(project_dir)
    for item in data["items"]:
        if isinstance(item, dict) and str(item.get("id")) == str(item_id):
            return item
    return None
