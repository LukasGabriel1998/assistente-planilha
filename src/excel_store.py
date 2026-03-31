from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import unicodedata
import zipfile

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import PatternFill

from .models import FinancialCommand, RefundCommand, StatusUpdateCommand

SHEET_SALES = "TOTAL DE VENDAS DE 2026"
# Nome normalizado; no Excel a aba pode ser "Compras Matéria-Prima" (com acento).
SHEET_MATERIAL = "Compras Materia-Prima"
SHEET_FIXED = "Gastos Fixos"
SHEET_LOG = "Log_Agente"
SHEET_TEMPLATE_SALES = "_tmpl_vendas"
SHEET_TEMPLATE_MATERIAL = "_tmpl_material"
SHEET_TEMPLATE_FIXED = "_tmpl_fixos"
SHEET_REMINDERS = "Lembretes"
SUPPORTED_WORKBOOK_EXTS = (".xlsx", ".xlsm", ".xltx", ".xltm")
SALES_HEADER_ROW = 2
TEMPLATE_ROW = 3
ANCHOR_TEMPLATE_ROW = 1048576
DATA_START_ROW = 3
SALES_REQUIRED_HEADERS = {
    # A aba TOTAL DE VENDAS DE 2026 agora usa explicitamente:
    # Coluna A: Data de venda
    # Coluna B: Data de Entrega
    "data de venda": "Data de venda",
    "data de entrega": "Data de Entrega",
    "id cliente": "ID Cliente",
    "id produto": "ID produto",
    "total de vendas (pago)": "Total de vendas (pago)",
    "valor (pendente)": "Valor (pendente)",
    "id venda": "ID VENDA",
    "status de valor": "Status de valor",
}

FILL_PENDING = PatternFill(start_color="FFF59D", end_color="FFF59D", fill_type="solid")  # amarelo claro
FILL_DONE = PatternFill(start_color="C8E6C9", end_color="C8E6C9", fill_type="solid")  # verde claro
MATERIAL_HEADER_ROW = 2
MATERIAL_REQUIRED_HEADERS = {
    "data": "Data",
    "descricao": "Descricao",
    "valor": "Valor",
}


@dataclass
class WriteAction:
    sheet: str
    row: int
    amount: float
    label: str
    sale_id: str | None = None


