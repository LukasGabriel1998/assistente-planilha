# -*- coding: utf-8 -*-
"""
Ponte Google Sheets ↔ openpyxl.

Leitura: 1 export .xlsx por abertura (em vez de 1 requisição por célula).
Gravação: batch_update agrupado (em vez de update_acell por célula).
"""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from .google_sheets_api import GoogleSheetsQuotaError, sheets_call

# Mesmo limite usado pelo excel_store.
_MAX_SYNC_ROW = 1048575
_MAX_SYNC_COL = 26  # A..Z


class GoogleSheetsBridge:
    def __init__(self, sheet_id: str, credentials_path: str | Path) -> None:
        self.sheet_id = sheet_id.strip()
        self.credentials_path = Path(credentials_path)
        if not self.credentials_path.is_file():
            raise FileNotFoundError(f"Credenciais Google nao encontradas: {self.credentials_path}")
        self._client = None
        self._spreadsheet = None
        self._worksheets: dict[str, Any] = {}
        self._baseline: dict[str, dict[str, Any]] = {}

    def _authorize(self):
        if self._client is not None:
            return self._client
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(str(self.credentials_path), scopes=scopes)
        self._client = gspread.authorize(creds)
        return self._client

    def _spreadsheet_obj(self):
        if self._spreadsheet is None:
            self._spreadsheet = sheets_call(
                lambda: self._authorize().open_by_key(self.sheet_id),
            )
        return self._spreadsheet

    def _worksheet(self, title: str):
        if title not in self._worksheets:
            spreadsheet = self._spreadsheet_obj()

            def _open():
                try:
                    return spreadsheet.worksheet(title)
                except Exception:
                    for ws in spreadsheet.worksheets():
                        if ws.title == title:
                            return ws
                    raise

            self._worksheets[title] = sheets_call(_open)
        return self._worksheets[title]

    @staticmethod
    def _serialize_value(value: Any) -> str | int | float:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        return str(value)

    @staticmethod
    def _cell_key(row: int, col: int) -> str:
        return f"{get_column_letter(col)}{row}"

    def _snapshot_workbook(self, wb) -> dict[str, dict[str, Any]]:
        snap: dict[str, dict[str, Any]] = {}
        for name in wb.sheetnames:
            ws = wb[name]
            cells: dict[str, Any] = {}
            for row in ws.iter_rows(
                min_row=1,
                max_row=min(ws.max_row or 1, _MAX_SYNC_ROW),
                max_col=_MAX_SYNC_COL,
            ):
                for cell in row:
                    if cell.value is None or cell.value == "":
                        continue
                    cells[self._cell_key(cell.row, cell.column)] = cell.value
            snap[name] = cells
        return snap

    def open_workbook(self, *, data_only: bool = False, read_only: bool = False):
        """Baixa a planilha inteira em uma única operação (export xlsx)."""
        from gspread.utils import ExportFormat

        def _export():
            return self._authorize().export(self.sheet_id, ExportFormat.EXCEL)

        data = sheets_call(_export)
        wb = load_workbook(BytesIO(data), data_only=data_only, read_only=read_only)
        self._baseline = self._snapshot_workbook(wb)
        self._worksheets.clear()
        return wb

    def save_workbook(self, wb) -> None:
        """Envia apenas células alteradas via batch_update (uma ou poucas requisições)."""
        if not self._baseline:
            self._baseline = self._snapshot_workbook(wb)
            return

        for name in wb.sheetnames:
            ws = wb[name]
            worksheet = self._worksheet(name)
            old_cells = self._baseline.get(name, {})
            batch: list[dict[str, Any]] = []

            for row in ws.iter_rows(
                min_row=1,
                max_row=min(ws.max_row or 1, _MAX_SYNC_ROW),
                max_col=_MAX_SYNC_COL,
            ):
                for cell in row:
                    key = self._cell_key(cell.row, cell.column)
                    new_val = cell.value
                    old_val = old_cells.get(key)
                    new_empty = new_val is None or new_val == ""
                    old_empty = old_val is None or old_val == ""
                    if new_empty and old_empty:
                        continue
                    if not new_empty and not old_empty and new_val == old_val:
                        continue
                    batch.append(
                        {
                            "range": key,
                            "values": [[self._serialize_value(new_val)]],
                        }
                    )

            if not batch:
                continue

            chunk_size = 400
            for i in range(0, len(batch), chunk_size):
                chunk = batch[i : i + chunk_size]

                def _write(c=chunk, w=worksheet):
                    w.batch_update(c, value_input_option="USER_ENTERED")

                sheets_call(_write, is_write=True)

        self._baseline = self._snapshot_workbook(wb)


__all__ = ["GoogleSheetsBridge", "GoogleSheetsQuotaError"]
