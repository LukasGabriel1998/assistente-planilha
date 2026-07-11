# -*- coding: utf-8 -*-
"""Factory: Excel local ou Google Sheets conforme o .env."""
from __future__ import annotations

import threading
from pathlib import Path

from .excel_store import SpreadsheetService
from .spreadsheet_config import (
    google_credentials_path,
    google_sheets_id,
    spreadsheet_config_status,
    uses_google_sheets,
)
from .workbook_paths import default_workbook_path, resolve_workbook_path

# Uma única ponte Google por processo: reusa auth, abas e cache em memória.
# Sem isso, cada save reabria a planilha do zero (e podia levar ~1 min).
_service_lock = threading.Lock()
_cached_service: SpreadsheetService | None = None
_cached_service_key: tuple[str, str] | None = None


def spreadsheet_is_ready() -> bool:
    status = spreadsheet_config_status()
    return status.ready


def get_workbook_path() -> str:
    """Caminho Excel local; vazio quando o backend é Google."""
    if uses_google_sheets():
        return ""
    import os

    env_path = os.getenv("WORKBOOK_PATH", "").strip()
    if env_path:
        try:
            return str(resolve_workbook_path(env_path))
        except Exception:
            pass
    roots = [Path.cwd()]
    if Path.cwd().parent.exists():
        roots.append(Path.cwd().parent)
    return default_workbook_path(roots) or ""


def clear_spreadsheet_service_cache() -> None:
    """Invalida o serviço em cache (útil após troca de .env em runtime)."""
    global _cached_service, _cached_service_key
    with _service_lock:
        bridge = getattr(_cached_service, "_google_bridge", None) if _cached_service else None
        if bridge is not None:
            try:
                bridge.invalidate_cache()
            except Exception:
                pass
        _cached_service = None
        _cached_service_key = None


def get_spreadsheet_service() -> SpreadsheetService:
    """Retorna SpreadsheetService (Excel ou Google via ponte openpyxl).

    No backend Google, reusa a mesma instância (auth + cache) entre as mensagens.
    """
    global _cached_service, _cached_service_key

    if uses_google_sheets():
        status = spreadsheet_config_status()
        if not status.ready:
            raise FileNotFoundError(status.message)
        sheet_id = google_sheets_id()
        creds = google_credentials_path()
        if not sheet_id or creds is None:
            raise FileNotFoundError("Google Sheets incompleto no .env.")
        key = (sheet_id, str(creds.resolve()))
        with _service_lock:
            if (
                _cached_service is not None
                and _cached_service_key == key
                and getattr(_cached_service, "_google_bridge", None) is not None
            ):
                return _cached_service
            from .google_sheets_bridge import GoogleSheetsBridge

            bridge = GoogleSheetsBridge(sheet_id, creds)
            _cached_service = SpreadsheetService(google_bridge=bridge)
            _cached_service_key = key
            return _cached_service

    path = get_workbook_path()
    if not path or not Path(path).exists():
        raise FileNotFoundError(
            "Planilha Excel nao encontrada. Configure WORKBOOK_PATH no .env."
        )
    # Excel local: arquivo no disco; instância leve, sem cache global necessário.
    return SpreadsheetService(path)
