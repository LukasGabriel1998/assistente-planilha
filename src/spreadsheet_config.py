# -*- coding: utf-8 -*-
"""Configuração da planilha: Google Sheets (padrão) ou Excel local (legado)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

BACKEND_GOOGLE = "google"
BACKEND_EXCEL = "excel"


def _clean_env(value: str) -> str:
    value = (value or "").strip().strip('"').strip("'")
    return value


def spreadsheet_backend() -> str:
    """Retorna 'google' ou 'excel'. Google é o padrão quando SPREADSHEET_BACKEND=google."""
    explicit = _clean_env(os.getenv("SPREADSHEET_BACKEND", "")).lower()
    if explicit in (BACKEND_GOOGLE, BACKEND_EXCEL):
        return explicit
    if google_sheets_id():
        return BACKEND_GOOGLE
    return BACKEND_EXCEL


def uses_google_sheets() -> bool:
    return spreadsheet_backend() == BACKEND_GOOGLE


def google_sheets_id() -> str:
    return _clean_env(os.getenv("GOOGLE_SHEETS_ID", ""))


def google_sheets_url() -> str:
    sheet_id = google_sheets_id()
    if not sheet_id:
        return ""
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


def google_credentials_path() -> Path | None:
    for key in ("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_APPLICATION_CREDENTIALS"):
        raw = _clean_env(os.getenv(key, ""))
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_DIR / path
        return path
    return None


@dataclass(frozen=True)
class SpreadsheetConfigStatus:
    backend: str
    ready: bool
    message: str
    sheets_id: str = ""
    credentials_path: str = ""


def spreadsheet_config_status() -> SpreadsheetConfigStatus:
    backend = spreadsheet_backend()
    if backend == BACKEND_GOOGLE:
        sheet_id = google_sheets_id()
        creds = google_credentials_path()
        creds_display = str(creds) if creds else ""
        if not sheet_id:
            return SpreadsheetConfigStatus(
                backend=backend,
                ready=False,
                message="GOOGLE_SHEETS_ID vazio no .env — cole o ID da planilha que voce vai compartilhar.",
                credentials_path=creds_display,
            )
        if creds is None:
            return SpreadsheetConfigStatus(
                backend=backend,
                ready=False,
                message="Credenciais Google ausentes — defina GOOGLE_SERVICE_ACCOUNT_JSON no .env.",
                sheets_id=sheet_id,
            )
        if not creds.is_file():
            return SpreadsheetConfigStatus(
                backend=backend,
                ready=False,
                message=f"Arquivo de credenciais nao encontrado: {creds}",
                sheets_id=sheet_id,
                credentials_path=creds_display,
            )
        return SpreadsheetConfigStatus(
            backend=backend,
            ready=True,
            message=f"Google Sheets configurado ({sheet_id[:12]}...).",
            sheets_id=sheet_id,
            credentials_path=creds_display,
        )

    workbook = _clean_env(os.getenv("WORKBOOK_PATH", ""))
    if workbook and Path(workbook).is_file():
        return SpreadsheetConfigStatus(
            backend=backend,
            ready=True,
            message=f"Planilha Excel local: {workbook}",
        )
    return SpreadsheetConfigStatus(
        backend=backend,
        ready=False,
        message="Planilha Excel nao encontrada — configure WORKBOOK_PATH no .env.",
    )
