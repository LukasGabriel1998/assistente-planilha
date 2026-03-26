from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from .models import FinancialCommand, MaterialAllocation, Payment, RefundCommand, StatusUpdateCommand

try:
    import dateparser
except Exception:  # pragma: no cover - optional dependency fallback
    dateparser = None


@dataclass
class ParseResult:
    command: FinancialCommand
    missing_fields: list[str] = field(default_factory=list)
    detected_values: dict[str, str] = field(default_factory=dict)
    intent: str = "sale"  # "sale" | "refund"
    refund_command: Optional[RefundCommand] = None
    status_update_command: Optional[StatusUpdateCommand] = None


MONTH_MAP = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

BAD_CUSTOMER_WORDS = {
    "me",
    "deu",
    "vai",
    "pagar",
    "entrada",
    "saldo",
    "restante",
    "material",
    "hoje",
    "amanha",
    "ontem",
    "dia",
    "data",
    "servico",
    "venda",
    "fechei",
    "valor",
    "total",
    "gastar",
    "fornecedor",
    "reais",
    "real",
    "por",
}

BAD_SUPPLIER_WORDS = {
    "material",
    "materia",
    "prima",
    "reais",
    "real",
    "gasto",
    "gastar",
    "valor",
    "servico",
    "para",
    "pra",
    "fazer",
}

BAD_PRODUCT_WORDS = {
    "cliente",
    "valor",
    "total",
    "venda",
    "entrada",
    "saldo",
    "restante",
    "pendente",
    "pago",
    "pagou",
    "reais",
    "real",
    "hoje",
    "amanha",
    "ontem",
    "dia",
    "data",
}

MONEY_TOKEN = r"(?:(?:r\$\s*)?\d+(?:[.\s]\d{3})*(?:[.,]\d{1,2})?(?:\s*mil)?|mil)"

WORD_UNITS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
}

LETTER_RX = r"[^\W\d_]"
TEXT_RX = r"[\w .&'/-]"


def _normalize(text: str) -> str:
    clean = text.lower().strip()
    clean = unicodedata.normalize("NFKD", clean)
    clean = "".join(ch for ch in clean if not unicodedata.combining(ch))
    return clean


def _strip_leading_article(text: str) -> str:
    return re.sub(r"^(?:um|uma|o|a)\s+", "", text.strip(), flags=re.IGNORECASE)


def _humanize_label(text: str) -> str:
    def _title_fragment(fragment: str) -> str:
        if not fragment:
            return fragment
        if len(fragment) == 1:
            return fragment.lower()
        return fragment[:1].upper() + fragment[1:].lower()

    parts: list[str] = []
    for word in text.split():
        lower = word.lower()
        if lower in {"da", "de", "do", "das", "dos", "e"}:
            parts.append(lower)
            continue
        if lower.startswith("mc") and len(word) > 2:
            tail = word[2:]
            if "'" in tail:
                fragments = tail.split("'")
                parts.append("Mc" + "'".join(_title_fragment(fragment) for fragment in fragments))
            else:
                parts.append("Mc" + _title_fragment(tail))
            continue
        if "'" in word:
            parts.append("'".join(_title_fragment(fragment) for fragment in word.split("'")))
            continue
        parts.append(_title_fragment(word))
    return " ".join(parts)


