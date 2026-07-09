# -*- coding: utf-8 -*-
"""Factory: Excel local ou Google Sheets conforme o .env."""
from __future__ import annotations

from pathlib import Path

from .excel_store import SpreadsheetService
from .spreadsheet_config import (
    google_credentials_path,
    google_sheets_id,
    spreadsheet_config_status,
    uses_google_sheets,
)
from .workbook_paths import default_workbook_path, resolve_workbook_path


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


def get_spreadsheet_service() -> SpreadsheetService:
    """Retorna SpreadsheetService (Excel ou Google via ponte openpyxl)."""
    if uses_google_sheets():
        status = spreadsheet_config_status()
        if not status.ready:
            raise FileNotFoundError(status.message)
        sheet_id = google_sheets_id()
        creds = google_credentials_path()
        if not sheet_id or creds is None:
            raise FileNotFoundError("Google Sheets incompleto no .env.")
        from .google_sheets_bridge import GoogleSheetsBridge

        bridge = GoogleSheetsBridge(sheet_id, creds)
        return SpreadsheetService(google_bridge=bridge)

    path = get_workbook_path()
    if not path or not Path(path).exists():
        raise FileNotFoundError(
            "Planilha Excel nao encontrada. Configure WORKBOOK_PATH no .env."
        )
    return SpreadsheetService(path)
