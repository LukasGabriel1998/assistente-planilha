# -*- coding: utf-8 -*-
"""
Ponte Google Sheets ↔ openpyxl.

Leitura: 1 values.batchGet para todas as abas (em vez de 1 get_all_values por aba).
Gravação: batch_update agrupado (em vez de update_acell por célula).
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
import re
import time
import unicodedata

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from .google_sheets_api import GoogleSheetsQuotaError, sheets_call

# Mesmo limite usado pelo excel_store.
_MAX_SYNC_ROW = 1048575
_MAX_SYNC_COL = 26  # A..Z

# Abas auxiliares: se falharem no sync, a venda principal ainda deve ser salva.
_OPTIONAL_SHEETS = frozenset({"Log_Agente", "Lembretes"})
# Janela curta pós-save para reutilizar a planilha em memória (ex.: gerar imagem).
_CACHE_TTL_SEC = 20.0


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
        self._aux_sheets_ready = False
        # Cache em memória: evita 2ª leitura completa logo após salvar (ex.: imagem da prévia).
        self._memory_wb: Workbook | None = None
        self._cache_until = 0.0

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

    @staticmethod
    def _normalize_sheet_title(title: str) -> str:
        clean = unicodedata.normalize("NFKD", (title or "").strip().lower())
        clean = "".join(ch for ch in clean if not unicodedata.combining(ch))
        return " ".join(clean.replace("_", " ").split())

    def _find_worksheet(self, spreadsheet, title: str):
        try:
            return spreadsheet.worksheet(title)
        except Exception:
            pass
        wanted = self._normalize_sheet_title(title)
        for ws in spreadsheet.worksheets():
            if ws.title == title:
                return ws
            if self._normalize_sheet_title(ws.title) == wanted:
                return ws
        return None

    def _worksheet(self, title: str, *, create_if_missing: bool = False):
        if title not in self._worksheets:
            spreadsheet = self._spreadsheet_obj()

            def _open():
                ws = self._find_worksheet(spreadsheet, title)
                if ws is not None:
                    return ws
                if not create_if_missing:
                    raise KeyError(
                        f"Aba '{title}' nao encontrada na planilha Google. "
                        "Crie a aba ou permita que a conta de servico a crie."
                    )
                try:
                    return spreadsheet.add_worksheet(title=title, rows=1000, cols=26)
                except Exception:
                    # Corrida / aba criada entre o find e o add.
                    ws = self._find_worksheet(spreadsheet, title)
                    if ws is not None:
                        return ws
                    raise

            self._worksheets[title] = sheets_call(_open, is_write=create_if_missing)
        return self._worksheets[title]

    def ensure_sheets(self, titles: list[str] | tuple[str, ...]) -> None:
        """Garante que as abas existam no Google Sheets (cria se faltar)."""
        pending = [
            t
            for t in titles
            if self._normalize_sheet_title(t)
            not in {self._normalize_sheet_title(cached) for cached in self._worksheets}
        ]
        if not pending and self._aux_sheets_ready:
            return
        for title in titles:
            try:
                self._worksheet(title, create_if_missing=True)
            except Exception as exc:
                print(f"[GoogleSheets] aviso: nao foi possivel garantir aba '{title}': {exc}")
        self._aux_sheets_ready = True

    @staticmethod
    def _serialize_value(value: Any) -> str | int | float:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, datetime):
            # Texto DD/MM/YYYY (Brasil). Apóstrofo evita o Google reinterpretar como MM/DD.
            return f"'{value.strftime('%d/%m/%Y')}"
        if isinstance(value, date):
            return f"'{value.strftime('%d/%m/%Y')}"
        text = str(value)
        # USER_ENTERED transforma "001" em número 1 — força texto para IDs com zero à esquerda.
        if text.isdigit() and len(text) >= 2 and text.startswith("0"):
            return f"'{text}"
        # Datas já no formato BR: força texto para não inverter dia/mês no locale US.
        if len(text) >= 8:
            m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text.strip())
            if m:
                day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if year < 100:
                    year += 2000
                try:
                    date(year, month, day)  # valida
                    return f"'{day:02d}/{month:02d}/{year}"
                except ValueError:
                    pass
        return text

    @staticmethod
    def _cell_key(row: int, col: int) -> str:
        return f"{get_column_letter(col)}{row}"

    @staticmethod
    def _coerce_cell_value(value: Any) -> Any:
        """Normaliza valores do batchGet (números crus; datas serial → date)."""
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            serial = float(value)
            # Serial típico de data (anos ~1950–2100); valores monetários ficam como número.
            # Datas de planilha financeira costumam estar nessa faixa e raramente coincidem
            # com totais de venda (que são < 20000 na prática do bot). Preferimos manter
            # número; a conversão de data fica a cargo de _parse_date_cell no excel_store
            # quando a coluna é de data e o valor formatado/ISO chega como texto.
            return serial if serial != int(serial) else int(serial) if abs(serial) < 1e15 else serial
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            return text
        return value

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

    def _clone_workbook(self, wb) -> Workbook:
        """Cópia leve só com valores (suficiente para leitura/gravação do bot)."""
        clone = Workbook()
        clone.remove(clone.active)
        for name in wb.sheetnames:
            src = wb[name]
            dst = clone.create_sheet(title=name[:31])
            for row in src.iter_rows(
                min_row=1,
                max_row=min(src.max_row or 1, _MAX_SYNC_ROW),
                max_col=_MAX_SYNC_COL,
            ):
                for cell in row:
                    if cell.value not in (None, ""):
                        dst.cell(row=cell.row, column=cell.column, value=cell.value)
        return clone

    def _workbook_from_baseline(self) -> Workbook:
        wb = Workbook()
        wb.remove(wb.active)
        for name, cells in self._baseline.items():
            sheet = wb.create_sheet(title=str(name)[:31])
            for key, value in cells.items():
                if value in (None, ""):
                    continue
                sheet[key] = value
        return wb

    def _build_workbook_from_grids(self, *, data_only: bool = False, read_only: bool = False):
        """Lê todas as abas em 1–2 chamadas à API (batchGet)."""
        spreadsheet = self._spreadsheet_obj()
        worksheets = sheets_call(spreadsheet.worksheets)
        if not worksheets:
            wb = Workbook()
            self._baseline = self._snapshot_workbook(wb)
            self._worksheets.clear()
            return wb

        # Cache local dos handles das abas (evita reabrir depois no save).
        for ws_meta in worksheets:
            self._worksheets[ws_meta.title] = ws_meta

        ranges = [f"'{ws_meta.title}'" for ws_meta in worksheets]

        def _batch_get():
            return spreadsheet.values_batch_get(
                ranges,
                params={
                    "valueRenderOption": "UNFORMATTED_VALUE",
                    "dateTimeRenderOption": "FORMATTED_STRING",
                },
            )

        try:
            payload = sheets_call(_batch_get)
        except Exception as exc:
            print(f"[GoogleSheets] aviso: batchGet falhou ({exc}); fallback get_all_values")
            return self._build_workbook_from_grids_fallback(worksheets)

        value_ranges = payload.get("valueRanges", []) if isinstance(payload, dict) else []
        wb = Workbook()
        wb.remove(wb.active)

        for idx, ws_meta in enumerate(worksheets):
            sheet = wb.create_sheet(title=ws_meta.title[:31])
            rows = []
            if idx < len(value_ranges):
                rows = value_ranges[idx].get("values") or []
            for r_idx, row in enumerate(rows, start=1):
                for c_idx, value in enumerate(row, start=1):
                    coerced = self._coerce_cell_value(value)
                    if coerced not in (None, ""):
                        sheet.cell(row=r_idx, column=c_idx, value=coerced)

        self._baseline = self._snapshot_workbook(wb)
        return wb

    def _build_workbook_from_grids_fallback(self, worksheets) -> Workbook:
        wb = Workbook()
        wb.remove(wb.active)
        for ws_meta in worksheets:
            rows = sheets_call(ws_meta.get_all_values)
            sheet = wb.create_sheet(title=ws_meta.title[:31])
            for r_idx, row in enumerate(rows, start=1):
                for c_idx, value in enumerate(row, start=1):
                    if value not in (None, ""):
                        sheet.cell(row=r_idx, column=c_idx, value=value)
        self._baseline = self._snapshot_workbook(wb)
        return wb

    def invalidate_cache(self) -> None:
        self._memory_wb = None
        self._cache_until = 0.0

    def open_workbook(self, *, data_only: bool = False, read_only: bool = False):
        """Carrega a planilha. Reusa cache em memória só na janela curta pós-save."""
        if self._memory_wb is not None and time.monotonic() < self._cache_until:
            return self._clone_workbook(self._memory_wb)
        wb = self._build_workbook_from_grids(data_only=data_only, read_only=read_only)
        self._memory_wb = self._clone_workbook(wb)
        self._cache_until = 0.0
        return wb

    def save_workbook(self, wb, *, allow_clears: bool = False) -> None:
        """Envia apenas células alteradas via batch_update (uma ou poucas requisições).

        Por padrão NÃO apaga valores existentes na nuvem quando a célula local está vazia
        (evita wipe acidental). Use allow_clears=True em exclusões explícitas.
        """
        if not self._baseline:
            self._baseline = self._snapshot_workbook(wb)
            self._memory_wb = self._clone_workbook(wb)
            self._cache_until = time.monotonic() + _CACHE_TTL_SEC
            return

        optional_failures: list[str] = []
        for name in wb.sheetnames:
            try:
                ws = wb[name]
                worksheet = self._worksheet(name, create_if_missing=True)
                old_cells = self._baseline.get(name, {})
                batch: list[dict[str, Any]] = []

                baseline_max_row = 1
                for key in old_cells:
                    digits = "".join(ch for ch in key if ch.isdigit())
                    if digits:
                        baseline_max_row = max(baseline_max_row, int(digits))
                # Limita varredura: dados reais + folga (nunca milhões de linhas da âncora).
                scan_max = min(
                    max(ws.max_row or 1, baseline_max_row + 5, 50),
                    2000,
                    _MAX_SYNC_ROW,
                )

                for row in ws.iter_rows(
                    min_row=1,
                    max_row=scan_max,
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
                        if new_empty and not old_empty and not allow_clears:
                            # Preserva valor na nuvem — não propaga vazio acidental.
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

                # Um único batch_update por aba (até 400 células; se passar, chunka).
                chunk_size = 400
                for i in range(0, len(batch), chunk_size):
                    chunk = batch[i : i + chunk_size]

                    def _write(c=chunk, w=worksheet):
                        w.batch_update(c, value_input_option="USER_ENTERED")

                    sheets_call(_write, is_write=True)
            except Exception as exc:
                if name in _OPTIONAL_SHEETS or self._normalize_sheet_title(name) in {
                    self._normalize_sheet_title(t) for t in _OPTIONAL_SHEETS
                }:
                    optional_failures.append(f"{name}: {exc}")
                    print(f"[GoogleSheets] aviso: falha ao sincronizar aba opcional '{name}': {exc}")
                    continue
                raise

        if optional_failures:
            print(
                "[GoogleSheets] venda/dados principais salvos; "
                f"abas auxiliares com aviso: {'; '.join(optional_failures)}"
            )

        self._baseline = self._snapshot_workbook(wb)
        self._memory_wb = self._clone_workbook(wb)
        self._cache_until = time.monotonic() + _CACHE_TTL_SEC


__all__ = ["GoogleSheetsBridge", "GoogleSheetsQuotaError"]