class SpreadsheetService:
    def __init__(self, workbook_path: str | Path) -> None:
        self.workbook_path = Path(workbook_path)
        if not self.workbook_path.exists():
            raise FileNotFoundError(f"Planilha nao encontrada: {self.workbook_path}")
        if self.workbook_path.is_dir():
            raise ValueError(
                "O caminho informado e uma pasta. Informe o arquivo da planilha "
                "(.xlsx, .xlsm, .xltx ou .xltm)."
            )
        if self.workbook_path.suffix.lower() not in SUPPORTED_WORKBOOK_EXTS:
            raise ValueError("Formato invalido de planilha. Use .xlsx, .xlsm, .xltx ou .xltm.")
        if self.workbook_path.name.startswith("~$"):
            raise ValueError(
                "Arquivo temporario do Excel detectado (~$...). "
                "Selecione o arquivo principal da planilha."
            )

    def _open_workbook(self, *, data_only: bool = False):
        try:
            return load_workbook(self.workbook_path, data_only=data_only)
        except PermissionError as exc:
            raise PermissionError(
                "Nao foi possivel abrir a planilha. Feche o arquivo no Excel e tente novamente."
            ) from exc
        except zipfile.BadZipFile as exc:
            raise ValueError(
                "Arquivo de planilha invalido ou corrompido. "
                "Abra e salve novamente no Excel como .xlsx/.xlsm."
            ) from exc
        except Exception as exc:
            msg = str(exc).lower()
            if "openpyxl does not support file format" in msg:
                raise ValueError(
                    "Formato de planilha nao suportado. Use .xlsx, .xlsm, .xltx ou .xltm."
                ) from exc
            raise

    def _save_workbook(self, wb) -> None:
        try:
            wb.save(self.workbook_path)
        except PermissionError as exc:
            raise PermissionError(
                "Sem permissao para salvar a planilha. Feche o arquivo no Excel e tente novamente."
            ) from exc
        except OSError as exc:
            msg = str(exc).lower()
            if ("permission denied" in msg) or ("being used by another process" in msg):
                raise PermissionError(
                    "Nao foi possivel salvar porque a planilha esta em uso. "
                    "Feche no Excel e tente novamente."
                ) from exc
            raise

    @staticmethod
    def _normalize_name(name: str) -> str:
        clean = name.strip().lower()
        clean = unicodedata.normalize("NFKD", clean)
        clean = "".join(ch for ch in clean if not unicodedata.combining(ch))
        return " ".join(clean.split())

    @classmethod
    def _resolve_sheet_name(cls, wb, expected_name: str) -> str:
        if expected_name in wb.sheetnames:
            return expected_name
        expected_norm = cls._normalize_name(expected_name).rsplit(" ", 1)[0]
        for real_name in wb.sheetnames:
            if cls._normalize_name(real_name).startswith(expected_norm):
                return real_name
        raise ValueError(f"Aba obrigatoria nao encontrada: {expected_name}")

    # Última linha da planilha guarda só o padrão (estilo, sem valores). O robô nunca escreve dados lá.
    MAX_DATA_ROW = ANCHOR_TEMPLATE_ROW - 1

    @staticmethod
    def _next_row(ws, key_col: str = "A", start_row: int = DATA_START_ROW) -> int:
        row = start_row
        max_row = min(ws.max_row, SpreadsheetService.MAX_DATA_ROW)
        while row <= max_row and ws[f"{key_col}{row}"].value not in (None, ""):
            row += 1
        # Nunca devolver a linha âncora (última linha); ela guarda só o padrão, sem dados
        return min(row, SpreadsheetService.MAX_DATA_ROW)

    @staticmethod
    def _next_row_for_empty_cols(
        ws,
        empty_cols: tuple[str, ...],
        *,
        start_row: int = DATA_START_ROW,
    ) -> int:
        row = start_row
        max_row = min(ws.max_row, SpreadsheetService.MAX_DATA_ROW)
        while row <= max_row:
            if all(ws[f"{col}{row}"].value in (None, "") for col in empty_cols):
                return row
            row += 1
        return row

    @staticmethod
    def _last_filled_row(ws, key_col: str = "A", start_row: int = DATA_START_ROW) -> int:
        for row in range(ws.max_row, start_row - 1, -1):
            if ws[f"{key_col}{row}"].value not in (None, ""):
                return row
        return start_row

    @staticmethod
    def _apply_currency_format(ws, col: str, row: int) -> None:
        ws[f"{col}{row}"].number_format = "R$ #,##0.00"

    @staticmethod
    def _apply_date_format(ws, col: str, row: int) -> None:
        ws[f"{col}{row}"].number_format = "DD/MM/YYYY"

    @staticmethod
    def _ensure_number_format_if_general(ws, col: str, row: int, fmt: str) -> None:
        """Só aplica formato se a célula estiver em General; não sobrescreve formatação da planilha."""
        cell = ws[f"{col}{row}"]
        current = str(getattr(cell, "number_format", None) or "General").strip()
        if not current or current == "General":
            cell.number_format = fmt

    @staticmethod
    def _excel_date_value(value) -> str:
        if hasattr(value, "strftime"):
            return value.strftime("%d/%m/%Y")
        return str(value)

    @classmethod
    def _header_map(cls, ws, header_row: int = SALES_HEADER_ROW) -> dict[str, str]:
        headers: dict[str, str] = {}
        for col_idx in range(1, ws.max_column + 1):
            value = ws.cell(row=header_row, column=col_idx).value
            if value in (None, ""):
                continue
            headers[cls._normalize_name(str(value))] = get_column_letter(col_idx)
        return headers

    @classmethod
    def _sales_columns(cls, ws) -> dict[str, str]:
        headers = cls._header_map(ws, header_row=SALES_HEADER_ROW)
        # Compatibilidade: algumas versões antigas da planilha usavam "Data".
        # Se existir "Data de venda", tratamos como a data principal.
        if "data" not in headers and "data de venda" in headers:
            headers["data"] = headers["data de venda"]
        if "data de venda" not in headers and "data" in headers:
            headers["data de venda"] = headers["data"]
        # Variações comuns de entrega
        if "data de entrega" not in headers:
            if "data entrega" in headers:
                headers["data de entrega"] = headers["data entrega"]
            elif "entrega" in headers:
                headers["data de entrega"] = headers["entrega"]
        missing = [label for key, label in SALES_REQUIRED_HEADERS.items() if key not in headers]
        if missing:
            raise ValueError(
                "Colunas obrigatorias da aba de vendas nao encontradas: " + ", ".join(missing)
            )
        return headers

    @staticmethod
    def _to_float(value) -> float:
        if value in (None, ""):
            return 0.0
        try:
            return float(value)
        except Exception:
            return 0.0

    @staticmethod
    def _status_text(pending_amount: float) -> str:
        return "pago" if abs(float(pending_amount or 0.0)) < 0.01 else "pendente"

    @staticmethod
    def _delivery_fill_for_pending(pending_amount: float):
        """Data de entrega segue status financeiro: pendente=amarelo, pago=verde."""
        return FILL_DONE if abs(float(pending_amount or 0.0)) < 0.01 else FILL_PENDING

    @staticmethod
    def _parse_date_cell(value):
        """Tenta interpretar valores da célula como data (string DD/MM/YYYY ou objeto date/datetime)."""
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value.date()
        if hasattr(value, "strftime"):
            # date (sem .date()) ou datetime (já coberto acima)
            try:
                return value.date()  # type: ignore[attr-defined]
            except Exception:
                return value  # type: ignore[return-value]
        s = str(value).strip()
        if not s:
            return None
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                continue
        return None

    @staticmethod
    def _match_text_case(template_value, text: str) -> str:
        if not text:
            return text
        template = str(template_value or "").strip()
        if not template:
            return text
        letters = [ch for ch in template if ch.isalpha()]
        if letters and all(ch.isupper() for ch in letters):
            return text.upper()
        if template == template.capitalize():
            return text.capitalize()
        if template == template.lower():
            return text.lower()
        return text

    def _generate_sale_id(self, ws, sale_id_col: str) -> str:
        used_short_ids: set[int] = set()
        max_id = 0
        for row in range(DATA_START_ROW, ws.max_row + 1):
            value = ws[f"{sale_id_col}{row}"].value
            if value in (None, ""):
                continue
            digits = re.findall(r"\d+", str(value))
            if not digits:
                continue
            numeric = int(digits[-1])
            if 1 <= numeric <= 999:
                used_short_ids.add(numeric)
            max_id = max(max_id, numeric)
        for candidate in range(1, 1000):
            if candidate not in used_short_ids:
                return f"{candidate:03d}"
        return str(max_id + 1)

    @classmethod
    def _material_columns(cls, ws) -> dict[str, str]:
        headers = cls._header_map(ws, header_row=MATERIAL_HEADER_ROW)
        normalized_map = {
            "data": headers.get("data"),
            "fornecedor": headers.get("fornecedor"),
            "descricao": headers.get("descricao") or headers.get("descrição"),
            "valor": next((col for key, col in headers.items() if key.startswith("valor")), None),
            "id venda": headers.get("id venda"),
        }
        missing = [label for key, label in MATERIAL_REQUIRED_HEADERS.items() if not normalized_map.get(key)]
        if missing:
            raise ValueError(
                "Colunas obrigatorias da aba de materia-prima nao encontradas: " + ", ".join(missing)
            )
        return normalized_map

    @staticmethod
    def _column_style(ws, col: str):
        style_id = getattr(ws.column_dimensions[col], "style", 0) or 0
        if style_id <= 0:
            return None
        try:
            return copy(ws.parent._cell_styles[style_id])
        except Exception:
            return None

    @staticmethod
    def _copy_row_style(
        ws,
        source_row: int,
        target_row: int,
        cols: tuple[str, ...],
        *,
        apply_row_dimensions: bool = True,
    ) -> None:
        SpreadsheetService._copy_row_style_between(
            ws, source_row, ws, target_row, cols, apply_row_dimensions=apply_row_dimensions
        )

    @staticmethod
    def _copy_cell_style(source_cell, target_cell) -> None:
        """Copia o estilo da célula de origem para a de destino (ex.: da linha 1048576).
        Mantém exatamente o padrão: negrito, cor da fonte, fundo, número/data, bordas, alinhamento."""
        if getattr(source_cell, "style_id", 0):
            target_cell._style = copy(source_cell._style)
        num_fmt = getattr(source_cell, "number_format", None)
        if num_fmt is not None and str(num_fmt).strip():
            target_cell.number_format = num_fmt
        try:
            if getattr(source_cell, "font", None) is not None:
                target_cell.font = copy(source_cell.font)
        except Exception:
            pass
        try:
            if getattr(source_cell, "fill", None) is not None:
                target_cell.fill = copy(source_cell.fill)
        except Exception:
            pass
        try:
            if getattr(source_cell, "alignment", None) is not None:
                target_cell.alignment = copy(source_cell.alignment)
        except Exception:
            pass
        try:
            if getattr(source_cell, "border", None) is not None:
                target_cell.border = copy(source_cell.border)
        except Exception:
            pass

    @classmethod
    def _should_copy_row_dimensions_for_target(cls, target_ws, logical_sheet_name: str) -> bool:
        """
        Na aba de vendas visível, não copiar row_dimensions do template: isso afeta a linha inteira
        e desalinha/oculta blocos de resumo ao lado da tabela (ex.: coluna J).
        """
        if cls._normalize_name(logical_sheet_name) != cls._normalize_name(SHEET_SALES):
            return True
        tmpl_title = cls._template_sheet_name_for(SHEET_SALES)
        return cls._normalize_name(getattr(target_ws, "title", "")) == cls._normalize_name(tmpl_title)

    @staticmethod
    def _copy_row_style_between(
        source_ws,
        source_row: int,
        target_ws,
        target_row: int,
        cols: tuple[str, ...],
        *,
        apply_row_dimensions: bool = True,
    ) -> None:
        for col in cols:
            source = source_ws[f"{col}{source_row}"]
            target = target_ws[f"{col}{target_row}"]
            SpreadsheetService._copy_cell_style(source, target)
        if not apply_row_dimensions:
            return
        source_dim = source_ws.row_dimensions[source_row]
        target_dim = target_ws.row_dimensions[target_row]
        if source_dim.height is not None:
            target_dim.height = source_dim.height
        target_dim.hidden = source_dim.hidden
        target_dim.outlineLevel = source_dim.outlineLevel
        target_dim.collapsed = source_dim.collapsed

    @staticmethod
    def _sheet_style_cols(ws) -> tuple[str, ...]:
        return tuple(get_column_letter(col_idx) for col_idx in range(1, ws.max_column + 1))

    @classmethod
    def _layout_cols_for_sheet(cls, ws, logical_sheet_name: str) -> tuple[str, ...]:
        logical_norm = cls._normalize_name(logical_sheet_name)
        if logical_norm == cls._normalize_name(SHEET_SALES):
            # Vendas: aplicar layout APENAS nas colunas da tabela de vendas.
            # Não usar a linha inteira porque isso pode sobrescrever blocos de layout/resumo
            # fora da tabela (ex.: coluna J com totais/fórmulas/caixas).
            return cls._sales_style_cols(ws)
        if logical_norm == cls._normalize_name(SHEET_MATERIAL):
            material_cols = cls._material_columns(ws)
            cols = (
                material_cols["data"],
                material_cols["descricao"],
                material_cols["valor"],
            )
            if material_cols.get("fornecedor"):
                cols = (material_cols["fornecedor"],) + cols
            if material_cols.get("id venda"):
                cols = cols + (material_cols["id venda"],)
            return cols
        if logical_norm == cls._normalize_name(SHEET_FIXED):
            return ("A", "B", "C")
        return cls._sheet_style_cols(ws)

    @classmethod
    def _sales_style_cols(cls, ws) -> tuple[str, ...]:
        """
        Colunas de estilo/dados da tabela de vendas.

        Importante: não usar a linha inteira para evitar sobrescrever colunas
        auxiliares de layout/resumo (ex.: coluna J com totais/fórmulas).
        """
        sales_cols = cls._sales_columns(ws)
        cols = [
            sales_cols["data de venda"],
            sales_cols["data de entrega"],
            sales_cols["id cliente"],
            sales_cols["id produto"],
            sales_cols["total de vendas (pago)"],
            sales_cols["valor (pendente)"],
            sales_cols["id venda"],
            sales_cols["status de valor"],
        ]
        # Algumas planilhas têm também a coluna "Status" (serviço) ao lado.
        status_col = sales_cols.get("status")
        if status_col:
            cols.append(status_col)
        # Remove duplicadas preservando ordem.
        return tuple(dict.fromkeys(cols))

    @staticmethod
    def _row_is_empty(ws, row: int, cols: tuple[str, ...]) -> bool:
        return all(ws[f"{col}{row}"].value in (None, "") for col in cols)

    @staticmethod
    def _row_has_values(ws, row: int, cols: tuple[str, ...]) -> bool:
        return any(ws[f"{col}{row}"].value not in (None, "") for col in cols)

    @staticmethod
    def _row_has_any_style(ws, row: int, cols: tuple[str, ...]) -> bool:
        return any((getattr(ws[f"{col}{row}"], "style_id", 0) or 0) > 0 for col in cols)

    @staticmethod
    def _row_has_any_border(ws, row: int, cols: tuple[str, ...]) -> bool:
        """
        Detecta se a linha já tem bordas aplicadas nas colunas alvo.
        Isso é importante porque alguns layouts no Excel podem ter bordas sem "style_id" não-zero.
        """
        for col in cols:
            cell = ws[f"{col}{row}"]
            border = getattr(cell, "border", None)
            if border is None:
                continue
            for side in (border.left, border.right, border.top, border.bottom):
                if getattr(side, "style", None):
                    return True
        return False

    @staticmethod
    def _clear_row_values(ws, row: int, cols: tuple[str, ...]) -> None:
        for col in cols:
            ws[f"{col}{row}"] = None

    @staticmethod
    def _style_row_for(ws, cols: tuple[str, ...], start_row: int = 3, search_limit: int = 20) -> int:
        last_row = min(ws.max_row, start_row + search_limit)
        for row in range(start_row, last_row + 1):
            if any(getattr(ws[f"{col}{row}"], "style_id", 0) for col in cols):
                return row
        return start_row

    @staticmethod
    def _empty_style_row_for(ws, cols: tuple[str, ...], start_row: int = 3, search_limit: int = 50) -> int:
        last_row = min(ws.max_row, start_row + search_limit)
        for row in range(start_row, last_row + 1):
            if not any(getattr(ws[f"{col}{row}"], "style_id", 0) for col in cols):
                continue
            if all(ws[f"{col}{row}"].value in (None, "") for col in cols):
                return row
        return SpreadsheetService._style_row_for(ws, cols, start_row=start_row, search_limit=search_limit)

    @staticmethod
    def _template_style_row_for(ws, cols: tuple[str, ...], start_row: int = 3, search_limit: int = 50) -> int:
        if any(getattr(ws[f"{col}{start_row}"], "style_id", 0) for col in cols):
            return start_row
        return SpreadsheetService._style_row_for(ws, cols, start_row=start_row, search_limit=search_limit)

    @staticmethod
    def _visible_template_row_for(ws, cols: tuple[str, ...], start_row: int = 3, search_limit: int = 50) -> int | None:
        last_row = min(max(ws.max_row, start_row), start_row + search_limit)
        for row in range(start_row, last_row + 1):
            if any(getattr(ws[f"{col}{row}"], "style_id", 0) for col in cols):
                return row
        return None

    @classmethod
    def _row_has_padrao(cls, ws, row: int, cols: tuple[str, ...]) -> bool:
        """True se a linha tiver formatação ou número/data (padrão definido)."""
        if cls._row_has_any_style(ws, row, cols):
            return True
        for col in cols:
            nf = str(getattr(ws[f"{col}{row}"], "number_format", None) or "General").strip()
            if nf and nf != "General":
                return True
        return False

    @classmethod
    def _row_3_has_padrao(cls, ws, cols: tuple[str, ...]) -> bool:
        """True se a linha 3 tiver formatação ou número/data (padrão que o usuário definiu)."""
        return cls._row_has_padrao(ws, TEMPLATE_ROW, cols)

    @classmethod
    def _save_padrao_row3_to_template(cls, wb, ws, logical_sheet_name: str) -> None:
        """Salva o padrão da linha 3 no template. Se a linha 1048576 já for o padrão (tem formatação ou dados), não sobrescreve."""
        # Para abas com linha-âncora (1048576), não usar linha 3 como fonte.
        if cls._anchor_template_row_for(logical_sheet_name) is not None:
            return
        style_cols = cls._layout_cols_for_sheet(ws, logical_sheet_name)
        if cls._anchor_template_row_for(logical_sheet_name) is not None:
            all_cols = cls._sheet_style_cols(ws)
            if cls._row_has_padrao(ws, ANCHOR_TEMPLATE_ROW, style_cols) or cls._row_has_values(ws, ANCHOR_TEMPLATE_ROW, all_cols):
                return
        if not cls._row_3_has_padrao(ws, style_cols):
            return
        cls._sync_template_store(wb, ws, logical_sheet_name, source_row=TEMPLATE_ROW)

    @classmethod
    def _load_padrao_from_anchor_row(cls, wb, ws, logical_sheet_name: str, cols: tuple[str, ...]):
        """Linha 1048576 = padrão único. Lê o estado atual dessa linha e replica o estilo para o template;
        todas as linhas que o robô preencher seguem esse padrão. A linha 1048576 não é apagada."""
        if cls._anchor_template_row_for(logical_sheet_name) is None:
            return None
        all_cols = cls._sheet_style_cols(ws)
        # Usar 1048576 se tiver formatação OU qualquer valor em qualquer coluna (ex.: exemplo do usuário)
        tem_padrao = cls._row_has_padrao(ws, ANCHOR_TEMPLATE_ROW, cols)
        tem_valor = cls._row_has_values(ws, ANCHOR_TEMPLATE_ROW, all_cols)
        if not tem_padrao and not tem_valor:
            return None
        template_ws = cls._ensure_template_sheet(wb, logical_sheet_name)
        cls._copy_row_style_between(ws, ANCHOR_TEMPLATE_ROW, template_ws, TEMPLATE_ROW, all_cols)
        cls._clear_row_values(template_ws, TEMPLATE_ROW, all_cols)
        return template_ws, TEMPLATE_ROW

    @staticmethod
    def _append_template_row(ws, row: int, cols: tuple[str, ...], start_row: int = 3, search_limit: int = 50) -> int:
        template_row = SpreadsheetService._template_style_row_for(
            ws,
            cols,
            start_row=start_row,
            search_limit=search_limit,
        )
        if template_row:
            return template_row
        return SpreadsheetService._style_row_for(ws, cols, start_row=start_row, search_limit=search_limit)

    @classmethod
    def _template_sheet_name_for(cls, logical_sheet_name: str) -> str:
        logical_norm = cls._normalize_name(logical_sheet_name)
        if logical_norm == cls._normalize_name(SHEET_SALES):
            return SHEET_TEMPLATE_SALES
        if logical_norm == cls._normalize_name(SHEET_MATERIAL):
            return SHEET_TEMPLATE_MATERIAL
        if logical_norm == cls._normalize_name(SHEET_FIXED):
            return SHEET_TEMPLATE_FIXED
        raise ValueError(f"Aba sem template configurado: {logical_sheet_name}")

    @classmethod
    def _anchor_template_row_for(cls, logical_sheet_name: str) -> int | None:
        """Linha 1048576 como padrão para TOTAL DE VENDAS e Compras Matéria-Prima."""
        logical_norm = cls._normalize_name(logical_sheet_name)
        if logical_norm in (
            cls._normalize_name(SHEET_SALES),
            cls._normalize_name(SHEET_MATERIAL),
        ):
            return ANCHOR_TEMPLATE_ROW
        return None

    @classmethod
    def _ensure_template_sheet(cls, wb, logical_sheet_name: str):
        template_name = cls._template_sheet_name_for(logical_sheet_name)
        if template_name in wb.sheetnames:
            ws = wb[template_name]
        else:
            ws = wb.create_sheet(template_name)
        ws.sheet_state = "veryHidden"
        return ws

    @staticmethod
    def _row_empty_and_no_style(ws, row: int, cols: tuple[str, ...]) -> bool:
        """True se a linha não tem valores e não tem formatação (evita sobrescrever padrão)."""
        if any(ws[f"{col}{row}"].value not in (None, "") for col in cols):
            return False
        if any((getattr(ws[f"{col}{row}"], "style_id", 0) or 0) > 0 for col in cols):
            return False
        if any(str(getattr(ws[f"{col}{row}"], "number_format", None) or "General").strip() not in ("", "General") for col in cols):
            return False
        return True

    @staticmethod
    def _copy_sheet_layout(source_ws, target_ws, row_limit: int = 12, style_cols: tuple[str, ...] | None = None) -> None:
        max_col = source_ws.max_column
        all_cols = tuple(get_column_letter(col_idx) for col_idx in range(1, max_col + 1))
        cols_to_check = style_cols or all_cols
        for merged in list(target_ws.merged_cells.ranges):
            target_ws.unmerge_cells(str(merged))
        for row in range(1, min(source_ws.max_row, row_limit) + 1):
            # Linhas de dados vazias e sem formato: não sobrescrever o template (mantém padrão da planilha)
            if row >= DATA_START_ROW and SpreadsheetService._row_empty_and_no_style(source_ws, row, cols_to_check):
                continue
            SpreadsheetService._copy_row_style_between(source_ws, row, target_ws, row, all_cols)
            for col_idx in range(1, max_col + 1):
                source = source_ws.cell(row=row, column=col_idx)
                target = target_ws.cell(row=row, column=col_idx)
                target.value = source.value
        for merged in source_ws.merged_cells.ranges:
            target_ws.merge_cells(str(merged))
        for col_idx in range(1, max_col + 1):
            col = get_column_letter(col_idx)
            source_dim = source_ws.column_dimensions[col]
            target_dim = target_ws.column_dimensions[col]
            target_dim.width = source_dim.width
            target_dim.hidden = source_dim.hidden
            target_dim.bestFit = source_dim.bestFit
            target_dim.outlineLevel = source_dim.outlineLevel
            target_dim.collapsed = source_dim.collapsed

    @staticmethod
    def _template_row_score(ws, row: int, cols: tuple[str, ...]) -> tuple[int, int, int, int]:
        style_ids = [getattr(ws[f"{col}{row}"], "style_id", 0) or 0 for col in cols]
        non_zero = [style_id for style_id in style_ids if style_id > 0]
        if not non_zero:
            return (0, 0, 0, 0)
        distinct_non_default_styles = len({style_id for style_id in non_zero if style_id != 1})
        special_numfmts = sum(1 for col in cols if str(ws[f"{col}{row}"].number_format or "General") != "General")
        special_fonts = sum(
            1
            for col in cols
            if (
                (getattr(ws[f"{col}{row}"], "style_id", 0) or 0) not in (0, 1)
                and ws[f"{col}{row}"].font.name not in (None, "", "Calibri")
            )
        )
        colored_fonts = sum(
            1
            for col in cols
            if (
                getattr(ws[f"{col}{row}"].font.color, "type", None) == "rgb"
                and getattr(ws[f"{col}{row}"].font.color, "rgb", None) not in (None, "00000000")
            )
        )
        return (distinct_non_default_styles, special_numfmts, special_fonts, colored_fonts)

    @classmethod
    def _row_has_rich_style(cls, ws, row: int, cols: tuple[str, ...]) -> bool:
        distinct_non_default_styles, special_numfmts, special_fonts, colored_fonts = cls._template_row_score(ws, row, cols)
        return (distinct_non_default_styles > 2) or (special_numfmts > 0) or (special_fonts > 1) or (colored_fonts > 0)

    @classmethod
    def _visible_template_is_rich(cls, ws, cols: tuple[str, ...]) -> bool:
        return cls._row_has_rich_style(ws, TEMPLATE_ROW, cols)

    @classmethod
    def _sync_template_store(cls, wb, source_ws, logical_sheet_name: str, source_row: int = TEMPLATE_ROW) -> None:
        template_ws = cls._ensure_template_sheet(wb, logical_sheet_name)
        style_cols = cls._layout_cols_for_sheet(source_ws, logical_sheet_name)
        cls._copy_sheet_layout(source_ws, template_ws, row_limit=12, style_cols=style_cols)
        all_cols = cls._sheet_style_cols(source_ws)
        if source_row != TEMPLATE_ROW:
            cls._copy_row_style_between(source_ws, source_row, template_ws, TEMPLATE_ROW, all_cols)
        # Hidden template sheets should keep only layout/style, never previous business data.
        for row in range(DATA_START_ROW, min(template_ws.max_row, 12) + 1):
            cls._clear_row_values(template_ws, row, all_cols)
        # Guardar o padrão também na última linha da planilha (só estilo, sem valores), como referência permanente.
        # O robô nunca escreve dados lá; usa só para copiar o padrão e não sobrescrever fora dele.
        if source_row == TEMPLATE_ROW and cls._anchor_template_row_for(logical_sheet_name) is not None:
            cls._copy_row_style_between(source_ws, TEMPLATE_ROW, source_ws, ANCHOR_TEMPLATE_ROW, style_cols)
            cls._clear_row_values(source_ws, ANCHOR_TEMPLATE_ROW, style_cols)

    @classmethod
    def _template_source(cls, wb, ws, logical_sheet_name: str, cols: tuple[str, ...]):
        template_ws = cls._ensure_template_sheet(wb, logical_sheet_name)
        anchored_sheet = cls._anchor_template_row_for(logical_sheet_name) is not None
        # Importante: em abas "ancoradas", o padrão é a linha 1048576.
        # O robô nunca deve tentar "atualizar" esse padrão automaticamente a partir da linha 3,
        # para não alterar bordas/layout que o usuário considera como referência fixa.
        # Padrão único: linha 1048576. Replicar esse estilo em todas as linhas que o robô preencher.
        # TOTAL DE VENDAS DE 2026 e Compras Matéria-Prima: mesma regra — usar só a linha 1048576 quando tiver conteúdo ou formatação.
        result = cls._load_padrao_from_anchor_row(wb, ws, logical_sheet_name, cols)
        if result is not None:
            return result

        # Em abas ancoradas, nunca cair para linha 3 visível como fonte.
        if anchored_sheet:
            if any(getattr(template_ws[f"{col}{TEMPLATE_ROW}"], "style_id", 0) for col in cols):
                return template_ws, TEMPLATE_ROW
            return ws, ANCHOR_TEMPLATE_ROW

        # Fallback: template já tem o padrão salvo (linha 3 com estilo).
        if cls._row_3_has_padrao(template_ws, cols):
            return template_ws, TEMPLATE_ROW

        # Prioridade 3: linha 3 visível tiver o padrão (salvar quando o usuário formatar a linha 3).
        if cls._row_3_has_padrao(ws, cols):
            cls._sync_template_store(wb, ws, logical_sheet_name, source_row=TEMPLATE_ROW)
            return template_ws, TEMPLATE_ROW

        visible_template_row = cls._visible_template_row_for(ws, cols)
        if visible_template_row is not None:
            # Só sincronizar se for a linha 3 (não sobrescrever o template com outras linhas)
            if visible_template_row == TEMPLATE_ROW:
                cls._sync_template_store(wb, ws, logical_sheet_name, source_row=TEMPLATE_ROW)
            return ws, visible_template_row

        anchor_row = cls._anchor_template_row_for(logical_sheet_name)
        if anchor_row and cls._row_has_padrao(ws, anchor_row, cols):
            all_cols = cls._sheet_style_cols(ws)
            template_ready = cls._row_has_any_style(template_ws, TEMPLATE_ROW, cols)
            if cls._row_has_values(ws, anchor_row, all_cols) or not template_ready:
                cls._sync_template_store(wb, ws, logical_sheet_name, source_row=anchor_row)
            return template_ws, TEMPLATE_ROW
        if any(getattr(template_ws[f"{col}{TEMPLATE_ROW}"], "style_id", 0) for col in cols):
            return template_ws, TEMPLATE_ROW
        cls._sync_template_store(wb, ws, logical_sheet_name)
        return ws, TEMPLATE_ROW

    @classmethod
    def _copy_sales_row_style_from_template(cls, wb, ws_sales, row: int) -> None:
        cols = cls._sales_style_cols(ws_sales)
        template_ws, template_row = cls._template_source(wb, ws_sales, SHEET_SALES, cols)
        cls._copy_row_style_between(
            template_ws, template_row, ws_sales, row, cols, apply_row_dimensions=False
        )

    @classmethod
    def _prepare_row_from_template(
        cls,
        wb,
        ws,
        row: int,
        logical_sheet_name: str,
        cols: tuple[str, ...],
        start_row: int = TEMPLATE_ROW,
        search_limit: int = 50,
    ):
        if cls._row_has_values(ws, row, cols):
            return ws, row
        # Se a linha já está formatada (ex.: bordas já desenhadas pelo usuário),
        # não copiar estilo do template para não sobrescrever o layout.
        if cls._row_has_any_border(ws, row, cols):
            return ws, row

        # Sempre usar o padrão salvo no template (linha 3) quando existir; não usar outras linhas visíveis que podem ter formato errado
        template_ws, template_row = cls._template_source(wb, ws, logical_sheet_name, cols)
        if template_ws is ws and template_row != ANCHOR_TEMPLATE_ROW:
            template_row = cls._append_template_row(ws, row, cols, start_row=start_row, search_limit=search_limit)
        if not (template_ws is ws and template_row == row):
            cls._copy_row_style_between(
                template_ws,
                template_row,
                ws,
                row,
                cols,
                apply_row_dimensions=cls._should_copy_row_dimensions_for_target(ws, logical_sheet_name),
            )
        return template_ws, template_row

    @classmethod
    def _normalize_sheet_layout(
        cls,
        wb,
        ws,
        logical_sheet_name: str,
        *,
        row_limit: int,
    ) -> None:
        style_cols = cls._layout_cols_for_sheet(ws, logical_sheet_name)
        template_ws, template_row = cls._template_source(wb, ws, logical_sheet_name, style_cols)
        effective_limit = cls._effective_layout_row_limit(ws, logical_sheet_name, style_cols, minimum_rows=row_limit)
        for row in range(TEMPLATE_ROW, effective_limit + 1):
            if template_ws is ws and template_row == row:
                continue
            if cls._row_has_values(ws, row, style_cols):
                continue
            # Nunca sobrescrever formatação existente: só aplicar template em linhas sem estilo
            if cls._row_has_any_style(ws, row, style_cols) or cls._row_has_any_border(ws, row, style_cols):
                continue
            cls._copy_row_style_between(
                template_ws,
                template_row,
                ws,
                row,
                style_cols,
                apply_row_dimensions=cls._should_copy_row_dimensions_for_target(ws, logical_sheet_name),
            )

    @classmethod
    def _effective_layout_row_limit(
        cls,
        ws,
        logical_sheet_name: str,
        cols: tuple[str, ...],
        *,
        minimum_rows: int,
        empty_streak: int = 25,
    ) -> int:
        anchor_row = cls._anchor_template_row_for(logical_sheet_name)
        max_scan_row = (anchor_row - 1) if anchor_row else ws.max_row
        last_non_empty = TEMPLATE_ROW
        streak = 0
        row = TEMPLATE_ROW
        minimum_target = max(TEMPLATE_ROW + minimum_rows - 1, TEMPLATE_ROW + empty_streak)
        while row <= max_scan_row:
            if cls._row_has_values(ws, row, cols):
                last_non_empty = row
                streak = 0
            else:
                streak += 1
                if row >= minimum_target and streak >= empty_streak:
                    break
            row += 1
        return max(last_non_empty + empty_streak, minimum_target)

    @classmethod
    def normalize_template_rows(
        cls,
        workbook_path: str | Path,
        *,
        row_limit: int = 12,
    ) -> None:
        service = cls(workbook_path)
        wb = service._open_workbook()
        try:
            sheet_names = (
                service._resolve_sheet_name(wb, SHEET_SALES),
                service._resolve_sheet_name(wb, SHEET_MATERIAL),
                service._resolve_sheet_name(wb, SHEET_FIXED),
            )
            for sheet_name in sheet_names:
                ws = wb[sheet_name]
                service._normalize_sheet_layout(wb, ws, sheet_name, row_limit=row_limit)
            service._save_workbook(wb)
        finally:
            wb.close()

    @staticmethod
    def _restore_visible_sheet(ws) -> None:
        for row in range(TEMPLATE_ROW, min(ws.max_row, TEMPLATE_ROW + 2) + 1):
            ws.row_dimensions[row].hidden = False

    def restore_visible_layout(self) -> None:
        wb = self._open_workbook()
        try:
            for sheet_name in (
                self._resolve_sheet_name(wb, SHEET_SALES),
                self._resolve_sheet_name(wb, SHEET_MATERIAL),
                self._resolve_sheet_name(wb, SHEET_FIXED),
            ):
                self._restore_visible_sheet(wb[sheet_name])
            self._save_workbook(wb)
        finally:
            wb.close()

    def _find_sale_row(self, ws, sale_id_col: str, sale_id: str) -> int:
        wanted = self._normalize_name(str(sale_id))
        for row in range(DATA_START_ROW, ws.max_row + 1):
            value = ws[f"{sale_id_col}{row}"].value
            if value in (None, ""):
                continue
            if self._normalize_name(str(value)) == wanted:
                return row
        raise ValueError(f"ID VENDA nao encontrado: {sale_id}")

    def _sale_product_by_id(self, ws, sale_id: str) -> str | None:
        sales_cols = self._sales_columns(ws)
        row = self._find_sale_row(ws, sales_cols["id venda"], sale_id)
        value = ws[f"{sales_cols['id produto']}{row}"].value
        if value in (None, ""):
            return None
        return str(value).strip() or None

    def _cleanup_incomplete_sales_rows(self, ws, row_limit: int = 200) -> None:
        sales_cols = self._sales_columns(ws)
        legacy_status_col = sales_cols.get("status")
        tracked_cols = (
            sales_cols["data de venda"],
            sales_cols["id cliente"],
            sales_cols["id produto"],
            sales_cols["total de vendas (pago)"],
            sales_cols["valor (pendente)"],
            sales_cols["id venda"],
            sales_cols["status de valor"],
        )
        if legacy_status_col:
            tracked_cols = tracked_cols + (legacy_status_col,)

        required_sale_cols = (
            sales_cols["id produto"],
            sales_cols["total de vendas (pago)"],
            sales_cols["valor (pendente)"],
            sales_cols["id venda"],
        )
        aux_only_cols = (
            sales_cols["data de venda"],
            sales_cols["id cliente"],
            sales_cols["status de valor"],
        )
        if legacy_status_col:
            aux_only_cols = aux_only_cols + (legacy_status_col,)

        for row in range(DATA_START_ROW, min(ws.max_row, row_limit) + 1):
            has_main_data = any(ws[f"{col}{row}"].value not in (None, "") for col in required_sale_cols)
            if has_main_data:
                continue
            has_aux_data = any(ws[f"{col}{row}"].value not in (None, "") for col in aux_only_cols)
            if not has_aux_data:
                continue
            for col in tracked_cols:
                ws[f"{col}{row}"] = None

    def _cleanup_incomplete_material_rows(self, ws, row_limit: int = 200) -> None:
        material_cols = self._material_columns(ws)
        tracked_cols = (
            material_cols["data"],
            material_cols["descricao"],
            material_cols["valor"],
        )
        if material_cols.get("fornecedor"):
            tracked_cols = (material_cols["fornecedor"],) + tracked_cols
        if material_cols.get("id venda"):
            tracked_cols = tracked_cols + (material_cols["id venda"],)

        required_cols = (
            material_cols["descricao"],
            material_cols["valor"],
        )
        if material_cols.get("id venda"):
            required_cols = required_cols + (material_cols["id venda"],)
        aux_cols = (material_cols["data"],)
        if material_cols.get("fornecedor"):
            aux_cols = aux_cols + (material_cols["fornecedor"],)

        for row in range(DATA_START_ROW, min(ws.max_row, row_limit) + 1):
            has_main_data = any(ws[f"{col}{row}"].value not in (None, "") for col in required_cols)
            if has_main_data:
                continue
            has_aux_data = any(ws[f"{col}{row}"].value not in (None, "") for col in aux_cols)
            if not has_aux_data:
                continue
            for col in tracked_cols:
                ws[f"{col}{row}"] = None

    @staticmethod
    def _cleanup_incomplete_fixed_rows(ws, row_limit: int = 200) -> None:
        for row in range(DATA_START_ROW, min(ws.max_row, row_limit) + 1):
            has_main_data = any(ws[f"{col}{row}"].value not in (None, "") for col in ("B", "C"))
            if has_main_data:
                continue
            if ws[f"A{row}"].value in (None, ""):
                continue
            for col in ("A", "B", "C"):
                ws[f"{col}{row}"] = None

    def repair_layout(self, row_limit: int = 50) -> None:
        wb = self._open_workbook()
        try:
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            material_name = self._resolve_sheet_name(wb, SHEET_MATERIAL)
            fixed_name = self._resolve_sheet_name(wb, SHEET_FIXED)

            ws_sales = wb[sales_name]
            ws_material = wb[material_name]
            ws_fixed = wb[fixed_name]

            self._cleanup_incomplete_sales_rows(ws_sales, row_limit=max(row_limit, 200))
            self._cleanup_incomplete_material_rows(ws_material, row_limit=max(row_limit, 200))
            self._cleanup_incomplete_fixed_rows(ws_fixed, row_limit=max(row_limit, 200))

            for sheet_name, ws in (
                (sales_name, ws_sales),
                (material_name, ws_material),
                (fixed_name, ws_fixed),
            ):
                self._normalize_sheet_layout(wb, ws, sheet_name, row_limit=row_limit)

            self._save_workbook(wb)
        finally:
            wb.close()

    @staticmethod
    def _ensure_log_sheet(wb):
        if SHEET_LOG in wb.sheetnames:
            return wb[SHEET_LOG]
        ws = wb.create_sheet(SHEET_LOG)
        ws.append(
            [
                "id",
                "timestamp",
                "origem",
                "cliente",
                "descricao",
                "valor",
                "data_ref",
                "aba",
                "linha",
                "texto_original",
            ]
        )
        return ws

    @staticmethod
    def _ensure_reminders_sheet(wb):
        if SHEET_REMINDERS in wb.sheetnames:
            return wb[SHEET_REMINDERS]
        ws = wb.create_sheet(SHEET_REMINDERS)
        ws.append(
            [
                "ID VENDA",
                "Cliente",
                "Descricao",
                "Data venda",
                "Data entrega",
                "Valor pendente",
                "Status pagamento",
                "Status servico",
                "Chat ID",
                "Criado em",
                "Atualizado em",
            ]
        )
        return ws

    @staticmethod
    def _reminders_header_map(ws) -> dict[str, int]:
        headers: dict[str, int] = {}
        for col_idx in range(1, ws.max_column + 1):
            value = ws.cell(row=1, column=col_idx).value
            if value in (None, ""):
                continue
            headers[SpreadsheetService._normalize_name(str(value))] = col_idx
        return headers

    def upsert_reminder(
        self,
        wb,
        *,
        sale_id: str,
        customer: str,
        description: str,
        sale_date,
        due_date,
        pending_amount: float,
        payment_status: str,
        service_status: str,
        chat_id: str,
    ) -> None:
        ws = self._ensure_reminders_sheet(wb)
        headers = self._reminders_header_map(ws)
        col_sale_id = headers.get(self._normalize_name("ID VENDA"), 1)
        target_row: int | None = None
        for row in range(2, ws.max_row + 1):
            if str(ws.cell(row=row, column=col_sale_id).value or "").strip() == str(sale_id).strip():
                target_row = row
                break
        if target_row is None:
            target_row = ws.max_row + 1

        now = datetime.now()

        def _set(label: str, value) -> None:
            idx = headers.get(self._normalize_name(label))
            if not idx:
                return
            ws.cell(row=target_row, column=idx).value = value

        _set("ID VENDA", sale_id)
        _set("Cliente", customer)
        _set("Descricao", description)
        _set("Data venda", self._excel_date_value(sale_date))
        _set("Data entrega", self._excel_date_value(due_date) if due_date else "")
        _set("Valor pendente", float(pending_amount or 0.0))
        _set("Status pagamento", payment_status)
        _set("Status servico", service_status)
        _set("Chat ID", str(chat_id))
        if not ws.cell(row=target_row, column=headers.get(self._normalize_name("Criado em"), 10)).value:
            _set("Criado em", now)
        _set("Atualizado em", now)

        fill = FILL_DONE if self._normalize_name(service_status) == "finalizado" else FILL_PENDING
        for col in range(1, ws.max_column + 1):
            ws.cell(row=target_row, column=col).fill = fill

    def list_due_reminders(self, wb, today) -> list[dict]:
        """
        Retorna lembretes do dia, mas agora com consistência:
        - Ignora lembretes cujos IDs não existam mais na aba de Vendas.
        - Busca cliente/descrição/valores diretamente da aba de Vendas
          (evita notificar "cliente apagado" por lembretes antigos).
        """
        if SHEET_REMINDERS not in wb.sheetnames:
            return []
        if SHEET_SALES not in wb.sheetnames:
            return []

        ws_rem = wb[SHEET_REMINDERS]
        headers = self._reminders_header_map(ws_rem)
        idx_due = headers.get(self._normalize_name("Data entrega"))
        idx_status = headers.get(self._normalize_name("Status servico"))
        if not idx_due or not idx_status:
            return []

        # Aba de vendas (fonte da verdade para dados exibidos no lembrete)
        sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
        ws_sales = wb[sales_name]
        sales_cols = self._sales_columns(ws_sales)

        result: list[dict] = []
        today_txt = self._excel_date_value(today)

        for row in range(2, ws_rem.max_row + 1):
            status = str(ws_rem.cell(row=row, column=idx_status).value or "").strip()
            if self._normalize_name(status) == "finalizado":
                continue

            due_raw = str(ws_rem.cell(row=row, column=idx_due).value or "").strip()
            if not (due_raw and due_raw == today_txt):
                continue

            # Lê campos mínimos do lembrete
            sale_id = str(ws_rem.cell(row=row, column=headers.get(self._normalize_name("ID VENDA"), 1)).value or "").strip()
            if not sale_id:
                continue

            # Se a venda foi apagada/limpada na planilha, não notificar.
            try:
                sales_row = self._find_sale_row(ws_sales, sales_cols["id venda"], sale_id)
            except Exception:
                continue

            customer = str(ws_sales[f"{sales_cols['id cliente']}{sales_row}"].value or "").strip()
            product_desc = str(ws_sales[f"{sales_cols['id produto']}{sales_row}"].value or "").strip()
            pending_amount = self._to_float(ws_sales[f"{sales_cols['valor (pendente)']}{sales_row}"].value)
            paid_amount = self._to_float(ws_sales[f"{sales_cols['total de vendas (pago)']}{sales_row}"].value)
            total_amount = round(pending_amount + paid_amount, 2)

            # Retorna também os campos originais do lembrete (Chat ID), mas
            # injeta cliente/descrição/valores atuais.
            record: dict = {}
            for key, idx in headers.items():
                record[key] = str(ws_rem.cell(row=row, column=idx).value or "")

            record["id venda"] = sale_id
            record["cliente"] = customer
            record["descricao"] = product_desc
            record["pending_amount_num"] = pending_amount
            record["total_amount_num"] = total_amount

            result.append(record)

        return result

    def finalize_reminder(self, wb, sale_id: str) -> bool:
        if SHEET_REMINDERS not in wb.sheetnames:
            return False
        ws = wb[SHEET_REMINDERS]
        headers = self._reminders_header_map(ws)
        col_sale_id = headers.get(self._normalize_name("ID VENDA"), 1)
        col_status = headers.get(self._normalize_name("Status servico"))
        col_updated = headers.get(self._normalize_name("Atualizado em"))
        if not col_status:
            return False
        for row in range(2, ws.max_row + 1):
            if str(ws.cell(row=row, column=col_sale_id).value or "").strip() != str(sale_id).strip():
                continue
            ws.cell(row=row, column=col_status).value = "FINALIZADO"
            if col_updated:
                ws.cell(row=row, column=col_updated).value = datetime.now()
            for col in range(1, ws.max_column + 1):
                ws.cell(row=row, column=col).fill = FILL_DONE
            return True
        return False

    def finalize_service(self, sale_id: str) -> bool:
        """Marca serviço como finalizado (Lembretes + cor verde na Data de Entrega da aba de vendas)."""
        wb = self._open_workbook()
        try:
            changed = False
            # 1) Aba Lembretes
            if self.finalize_reminder(wb, sale_id):
                changed = True

            # 2) Aba de vendas: pintar Data de Entrega de verde
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            ws_sales = wb[sales_name]
            sales_cols = self._sales_columns(ws_sales)
            col_sale_id = sales_cols["id venda"]
            col_delivery = sales_cols["data de entrega"]
            for row in range(DATA_START_ROW, min(ws_sales.max_row + 1, self.MAX_DATA_ROW)):
                if str(ws_sales[f"{col_sale_id}{row}"].value or "").strip() != str(sale_id).strip():
                    continue
                ws_sales[f"{col_delivery}{row}"].fill = FILL_DONE
                changed = True
                break

            if changed:
                self._save_workbook(wb)
            return changed
        finally:
            wb.close()

    def _sale_snapshot(self, ws_sales, sale_id: str) -> dict[str, str]:
        """Lê dados principais da venda pelo ID VENDA para atualizar lembretes mesmo em mensagens de atualização."""
        sales_cols = self._sales_columns(ws_sales)
        col_sale_id = sales_cols["id venda"]
        row_found = None
        for row in range(DATA_START_ROW, min(ws_sales.max_row + 1, self.MAX_DATA_ROW)):
            if str(ws_sales[f"{col_sale_id}{row}"].value or "").strip() == str(sale_id).strip():
                row_found = row
                break
        if row_found is None:
            return {}
        def _v(key: str) -> str:
            col = sales_cols.get(key)
            if not col:
                return ""
            return str(ws_sales[f"{col}{row_found}"].value or "").strip()
        return {
            "sale_id": str(sale_id).strip(),
            "customer": _v("id cliente"),
            "description": _v("id produto"),
            "sale_date": _v("data de venda") or _v("data"),
            "delivery_date": _v("data de entrega"),
            "pending_amount": _v("valor (pendente)"),
            "payment_status": _v("status de valor"),
        }

    def _append_sale(self, wb, ws, cmd: FinancialCommand) -> tuple[int, str, float]:
        """Adiciona uma linha de venda em qualquer linha. Copia estilo da planilha (negrito, cores, formato); só preenche valores."""
        sales_cols = self._sales_columns(ws)
        style_cols = self._sales_style_cols(ws)
        row = self._next_row_for_empty_cols(
            ws,
            (
                sales_cols["id produto"],
                sales_cols["total de vendas (pago)"],
                sales_cols["valor (pendente)"],
                sales_cols["id venda"],
            ),
            start_row=DATA_START_ROW,
        )
        template_ws, template_row = self._prepare_row_from_template(
            wb,
            ws,
            row,
            SHEET_SALES,
            style_cols,
            start_row=TEMPLATE_ROW,
        )
        # Não sobrescrever bordas/estilo que já existam na linha (muitos usuários formatam a tabela inteira).
        # Só aplica o template quando a linha estiver realmente sem estilo.
        if not self._row_has_any_style(ws, row, style_cols):
            self._copy_sales_row_style_from_template(wb, ws, row)

        paid_amount = round(sum(p.value for p in cmd.payments if p.status == "pago"), 2)
        pending_amount = round(sum(p.value for p in cmd.payments if p.status != "pago"), 2)
        if abs((paid_amount + pending_amount) - float(cmd.total_value or 0.0)) >= 0.01:
            pending_amount = round(max(float(cmd.total_value or 0.0) - paid_amount, 0.0), 2)
        sale_id = (cmd.sale_id or "").strip() or self._generate_sale_id(ws, sales_cols["id venda"])
        value_status = self._status_text(pending_amount)
        value_status_display = self._match_text_case(
            template_ws[f"{sales_cols['status de valor']}{template_row}"].value,
            value_status,
        )

        # Datas seguindo o padrão da planilha (Data de venda / Data de Entrega)
        ws[f"{sales_cols['data de venda']}{row}"] = self._excel_date_value(cmd.sale_date)
        # Data de Entrega:
        # - Preferência: campo explícito (cmd.service_due_date).
        # - Fallback: vence do "Saldo" (quando o usuário só fala "restante dia 10/04").
        delivery_date = cmd.service_due_date
        if delivery_date is None and cmd.payments:
            for p in cmd.payments:
                if str(getattr(p, "label", "") or "").strip().lower() == "saldo" and getattr(p, "due_date", None):
                    delivery_date = p.due_date
                    break

        if delivery_date:
            ws[f"{sales_cols['data de entrega']}{row}"] = self._excel_date_value(delivery_date)
            delivery_cell = ws[f"{sales_cols['data de entrega']}{row}"]
            ref_date = datetime.now().date()
            due_date = delivery_date
            # Cor segue regra:
            # - Se pagou (sem pendente), verde.
            # - Se ainda há pendente e a entrega é futura, amarelo.
            # - Se pendente e entrega nao é futura, mantem o preenchimento-base do template.
            if abs(float(pending_amount or 0.0)) < 0.01:
                delivery_cell.fill = FILL_DONE
            elif due_date and due_date > ref_date:
                delivery_cell.fill = FILL_PENDING
        else:
            # Se não houver prazo, limpa cor para manter o estilo original da planilha.
            ws[f"{sales_cols['data de entrega']}{row}"].fill = copy(template_ws[f"{sales_cols['data de entrega']}{template_row}"].fill)
        ws[f"{sales_cols['id cliente']}{row}"] = cmd.customer
        ws[f"{sales_cols['id produto']}{row}"] = cmd.product_id or cmd.description
        ws[f"{sales_cols['total de vendas (pago)']}{row}"] = float(paid_amount)
        ws[f"{sales_cols['valor (pendente)']}{row}"] = float(pending_amount)
        ws[f"{sales_cols['id venda']}{row}"] = sale_id
        ws[f"{sales_cols['status de valor']}{row}"] = value_status_display

        # Garantir formato data/moeda quando a célula estiver em General (não sobrescreve formatação da planilha)
        self._ensure_number_format_if_general(ws, sales_cols["data de venda"], row, "DD/MM/YYYY")
        self._ensure_number_format_if_general(ws, sales_cols["data de entrega"], row, "DD/MM/YYYY")
        return row, sale_id, paid_amount

    def _append_material(
        self,
        wb,
        ws,
        supplier: str,
        description: str,
        amount: float,
        ref_date,
        sale_id: str | None = None,
    ) -> int:
        """Adiciona linha na aba Compras Matéria-Prima. Formatação = linha 1048576 dessa aba (Data, Fornecedor, Descrição, ID VENDA, Valor)."""
        material_cols = self._material_columns(ws)
        style_cols = (
            material_cols["data"],
            material_cols["descricao"],
            material_cols["valor"],
        )
        if material_cols.get("fornecedor"):
            style_cols = (material_cols["fornecedor"],) + style_cols
        if material_cols.get("id venda"):
            style_cols = style_cols + (material_cols["id venda"],)
        empty_cols = (material_cols["descricao"], material_cols["valor"])
        if material_cols.get("id venda"):
            empty_cols = empty_cols + (material_cols["id venda"],)
        row = self._next_row_for_empty_cols(ws, empty_cols, start_row=DATA_START_ROW)
        self._prepare_row_from_template(
            wb,
            ws,
            row,
            SHEET_MATERIAL,
            style_cols,
            start_row=TEMPLATE_ROW,
        )
        ws[f"{material_cols['data']}{row}"] = self._excel_date_value(ref_date)
        if material_cols.get("fornecedor"):
            ws[f"{material_cols['fornecedor']}{row}"] = supplier
        ws[f"{material_cols['descricao']}{row}"] = description
        ws[f"{material_cols['valor']}{row}"] = float(amount)
        if material_cols.get("id venda") and sale_id:
            ws[f"{material_cols['id venda']}{row}"] = sale_id
        self._ensure_number_format_if_general(ws, material_cols["data"], row, "DD/MM/YYYY")
        self._ensure_number_format_if_general(ws, material_cols["valor"], row, "R$ #,##0.00")
        return row

    def _append_fixed(self, wb, ws, label: str, amount: float, ref_date) -> int:
        row = self._next_row_for_empty_cols(ws, ("B", "C"), start_row=DATA_START_ROW)
        self._prepare_row_from_template(
            wb,
            ws,
            row,
            SHEET_FIXED,
            ("A", "B", "C"),
            start_row=TEMPLATE_ROW,
        )
        ws[f"A{row}"] = self._excel_date_value(ref_date)
        ws[f"B{row}"] = label
        ws[f"C{row}"] = float(amount)
        self._ensure_number_format_if_general(ws, "A", row, "DD/MM/YYYY")
        self._ensure_number_format_if_general(ws, "C", row, "R$ #,##0.00")
        return row

    @staticmethod
    def _append_log(ws, log_id: str, origin: str, cmd: FinancialCommand, amount: float, ref_date, sheet: str, row: int, original_text: str) -> None:
        ws.append(
            [
                log_id,
                datetime.now(),
                origin,
                cmd.customer,
                cmd.description,
                amount,
                ref_date,
                sheet,
                row,
                original_text,
            ]
        )

    def apply_command(
        self,
        cmd: FinancialCommand,
        original_text: str,
        origin: str = "texto",
        *,
        chat_id: str | None = None,
    ) -> list[WriteAction]:
        wb = self._open_workbook()
        try:
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            material_name = self._resolve_sheet_name(wb, SHEET_MATERIAL)
            fixed_name = self._resolve_sheet_name(wb, SHEET_FIXED)

            ws_sales = wb[sales_name]
            ws_material = wb[material_name]
            ws_fixed = wb[fixed_name]
            ws_log = self._ensure_log_sheet(wb)
            # Salva o padrão da linha 3 no template (negrito, cores, amarelo em pendente). Mesmo que a pessoa apague a linha 3, o robô mantém esse padrão.
            self._save_padrao_row3_to_template(wb, ws_sales, sales_name)
            self._save_padrao_row3_to_template(wb, ws_material, material_name)
            self._save_padrao_row3_to_template(wb, ws_fixed, fixed_name)
            self._cleanup_incomplete_sales_rows(ws_sales)
            self._cleanup_incomplete_material_rows(ws_material)
            self._cleanup_incomplete_fixed_rows(ws_fixed)
            self._normalize_sheet_layout(wb, ws_sales, sales_name, row_limit=120)
            self._normalize_sheet_layout(wb, ws_material, material_name, row_limit=120)
            self._normalize_sheet_layout(wb, ws_fixed, fixed_name, row_limit=120)
            actions: list[WriteAction] = []
            log_root = datetime.now().strftime("%Y%m%d%H%M%S")
            created_sale_id: str | None = cmd.sale_id

            if cmd.total_value > 0:
                row, sale_id, paid_amount = self._append_sale(wb, ws_sales, cmd)
                created_sale_id = sale_id
                actions.append(
                    WriteAction(
                        sheet=sales_name,
                        row=row,
                        amount=cmd.total_value,
                        label="Venda",
                        sale_id=sale_id,
                    )
                )
                self._append_log(
                    ws=ws_log,
                    log_id=f"{log_root}-V-1",
                    origin=origin,
                    cmd=FinancialCommand(
                        customer=cmd.customer,
                        description=cmd.product_id or cmd.description,
                        sale_date=cmd.sale_date,
                        total_value=cmd.total_value,
                        payments=cmd.payments,
                        product_id=cmd.product_id,
                        sale_id=sale_id,
                    ),
                    amount=paid_amount,
                    ref_date=cmd.sale_date,
                    sheet=sales_name,
                    row=row,
                    original_text=original_text,
                )

                # Registrar/atualizar lembrete (aba Lembretes) quando o comando veio do bot.
                if created_sale_id:
                    pending_amount = 0.0
                    latest_due = None
                    for p in cmd.payments:
                        if (p.status or "").strip().lower() != "pago":
                            pending_amount += float(p.value or 0.0)
                            latest_due = max(latest_due, p.due_date) if latest_due else p.due_date
                    payment_status = "PENDENTE" if pending_amount > 0.01 else "PAGO"
                    due_date = cmd.service_due_date or latest_due
                    service_status = "FINALIZADO" if (cmd.service_status or "").strip().lower() == "finalizado" else "PENDENTE"
                    if due_date or pending_amount > 0.01 or (chat_id and str(chat_id).strip()):
                        self.upsert_reminder(
                            wb,
                            sale_id=str(created_sale_id),
                            customer=cmd.customer or "",
                            description=cmd.product_id or cmd.description or "",
                            sale_date=cmd.sale_date,
                            due_date=due_date,
                            pending_amount=pending_amount,
                            payment_status=payment_status,
                            service_status=service_status,
                            chat_id=str(chat_id or ""),
                        )

            if cmd.material_allocations:
                for idx, allocation in enumerate(cmd.material_allocations, start=1):
                    material_description = allocation.description or self._sale_product_by_id(ws_sales, allocation.sale_id)
                    if not material_description:
                        material_description = f"Material da venda {allocation.sale_id}"
                    mat_row = self._append_material(
                        wb,
                        ws_material,
                        supplier="",
                        description=material_description,
                        amount=allocation.amount,
                        ref_date=allocation.material_date,
                        sale_id=allocation.sale_id,
                    )
                    actions.append(
                        WriteAction(
                            sheet=material_name,
                            row=mat_row,
                            amount=allocation.amount,
                            label="Material",
                            sale_id=allocation.sale_id,
                        )
                    )
                    self._append_log(
                        ws=ws_log,
                        log_id=f"{log_root}-M-{idx}",
                        origin=origin,
                        cmd=FinancialCommand(
                            customer=cmd.customer,
                            description=material_description,
                            sale_date=cmd.sale_date,
                            total_value=0.0,
                            payments=[],
                            sale_id=allocation.sale_id,
                        ),
                        amount=allocation.amount,
                        ref_date=allocation.material_date,
                        sheet=material_name,
                        row=mat_row,
                        original_text=original_text,
                    )
            elif cmd.material_cost and cmd.material_cost > 0:
                material_description = cmd.product_id or cmd.description
                if created_sale_id and (not material_description or str(material_description).startswith("Material da venda ")):
                    material_description = self._sale_product_by_id(ws_sales, created_sale_id) or material_description
                mat_row = self._append_material(
                    wb,
                    ws_material,
                    supplier="",
                    description=material_description,
                    amount=cmd.material_cost,
                    ref_date=cmd.material_date or cmd.sale_date,
                    sale_id=created_sale_id,
                )
                actions.append(
                    WriteAction(
                        sheet=material_name,
                        row=mat_row,
                        amount=cmd.material_cost,
                        label="Material",
                        sale_id=created_sale_id,
                    )
                )
                self._append_log(
                    ws=ws_log,
                    log_id=f"{log_root}-M-1",
                    origin=origin,
                    cmd=cmd,
                    amount=cmd.material_cost,
                    ref_date=cmd.material_date or cmd.sale_date,
                    sheet=material_name,
                    row=mat_row,
                    original_text=original_text,
                )

            if cmd.fixed_cost and cmd.fixed_cost > 0:
                fixed_row = self._append_fixed(
                    wb,
                    ws_fixed,
                    label=cmd.fixed_cost_label or "Gasto fixo via audio",
                    amount=cmd.fixed_cost,
                    ref_date=cmd.fixed_cost_date or cmd.sale_date,
                )
                actions.append(WriteAction(sheet=fixed_name, row=fixed_row, amount=cmd.fixed_cost, label="Gasto fixo"))
                self._append_log(
                    ws=ws_log,
                    log_id=f"{log_root}-F-1",
                    origin=origin,
                    cmd=cmd,
                    amount=cmd.fixed_cost,
                    ref_date=cmd.fixed_cost_date or cmd.sale_date,
                    sheet=fixed_name,
                    row=fixed_row,
                    original_text=original_text,
                )

            self._save_workbook(wb)
            return actions
        finally:
            wb.close()

    def apply_refund(
        self,
        refund: RefundCommand,
        original_text: str = "",
        origin: str = "audio",
    ) -> WriteAction:
        """Registra um estorno na aba de vendas (valor negativo) e no log."""
        wb = self._open_workbook()
        try:
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            ws_sales = wb[sales_name]
            ws_log = self._ensure_log_sheet(wb)
            self._save_padrao_row3_to_template(wb, ws_sales, sales_name)
            self._cleanup_incomplete_sales_rows(ws_sales)
            self._normalize_sheet_layout(wb, ws_sales, sales_name, row_limit=120)
            sales_cols = self._sales_columns(ws_sales)
            style_cols = self._sales_style_cols(ws_sales)
            row = self._next_row_for_empty_cols(
                ws_sales,
                (
                    sales_cols["id produto"],
                    sales_cols["total de vendas (pago)"],
                    sales_cols["valor (pendente)"],
                    sales_cols["id venda"],
                ),
                start_row=DATA_START_ROW,
            )
            amount = -abs(float(refund.amount))
            sale_id = self._generate_sale_id(ws_sales, sales_cols["id venda"])
            template_ws, template_row = self._prepare_row_from_template(
                wb,
                ws_sales,
                row,
                SHEET_SALES,
                style_cols,
                start_row=TEMPLATE_ROW,
            )
            status_paid = self._match_text_case(
                template_ws[f"{sales_cols['status de valor']}{template_row}"].value,
                "pago",
            )
            ws_sales[f"{sales_cols['data de venda']}{row}"] = self._excel_date_value(refund.ref_date)
            ws_sales[f"{sales_cols['id cliente']}{row}"] = refund.customer
            ws_sales[f"{sales_cols['id produto']}{row}"] = f"Estorno - {refund.reason}"
            ws_sales[f"{sales_cols['total de vendas (pago)']}{row}"] = amount
            ws_sales[f"{sales_cols['valor (pendente)']}{row}"] = 0.0
            ws_sales[f"{sales_cols['id venda']}{row}"] = sale_id
            ws_sales[f"{sales_cols['status de valor']}{row}"] = status_paid
            self._ensure_number_format_if_general(ws_sales, sales_cols["data de venda"], row, "DD/MM/YYYY")
            action = WriteAction(sheet=sales_name, row=row, amount=amount, label="Estorno", sale_id=sale_id)
            self._append_log(
                ws=ws_log,
                log_id=f"{datetime.now().strftime('%Y%m%d%H%M%S')}-E-1",
                origin=origin,
                cmd=FinancialCommand(
                    customer=refund.customer,
                    description=refund.reason,
                    sale_date=refund.ref_date,
                    total_value=refund.amount,
                    payments=[],
                    sale_id=sale_id,
                ),
                amount=amount,
                ref_date=refund.ref_date,
                sheet=sales_name,
                row=row,
                original_text=original_text,
            )
            self._save_workbook(wb)
            return action
        finally:
            wb.close()

    def update_sale_status(
        self,
        status_update: StatusUpdateCommand,
        original_text: str = "",
        origin: str = "status-update",
    ) -> WriteAction:
        wb = self._open_workbook()
        try:
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            ws_sales = wb[sales_name]
            ws_log = self._ensure_log_sheet(wb)
            self._save_padrao_row3_to_template(wb, ws_sales, sales_name)
            self._normalize_sheet_layout(wb, ws_sales, sales_name, row_limit=120)
            sales_cols = self._sales_columns(ws_sales)
            row = self._find_sale_row(ws_sales, sales_cols["id venda"], status_update.sale_id)

            paid_col = sales_cols["total de vendas (pago)"]
            pending_col = sales_cols["valor (pendente)"]
            value_status_col = sales_cols["status de valor"]
            # Reaplica o padrão visual da linha inteira para recuperar bordas
            # caso alguém tenha apagado estilo manualmente.
            self._copy_sales_row_style_from_template(wb, ws_sales, row)

            current_paid = self._to_float(ws_sales[f"{paid_col}{row}"].value)
            current_pending = self._to_float(ws_sales[f"{pending_col}{row}"].value)
            status = status_update.status.strip().lower()
            amount_moved = 0.0

            if status == "pago" and current_pending > 0:
                amount_moved = current_pending
                current_paid = round(current_paid + current_pending, 2)
                current_pending = 0.0

            status_display = self._match_text_case(ws_sales[f"{value_status_col}{row}"].value, status)
            ws_sales[f"{paid_col}{row}"] = current_paid
            ws_sales[f"{pending_col}{row}"] = current_pending
            ws_sales[f"{value_status_col}{row}"] = status_display
            # Garante padrão visual do financeiro (cores/fontes do template da linha 3).
            template_ws, template_row = self._template_source(
                wb,
                ws_sales,
                SHEET_SALES,
                self._sales_style_cols(ws_sales),
            )
            self._copy_row_style_between(
                template_ws,
                template_row,
                ws_sales,
                row,
                (paid_col, pending_col, value_status_col),
                apply_row_dimensions=False,
            )
            ws_sales[f"{paid_col}{row}"] = current_paid
            ws_sales[f"{pending_col}{row}"] = current_pending
            ws_sales[f"{value_status_col}{row}"] = status_display
            # Quando status muda, refletir também na cor da Data de Entrega.
            delivery_col = sales_cols.get("data de entrega")
            if delivery_col:
                # Reaplica o estilo-base da coluna para preservar bordas/fonte
                # sem perder o valor já registrado da data de entrega.
                current_delivery_value = ws_sales[f"{delivery_col}{row}"].value
                template_ws, template_row = self._template_source(
                    wb,
                    ws_sales,
                    SHEET_SALES,
                    self._sales_style_cols(ws_sales),
                )
                self._copy_row_style_between(
                    template_ws, template_row, ws_sales, row, (delivery_col,), apply_row_dimensions=False
                )
                ws_sales[f"{delivery_col}{row}"] = current_delivery_value
                delivery_cell = ws_sales[f"{delivery_col}{row}"]
                ref_date = status_update.ref_date
                due_date = self._parse_date_cell(current_delivery_value)
                if abs(float(current_pending or 0.0)) < 0.01:
                    delivery_cell.fill = FILL_DONE
                elif due_date and due_date > ref_date:
                    delivery_cell.fill = FILL_PENDING
                # Caso nao seja entrega futura (ou nao haja data), mantem o preenchimento do template.
                self._ensure_number_format_if_general(ws_sales, delivery_col, row, "DD/MM/YYYY")

            customer = status_update.customer or str(ws_sales[f"{sales_cols['id cliente']}{row}"].value or "")
            product = str(ws_sales[f"{sales_cols['id produto']}{row}"].value or "")
            self._append_log(
                ws=ws_log,
                log_id=f"{datetime.now().strftime('%Y%m%d%H%M%S')}-S-1",
                origin=origin,
                cmd=FinancialCommand(
                    customer=customer,
                    description=product or f"Atualizacao de status {status_update.sale_id}",
                    sale_date=status_update.ref_date,
                    total_value=current_paid + current_pending,
                    payments=[],
                    product_id=product or None,
                    sale_id=status_update.sale_id,
                ),
                amount=amount_moved,
                ref_date=status_update.ref_date,
                sheet=sales_name,
                row=row,
                original_text=original_text,
            )

            self._save_workbook(wb)
            return WriteAction(
                sheet=sales_name,
                row=row,
                amount=amount_moved,
                label=f"Status {status}",
                sale_id=status_update.sale_id,
            )
        finally:
            wb.close()

    def update_sale_delivery_date(self, sale_id: str, delivery_date) -> None:
        """Atualiza apenas a coluna 'Data de Entrega' para um ID VENDA existente.

        Observação: alguns usuários enviam "cliente id 003" querendo dizer o ID VENDA.
        Por isso, se não achar por ID VENDA, tentamos também casar pelo ID Cliente.
        """
        wb = self._open_workbook()
        try:
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            ws_sales = wb[sales_name]
            sales_cols = self._sales_columns(ws_sales)
            col_sale_id = sales_cols["id venda"]
            col_delivery = sales_cols["data de entrega"]
            col_customer = sales_cols.get("id cliente")
            target_row = None
            needle = str(sale_id).strip()
            # 1) Primeiro tenta por ID VENDA
            for row in range(DATA_START_ROW, min(ws_sales.max_row + 1, self.MAX_DATA_ROW)):
                if str(ws_sales[f"{col_sale_id}{row}"].value or "").strip() == needle:
                    target_row = row
                    break
            # 2) Fallback: tenta por ID Cliente (quando o usuário fala "cliente id 003")
            if target_row is None and col_customer:
                for row in range(DATA_START_ROW, min(ws_sales.max_row + 1, self.MAX_DATA_ROW)):
                    if str(ws_sales[f"{col_customer}{row}"].value or "").strip() == needle:
                        target_row = row
                        break
            if target_row is None:
                return
            # Não reaplicar estilo da linha inteira em updates: preserva bordas já existentes.
            ws_sales[f"{col_delivery}{target_row}"] = self._excel_date_value(delivery_date)
            # Cor da Data de Entrega acompanha status financeiro atual da linha.
            pending_col = sales_cols["valor (pendente)"]
            current_pending = self._to_float(ws_sales[f"{pending_col}{target_row}"].value)
            delivery_cell = ws_sales[f"{col_delivery}{target_row}"]
            if abs(float(current_pending or 0.0)) < 0.01:
                delivery_cell.fill = FILL_DONE
            else:
                # Pendente => amarelo (mesmo se a data for hoje ou passada).
                delivery_cell.fill = FILL_PENDING
            # Mantém formato de data se a célula estiver como General.
            self._ensure_number_format_if_general(ws_sales, col_delivery, target_row, "DD/MM/YYYY")
            self._save_workbook(wb)
        finally:
            wb.close()

    def apply_partial_payment(self, sale_id: str, amount: float, ref_date: date, original_text: str = "", origin: str = "payment_update") -> WriteAction | None:
        """Move parte do valor pendente -> pago para um ID VENDA (correção de entrada parcial)."""
        if amount is None or float(amount) <= 0:
            return None
        wb = self._open_workbook()
        try:
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            ws_sales = wb[sales_name]
            ws_log = self._ensure_log_sheet(wb)
            sales_cols = self._sales_columns(ws_sales)
            row = self._find_sale_row(ws_sales, sales_cols["id venda"], str(sale_id).strip())
            paid_col = sales_cols["total de vendas (pago)"]
            pending_col = sales_cols["valor (pendente)"]
            status_col = sales_cols["status de valor"]
            delivery_col = sales_cols.get("data de entrega")

            current_paid = self._to_float(ws_sales[f"{paid_col}{row}"].value)
            current_pending = self._to_float(ws_sales[f"{pending_col}{row}"].value)
            move = min(float(amount), float(current_pending))
            current_paid = round(current_paid + move, 2)
            current_pending = round(max(current_pending - move, 0.0), 2)
            ws_sales[f"{paid_col}{row}"] = current_paid
            ws_sales[f"{pending_col}{row}"] = current_pending
            ws_sales[f"{status_col}{row}"] = self._match_text_case(
                ws_sales[f"{status_col}{row}"].value,
                self._status_text(current_pending),
            )

            # Atualizar cor da entrega conforme pendência (sem mexer em bordas)
            if delivery_col:
                cell = ws_sales[f"{delivery_col}{row}"]
                if abs(float(current_pending or 0.0)) < 0.01:
                    cell.fill = FILL_DONE
                else:
                    cell.fill = FILL_PENDING

            customer = str(ws_sales[f"{sales_cols['id cliente']}{row}"].value or "")
            product = str(ws_sales[f"{sales_cols['id produto']}{row}"].value or "")
            self._append_log(
                ws=ws_log,
                log_id=f"{datetime.now().strftime('%Y%m%d%H%M%S')}-P-1",
                origin=origin,
                cmd=FinancialCommand(
                    customer=customer,
                    description=product or f"Pagamento parcial {sale_id}",
                    sale_date=ref_date,
                    total_value=current_paid + current_pending,
                    payments=[],
                    product_id=product or None,
                    sale_id=str(sale_id).strip(),
                ),
                amount=move,
                ref_date=ref_date,
                sheet=sales_name,
                row=row,
                original_text=original_text,
            )
            self._save_workbook(wb)
            return WriteAction(sheet=sales_name, row=row, amount=move, label="Pagamento parcial", sale_id=str(sale_id).strip())
        except Exception:
            return None
        finally:
            wb.close()

    def update_row(
        self,
        sheet_name: str,
        row: int,
        ref_date,
        party: str,
        description: str,
        amount: float,
        original_text: str = "",
        origin: str = "correcao",
    ) -> None:
        if row < DATA_START_ROW:
            raise ValueError(f"Linha invalida. Use linhas a partir da {DATA_START_ROW}.")

        wb = self._open_workbook()
        try:
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            material_name = self._resolve_sheet_name(wb, SHEET_MATERIAL)
            fixed_name = self._resolve_sheet_name(wb, SHEET_FIXED)
            target_name = self._resolve_sheet_name(wb, sheet_name)

            ws = wb[target_name]
            ws_log = self._ensure_log_sheet(wb)
            self._save_padrao_row3_to_template(wb, ws, target_name)
            self._normalize_sheet_layout(wb, ws, target_name, row_limit=max(120, row))

            target_norm = self._normalize_name(target_name)
            if target_norm in (self._normalize_name(sales_name), self._normalize_name(material_name)):
                if target_norm == self._normalize_name(sales_name):
                    sales_cols = self._sales_columns(ws)
                    style_cols = self._sales_style_cols(ws)

            # Se foi uma atualização por ID (ex.: "ID VENDA 1001, gastei 800 de material"),
            # atualiza/garante lembrete com base no que já está na planilha de vendas.
            target_sale_id = created_sale_id
            if not target_sale_id:
                if cmd.sale_id:
                    target_sale_id = str(cmd.sale_id).strip()
                elif cmd.material_allocations:
                    target_sale_id = str(cmd.material_allocations[0].sale_id).strip()
            if chat_id and target_sale_id:
                snap = self._sale_snapshot(ws_sales, target_sale_id)
                if snap:
                    pending_amount = self._to_float(snap.get("pending_amount"))
                    payment_status = snap.get("payment_status") or ("PENDENTE" if pending_amount > 0.01 else "PAGO")
                    due_date = snap.get("delivery_date") or ""
                    self.upsert_reminder(
                        wb,
                        sale_id=target_sale_id,
                        customer=snap.get("customer", ""),
                        description=snap.get("description", ""),
                        sale_date=snap.get("sale_date") or cmd.sale_date,
                        due_date=due_date or cmd.service_due_date,
                        pending_amount=pending_amount,
                        payment_status=payment_status,
                        service_status="PENDENTE",
                        chat_id=str(chat_id),
                    )
                    self._prepare_row_from_template(
                        wb,
                        ws,
                        row,
                        SHEET_SALES,
                        style_cols,
                        start_row=TEMPLATE_ROW,
                    )
                    ws[f"{sales_cols['data de venda']}{row}"] = self._excel_date_value(ref_date)
                    ws[f"{sales_cols['id cliente']}{row}"] = party
                    ws[f"{sales_cols['id produto']}{row}"] = description
                    ws[f"{sales_cols['total de vendas (pago)']}{row}"] = float(amount)
                    if ws[f"{sales_cols['valor (pendente)']}{row}"].value in (None, ""):
                        ws[f"{sales_cols['valor (pendente)']}{row}"] = 0.0
                    pending_amount = self._to_float(ws[f"{sales_cols['valor (pendente)']}{row}"].value)
                    status = self._status_text(pending_amount)
                    ws[f"{sales_cols['status de valor']}{row}"] = self._match_text_case(
                        ws[f"{sales_cols['status de valor']}{row}"].value,
                        status,
                    )
                    # Reforça visual do padrão da planilha para valores/status.
                    template_ws, template_row = self._template_source(
                        wb,
                        ws,
                        SHEET_SALES,
                        self._sales_style_cols(ws),
                    )
                    self._copy_row_style_between(
                        template_ws,
                        template_row,
                        ws,
                        row,
                        (
                            sales_cols["total de vendas (pago)"],
                            sales_cols["valor (pendente)"],
                            sales_cols["status de valor"],
                        ),
                        apply_row_dimensions=False,
                    )
                    ws[f"{sales_cols['total de vendas (pago)']}{row}"] = float(amount)
                    if ws[f"{sales_cols['valor (pendente)']}{row}"].value in (None, ""):
                        ws[f"{sales_cols['valor (pendente)']}{row}"] = 0.0
                    pending_amount = self._to_float(ws[f"{sales_cols['valor (pendente)']}{row}"].value)
                    status = self._status_text(pending_amount)
                    ws[f"{sales_cols['status de valor']}{row}"] = self._match_text_case(
                        ws[f"{sales_cols['status de valor']}{row}"].value,
                        status,
                    )
                    self._ensure_number_format_if_general(ws, sales_cols["data de venda"], row, "DD/MM/YYYY")
                else:
                    material_cols = self._material_columns(ws)
                    style_cols = (
                        material_cols["data"],
                        material_cols["descricao"],
                        material_cols["valor"],
                    )
                    if material_cols.get("fornecedor"):
                        style_cols = (material_cols["fornecedor"],) + style_cols
                    if material_cols.get("id venda"):
                        style_cols = style_cols + (material_cols["id venda"],)
                    self._prepare_row_from_template(
                        wb,
                        ws,
                        row,
                        SHEET_MATERIAL,
                        style_cols,
                        start_row=TEMPLATE_ROW,
                    )
                    ws[f"{material_cols['data']}{row}"] = self._excel_date_value(ref_date)
                    if material_cols.get("fornecedor"):
                        ws[f"{material_cols['fornecedor']}{row}"] = party
                    ws[f"{material_cols['descricao']}{row}"] = description
                    ws[f"{material_cols['valor']}{row}"] = float(amount)
                    self._ensure_number_format_if_general(ws, material_cols["data"], row, "DD/MM/YYYY")
                    self._ensure_number_format_if_general(ws, material_cols["valor"], row, "R$ #,##0.00")
            elif target_norm == self._normalize_name(fixed_name):
                self._prepare_row_from_template(
                    wb,
                    ws,
                    row,
                    SHEET_FIXED,
                    ("A", "B", "C"),
                    start_row=TEMPLATE_ROW,
                )
                ws[f"A{row}"] = self._excel_date_value(ref_date)
                ws[f"B{row}"] = description
                ws[f"C{row}"] = float(amount)
                self._ensure_number_format_if_general(ws, "A", row, "DD/MM/YYYY")
                self._ensure_number_format_if_general(ws, "C", row, "R$ #,##0.00")
            else:
                raise ValueError(f"Aba nao suportada para correcao: {target_name}")

            self._append_log(
                ws=ws_log,
                log_id=f"{datetime.now().strftime('%Y%m%d%H%M%S')}-U-1",
                origin=origin,
                cmd=FinancialCommand(
                    customer=party or "",
                    description=description,
                    sale_date=ref_date,
                    total_value=float(amount),
                    payments=[],
                ),
                amount=float(amount),
                ref_date=ref_date,
                sheet=target_name,
                row=row,
                original_text=original_text,
            )

            self._save_workbook(wb)
        finally:
            wb.close()

    def read_last_rows(self, sheet_name: str, limit: int = 8) -> list[dict[str, str]]:
        wb = self._open_workbook(data_only=True)
        try:
            target_name = self._resolve_sheet_name(wb, sheet_name)
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            fixed_name = self._resolve_sheet_name(wb, SHEET_FIXED)
            ws = wb[target_name]

            if self._normalize_name(target_name) == self._normalize_name(fixed_name):
                cols = ("A", "B", "C")
            elif self._normalize_name(target_name) == self._normalize_name(sales_name):
                sales_cols = self._sales_columns(ws)
                cols = tuple(
                    sales_cols[key]
                    for key in (
                        "data de venda",
                        "data de entrega",
                        "id cliente",
                        "id produto",
                        "total de vendas (pago)",
                        "valor (pendente)",
                        "id venda",
                        "status de valor",
                    )
                )
            else:
                material_cols = self._material_columns(ws)
                cols = (
                    material_cols["data"],
                    material_cols["descricao"],
                    material_cols["valor"],
                )
                if material_cols.get("fornecedor"):
                    cols = (material_cols["data"], material_cols["fornecedor"], material_cols["descricao"], material_cols["valor"])
                if material_cols.get("id venda"):
                    cols = cols + (material_cols["id venda"],)

            headers = [ws[f"{col}{SALES_HEADER_ROW if self._normalize_name(target_name) == self._normalize_name(sales_name) else 2}"].value for col in cols]
            rows: list[dict[str, str]] = []
            for row in range(ws.max_row, DATA_START_ROW - 1, -1):
                vals = [ws[f"{col}{row}"].value for col in cols]
                if all(v in (None, "") for v in vals):
                    continue
                rows.append({str(headers[i]): str(vals[i]) for i in range(len(cols))})
                if len(rows) >= limit:
                    break
            return rows
        finally:
            wb.close()

    def get_planilha_summary(self, max_rows_scan: int = 500) -> str:
        """Resumo amigável de vendas, matéria-prima, gastos fixos e lucro para o bot."""
        wb = self._open_workbook(data_only=True)
        try:
            def _format_currency_pt(value: float) -> str:
                txt = f"{float(value):,.2f}"
                # pt-BR: separador decimal vírgula e milhares ponto
                txt = txt.replace(",", "X").replace(".", ",").replace("X", ".")
                return f"R$ {txt}"

            # Totais de vendas (pago/pendente)
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            ws_sales = wb[sales_name]
            sales_cols = self._sales_columns(ws_sales)
            col_pago = sales_cols.get("total de vendas (pago)")
            col_pendente = sales_cols.get("valor (pendente)")
            col_id = sales_cols.get("id venda")
            n_sales = 0
            total_pago = 0.0
            total_pendente = 0.0
            for row in range(DATA_START_ROW, min(ws_sales.max_row + 1, DATA_START_ROW + max_rows_scan)):
                if col_id and ws_sales[f"{col_id}{row}"].value not in (None, ""):
                    n_sales += 1
                if col_pago:
                    total_pago += self._to_float(ws_sales[f"{col_pago}{row}"].value)
                if col_pendente:
                    total_pendente += self._to_float(ws_sales[f"{col_pendente}{row}"].value)

            # Totais de matéria-prima
            material_name = self._resolve_sheet_name(wb, SHEET_MATERIAL)
            ws_mat = wb[material_name]
            mat_cols = self._material_columns(ws_mat)
            col_val = mat_cols.get("valor")
            col_desc = mat_cols.get("descricao")
            n_mat = 0
            total_mat = 0.0
            for row in range(DATA_START_ROW, min(ws_mat.max_row + 1, DATA_START_ROW + max_rows_scan)):
                if col_desc and ws_mat[f"{col_desc}{row}"].value not in (None, ""):
                    n_mat += 1
                if col_val:
                    total_mat += self._to_float(ws_mat[f"{col_val}{row}"].value)

            # Totais de gastos fixos (somando a coluna Valor)
            fixed_name = self._resolve_sheet_name(wb, SHEET_FIXED)
            ws_fixed = wb[fixed_name]
            total_fixos = 0.0
            for row in range(DATA_START_ROW, min(ws_fixed.max_row + 1, DATA_START_ROW + max_rows_scan)):
                total_fixos += self._to_float(ws_fixed[f"D{row}"].value)

            # Fallback (se o modelo mudar e a aba não existir/estragar leitura).
            # Lucro deve usar vendas totais (pago + pendente), para bater com a aba.
            lucro = (total_pago + total_pendente) - total_mat - total_fixos

            # Formato (padrão da aba "Lucro Mensal e Anual"):
            # Total Vendas | total de vendas (pago) | Valor (pendente) | Total Compras Matéria Prima | Gastos Fixos | Lucro
            total_vendas = total_pago + total_pendente
            return "\n".join(
                [
                    f"• Total Vendas: {_format_currency_pt(total_vendas)}",
                    f"• Total de vendas (pago): {_format_currency_pt(total_pago)}",
                    f"• Valor (pendente): {_format_currency_pt(total_pendente)}",
                    f"• Total Compras Materia Prima: {_format_currency_pt(total_mat)}",
                    f"• Gastos Fixos: {_format_currency_pt(total_fixos)}",
                    f"• Lucro: {_format_currency_pt(lucro)}",
                ]
            )
        except Exception as e:
            return f"Erro ao ler planilha: {e}"
        finally:
            wb.close()

    def get_sales_preview(self, limit: int = 12) -> str:
        """Prévia curta para o Telegram: últimas vendas com pendência e/ou prazo de entrega."""
        wb = self._open_workbook(data_only=True)
        try:
            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            ws = wb[sales_name]
            sales_cols = self._sales_columns(ws)

            col_id = sales_cols["id venda"]
            col_customer = sales_cols["id cliente"]
            col_desc = sales_cols["id produto"]
            col_pending = sales_cols["valor (pendente)"]
            col_status = sales_cols["status de valor"]
            col_delivery = sales_cols["data de entrega"]
            col_sale_date = sales_cols.get("data de venda")

            rows: list[dict[str, str]] = []
            for row in range(min(ws.max_row, self.MAX_DATA_ROW), DATA_START_ROW - 1, -1):
                sale_id = str(ws[f"{col_id}{row}"].value or "").strip()
                if not sale_id:
                    continue
                customer = str(ws[f"{col_customer}{row}"].value or "").strip()
                desc = str(ws[f"{col_desc}{row}"].value or "").strip()
                pending = self._to_float(ws[f"{col_pending}{row}"].value)
                status = str(ws[f"{col_status}{row}"].value or "").strip()
                delivery = str(ws[f"{col_delivery}{row}"].value or "").strip()
                sale_date = str(ws[f"{col_sale_date}{row}"].value or "").strip()

                # Mostrar sempre se tiver pendência ou entrega informada
                if (pending <= 0.01) and (not delivery):
                    continue
                rows.append(
                    {
                        "id": sale_id,
                        "cliente": customer,
                        "desc": desc,
                        "pendente": pending,
                        "status": status,
                        "entrega": delivery,
                        "data": sale_date,
                    }
                )
                if len(rows) >= limit:
                    break

            if not rows:
                return "📄 *Prévia da planilha*\n\nNenhuma venda com pendência ou prazo de entrega encontrada nas últimas linhas."

            lines = ["📄 *Prévia da planilha (pendências e entregas)*", ""]
            for item in rows:
                pend_txt = f"R$ {item['pendente']:,.2f}" if item["pendente"] > 0.01 else "R$ 0,00"
                entrega = item["entrega"] or "-"
                cliente = item["cliente"] or "-"
                lines.append(
                    f"• ID {item['id']} | {cliente}\n"
                    f"  Venda: {item['data'] or '-'} | Pendente: {pend_txt} ({item['status'] or '-'}) | Entrega: {entrega}"
                )
            lines.append("")
            # Dica baseada em um exemplo real de pendência da prévia.
            example_customer = None
            for item in rows:
                if item.get("cliente") and self._to_float(item.get("pendente", 0.0)) > 0.01:
                    example_customer = item.get("cliente")
                    break
            if not example_customer and rows:
                example_customer = rows[0].get("cliente")

            if example_customer:
                lines.append(
                    f"Dica: se o cliente {example_customer} tem pendência, envie `Cliente ID {example_customer} pagou` "
                    f"para marcar a venda como paga."
                )
            else:
                lines.append("Dica: envie `ID VENDA 001 pagou` para atualizar o status.")
            return "\n".join(lines)
        finally:
            wb.close()

    def get_pending_sales_by_customer(
        self,
        customer_id: str,
        max_rows_scan: int = 500,
        *,
        include_paid: bool = False,
    ) -> list[dict[str, str]]:
        """
        Retorna vendas pendentes (ou com status pendente) para um ID de cliente.
        Usado no Telegram para interpretar "Cliente ID XXX pagou".
        """
        wb = self._open_workbook(data_only=True)
        try:
            import re

            def _norm_id(v: object) -> str:
                """
                Normaliza IDs salvos no Excel.
                - Se for só dígitos e tiver <= 3, força zfill(3) (ex.: 3 -> 003)
                - Caso contrário, devolve em string como está (trim/upper).
                """
                raw = str(v or "").strip()
                digits = re.sub(r"\D", "", raw)
                if digits:
                    if len(digits) <= 3:
                        return digits.zfill(3)
                    return digits
                return raw.upper()

            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            ws = wb[sales_name]
            sales_cols = self._sales_columns(ws)

            col_id = sales_cols.get("id venda")
            col_customer = sales_cols.get("id cliente")
            col_desc = sales_cols.get("id produto")
            col_pending = sales_cols.get("valor (pendente)")
            col_status = sales_cols.get("status de valor")
            col_delivery = sales_cols.get("data de entrega")
            col_sale_date = sales_cols.get("data de venda")

            if not col_id or not col_customer:
                return []

            normalized_customer = _norm_id(customer_id)
            rows: list[dict[str, str]] = []
            start_row = min(ws.max_row, self.MAX_DATA_ROW, DATA_START_ROW + max_rows_scan)
            for row in range(start_row, DATA_START_ROW - 1, -1):
                cust_val_raw = ws[f"{col_customer}{row}"].value
                cust_val = _norm_id(cust_val_raw)
                if cust_val != normalized_customer:
                    continue

                pending = self._to_float(ws[f"{col_pending}{row}"].value) if col_pending else 0.0
                status_txt = str(ws[f"{col_status}{row}"].value or "").strip().lower() if col_status else ""
                if not include_paid:
                    if pending <= 0.01 and status_txt != "pendente":
                        continue

                delivery = str(ws[f"{col_delivery}{row}"].value or "").strip() if col_delivery else ""
                sale_date = str(ws[f"{col_sale_date}{row}"].value or "").strip() if col_sale_date else ""
                desc = str(ws[f"{col_desc}{row}"].value or "").strip() if col_desc else ""

                rows.append(
                    {
                        "sale_id": str(ws[f"{col_id}{row}"].value or "").strip(),
                        "cliente": cust_val,
                        "desc": desc,
                        "pendente": f"{pending:.2f}",
                        "status": status_txt or ("pendente" if pending > 0.01 else "pago"),
                        "delivery": delivery,
                        "sale_date": sale_date,
                    }
                )
                if len(rows) >= 5:
                    break
            return rows
        finally:
            wb.close()

    def get_pending_sale_by_sale_id(
        self,
        sale_id: str,
        max_rows_scan: int = 500,
        *,
        include_paid: bool = False,
    ) -> list[dict[str, str]]:
        """
        Retorna uma venda pendente (status pendente/pagamento pendente) por ID VENDA.
        Usado como fallback quando o usuário manda "Cliente ID X pagou" e X na prática é o ID VENDA.
        """
        wb = self._open_workbook(data_only=True)
        try:
            import re

            def _norm_sale_id(v: object) -> str:
                raw = str(v or "").strip()
                digits = re.sub(r"\D", "", raw)
                if digits and len(digits) <= 3:
                    return digits.zfill(3)
                return digits or raw.strip().upper()

            sales_name = self._resolve_sheet_name(wb, SHEET_SALES)
            ws = wb[sales_name]
            sales_cols = self._sales_columns(ws)

            col_id = sales_cols.get("id venda")
            col_customer = sales_cols.get("id cliente")
            col_desc = sales_cols.get("id produto")
            col_pending = sales_cols.get("valor (pendente)")
            col_status = sales_cols.get("status de valor")
            col_delivery = sales_cols.get("data de entrega")
            col_sale_date = sales_cols.get("data de venda")

            if not col_id:
                return []

            normalized_sale_id = _norm_sale_id(sale_id)
            rows: list[dict[str, str]] = []
            start_row = min(ws.max_row, self.MAX_DATA_ROW, DATA_START_ROW + max_rows_scan)
            for row in range(start_row, DATA_START_ROW - 1, -1):
                sale_val_raw = ws[f"{col_id}{row}"].value
                sale_val = _norm_sale_id(sale_val_raw)
                if sale_val != normalized_sale_id:
                    continue

                pending = self._to_float(ws[f"{col_pending}{row}"].value) if col_pending else 0.0
                status_txt = str(ws[f"{col_status}{row}"].value or "").strip().lower() if col_status else ""
                if not include_paid:
                    if pending <= 0.01 and status_txt != "pendente":
                        # Já está pago/sem pendência
                        return []

                delivery = str(ws[f"{col_delivery}{row}"].value or "").strip() if col_delivery else ""
                sale_date = str(ws[f"{col_sale_date}{row}"].value or "").strip() if col_sale_date else ""
                desc = str(ws[f"{col_desc}{row}"].value or "").strip() if col_desc else ""
                cliente = str(ws[f"{col_customer}{row}"].value or "").strip() if col_customer else ""

                rows.append(
                    {
                        "sale_id": sale_val,
                        "cliente": cliente,
                        "desc": desc,
                        "pendente": f"{pending:.2f}",
                        "status": status_txt or ("pendente" if pending > 0.01 else "pago"),
                        "delivery": delivery,
                        "sale_date": sale_date,
                    }
                )
                break
            return rows
        finally:
            wb.close()
