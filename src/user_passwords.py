# -*- coding: utf-8 -*-
"""Senhas pessoais por chat_id (hash PBKDF2 — sem texto puro)."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from pathlib import Path
from typing import Any

from .runtime_paths import runtime_file

_LOCK = threading.Lock()
_USERS_NAME = "user_passwords.json"
_ITERATIONS = 120_000


def _path(project_dir: Path) -> Path:
    return runtime_file(project_dir, _USERS_NAME)


def _load(project_dir: Path) -> dict[str, Any]:
    path = _path(project_dir)
    if not path.is_file():
        return {"users": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"users": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("users"), dict):
        return {"users": {}}
    return raw


def _save(project_dir: Path, data: dict[str, Any]) -> None:
    _path(project_dir).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _key(chat_id: int | str) -> str:
    return str(chat_id)


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _ITERATIONS,
    )
    return digest.hex()


def set_password(project_dir: Path, chat_id: int | str, password: str) -> None:
    cleaned = (password or "").strip()
    salt = secrets.token_hex(16)
    entry = {
        "salt": salt,
        "hash": _hash_password(cleaned, salt),
        "iterations": _ITERATIONS,
    }
    with _LOCK:
        data = _load(project_dir)
        data["users"][_key(chat_id)] = entry
        _save(project_dir, data)


def verify_password(project_dir: Path, chat_id: int | str, password: str) -> bool:
    cleaned = (password or "").strip()
    with _LOCK:
        data = _load(project_dir)
        entry = data["users"].get(_key(chat_id))
    if not isinstance(entry, dict):
        return False
    salt = str(entry.get("salt") or "")
    expected = str(entry.get("hash") or "")
    if not salt or not expected:
        return False
    attempt = _hash_password(cleaned, salt)
    return hmac.compare_digest(attempt, expected)


def has_password(project_dir: Path, chat_id: int | str) -> bool:
    with _LOCK:
        data = _load(project_dir)
        entry = data["users"].get(_key(chat_id))
    return isinstance(entry, dict) and bool(entry.get("hash"))