def _clean_extracted_phrase(candidate: str) -> str:
    cleaned = candidate.strip()
    cleaned = re.sub(r"^[^\w\d]+", "", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned


def _is_probable_sale_id(value: str) -> bool:
    token = value.strip().upper()
    if not token:
        return False
    if not re.fullmatch(r"[A-Z0-9_-]{1,30}", token):
        return False
    return any(ch.isdigit() for ch in token)


def _segment_near(text: str, keyword: str, before: int = 12, after: int = 90) -> str:
    norm = _normalize(text)
    idx = norm.find(keyword)
    if idx == -1:
        return ""
    return text[max(0, idx - before) : idx + after]


def _to_float(value_text: str) -> Optional[float]:
    txt = _normalize(value_text)
    txt = txt.replace("r$", "").replace("reais", "").replace("real", "")
    txt = txt.replace(" ", "")
    if not txt:
        return None

    if "," in txt and "." in txt:
        if txt.rfind(",") > txt.rfind("."):
            txt = txt.replace(".", "").replace(",", ".")
        else:
            txt = txt.replace(",", "")
    elif "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "." in txt:
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", txt):
            txt = txt.replace(".", "")
        elif re.fullmatch(r"\d\.\d{2}", txt):
            txt = txt.replace(".", "") + "0"

    try:
        return float(txt)
    except ValueError:
        return None


def _is_money_like(raw_value: str) -> bool:
    norm = _normalize(raw_value)
    digits = re.sub(r"\D", "", norm)
    if digits and len(digits) > 1 and digits.startswith("0"):
        return False
    return ("r$" in norm) or ("mil" in norm) or ("," in norm) or ("." in norm) or len(digits) >= 3


def _parse_money_from_fragment(fragment: str) -> Optional[float]:
    norm = _normalize(fragment)
    if re.search(r"\bmil\b", norm, flags=re.IGNORECASE) and not re.search(r"\d", norm):
        return 1000.0
    word_thousand = re.search(
        r"\b(" + "|".join(re.escape(word) for word in WORD_UNITS.keys()) + r")\s+mil\b",
        norm,
        flags=re.IGNORECASE,
    )
    if word_thousand:
        unit_word = _normalize(word_thousand.group(1))
        base = WORD_UNITS.get(unit_word)
        if base:
            return float(base * 1000)

    mil_match = re.search(r"(\d+(?:[.,]\d+)?)\s*mil\b", norm, flags=re.IGNORECASE)
    if mil_match:
        base = _to_float(mil_match.group(1))
        if base is not None:
            return round(base * 1000.0, 2)

    number_match = re.search(MONEY_TOKEN, norm, flags=re.IGNORECASE)
    if not number_match:
        return None
    value = _to_float(number_match.group(0))
    if value is None:
        return None
    return round(value, 2)


def _currency_candidates(text: str) -> list[float]:
    values: list[float] = []
    norm = _normalize(text)

    for match in re.finditer(
        r"\b(" + "|".join(re.escape(word) for word in WORD_UNITS.keys()) + r")\s+mil\b",
        norm,
        flags=re.IGNORECASE,
    ):
        unit_word = _normalize(match.group(1))
        base = WORD_UNITS.get(unit_word)
        if base and base > 0:
            values.append(float(base * 1000))

    for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*mil\b", norm, flags=re.IGNORECASE):
        base = _to_float(match.group(1))
        if base is None or base <= 0:
            continue
        values.append(round(base * 1000.0, 2))

    for raw in re.findall(r"(?:r\$\s*)?\d+(?:[.\s]\d{3})*(?:[.,]\d{1,2})?", norm):
        value = _to_float(raw)
        if value is None or value <= 0:
            continue
        digits = re.sub(r"\D", "", raw)
        has_money_shape = ("r$" in raw) or ("," in raw) or ("." in raw) or (" " in raw) or len(digits) >= 3
        if not has_money_shape:
            continue
        values.append(round(value, 2))
    return values


def _parse_pt_date(fragment: str, reference_date: date) -> Optional[date]:
    norm = _normalize(fragment)
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", norm)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else reference_date.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            pass

    # Se nao houver data explicita (dd/mm), ai sim aplica termos relativos.
    if ("hoje" in norm) or re.search(r"\bhj\b", norm):
        return reference_date
    if "amanha" in norm:
        return reference_date + timedelta(days=1)
    if "ontem" in norm:
        return reference_date - timedelta(days=1)

    match = re.search(r"\bdia\s+(\d{1,2})(?:\s+de\s+([a-z]+))?", norm)
    if match:
        day = int(match.group(1))
        month_txt = match.group(2)
        year = reference_date.year
        if month_txt:
            month_num = MONTH_MAP.get(month_txt)
            if month_num:
                try:
                    parsed = date(year, month_num, day)
                except ValueError:
                    parsed = None
                if parsed and parsed < reference_date - timedelta(days=15):
                    parsed = date(year + 1, month_num, day)
                return parsed
        else:
            try:
                parsed = date(year, reference_date.month, day)
            except ValueError:
                return None
            if parsed < reference_date - timedelta(days=15):
                if reference_date.month == 12:
                    return date(year + 1, 1, day)
                return date(year, reference_date.month + 1, day)
            return parsed

    if dateparser is not None:
        parsed = dateparser.parse(
            fragment,
            languages=["pt"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": datetime.combine(reference_date, datetime.min.time()),
            },
        )
        if parsed:
            return parsed.date()
    return None


def _extract_customer(text: str) -> Optional[str]:
    patterns = [
        # IDs numéricos de cliente (ex.: "cliente id 004", "id cliente 004")
        r"\b(?:id\s*cliente|cliente\s*id)\s*[:\-]?\s*([a-zA-Z0-9_-]{1,30})\b",
        # "cliente é 004" / "cliente: 004"
        r"\bcliente\s+(?:e|eh|é|:|-)\s*([a-zA-Z0-9_-]{1,30})\b",
        # "cliente 004" (parando em digitos)
        r"\bcliente\s+(?:id\s*)?[:\-]?\s*(\d{1,6})\b",
        r"\bid\s*cliente\s*[:\-]?\s*(\d{1,6})\b",
        # "Cliente é PC GAMER" / "cliente: Nome" / "cliente - Nome"
        r"\bcliente\s+(?:e|eh|é|:|-)\s*([^,.;\n]+?)(?=\s*[,.]|\s+e\s+o\s+produto|\s*$)",
        r"\bcliente\s+(?:e|eh|é|:|-)\s*([^,.;\n]+)",
        # "Vendi uma placa para o João por 2000" / "vendi X para o Nome por valor"
        r"\b(?:para|pro|pra)\s+(?:(?:o|a)\s+)?([^,.;\n]+?)\s+por\s+(?:r\$\s*)?\d",
        r"\b(?:acabei\s+de\s+)?vend(?:i|emos|er)\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?(.+?)(?=\s+(?:um|uma|o|a)\s+[^,.;\n]+?\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar)|\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar)|[,.])",
        r"\bfechei\s+com\s+(.+?)(?=\s+(?:um|uma|o|a)\s+[^,.;\n]+?\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar)|\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar)|[,.])",
        r"\bfechamos\s+com\s+(.+?)(?=\s+(?:um|uma|o|a)\s+[^,.;\n]+?\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar)|\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar)|[,.])",
        r"\bnome\s+da\s+(?:empresa|loja)\s*(?:e|eh|é|:|-)?\s*([^,.;\n]+)",
        r"\bempresa\s+(?:chamad[ao]\s+|com\s+nome\s+|e|eh|é|:|-)?\s*([^,.;\n]+)",
        r"\bacabei\s+de\s+fazer\s+(?:uma\s+)?venda\s+(?:no|na|com)\s+([^,.;\n]+)",
        r"\bfiz\s+(?:uma\s+)?venda\s+(?:para|pro|pra|no|na|com)\s+([^,.;\n]+)",
        r"\bvend(?:i|emos|er)\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?([^,.;\n]+)",
        r"\bfechei\s+com\s+([^,.;\n]+)",
        r"\bcliente\s+(?:chamad[oa]\s+|com\s+nome\s+)([^,.;\n]+)",
        rf"\bnome\s+(?:do\s+)?cliente\s+(?:e|eh|é)?\s*({LETTER_RX}{TEXT_RX}{{1,60}})",
        r"\bcom\s+(?:(?:o|a)\s+)?cliente\s+([^,.;\n]+)",
        # "vendi 5000 para o cliente PC GAMER, ele me pagou a metade" -> captura só "PC GAMER"
        r"\b(?:para|pro|pra)\s+(?:(?:o|a)\s+)?cliente\s+([^,.;\n]+?)(?=\s+(?:ele|ela|me|pagou|deu|vai|paga)\s|,|\.|;|\s*$)",
        r"\b(?:para|pro|pra)\s+(?:(?:o|a)\s+)?cliente\s+([^,.;\n]+)",
        r"\bcliente\s+([^,.;\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _clean_extracted_phrase(match.group(1))
        candidate = re.split(
            r"[,.;]|(?:\b(?:esse cliente|ele comprou|eles fecharam|fecharam com a gente|comprou|onde|valor|um valor|pagou|paguei|entrada|saldo|restante|vou|no dia|dia|data|mes|gastar|material|porque|por)\b)",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ,.-")
        candidate = re.sub(
            r"\s+(?:um|uma|o|a)\s+[^\d,.;]+?(?=\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar|e\b|restante|metade|saldo|entrada|,|\.|;)|$)",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = _clean_extracted_phrase(candidate)
        words = [word for word in candidate.split() if word]
        if not words:
            continue
        if len(words) > 4:
            continue
        normalized_words = [_normalize(word) for word in words]
        if any(word in BAD_CUSTOMER_WORDS for word in normalized_words):
            continue
        if any(any(ch.isdigit() for ch in word) for word in words):
            # Aceita IDs curtos (ex.: "004"), mas rejeita valores monetarios/quantias.
            digits_only = "".join(ch for ch in candidate if ch.isdigit())
            if not digits_only:
                continue

            # Ex.: "004", "0123"
            if candidate.strip().upper() == digits_only and len(digits_only) <= 4:
                return _humanize_label(candidate)

            # Ex.: "A12", "ID-004" (curto e parece identificador)
            if len(digits_only) <= 4 and len(candidate) <= 12 and re.search(r"\d", candidate):
                return _humanize_label(candidate)

            continue
        return _humanize_label(" ".join(words))
    return None


def _extract_product(text: str) -> Optional[str]:
    patterns = [
        # "vendi uma placa para o cliente X ..."
        rf"\b(?:acabei\s+de\s+)?vend(?:i|er)\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}}?)\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?cliente\b",
        # "fiz uma fachada para o cliente X ..."
        rf"\b(?:acabei\s+de\s+)?fiz\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}}?)\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?cliente\b",
        rf"\b(?:acabei\s+de\s+)?vend(?:i|emos|er)\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?[^,.;\n]+?\s+(?:um|uma|o|a)\s+({LETTER_RX}[\w .'/+-]{{1,50}}?)(?=\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar|e\b|,|\.|;))",
        rf"\bfechei\s+com\s+[^,.;\n]+?\s+(?:um|uma|o|a)\s+({LETTER_RX}[\w .'/+-]{{1,50}}?)(?=\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar|e\b|,|\.|;))",
        rf"\bfechamos\s+com\s+[^,.;\n]+?\s+(?:um|uma|o|a)\s+({LETTER_RX}[\w .'/+-]{{1,50}}?)(?=\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar|e\b|,|\.|;))",
        rf"\b(?:para|pro|pra)\s+(?:(?:o|a)\s+)?[^,.;\n]+[,;:-]\s*((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})(?=[,.;]\s*(?:vend|fech|valor))",
        rf"\b(?:eles?|cliente)\s+fechar(?:am|ou)\s+com\s+(?:a\s+gente|nos|n[oó]s)\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})",
        rf"\bfechar(?:am|ou)\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})",
        rf"\bfechei\s+com\s+(?:ela|ele)\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})",
        rf"\bfechamos\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})",
        rf"\bcliente\s+[^,.;]+[,;:-]\s*((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}}?)(?=\s+(?:r\$\s*)?\d)",
        rf"\bproduto\s+(?:(?:foi|era|e|eh|é)\s+)?((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})",
        rf"\bvendi\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})\s+(?:para|pro|pra|ao|a)\b",
        rf"\bvendi\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})",
        rf"\bcomprou\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})",
        rf"\bfiz\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})\s+(?:para|pro|pra|ao|a)\b",
        rf"\bfiz\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})",
        rf"\bfechei\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})\s+(?:para|pro|pra|ao|a)\b",
        rf"\bfechei\s+((?:um|uma|o|a)\s+)?({LETTER_RX}[\w .'/+-]{{1,50}})",
        rf"\bservic[oç]\s+(?:de|do|da)?\s*({LETTER_RX}[\w .'/+-]{{1,50}})",
        rf"\bfazer\s+esse\s+servic[oç]\s+de\s+({LETTER_RX}[\w .'/+-]{{1,50}})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _clean_extracted_phrase(match.group(match.lastindex or 1) or "")
        candidate = re.sub(r"^(?:com\s+(?:ela|ele)\s+)", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(
            r"^(?:fechei|fechamos|fiz|vendi|vendemos|acabei\s+de\s+vender)\s+",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.split(
            r"[,.;]|(?:\b(?:minha|minho|cliente|valor|um valor|pagou|entrada|saldo|restante|vou|vao|vão|quando|no dia|dia|data|mes|por|de|para|pra|e eu|eu vou|no|com esse valor)\b)",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ,.-")
        candidate = re.sub(r"\s+e\s+v.*$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+e\s+(?:vao|vão|vai|pag\w+|restante|metade|quando).*$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+no\s+valor.*$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+e$", "", candidate, flags=re.IGNORECASE)
        candidate = _clean_extracted_phrase(candidate)
        if _normalize(candidate).startswith("com "):
            continue
        candidate = _strip_leading_article(candidate)
        words = [word for word in candidate.split() if word]
        if not words:
            continue
        normalized_words = [_normalize(word) for word in words]
        if any(word in BAD_PRODUCT_WORDS for word in normalized_words):
            continue
        if _parse_money_from_fragment(candidate) is not None:
            continue
        return _humanize_label(" ".join(words))
    return None


def _extract_sale_id_from_text(text: str) -> Optional[str]:
    patterns = [
        r"\bid\s*de\s*venda\s*(?:numero|n[uú]mero|n\.?|codigo|c[oó]digo)?\s*[:\-]?\s*([a-zA-Z0-9_-]{1,30})",
        r"\bid\s*venda\s*(?:numero|n[uú]mero|n\.?|codigo|c[oó]digo)?\s*[:\-]?\s*([a-zA-Z0-9_-]{1,30})",
        r"\bc[oó]digo\s*(?:da\s*venda)?\s*[:\-]?\s*([a-zA-Z0-9_-]{1,30})",
        # Observacao: nao tentamos inferir ID VENDA a partir de "cliente 002".
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip().upper()
            if _is_probable_sale_id(candidate):
                return candidate
    return None


def _extract_material_allocations(text: str, reference_date: date) -> list[MaterialAllocation]:
    allocations: list[MaterialAllocation] = []
    norm_text = _normalize(text)
    explicit_sale_id = _extract_sale_id_from_text(text)
    material_context = any(
        token in norm_text
        for token in ("material", "materia prima", "fornecedor", "comprar", "comprei", "gastar")
    )
    if not material_context:
        return allocations

    # Para material, queremos vincular ao ID da venda (linha especifica),
    # nao ao ID do cliente.
    id_pattern = r"(?:id\s*(?:de\s*)?venda|codigo\s*(?:da\s*)?venda)\s*([a-zA-Z0-9_-]{1,30})"
    loose_id_pattern = r"\b([a-zA-Z]*\d[a-zA-Z0-9_-]{0,29})\b"
    money_pattern = r"(r\$\s*\d[\d\.,]*|\d{2,}(?:[\.,]\d{1,2})?|\bmil\b|\b(?:um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez)\s+mil\b)"
    # Padroes: aqui so consideramos o ID da venda se vier com algum marcador ("id venda ...").
    # Isso evita confundir "cliente 002" (ID do cliente) com "ID VENDA" (ID da linha na planilha).
    direct_material_patterns = [
        re.compile(
            r"(?:material|fornecedor|gastar|comprar|comprei|adiciona|adicionar|coloca|colocar)"
            + r"(?:\s+\w+){0,10}?\s*"
            + money_pattern
            + r"(?:\s+\w+){0,8}?\s*(?:de\s+material|material)?"
            + r"(?:\s+\w+){0,8}?\s*(?:para|pro|pra|no|na|ao|a)"
            + r"(?:\s+\w+){0,4}?\s*"
            + id_pattern,
            flags=re.IGNORECASE,
        ),
    ]
    explicit_patterns = [
        (
            re.compile(
                r"(?:material|fornecedor|gastar|comprar|comprei|adiciona|adicionar|coloca|colocar)"
                + r"(?:\s+\w+){0,10}?\s*"
                + money_pattern
                + r"(?:\s+\w+){0,8}?\s*(?:de\s+material|material)?"
                + r"(?:\s+\w+){0,8}?\s*(?:para|pro|pra|no|na|ao|a)"
                + r"(?:\s+\w+){0,4}?\s*"
                + loose_id_pattern,
                flags=re.IGNORECASE,
            ),
            "amount-first",
        ),
        (
            re.compile(
                r"(?:material|fornecedor|gastar|comprar|comprei|adiciona|adicionar|coloca|colocar)"
                + r"(?:\s+\w+){0,10}?\s*"
                + money_pattern
                + r"(?:\s+\w+){0,8}?\s*(?:de\s+material|material)?"
                + r"(?:\s+\w+){0,8}?\s*(?:para|pro|pra|no|na|ao|a)"
                + r"(?:\s+\w+){0,4}?\s*"
                + id_pattern,
                flags=re.IGNORECASE,
            ),
            "amount-first",
        ),
        (
            re.compile(
                id_pattern
                + r"(?:\s+\w+){0,12}?\s*(?:material|fornecedor|gastar|comprar|comprei)"
                + r"(?:\s+\w+){0,8}?\s*"
                + money_pattern,
                flags=re.IGNORECASE,
            ),
            "id-first",
        ),
        (
            re.compile(
                money_pattern
                + r"(?:\s+\w+){0,10}?\s*(?:tem\s+que\s+ir|vai|ir|ser|para|pro|pra|no|na|ao|a)"
                + r"(?:\s+\w+){0,4}?\s*"
                + id_pattern,
                flags=re.IGNORECASE,
            ),
            "amount-first",
        ),
        (
            re.compile(
                id_pattern
                + r"(?:\s+\w+){0,12}?\s*"
                + money_pattern
                + r"(?:\s+\w+){0,4}?\s*(?:de\s+material|material)",
                flags=re.IGNORECASE,
            ),
            "id-first",
        ),
    ]
    seen: set[tuple[str, float, int]] = set()
    parsed_date = _parse_pt_date(text, reference_date) or reference_date

    def _append_match(sale_id: str, amount_text: str, position: int) -> None:
        normalized_sale_id = sale_id.strip().upper()
        if not _is_money_like(amount_text):
            return
        amount = _parse_money_from_fragment(amount_text or "")
        if not _is_probable_sale_id(normalized_sale_id) or amount is None or amount <= 0:
            return
        key = (normalized_sale_id, round(float(amount), 2), position)
        if key in seen:
            return
        seen.add(key)
        allocations.append(
            MaterialAllocation(
                sale_id=normalized_sale_id,
                amount=float(amount),
                material_date=parsed_date,
            )
        )

    for pattern in direct_material_patterns:
        for match in pattern.finditer(text):
            amount_text, sale_id = match.groups()
            _append_match(sale_id, amount_text, match.start())
    if allocations:
        return allocations

    for pattern, order in explicit_patterns:
        for match in pattern.finditer(text):
            first, second = match.groups()
            if order == "id-first" and _is_probable_sale_id(str(second).strip().upper()):
                continue
            if order == "amount-first" and _is_probable_sale_id(str(first).strip().upper()):
                continue
            if (
                order == "id-first"
                and explicit_sale_id
                and re.sub(r"\D", "", first) == re.sub(r"\D", "", second)
            ):
                _append_match(explicit_sale_id, second, match.start())
                continue
            if order == "id-first":
                _append_match(first, second, match.start())
            else:
                _append_match(second, first, match.start())

    if allocations:
        return allocations

    fragments = re.split(r"[,;]|\be\b", text, flags=re.IGNORECASE)
    current_sale_id: str | None = None
    for fragment in fragments:
        id_match = re.search(id_pattern, fragment, flags=re.IGNORECASE)
        if id_match:
            possible_id = id_match.group(1).strip().upper()
            if _is_probable_sale_id(possible_id):
                current_sale_id = possible_id
        money_match = re.search(money_pattern, fragment, flags=re.IGNORECASE)
        if current_sale_id and money_match and any(token in _normalize(fragment) for token in ("material", "fornecedor", "compr", "gastar")):
            _append_match(current_sale_id, money_match.group(1), text.find(fragment))

    return allocations


def _extract_status_value(text: str) -> Optional[str]:
    norm = _normalize(text)
    if (
        ("ja pagou" in norm)
        or ("ja foi pago" in norm)
        or ("acabou de pagar" in norm)
        or ("acabou de ser pago" in norm)
        or ("quitou" in norm)
        or ("quitado" in norm)
        or ("acertou" in norm)
        or ("acertou tudo" in norm)
        or ("acertou o restante" in norm)
        or ("pagamento concluido" in norm)
        or ("pagamento concluído" in norm)
        or ("tudo certo" in norm)
        or ("trabalho foi feito" in norm)
        or ("servico foi feito" in norm)
        or ("servico foi finalizado" in norm)
        or ("servico finalizado" in norm)
        or ("trabalho finalizado" in norm)
        or ("recebi o restante" in norm)
        or ("recebi a outra metade" in norm)
        or ("recebi o valor pendente" in norm)
        or ("pode marcar como pago" in norm)
        or ("atualiza para pago" in norm)
    ):
        return "pago"
    if "pago" in norm:
        return "pago"
    if "pendente" in norm:
        return "pendente"
    return None


def _extract_amount_after_prefix(text: str, prefixes: list[str], max_gap_words: int = 0) -> Optional[float]:
    norm_text = _normalize(text)
    for prefix in prefixes:
        gap = rf"(?:\s+\S+){{0,{max_gap_words}}}?" if max_gap_words > 0 else ""
        pattern = rf"(?:{prefix}){gap}\s*({MONEY_TOKEN})"
        match = re.search(pattern, norm_text, flags=re.IGNORECASE)
        if not match:
            continue
        token = match.group(1)
        if not _is_money_like(token):
            continue
        value = _parse_money_from_fragment(token)
        if value is not None and value > 0:
            return value
    return None


def _extract_amount_before_prefix(text: str, prefixes: list[str], max_gap_words: int = 0) -> Optional[float]:
    """
    Extrai um valor que aparece antes do prefixo.
    Ex.: "1000 a mais no material" (valor antes de "material").
    """
    norm_text = _normalize(text)
    for prefix in prefixes:
        gap = rf"(?:\s+\S+){{0,{max_gap_words}}}?" if max_gap_words > 0 else ""
        pattern = rf"({MONEY_TOKEN}){gap}\s*(?:{prefix})"
        match = re.search(pattern, norm_text, flags=re.IGNORECASE)
        if not match:
            continue
        token = match.group(1)
        if not _is_money_like(token):
            continue
        value = _parse_money_from_fragment(token)
        if value is not None and value > 0:
            return value
    return None


def _extract_total_value(text: str, numbers: list[float]) -> Optional[float]:
    value = _extract_amount_after_prefix(
        text,
        prefixes=[
            r"no\s+valor\s+de",
            r"trabalho\s+no\s+valor\s+de",
            r"servic[oç]\s+no\s+valor\s+de",
            r"fech(?:ei|ou)(?:\s+\w+){0,8}\s+no\s+valor\s+de",
        ],
        max_gap_words=0,
    )
    if value:
        return value

    value = _extract_amount_after_prefix(
        text,
        prefixes=[
            r"valor\s+(?:de\s+)?(?:da\s+)?venda\s*(?:foi|de|por)?",
            r"valor\s+(?:do\s+)?(?:orcamento|orcamento|total|venda)\s*(?:foi|de|por)?",
            r"fechei(?:\s+\w+){0,6}\s+por",
            r"venda\s+de",
            r"valor\s+fech(?:ei|ou)\s+por",
            r"valor\s+foi\s*",
        ],
        max_gap_words=0,
    )
    if value:
        return value
    if not numbers:
        return None
    big = [number for number in numbers if number >= 100]
    return big[0] if big else numbers[0]


def _extract_itemized_products_and_total(text: str) -> tuple[list[str], Optional[float]]:
    """
    Captura casos como:
    "o painel eu vendi por 3 mil e o banner eu vendi por 5 mil"
    Retorna (produtos, total_somado) quando detectar itens claros.
    """
    products: list[str] = []
    values: list[float] = []
    product_chunk = r"((?:[A-Za-zÀ-ÖØ-öø-ÿ0-9/-]+\s*){1,4}?)"
    patterns = [
        re.compile(
            rf"\b(?:o|a)\s+{product_chunk}\s+(?:eu\s+)?vendi\s+(?:no\s+valor\s+de|por)\s*({MONEY_TOKEN})",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"\bvendi\s+(?:um|uma|o|a)\s+{product_chunk}\s+(?:por|no\s+valor\s+de)\s*({MONEY_TOKEN})",
            flags=re.IGNORECASE,
        ),
    ]
    seen_pairs: set[tuple[str, float]] = set()
    for pattern in patterns:
        for m in pattern.finditer(text):
            prod = _clean_extracted_phrase(m.group(1) or "")
            prod = _strip_leading_article(prod)
            prod = re.sub(r"\b(eu|aqui|pra|para)\b\s*$", "", prod, flags=re.IGNORECASE).strip(" ,.-")
            if not prod:
                continue
            norm_words = [_normalize(w) for w in prod.split() if w]
            if any(w in BAD_PRODUCT_WORDS for w in norm_words):
                continue
            val = _parse_money_from_fragment(m.group(2) or "")
            if val is None or val <= 0:
                continue
            human_prod = _humanize_label(prod)
            pair = (_normalize(human_prod), float(val))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            products.append(human_prod)
            values.append(float(val))
    # Dedup preservando ordem
    uniq_products: list[str] = []
    for p in products:
        if p not in uniq_products:
            uniq_products.append(p)
    if len(values) >= 2:
        return uniq_products, round(sum(values), 2)
    return uniq_products, None


def _extract_material_cost(text: str) -> Optional[float]:
    """
    Extrai custo de material priorizando o trecho próximo a palavras-chave
    para evitar capturar "metade" da venda por engano.
    """
    norm = _normalize(text)
    keyword_positions: list[int] = []
    for kw in ("material", "materia prima", "fornecedor", "gastar", "gasto", "comprar", "comprei"):
        idx = norm.find(kw)
        if idx >= 0:
            keyword_positions.append(idx)
    candidates: list[float] = []
    for idx in keyword_positions:
        snippet = text[max(0, idx - 20) : idx + 110]
        for v in _currency_candidates(snippet):
            if v > 0:
                candidates.append(float(v))
    if candidates:
        return max(candidates)
    return None


def _extract_payment_value(text: str, label: str, total: Optional[float], fallback_numbers: list[float]) -> Optional[float]:
    norm = _normalize(text)
    if "metade" in norm and total:
        entry_half_tokens = (
            "pagou",
            "entrada",
            "deu entrada",
            "me deu",
            "recebi",
            "metade hoje",
            "metade agora",
            "metade no pix",
            "metade na hora",
        )
        balance_half_tokens = (
            "restante",
            "saldo",
            "receber",
            "vai me pagar",
            "outra metade",
            "metade depois",
            "metade quando",
            "metade pendente",
            "falta receber",
        )
        if label == "entrada" and any(token in norm for token in entry_half_tokens):
            return round(total / 2, 2)
        if label == "saldo" and any(token in norm for token in balance_half_tokens):
            return round(total / 2, 2)

    if label == "entrada":
        prefixes = [
            r"pagou",
            r"entrada\s*(?:de|foi)?",
            r"deu\s+(?:uma\s+)?entrada\s*(?:de|foi)?",
            r"me\s+deu",
            r"recebi",
        ]
    else:
        prefixes = [
            r"restante\s*(?:de|foi)?",
            r"saldo\s*(?:de|foi)?",
            r"vai\s+me\s+pagar",
            r"vou\s+receber",
            r"receber",
            r"recebo",
        ]
    value = _extract_amount_after_prefix(text, prefixes=prefixes, max_gap_words=0)
    if value:
        return value

    if label == "saldo" and total:
        entrada = _extract_payment_value(text, "entrada", total, fallback_numbers)
        if entrada is not None:
            return round(max(total - entrada, 0), 2)
    return None


def _extract_date_near(
    text: str,
    keyword: str,
    reference_date: date,
    stop_keywords: tuple[str, ...] = (),
) -> Optional[date]:
    segment = _segment_near(text, keyword)
    if not segment:
        return None
    norm = _normalize(text)
    idx = norm.find(keyword)
    forward = text[idx : idx + 90] if idx >= 0 else segment
    if stop_keywords:
        norm_forward = _normalize(forward)
        cut_points = [norm_forward.find(stop) for stop in stop_keywords if norm_forward.find(stop) != -1]
        if cut_points:
            forward = forward[: min(cut_points)]
    parsed = _parse_pt_date(forward, reference_date)
    if parsed:
        return parsed
    if stop_keywords:
        return None
    return _parse_pt_date(segment, reference_date)


def _extract_first_date_by_keywords(
    text: str,
    reference_date: date,
    keywords: tuple[str, ...],
    stop_keywords: tuple[str, ...] = (),
) -> Optional[date]:
    for keyword in keywords:
        parsed = _extract_date_near(text, keyword, reference_date, stop_keywords=stop_keywords)
        if parsed:
            return parsed
    return None


def _extract_sale_date(text: str, reference_date: date) -> date:
    norm = _normalize(text)
    if ("hoje" in norm) or re.search(r"\bhj\b", norm):
        return reference_date
    if "ontem" in norm:
        return reference_date - timedelta(days=1)

    parsed = _extract_first_date_by_keywords(
        text,
        reference_date,
        keywords=("data da venda", "venda", "fechei", "fechou", "vendi"),
        stop_keywords=("restante", "saldo", "receber", "material", "fornecedor"),
    )
    return parsed or reference_date


def _extract_material_supplier(text: str) -> Optional[str]:
    patterns = [
        r"\bfornecedor\s+(?:e|eh|e|chama(?:-se)?)?\s*([a-zA-Z][a-zA-Z0-9 .'-]{1,40})",
        r"\bloja\s+([a-zA-Z][a-zA-Z0-9 .'-]{1,40})",
        r"\bcompr(?:ei|ar)\s+(?:no|na)\s+([a-zA-Z][a-zA-Z0-9 .'-]{1,40})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip()
        candidate = re.split(
            r"[,.;]|(?:\b(?:valor|gasto|material|reais|real|para|pra|fazer|servico|dia|data)\b)",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ,.-")
        if not candidate:
            continue
        if _parse_money_from_fragment(candidate) is not None:
            continue
        normalized_words = [_normalize(word) for word in candidate.split()]
        if any(word in BAD_SUPPLIER_WORDS for word in normalized_words):
            continue
        return candidate.title()
    return None


def _has_placeholder_date(text: str) -> bool:
    norm = _normalize(text)
    placeholders = [
        "dia tal",
        "data tal",
        "mes tal",
        "tal dia",
        "data depois",
        "final do servico",
        "final de servico",
    ]
    return any(token in norm for token in placeholders)


def _contains_explicit_date_hint(text: str) -> bool:
    norm = _normalize(text)
    if any(token in norm for token in ("hoje", "amanha", "ontem", "hj")):
        return True
    if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", norm):
        return True
    if re.search(r"\bdia\s+\d{1,2}\b", norm):
        return True
    return False


def _contains_future_balance_hint(text: str) -> bool:
    norm = _normalize(text)
    future_tokens = (
        "amanha",
        "amanha me paga",
        "amanha paga",
        "amanha eu recebo",
        "depois",
        "depois que",
        "mais pra frente",
        "posteriormente",
        "quando eu finalizar",
        "quando finalizar",
        "quando terminar",
        "quando eu terminar",
        "quando eu concluir",
        "quando concluir",
        "quando entregar",
        "quando eu entregar",
        "na entrega",
        "final do servico",
        "final de servico",
        "finalizar o servico",
        "terminar o servico",
        "concluir o servico",
        "outra metade",
        "falta receber",
        "receber o restante",
        "receber a outra metade",
        "vai me pagar",
        "vou receber",
        "restante depois",
    )
    return any(token in norm for token in future_tokens)


def parse_financial_message(message: str, reference_date: Optional[date] = None) -> ParseResult:
    if reference_date is None:
        reference_date = date.today()

    raw_text = message.strip()
    norm_text = _normalize(raw_text)
    numbers = _currency_candidates(raw_text)
    sale_id = _extract_sale_id_from_text(raw_text)
    material_allocations = _extract_material_allocations(raw_text, reference_date)
    if not sale_id and material_allocations:
        sale_id = material_allocations[0].sale_id
    status_value = _extract_status_value(raw_text)
    sale_creation_context = any(
        token in norm_text
        for token in (
            "acabei de fazer uma venda",
            "fiz uma venda",
            "fiz um servico",
            "fiz uma",
            "fiz um",
            "vender",
            "vendi",
            "vendemos",
            "fechei",
            "fechamos",
            "comprou",
        )
    )

    customer = _extract_customer(raw_text) or ""
    product_id = _extract_product(raw_text) or ""
    total_value = _extract_total_value(raw_text, numbers)
    itemized_products, itemized_total = _extract_itemized_products_and_total(raw_text)
    if itemized_total is not None:
        total_value = itemized_total
    if itemized_products:
        joined_products = " + ".join(itemized_products)
        product_id = joined_products
    # Se a mensagem for claramente "gasto de material" (ex.: "gastei 1000 de material"),
    # nao tratamos como venda/total no caixa: suprimimos total_value e montamos apenas
    # a atualizacao de Compras Matéria-Prima.
    material_expense_context = any(
        token in norm_text
        for token in (
            "material",
            "materia prima",
            "fornecedor",
            "comprar",
            "comprei",
            "gastar",
            "gasto",
            "pagar",
        )
    )
    material_reference_only = bool(
        (not sale_creation_context)
        and (status_value is None)
        and material_expense_context
        and bool(numbers)
    )
    if material_reference_only:
        total_value = None
        product_id = ""

    sale_date = _extract_sale_date(raw_text, reference_date)
    entry_date = (
        _extract_first_date_by_keywords(
            raw_text,
            reference_date,
            keywords=("pagou", "entrada", "deu uma entrada"),
            stop_keywords=("restante", "saldo", "receber"),
        )
        or sale_date
    )
    balance_segment = (
        _segment_near(raw_text, "restante")
        or _segment_near(raw_text, "saldo")
        or _segment_near(raw_text, "vai me pagar")
        or _segment_near(raw_text, "vou receber")
        or _segment_near(raw_text, "receber")
        or _segment_near(raw_text, "recebo")
        or _segment_near(raw_text, "final do servico")
        or _segment_near(raw_text, "final de servico")
        or _segment_near(raw_text, "finalizar o servico")
        or _segment_near(raw_text, "terminar o servico")
    )
    balance_date = (
        _extract_first_date_by_keywords(
            raw_text,
            reference_date,
            keywords=(
                "restante",
                "saldo",
                "vai me pagar",
                "vou receber",
                "receber",
                "recebo",
                "final do servico",
                "final de servico",
                "finalizar o servico",
                "terminar o servico",
                "concluir o servico",
                "entrega",
                "entregar",
            ),
        )
        or entry_date
    )
    # Heurística: "amanha" + contexto de saldo/restante => saldo vence amanhã.
    if ("amanha" in norm_text) and any(tok in norm_text for tok in ("restante", "saldo", "receber", "recebo", "vai me pagar")):
        balance_date = max(balance_date, reference_date + timedelta(days=1))

    balance_future_hint = _contains_future_balance_hint(balance_segment or "") or _contains_future_balance_hint(raw_text)
    if balance_segment and not _contains_explicit_date_hint(balance_segment) and balance_future_hint:
        balance_date = max(balance_date, sale_date + timedelta(days=1))

    # Prazo/entrega do serviço (independente de pagamento).
    # Ex.: "entrego dia 20", "prazo dia 20", "finalizar dia 20", "até dia 20".
    service_due_date = (
        _extract_first_date_by_keywords(
            raw_text,
            reference_date,
            keywords=(
                "data de entrega",
                "data entrega",
                "entrega",
                "entregar",
                "prazo",
                "prazo para",
                "para dia",
                "até dia",
                "ate dia",
                "finalizar",
                "finalizar o servico",
                "terminar",
                "concluir",
            ),
        )
        or None
    )
    # Heurística: quando o cliente fala "amanha" e também menciona entrega,
    # consideramos amanhã como Data de Entrega.
    if service_due_date is None and ("amanha" in norm_text) and any(
        tok in norm_text for tok in ("entrega", "entregar", "servico", "serviço", "fazer o servico", "fazer o serviço")
    ):
        service_due_date = reference_date + timedelta(days=1)

    entry_value = _extract_payment_value(raw_text, "entrada", total_value, numbers)
    balance_value = _extract_payment_value(raw_text, "saldo", total_value, numbers)

    material_cost = _extract_material_cost(raw_text)
    if material_cost is None:
        material_cost = _extract_amount_after_prefix(
            raw_text,
            prefixes=[r"material", r"materia prima", r"mat[eé]ria prima"],
            max_gap_words=5,
        )
    if material_cost is None:
        material_cost = _extract_amount_after_prefix(raw_text, prefixes=[r"gastar", r"gasto", r"pagar"], max_gap_words=8)
    if material_cost is None:
        material_cost = _extract_amount_before_prefix(
            raw_text,
            prefixes=[
                r"material",
                r"materia prima",
                r"mat[eé]ria prima",
                r"de\s+material",
            ],
            max_gap_words=10,
        )
    material_supplier = _extract_material_supplier(raw_text)
    material_date = _extract_date_near(raw_text, "material", reference_date) or sale_date
    if sale_id and material_cost and not material_allocations and not sale_creation_context:
        material_allocations = [
            MaterialAllocation(
                sale_id=sale_id,
                amount=float(material_cost),
                material_date=material_date,
            )
        ]

    fixed_cost = _extract_amount_after_prefix(
        raw_text,
        prefixes=[r"gastos?\s+fixos?\s*(?:de|foi)?"],
        max_gap_words=2,
    )
    fixed_cost_label = "Gasto fixo via audio" if fixed_cost else None
    fixed_cost_date = _extract_date_near(raw_text, "gasto fixo", reference_date) or sale_date

    warnings: list[str] = []
    missing: list[str] = []
    material_expense_only = bool((material_allocations or material_cost) and (not sale_creation_context) and not total_value)
    if material_expense_only:
        # Para "gasto de material", precisamos do ID do cliente (campo ID Cliente na planilha)
        # e do ID VENDA para vincular a linha correta em "Compras Matéria-Prima".
        if not customer:
            missing.append("ID Cliente")
        if not sale_id and not material_allocations:
            missing.append("ID VENDA")
    else:
        # Fluxo de venda normal: exige cliente e valor (produto é opcional).
        if not customer:
            missing.append("ID Cliente")
        if not total_value:
            missing.append("Valor total da venda")
    if _has_placeholder_date(raw_text):
        warnings.append("Foi detectada data indefinida (ex.: 'dia tal'). Confirme as datas antes de salvar.")
    has_global_explicit_date = _contains_explicit_date_hint(raw_text)
    if balance_segment and not _contains_explicit_date_hint(balance_segment) and not has_global_explicit_date:
        if balance_future_hint:
            warnings.append("Saldo marcado como pendente ate voce informar a data final do recebimento.")
        else:
            warnings.append("Data do saldo nao foi identificada com clareza. Ajuste antes de salvar.")
            missing.append("Data do saldo")

    if total_value and not entry_value and not balance_value:
        if balance_segment:
            # Se o texto menciona "entrada" mas nao informa o valor explicitamente,
            # assumir metade do total (melhor experiencia para escrita sem numeros).
            if "entrada" in norm_text:
                half = round(total_value / 2.0, 2)
                entry_value = half
                balance_value = round(max(total_value - half, 0.0), 2)
                warnings.append(
                    "Entrada e saldo divididos automaticamente (metade) porque entrada/restante foram mencionados sem valor da entrada."
                )
            else:
                entry_value = 0.0
                balance_value = total_value
                warnings.append(
                    "Saldo assumido como valor total porque foi citado prazo futuro, "
                    "mas o valor ja pago nao foi informado."
                )
        else:
            entry_value = total_value
            balance_value = 0.0
            warnings.append("Pagamento total assumido porque entrada/saldo nao foram informados.")
    if total_value and entry_value is not None and balance_value is None:
        balance_value = round(max(total_value - entry_value, 0), 2)
        warnings.append("Saldo calculado automaticamente (total - entrada).")
    if total_value and balance_value is not None and entry_value is None:
        entry_value = round(max(total_value - balance_value, 0), 2)
        warnings.append("Entrada calculada automaticamente (total - saldo).")

    payments: list[Payment] = []
    if entry_value and entry_value > 0:
        payments.append(
            Payment(
                label="Entrada",
                value=float(entry_value),
                due_date=entry_date,
                status="pago" if entry_date <= sale_date else "pendente",
            )
        )
    if balance_value and balance_value > 0:
        payments.append(
            Payment(
                label="Saldo",
                value=float(balance_value),
                due_date=balance_date,
                status="pendente" if (balance_future_hint or balance_date > sale_date) else "pago",
            )
        )

    if total_value and payments:
        payment_total = round(sum(payment.value for payment in payments), 2)
        if abs(payment_total - total_value) >= 0.01:
            warnings.append(f"Soma dos pagamentos ({payment_total:.2f}) diferente do total ({total_value:.2f}).")

    if product_id:
        description = product_id
    elif material_expense_only and sale_id:
        description = f"Material da venda {sale_id}"
    elif material_expense_only and material_allocations:
        description = "Compra de material vinculada a IDs existentes"
    elif material_expense_only and customer:
        description = f"Material para {customer}"
    elif customer:
        description = f"Servico para {customer}"
    else:
        description = "Servico sem cliente identificado"
    command = FinancialCommand(
        customer=customer,
        description=description,
        sale_date=sale_date,
        total_value=total_value or 0.0,
        payments=payments,
        product_id=product_id or None,
        sale_id=sale_id or None,
        material_cost=material_cost,
        material_date=material_date if material_cost else None,
        material_supplier=material_supplier if material_cost else None,
        material_allocations=material_allocations,
        fixed_cost=fixed_cost,
        fixed_cost_label=fixed_cost_label,
        fixed_cost_date=fixed_cost_date if fixed_cost else None,
        service_due_date=service_due_date,
        service_status=None,
        warnings=warnings,
    )

    return ParseResult(
        command=command,
        missing_fields=list(dict.fromkeys(missing)),
        detected_values={
            "cliente": command.customer or "-",
            "produto": command.product_id or "-",
            "valor_total": f"{command.total_value:.2f}" if command.total_value else "-",
            "qtd_pagamentos": str(len(command.payments)),
            "material": f"{command.material_cost:.2f}" if command.material_cost else "-",
            "gasto_fixo": f"{command.fixed_cost:.2f}" if command.fixed_cost else "-",
        },
        intent="sale",
    )


REFUND_KEYWORDS = (
    "cancelou",
    "cancelar",
    "devolver",
    "devolucao",
    "devolucao",
    "estorno",
    "desistiu",
    "dinheiro de volta",
    "quer o dinheiro de volta",
    "quer dinheiro de volta",
    "nao vai querer",
    "nao vai querer",
    "desistir",
    "devolv",
)

STATUS_UPDATE_KEYWORDS = (
    "status",
    "quitado",
    "quitou",
    "ja pagou",
    "já pagou",
    "acabou de pagar",
    "acertou",
    "acertou tudo",
    "pagamento concluido",
    "pago",
    "pendente",
    "trabalho foi feito",
    "servico foi feito",
    "serviço foi feito",
    "finalizado",
    "recebi o restante",
    "recebi a outra metade",
    "valor pendente",
    "atualiza",
    "marcar como pago",
)


def detect_intent(message: str) -> str:
    norm = _normalize(message)
    # Se for mensagem de criação de venda, prioriza o fluxo "sale".
    # Isso evita confundir trechos como "cliente id 004 pagou" (entrada) como "ID VENDA ... pagou".
    sale_creation_context = any(
        token in norm
        for token in (
            "acabei de fazer uma venda",
            "fiz uma venda",
            "fiz um servico",
            "fiz uma",
            "fiz um",
            "vender",
            "vendi",
            "vendemos",
            "fechei",
            "fechamos",
            "comprou",
        )
    )
    sale_id = _extract_sale_id_from_text(message)
    status = _extract_status_value(message)
    material_cost = _extract_amount_after_prefix(
        message,
        prefixes=[
            r"material",
            r"materia prima",
            r"mat[eé]ria prima",
            r"adicionar(?:\s+o)?\s+valor\s+de\s+material",
            r"compra\s+de\s+material",
            r"gastar",
            r"gasto",
        ],
        max_gap_words=8,
    )
    material_allocations = _extract_material_allocations(message, date.today())
    # Refund sempre ganha, mesmo que a mensagem tenha outros tokens.
    if sale_id and (material_allocations or material_cost) and not status:
        return "sale"
    if any(keyword in norm for keyword in REFUND_KEYWORDS):
        return "refund"
    if sale_creation_context:
        return "sale"
    if sale_id and status:
        return "status_update"
    return "sale"


def parse_status_update_message(message: str, reference_date: Optional[date] = None) -> StatusUpdateCommand:
    if reference_date is None:
        reference_date = date.today()
    sale_id = _extract_sale_id_from_text(message)
    if not sale_id:
        raise ValueError("ID VENDA nao identificado na mensagem.")
    status = _extract_status_value(message)
    if not status:
        raise ValueError("Status nao identificado. Use pago ou pendente.")
    customer = _extract_customer(message)
    ref_date = _parse_pt_date(message, reference_date) or reference_date
    return StatusUpdateCommand(
        sale_id=sale_id,
        status=status,
        ref_date=ref_date,
        customer=customer,
    )


def parse_refund_message(message: str, reference_date: Optional[date] = None) -> RefundCommand:
    if reference_date is None:
        reference_date = date.today()
    raw = message.strip()
    norm = _normalize(raw)
    customer = _extract_customer(raw) or "Cliente nao identificado"
    numbers = _currency_candidates(raw)
    amount = numbers[0] if numbers else 0.0
    ref_date = _parse_pt_date(raw, reference_date) or reference_date
    reason = "Cancelamento / devolucao solicitada pelo cliente"
    if ("cancelou" in norm) or ("cancelar" in norm):
        reason = "Venda cancelada pelo cliente"
    elif ("devolv" in norm) or ("dinheiro de volta" in norm):
        reason = "Devolucao solicitada pelo cliente"
    return RefundCommand(customer=customer, amount=float(amount or 0.0), reason=reason, ref_date=ref_date)


def parse_message(message: str, reference_date: Optional[date] = None) -> ParseResult:
    financial_result = parse_financial_message(message, reference_date)
    intent = detect_intent(message)
    if intent == "status_update":
        status_update = parse_status_update_message(message, reference_date)
        has_material_updates = bool(financial_result.command.material_allocations)
        if has_material_updates:
            financial_result.intent = "mixed_update"
            financial_result.status_update_command = status_update
            financial_result.detected_values["id_venda_status"] = status_update.sale_id
            financial_result.detected_values["status"] = status_update.status
            return financial_result
    if intent == "status_update":
        status_update = parse_status_update_message(message, reference_date)
        return ParseResult(
            command=FinancialCommand(
                customer=status_update.customer or "",
                description=f"Atualizacao do status da venda {status_update.sale_id}",
                sale_date=status_update.ref_date,
                total_value=0.0,
                payments=[],
                sale_id=status_update.sale_id,
            ),
            missing_fields=[],
            detected_values={
                "id_venda": status_update.sale_id,
                "status": status_update.status,
                "cliente": status_update.customer or "-",
            },
            intent="status_update",
            status_update_command=status_update,
        )
    if intent == "refund":
        refund = parse_refund_message(message, reference_date)
        return ParseResult(
            command=FinancialCommand(
                customer=refund.customer,
                description=refund.reason,
                sale_date=refund.ref_date,
                total_value=0.0,
                payments=[],
            ),
            missing_fields=[] if refund.amount > 0 else ["Valor do estorno"],
            detected_values={
                "cliente": refund.customer,
                "valor_estorno": f"{refund.amount:.2f}" if refund.amount else "-",
                "motivo": refund.reason,
            },
            intent="refund",
            refund_command=refund,
        )
    return financial_result
