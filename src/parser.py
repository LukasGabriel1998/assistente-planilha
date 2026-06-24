from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from .models import DeleteSaleCommand, FinancialCommand, MaterialAllocation, Payment, RefundCommand, StatusUpdateCommand

try:
    import dateparser
except Exception:  # pragma: no cover - optional dependency fallback
    dateparser = None


@dataclass
class ParseResult:
    command: FinancialCommand
    missing_fields: list[str] = field(default_factory=list)
    detected_values: dict[str, str] = field(default_factory=dict)
    intent: str = "sale"  # "sale" | "refund" | "sale_delete" | ...
    refund_command: Optional[RefundCommand] = None
    delete_command: Optional[DeleteSaleCommand] = None
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
    "mim",
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
    "ele",
    "ela",
    "eles",
    "cliente",
    "empresa",
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
    "que",
}

WORD_UNITS = {
    "zero": 0,
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

_SPOKEN_DIGIT_CHARS = {
    "zero": "0",
    "um": "1",
    "uma": "1",
    "dois": "2",
    "duas": "2",
    "tres": "3",
    "quatro": "4",
    "cinco": "5",
    "seis": "6",
    "sete": "7",
    "oito": "8",
    "nove": "9",
}


def normalize_spoken_ids_in_text(text: str) -> str:
    """Converte leitura dígito a dígito (ex.: 'zero zero dois') em numerais ('002')."""
    raw = (text or "").strip()
    if not raw:
        return raw
    tokens = _normalize(raw).split()
    if not tokens:
        return raw
    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i].strip(".,;:!?")
        if token in _SPOKEN_DIGIT_CHARS:
            digits: list[str] = []
            j = i
            while j < len(tokens):
                spoken = tokens[j].strip(".,;:!?")
                if spoken not in _SPOKEN_DIGIT_CHARS:
                    break
                digits.append(_SPOKEN_DIGIT_CHARS[spoken])
                j += 1
            if len(digits) >= 2:
                out.append("".join(digits))
                i = j
                continue
        out.append(token)
        i += 1
    normalized = " ".join(out)
    return normalized if normalized != _normalize(raw) else raw

WORD_NUMBERS = {
    **WORD_UNITS,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "duzentas": 200,
    "trezentos": 300,
    "trezentas": 300,
    "quatrocentos": 400,
    "quatrocentas": 400,
    "quinhentos": 500,
    "quinhentas": 500,
    "seiscentos": 600,
    "seiscentas": 600,
    "setecentos": 700,
    "setecentas": 700,
    "oitocentos": 800,
    "oitocentas": 800,
    "novecentos": 900,
    "novecentas": 900,
}
NUMBER_WORD_PATTERN = "|".join(
    re.escape(word) for word in sorted({*WORD_NUMBERS.keys(), "mil"}, key=len, reverse=True)
)
MONEY_TOKEN = r"(?:(?:r\$\s*)?\d+(?:[.\s]\d{3})*(?:[.,]\d{1,2})?(?:\s*mil)?|mil)"

LETTER_RX = r"[^\W\d_]"
TEXT_RX = r"[\w .&'/-]"


def _normalize(text: str) -> str:
    clean = text.lower().strip()
    clean = unicodedata.normalize("NFKD", clean)
    clean = "".join(ch for ch in clean if not unicodedata.combining(ch))
    return clean


def _strip_leading_article(text: str) -> str:
    return re.sub(r"^(?:um|uma|o|a)\s+", "", text.strip(), flags=re.IGNORECASE)


_PRODUCT_TRAILING_STOP_WORDS = frozenset(
    {
        "pra",
        "para",
        "pro",
        "eles",
        "elas",
        "ele",
        "ela",
        "vendi",
        "vendemos",
        "vender",
        "fechei",
        "fechamos",
        "cliente",
        "por",
        "valor",
        "pagou",
        "pagaram",
        "restante",
        "saldo",
        "entrada",
        "no",
        "dia",
        "data",
        "mes",
        "mês",
        "eu",
        "aqui",
    }
    | BAD_PRODUCT_WORDS
)


def _trim_product_name(candidate: str) -> str:
    """Recorta ruído comum após o nome do produto em frases faladas."""
    candidate = _clean_extracted_phrase(candidate)
    candidate = _strip_leading_article(candidate)
    if not candidate:
        return ""
    candidate = re.split(r"[,.;]", candidate, maxsplit=1)[0].strip()
    candidate = re.split(
        r"\s+(?:pra|para|pro)\s+(?:eles|elas|ele|ela|o|a|mim|nos|nós|gente|cliente)\b",
        candidate,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    words = candidate.split()
    trimmed: list[str] = []
    for word in words:
        norm = _normalize(word.strip(".,;:"))
        if norm in _PRODUCT_TRAILING_STOP_WORDS and trimmed:
            break
        if norm in {"vendi", "vendemos", "vender", "fechei", "fechamos"}:
            break
        trimmed.append(word)
    return " ".join(trimmed).strip(" ,.-")


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
    txt = txt.replace("centavos", "").replace("centavo", "")
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


def _parse_number_words_pt(fragment: str) -> Optional[int]:
    norm = _normalize(fragment)
    tokens = re.findall(r"[a-z]+", norm)
    total = 0
    current = 0
    used = False
    for token in tokens:
        if token in {"e", "de", "da", "do", "das", "dos", "reais", "real", "centavos", "centavo"}:
            continue
        if token == "mil":
            total += (current or 1) * 1000
            current = 0
            used = True
            continue
        value = WORD_NUMBERS.get(token)
        if value is None:
            continue
        current += value
        used = True
    if not used:
        return None
    return total + current


def _parse_colloquial_short_thousands(fragment: str) -> Optional[float]:
    """
    Interpreta formas faladas abreviadas, ex.:
    'dois e oitocentos' (= 2800), 'tres e quinhentos' (= 3500).
    """
    norm = _normalize(fragment)
    match = re.search(
        r"\b("
        + "|".join(re.escape(w) for w in WORD_UNITS if w not in {"zero"})
        + r"|dez|onze|doze|treze|quatorze|catorze|quinze|dezesseis|dezessete|dezoito|dezenove|"
        r"vinte|trinta|quarenta|cinquenta)\s+(?:e\s+)?("
        + "|".join(
            sorted(
                (w for w in WORD_NUMBERS if w.startswith(("duzent", "trezent", "quatrocent", "quinhent", "seiscent", "setecent", "oitocent", "novecent", "cem", "cento"))),
                key=len,
                reverse=True,
            )
        )
        + r")\w*\b",
        norm,
    )
    if not match:
        return None
    unit_word = match.group(1)
    hundreds_word = match.group(2)
    # Recupera palavra completa (ex.: oitocent -> oitocentos)
    hundreds_full = None
    for word, val in WORD_NUMBERS.items():
        if word.startswith(hundreds_word) and val >= 100:
            hundreds_full = word
            hundreds_val = val
            break
    if hundreds_full is None:
        return None
    unit_val = WORD_UNITS.get(unit_word) or WORD_NUMBERS.get(unit_word)
    if unit_val is None or unit_val <= 0 or unit_val > 50:
        return None
    return round(float(unit_val) * 1000 + float(hundreds_val), 2)


def _parse_amount_token(token: str) -> Optional[float]:
    if re.search(r"\d", token):
        matches = re.findall(r"(?:r\$\s*)?\d+(?:[.\s]\d{3})*(?:[.,]\d{1,2})?(?:\s*mil)?", token)
        if matches:
            return _parse_money_from_fragment(matches[-1])
        return _to_float(token)
    value = _parse_number_words_pt(token)
    return float(value) if value is not None else None


def _trim_money_context(fragment: str) -> str:
    text = _normalize(fragment).strip()
    markers = (
        " no valor de ",
        " valor de ",
        " valor ",
        " ficou ",
        " foi ",
        " por ",
        " de ",
    )
    last_pos = -1
    last_marker = ""
    padded = f" {text} "
    for marker in markers:
        pos = padded.rfind(marker)
        if pos > last_pos:
            last_pos = pos
            last_marker = marker
    if last_pos >= 0:
        text = padded[last_pos + len(last_marker) :].strip()
    return text


def _parse_reais_e_centavos(fragment: str) -> Optional[float]:
    """Ex.: '5877 e 80 centavos', '5.877 e 80 centavos' -> 5877.80"""
    norm = _normalize(fragment)
    match = re.search(
        r"(\d[\d.,\s]*)\s+e\s+(\d{1,2})\s*centavos?\b",
        norm,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    reais = _to_float(match.group(1).replace(" ", ""))
    if reais is None:
        return None
    try:
        cents = int(match.group(2))
    except ValueError:
        return None
    if cents >= 100:
        return None
    return round(float(reais) + (cents / 100.0), 2)


def _parse_money_phrase(fragment: str) -> Optional[float]:
    norm = _normalize(fragment)
    combined = _parse_reais_e_centavos(norm)
    if combined is not None:
        return combined

    if "real" in norm or "reais" in norm:
        before, _, after = norm.partition("reais")
        if not after and "real" in norm:
            before, _, after = norm.partition("real")
        reais = _parse_amount_token(_trim_money_context(before))
        cents = 0.0
        if "centavo" in after:
            cents_text = after.split("centavo", 1)[0]
            cents_text = re.sub(r"^\s*e\s+", "", cents_text).strip()
            parsed_cents = _parse_amount_token(cents_text)
            if parsed_cents is not None:
                cents = parsed_cents
        if reais is not None:
            return round(float(reais) + (float(cents) / 100.0), 2)

    if "centavo" in norm:
        if re.search(r"\d[\d.,\s]*\s+e\s+\d{1,2}\s*centavos?\b", norm, flags=re.IGNORECASE):
            return None
        cents_text = norm.split("centavo", 1)[0]
        cents_text = re.sub(r"^.*?\be\s+", "", cents_text).strip() or cents_text.strip()
        cents = _parse_amount_token(cents_text)
        if cents is not None:
            return round(float(cents) / 100.0, 2)

    return None


def _word_window_after_prefix(text: str, prefix: str, max_words: int = 16) -> str:
    norm_text = _normalize(text)
    match = re.search(prefix, norm_text, flags=re.IGNORECASE)
    if not match:
        return ""
    fragment = norm_text[match.end() :]
    fragment = re.split(
        r"[,.;]|\b(?:para|pra|cliente|id venda|id cliente|produto|data|dia|restante|saldo|amanha|amanhã|e o restante|e ela|e ele|mas|pagou|pagaram|entrada)\b",
        fragment,
        maxsplit=1,
    )[0]
    words = fragment.strip().split()
    return " ".join(words[:max_words])


def _word_window_before_prefix(text: str, prefix: str, max_words: int = 16) -> str:
    norm_text = _normalize(text)
    match = re.search(prefix, norm_text, flags=re.IGNORECASE)
    if not match:
        return ""
    fragment = norm_text[: match.start()]
    fragment = re.split(r"[,.;]", fragment)[-1]
    words = fragment.strip().split()
    return " ".join(words[-max_words:])


def _is_money_like(raw_value: str) -> bool:
    norm = _normalize(raw_value)
    digits = re.sub(r"\D", "", norm)
    if digits and len(digits) > 1 and digits.startswith("0"):
        return False
    if any(token in norm for token in ("r$", "real", "reais", "centavo", "centavos", "mil")):
        return True
    if ("," in norm) or ("." in norm) or len(digits) >= 3:
        return True
    word_value = _parse_number_words_pt(norm)
    return bool(word_value is not None and word_value >= 100)


def parse_money_value(fragment: str) -> Optional[float]:
    return _parse_money_from_fragment(fragment)


def _parse_spoken_amount_pt(fragment: str) -> Optional[float]:
    """Interpreta valor falado por extenso (ex.: dois mil setecentos e setenta e sete)."""
    norm = _normalize(fragment)
    if not re.search(
        r"\b(mil|cento|cem|reais?|real|centavos?|centavo|" + NUMBER_WORD_PATTERN + r")\b",
        norm,
        flags=re.IGNORECASE,
    ):
        return None
    word_value = _parse_number_words_pt(norm)
    if word_value is None or word_value <= 0:
        return None
    return round(float(word_value), 2)


def _parse_money_from_fragment(fragment: str, *, prefer_leading: bool = False) -> Optional[float]:
    norm = _normalize(fragment)
    if prefer_leading:
        words = norm.split()
        best_val: Optional[float] = None
        best_n = 0
        for n in range(1, min(len(words), 12) + 1):
            prefix = " ".join(words[:n])
            if re.search(r"\s(?:o|a)$", prefix) and n < len(words):
                continue
            if re.search(r"\se$", prefix) and n < len(words):
                continue
            prefix_val = _parse_money_from_fragment(prefix, prefer_leading=False)
            if prefix_val is not None and prefix_val > 0 and n >= best_n:
                best_val = prefix_val
                best_n = n
        if best_val is not None:
            return best_val

    colloquial = _parse_colloquial_short_thousands(norm)
    if colloquial is not None:
        return colloquial

    phrase_value = _parse_money_phrase(norm)
    if phrase_value is not None:
        return phrase_value

    spoken = _parse_spoken_amount_pt(norm)
    if spoken is not None and _is_money_like(norm):
        return spoken

    mil_match = re.search(r"(\d+(?:[.,]\d+)?)\s*mil\b", norm, flags=re.IGNORECASE)
    if mil_match:
        base = _to_float(mil_match.group(1))
        if base is not None:
            return round(base * 1000.0, 2)

    word_thousand = re.search(
        r"\b(" + "|".join(re.escape(word) for word in WORD_UNITS.keys()) + r")\s+mil\b(?!\s+(?:e\s+)?(?:cento|cem|duzent|trezent|quatrocent|quinhent|seiscent|setecent|oitocent|novecent))",
        norm,
        flags=re.IGNORECASE,
    )
    if word_thousand:
        unit_word = _normalize(word_thousand.group(1))
        base = WORD_UNITS.get(unit_word)
        if base:
            return float(base * 1000)

    numeric_values: list[float] = []
    for match in re.finditer(MONEY_TOKEN, norm, flags=re.IGNORECASE):
        value = _to_float(match.group(0))
        if value is not None and value > 0:
            numeric_values.append(round(value, 2))
    if numeric_values:
        if len(numeric_values) == 1:
            return numeric_values[0]
        if any(tok in norm for tok in ("valor", "total", "por", "foi", "venda", "pagou", "entrada")):
            return max(numeric_values)
        if len(norm.split()) <= 8:
            return max(numeric_values)

    word_value = _parse_number_words_pt(norm)
    if word_value is not None and _is_money_like(norm):
        if len(norm.split()) <= 12 and not numeric_values:
            return round(float(word_value), 2)
    if re.fullmatch(r"mil", norm, flags=re.IGNORECASE):
        return 1000.0

    number_match = re.search(MONEY_TOKEN, norm, flags=re.IGNORECASE)
    if not number_match:
        return None
    value = _to_float(number_match.group(0))
    if value is None:
        return None
    return round(value, 2)


def _mask_id_number_spans(text: str) -> str:
    """Oculta números que são IDs (cliente 004, cliente id 002, id venda 005) para não virarem valor monetário."""
    masked = text
    id_patterns = (
        r"\bcliente\s+\d{1,6}\b",
        r"\bcliente\s*id\s*[:\-]?\s*\d{1,6}\b",
        r"\bid\s*cliente\s*[:\-]?\s*\d{1,6}\b",
        r"\bid\s*(?:de\s*)?venda\s*[:\-]?\s*\d{1,6}\b",
        r"\bid\s*[:\-]?\s*\d{1,6}\b",
    )
    for pattern in id_patterns:
        masked = re.sub(
            pattern,
            lambda m: " " * len(m.group(0)),
            masked,
            flags=re.IGNORECASE,
        )
    return masked


def _is_delivery_explicitly_pending(text: str) -> bool:
    """Detecta quando o usuário deixa claro que a entrega ainda NÃO foi feita."""
    norm = _normalize(text)
    pending_patterns = (
        r"\b(?:nao|não)\s+(?:foi\s+)?entreg",
        r"\b(?:nao|não)\s+entreg",
        r"\bainda\s+(?:nao|não)\s+(?:foi\s+)?entreg",
        r"\bpor(?:em|ém)\s+(?:nao|não)\s+(?:foi\s+)?entreg",
        r"\bsem\s+entreg",
        r"\bfalta\s+entreg",
        r"\bpendente\s+(?:de\s+)?entreg",
    )
    return any(re.search(pattern, norm) for pattern in pending_patterns)


def _is_service_delivery_finalized(text: str) -> bool:
    if _is_delivery_explicitly_pending(text):
        return False
    norm = _normalize(text)
    if re.search(r"\bentreg(?:ue|a)\s+hoje\b", norm):
        return True
    if re.search(r"\b(?:foi\s+)?entreg(?:ue|a)\b", norm) and (
        "hoje" in norm or "agora" in norm or re.search(r"\bfoi\s+entreg", norm)
    ):
        return True
    if re.search(r"\bja\s+entreg", norm):
        return True
    if re.search(r"\bja\s+foi\s+entreg", norm):
        return True
    return any(
        token in norm
        for token in (
            "finalizado",
            "finalizada",
            "finalizou",
            "foi finalizado",
            "foi entregue",
            "entregue",
            "entregamos",
            "concluido",
            "concluído",
            "servico pronto",
            "serviço pronto",
            "trabalho pronto",
        )
    )


_UPDATE_CONTEXT_TOKENS = (
    "material",
    "materia prima",
    "matéria prima",
    "fornecedor",
    "gastar",
    "gasto",
    "gastei",
    "pagou",
    "pago",
    "pendente",
    "entrega",
    "entregar",
    "entregue",
    "finaliz",
    "id venda",
    "apagar",
    "apaga",
    "excluir",
    "exclui",
    "deletar",
    "remover",
    "atualiza",
    "ajusta",
    "corrige",
    "altera",
    "alterar",
)


def _is_update_context(text: str) -> bool:
    norm = _normalize(text or "")
    return any(tok in norm for tok in _UPDATE_CONTEXT_TOKENS)


def _message_has_explicit_sale_reference(text: str) -> bool:
    raw = text or ""
    if _extract_sale_id_from_text(raw) or _extract_delete_sale_id(raw):
        return True
    if re.search(r"\bcliente\s+(?:id\s*)?[:\-]?\s*\d{1,6}\b", raw, flags=re.IGNORECASE):
        return True
    if re.search(r"\bid\s*cliente\s*[:\-]?\s*\d{1,6}\b", raw, flags=re.IGNORECASE):
        return True
    if re.search(r"\b(?:do\s+)?id\s*[:\-]?\s*\d{1,6}\b", raw, flags=re.IGNORECASE):
        return True
    return False


def _is_preview_field_correction(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    return bool(
        re.match(
            r"(?i)^(material|custo|custos|valor|produto|cliente|id|entrada|saldo|restante|entrega|venda)\s*[:\-=]",
            raw,
        )
    )


def enrich_with_last_sale_context(text: str, last_sale_id: str | None) -> str:
    """
    Mantém o ID VENDA ativo na conversa: após o usuário informar um ID,
    mensagens seguintes (custo, pagamento, entrega etc.) vinculam à mesma venda
    até reiniciar ou iniciar nova conversa.
    """
    raw = (text or "").strip()
    if not raw or not last_sale_id:
        return raw
    if _extract_target_sale_id_for_updates(raw) or _extract_sale_id_from_text(raw) or _extract_delete_sale_id(raw):
        return raw
    norm = _normalize(raw)
    sale_creation = any(
        tok in norm
        for tok in (
            "vendi",
            "vender",
            "acabei de fazer uma venda",
            "fiz uma venda",
            "fiz um servico",
            "fiz uma",
            "fiz um",
            "fechei",
            "fechamos",
            "comprou",
            "compraram",
        )
    )
    if sale_creation:
        return raw
    if should_replace_pending_preview(raw):
        return raw
    sid = str(last_sale_id).strip().zfill(3) if str(last_sale_id).strip().isdigit() and len(str(last_sale_id).strip()) <= 3 else str(last_sale_id).strip()
    return f"cliente id {sid} {raw}"


def _currency_candidates(text: str) -> list[float]:
    values: list[float] = []
    norm = _normalize(_mask_id_number_spans(text))

    for match in re.finditer(r"\breais?\b", norm, flags=re.IGNORECASE):
        start = max(0, match.start() - 90)
        end = min(len(norm), match.end() + 60)
        value = _parse_money_phrase(norm[start:end])
        if value is not None and value > 0:
            values.append(value)

    for match in re.finditer(
        r"(\d[\d.,\s]*)\s+e\s+(\d{1,2})\s*centavos?\b",
        norm,
        flags=re.IGNORECASE,
    ):
        combined = _parse_reais_e_centavos(match.group(0))
        if combined is not None and combined > 0:
            values.append(combined)

    for match in re.finditer(
        r"\b(" + "|".join(re.escape(word) for word in WORD_UNITS.keys()) + r")\s+mil(?:\s+e\s+\w+)?\b",
        norm,
        flags=re.IGNORECASE,
    ):
        spoken = _parse_money_from_fragment(match.group(0))
        if spoken is not None and spoken > 0:
            values.append(spoken)

    for match in re.finditer(
        r"\b(dois|tres|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez)\s+(?:e\s+)?"
        r"(duzent\w*|trezent\w*|quatrocent\w*|quinhent\w*|seiscent\w*|setecent\w*|oitocent\w*|novecent\w*|cento|cem)\b",
        norm,
        flags=re.IGNORECASE,
    ):
        colloquial = _parse_colloquial_short_thousands(match.group(0))
        if colloquial is not None and colloquial > 0:
            values.append(colloquial)

    for match in re.finditer(
        r"(?:(?:valor\s+(?:total|ficou|foi)|no\s+valor(?:\s+total)?|me\s+pagou|pagou|pagaram|recebi|entrada)\s+(?:de\s+)?)"
        r"((?:\w+\s+){1,14}?)"
        r"(?=\s+(?:mas|e\s+(?:o|ela|ele)|o\s+restante|restante|saldo|amanha|amanhã)|$)",
        norm,
        flags=re.IGNORECASE,
    ):
        spoken = _parse_spoken_amount_pt(match.group(1).strip())
        if spoken is None or spoken <= 0:
            spoken = _parse_money_from_fragment(match.group(1).strip(), prefer_leading=True)
        if spoken is not None and spoken > 0:
            values.append(spoken)

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


def _extract_month_from_text(text: str) -> Optional[int]:
    """Retorna o número do mês se houver nome de mês no texto (ex.: 'junho')."""
    norm = _normalize(text)
    for name, num in MONTH_MAP.items():
        if re.search(rf"\b{re.escape(name)}\b", norm):
            return num
    return None


def _resolve_year_for_month(month: int, day: int, reference_date: date) -> int:
    """Escolhe o ano mais plausível para mês/dia com base na data de referência (hoje)."""
    year = reference_date.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        last_day = calendar.monthrange(year, month)[1]
        candidate = date(year, month, min(day, last_day))
    if candidate < reference_date - timedelta(days=15):
        year += 1
    return year


def _build_date(day: int, month: int, reference_date: date) -> date:
    year = _resolve_year_for_month(month, day, reference_date)
    try:
        return date(year, month, day)
    except ValueError:
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(day, last_day))


def _date_from_month_mention(
    text: str,
    reference_date: date,
    *,
    preferred_day: Optional[int] = None,
) -> Optional[date]:
    """Interpreta 'em junho', 'a data será em junho', etc."""
    month = _extract_month_from_text(text)
    if month is None:
        return None
    norm = _normalize(text)
    day = preferred_day
    match = re.search(r"\bdia\s+(\d{1,2})\b", norm)
    if match:
        day = int(match.group(1))
    match = re.search(r"\b(\d{1,2})\s+de\s+[a-z]+\b", norm)
    if match:
        day = int(match.group(1))
    if day is None:
        day = reference_date.day
    return _build_date(day, month, reference_date)


def _parse_pt_date(fragment: str, reference_date: date, *, full_text: str = "") -> Optional[date]:
    context = full_text or fragment
    norm = _normalize(fragment)
    context_norm = _normalize(context)

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

    ordinal_day = re.search(
        r"\b(?:no\s+)?dia\s+(primeiro|primeira|segundo|segunda|terceiro|terceira)\b",
        norm,
    )
    if ordinal_day:
        day_map = {"primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2, "terceiro": 3, "terceira": 3}
        day = day_map.get(ordinal_day.group(1))
        if day:
            inferred = _extract_month_from_text(context)
            if inferred:
                return _build_date(day, inferred, reference_date)
            month = reference_date.month
            if day < reference_date.day:
                month = 1 if month == 12 else month + 1
            return _build_date(day, month, reference_date)

    match = re.search(r"\b(?:no\s+)?dia\s+(\d{1,2})(?:\s+de\s+([a-z]+))?\b", norm)
    if match:
        day = int(match.group(1))
        month_txt = match.group(2)
        if month_txt and month_txt in MONTH_MAP:
            return _build_date(day, MONTH_MAP[month_txt], reference_date)
        inferred = _extract_month_from_text(context)
        if inferred:
            return _build_date(day, inferred, reference_date)
        return _build_date(day, reference_date.month, reference_date)

    match = re.search(r"\b(\d{1,2})\s+de\s+([a-z]+)\b", norm)
    if match:
        month_txt = match.group(2)
        if month_txt in MONTH_MAP:
            return _build_date(int(match.group(1)), MONTH_MAP[month_txt], reference_date)

    month_only = _date_from_month_mention(fragment, reference_date)
    if month_only:
        return month_only

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
    update_context = _is_update_context(text)
    _cust_stop = (
        r"(?=\s*[,.]"
        r"|\s+(?:ela|ele|eles|elas|adiciona|comprou|compraram|pagou|pago|no\s+valor|valor|entrou|saldo|restante|vai)\b"
        r"|\s*$)"
    )
    patterns = [
        rf"\bacabei\s+de\s+fazer\s+(?:uma\s+)?venda\s+(?:aqui\s+)?(?:para|pro|pra)\s+(?:o|a)\s+cliente\s+([^,.;\n]+?){_cust_stop}",
        rf"\b(?:para|pro|pra)\s+(?:o|a)\s+cliente\s+([^,.;\n]+?){_cust_stop}",
        # "fiz outra venda aqui para a Aline" / "fiz venda para João"
        rf"\bfiz\s+(?:outra\s+)?venda\s+(?:aqui\s+)?(?:para|pro|pra)\s+(?:(?:o|a)\s+)?([^,.;\n]+?){_cust_stop}",
        # "acabei de fazer uma venda aqui para o Adriel" / "venda para a Maria"
        rf"\bacabei\s+de\s+fazer\s+(?:uma\s+)?venda\s+(?:aqui\s+)?(?:para|pro|pra)\s+(?:(?:o|a)\s+)?([^,.;\n]+?){_cust_stop}",
        # "acabei de fazer uma venda de um banner para a Maria"
        rf"\bacabei\s+de\s+fazer\s+(?:uma\s+)?venda\s+(?:aqui\s+)?de\s+(?:um|uma|o|a)\s+[^,.;\n]+?\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?([^,.;\n]+?){_cust_stop}",
        # "fiz uma venda de um banner para a Maria"
        rf"\bfiz\s+(?:uma\s+)?venda\s+(?:aqui\s+)?de\s+(?:um|uma|o|a)\s+[^,.;\n]+?\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?([^,.;\n]+?){_cust_stop}",
        r"\bfiz\s+(?:uma\s+)?venda\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?([^,.;\n]+?)(?=\s*[,.]|\s+(?:ela|ele)\b|\s+no\s+valor|\s+valor\b)",
        # "vendi um banner para a Maria"
        rf"\bvend(?:i|emos|er)\s+(?:um|uma|o|a)\s+[^,.;\n]+?\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?([^,.;\n]+?){_cust_stop}",
        # "fechei um servico para a Maria" / "fechei servico para a empresa Joao Joao"
        rf"\b(?:acabei\s+de\s+)?fech(?:ar|ei|amos)\s+(?:um|uma|o|a\s+)?servic[oç]\w*\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?(?:empresa\s+)?([^,.;\n]+?){_cust_stop}",
        # "servico para a Maria" / "servico para a empresa X"
        rf"\bservic[oç]\w*\s+(?:para|pro|pra)\s+(?:(?:o|a)\s+)?(?:empresa\s+)?([^,.;\n]+?){_cust_stop}",
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
        # fallback amplo — evitar em atualizações onde "cliente 004 gasto..." vira nome errado
        *([] if update_context else [r"\bcliente\s+([^,.;\n]+)"]),
        # fallback: "Adriel comprou o banner"
        rf"\b({LETTER_RX}[\w'-]{{1,30}}(?:\s+{LETTER_RX}[\w'-]{{1,30}}){{0,3}})\s+comprou\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _clean_extracted_phrase(match.group(1))
        # Ex.: "fiz uma venda para P26 de uma fachada ..." -> queremos "P26" (não "P26 de")
        candidate = re.sub(r"\s+\bde\b\s*$", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(
            r"\s+\bde\b\s+(?=(?:um|uma|o|a)\s+)",
            " ",
            candidate,
            flags=re.IGNORECASE,
        ).strip()
        candidate = re.split(
            r"[,.;]|(?:\b(?:esse cliente|ele comprou|eles fecharam|fecharam com a gente|comprou|onde|valor|um valor|pagou|paguei|entrada|saldo|restante|vou|no dia|dia|data|mes|gastar|material|porque|por)\b)|\s+e\s+(?:ele|ela|eles|elas)\b",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ,.-")
        candidate = re.sub(r"\s+\be\s*$", "", candidate, flags=re.IGNORECASE).strip(" ,.-")
        candidate = re.sub(
            r"\s+(?:um|uma|o|a)\s+[^\d,.;]+?(?=\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar|e\b|restante|metade|saldo|entrada|,|\.|;)|$)",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = _clean_extracted_phrase(candidate)
        candidate = _strip_leading_article(candidate)
        words = [word for word in candidate.split() if word]
        if not words:
            continue
        if len(words) > 4:
            continue
        normalized_words = [_normalize(word) for word in words]
        if _normalize(candidate) in BAD_CUSTOMER_WORDS:
            continue
        if any(word in BAD_CUSTOMER_WORDS for word in normalized_words):
            continue
        if any(any(ch.isdigit() for ch in word) for word in words):
            # Aceita IDs curtos (ex.: "004"), mas rejeita valores monetarios/quantias.
            digits_only = "".join(ch for ch in candidate if ch.isdigit())
            if not digits_only:
                continue

            # Em atualizações (material, pagamento...), "cliente 004" refere-se ao ID VENDA.
            if update_context and candidate.strip().upper() == digits_only and len(digits_only) <= 6:
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
        rf"\bproduto\s+que\s+(?:ela|ele|eles)\s+comprou\s+foi\s+(?:um|uma|o|a)\s+({LETTER_RX}[\w .'/+-]{{1,50}}?)(?=\s+(?:a\s+data|data|valor|no\s+valor|pagou|entrada|saldo|restante)\b|\s*$)",
        # "eles compraram uma fachada" / "comprou um banner"
        rf"\b(?:eles?\s+)?compr(?:ou|aram|amos)\s+(?:um|uma|o|a)\s+({LETTER_RX}[\w .'/+-]{{1,50}}?)(?=\s*[,.]|\s+(?:eu\s+vendi|vendi\s+ele|adiciona|valor|no\s+valor|pagou|pagaram|vai|vao|vão)\b|\s*$)",
        # "fiz uma venda para P26 de uma fachada ..." -> produto = "fachada"
        rf"\b(?:acabei\s+de\s+fazer\s+)?fiz\s+(?:uma\s+)?venda\s+(?:para|pro|pra)\s+[^,.;\n]+?\s+de\s+(?:um|uma|o|a)\s+({LETTER_RX}[\w .'/+-]{{1,50}}?)(?=\s+(?:por|no\s+valor|valor|pagou|vai\s+pagar|e\b|,|\.|;)|\s*$)",
        # "fiz uma venda de uma fachada para P26 ..." -> produto = "fachada"
        rf"\b(?:acabei\s+de\s+fazer\s+)?fiz\s+(?:uma\s+)?venda\s+de\s+(?:um|uma|o|a)\s+({LETTER_RX}[\w .'/+-]{{1,50}}?)\s+(?:para|pro|pra)\b",
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
            r"[,.;]|(?:\b(?:minha|minho|cliente|valor|um valor|pagou|entrada|saldo|restante|vou|vao|vão|quando|no dia|dia|data|mes|por|de|para|pra|e eu|eu vou|no|com esse valor|eu vendi|vendi ele)\b)",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ,.-")
        candidate = re.sub(r"\s+e\s+v.*$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+e\s+(?:vao|vão|vai|pag\w+|restante|metade|quando).*$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+no\s+valor.*$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+e$", "", candidate, flags=re.IGNORECASE)
        candidate = _trim_product_name(candidate)
        if _normalize(candidate).startswith("com "):
            continue
        candidate = _strip_leading_article(candidate)
        words = [word for word in candidate.split() if word]
        if not words:
            continue
        trimmed_words: list[str] = []
        for word in words:
            if _normalize(word) in {"eu", "ele", "ela", "vendi", "vendemos", "vender"} and trimmed_words:
                break
            trimmed_words.append(word)
        words = trimmed_words or words
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


def _extract_target_sale_id_for_updates(text: str) -> Optional[str]:
    """
    Extrai um ID de VENDA para mensagens de atualização (ex.: ajustar entrega/material)
    aceitando também variações comuns como "cliente id 003" (muitos usuários usam isso como ID VENDA).
    """
    raw = text or ""
    sale_id = _extract_sale_id_from_text(raw)
    if sale_id:
        return sale_id
    norm = _normalize(raw)
    update_context = any(
        tok in norm
        for tok in (
            "data de entrega",
            "data entrega",
            "entrega",
            "entregar",
            "material",
            "materia prima",
            "matéria prima",
            "gastar",
            "gasto",
            "custo",
            "custos",
            "adiciona",
            "adicionar",
            "ajusta",
            "corrige",
            "atualiza",
            "altera",
            "alterar",
            "mudar",
            "vai mudar",
            "data do cliente",
            "pagou",
            "pago",
            "quitou",
            "finalizado",
            "finalizada",
            "entregue",
        )
    )
    if not update_context:
        return None
    for pattern in (
        r"\bclientes?\s*id\s*[:\-]?\s*(\d{1,6})\b",
        r"\bid\s*cliente\s*[:\-]?\s*(\d{1,6})\b",
        r"\bclientes?\s+(\d{1,6})\b",
    ):
        m = re.search(pattern, raw, flags=re.IGNORECASE)
        if m:
            return _format_sale_id_digits(m.group(1))
    return None


def extract_supplemental_sale_id(text: str) -> Optional[str]:
    """Extrai ID VENDA em respostas curtas (ex.: 'id 002', 'cliente id 003', '002')."""
    raw = normalize_spoken_ids_in_text(text or "")
    sale_id = _extract_delete_sale_id(raw) or _extract_sale_id_from_text(raw)
    if sale_id:
        return sale_id
    for pattern in (
        r"\bcliente\s+(?:do\s+)?id\s*[:\-]?\s*(\d{1,6})\b",
        r"\b(?:do\s+)?id\s*[:\-]?\s*(\d{1,6})\b",
    ):
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            return _format_sale_id_digits(match.group(1))
    match = re.fullmatch(r"(\d{1,6})", raw.strip())
    if match:
        return _format_sale_id_digits(match.group(1))
    return None


def _format_sale_id_digits(digits: str) -> str:
    digits = str(digits or "").strip()
    return digits.zfill(3) if len(digits) <= 3 else digits


def extract_sale_ids_list_for_updates(text: str) -> list[str]:
    """
    Extrai um ou mais ID VENDA em mensagens de atualização (pagamento, entrega, etc.).
    Ex.: "cliente id 004, 005 e 008 foi entregue" ou "ID VENDA 004, 005 pagou".
    """
    raw = normalize_spoken_ids_in_text(text or "")
    lower = raw.lower()
    collected: list[str] = []

    cluster_patterns = (
        r"\bid\s*(?:de\s*)?venda\s*[:\-]?\s*([0-9,\seE]+?)(?=\s+(?:foi\s+)?(?:entreg|pagou|pago|finaliz|recebeu|quit)|\s*(?:foi\s+)?(?:entreg|pagou|pago|finaliz|recebeu|quit)|[,.]|$)",
        r"\bclientes?\s*(?:id)?\s*[:\-]?\s*([0-9,\seE]+?)(?=\s+(?:foi\s+)?(?:entreg|pagou|pago|finaliz|recebeu|quit)|\s*(?:foi\s+)?(?:entreg|pagou|pago|finaliz|recebeu|quit)|[,.]|$)",
        r"(?:atualiz\w*|marca\w*|confirma\w*)\s+(?:a[ií]\s+)?(?:que\s+)?(?:foi\s+)?(?:entreg\w*|pag\w*|quit\w*)\s+(?:clientes?\s*)?(?:id\s*)?([0-9,\seE]+)",
        r"(?:foi\s+)?entreg\w*[^.\n]{0,80}clientes?\s*(?:id\s*)?([0-9,\seE]+)",
    )
    for pattern in cluster_patterns:
        match = re.search(pattern, lower, flags=re.IGNORECASE)
        if match:
            collected.extend(re.findall(r"\d{1,6}", match.group(1)))
            if collected:
                break

    if not collected:
        tail = re.search(r"clientes?\s*id\s*(.+)$", lower, flags=re.IGNORECASE)
        if tail and re.search(r"entreg|pagou|pago|quit|finaliz", lower, flags=re.IGNORECASE):
            collected.extend(re.findall(r"\d{1,6}", tail.group(1)))

    if not collected:
        collected = re.findall(r"\bid\s*[:\-]?\s*(\d{1,6})\b", lower)

    seen: set[str] = set()
    ordered: list[str] = []
    for raw_id in collected:
        sale_id = _format_sale_id_digits(raw_id)
        if sale_id not in seen:
            seen.add(sale_id)
            ordered.append(sale_id)
    return ordered


def _extract_delete_sale_id(text: str) -> Optional[str]:
    """Extrai ID VENDA em pedidos de exclusão (ex.: 'apagar cliente id 003')."""
    raw = normalize_spoken_ids_in_text(text or "")
    sale_id = _extract_sale_id_from_text(raw)
    if sale_id:
        return sale_id
    for pattern in (
        r"\bcliente\s+(?:do\s+)?id\s*[:\-]?\s*(\d{1,6})\b",
        r"\bcliente\s*id\s*[:\-]?\s*(\d{1,6})\b",
        r"\bid\s*cliente\s*[:\-]?\s*(\d{1,6})\b",
        r"\b(?:apagar|apaga|excluir|exclui|deletar|remover)\s+(?:o\s+)?cliente\s+(?:do\s+)?id\s*[:\-]?\s*(\d{1,6})\b",
        r"\b(?:apagar|apaga|excluir|exclui|deletar|remover)\s+(?:o\s+)?cliente\s+(\d{1,6})\b",
        r"\b(?:apagar|apaga|excluir|exclui|deletar|remover)\s+(?:a\s+)?venda\s+(\d{1,6})\b",
    ):
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue
        return _format_sale_id_digits(match.group(1))
    if _is_sale_delete_request(raw):
        match = re.search(r"\b(?:do\s+)?id\s*[:\-]?\s*(\d{1,6})\b", raw, flags=re.IGNORECASE)
        if match:
            return _format_sale_id_digits(match.group(1))
    return None


def extract_delete_sale_ids_list(text: str) -> list[str]:
    """
    Extrai um ou mais ID VENDA em pedidos de exclusão.
    Ex.: "apaga id 002, 004 e 005" ou "excluir venda 002 e 004".
    """
    raw = normalize_spoken_ids_in_text(text or "")
    if not _is_sale_delete_request(raw):
        return []

    lower = raw.lower()
    collected: list[str] = []
    cluster_patterns = (
        r"\b(?:apagar|apaga|excluir|exclui|deletar|remover|cancelar|tirar|limpar)\b[^.\n]*?\bid\s*[:\-]?\s*([0-9,\seE]+)",
        r"\b(?:apagar|apaga|excluir|exclui|deletar|remover)\s+(?:a\s+)?venda\s*[:\-]?\s*([0-9,\seE]+)",
        r"\bid\s*(?:de\s*)?venda\s*[:\-]?\s*([0-9,\seE]+?)(?=[,.]|$|\s+(?:e\s+)?(?:id|cliente|venda))",
        r"\bcliente\s*(?:id)?\s*[:\-]?\s*([0-9,\seE]+?)(?=[,.]|$|\s+(?:e\s+)?(?:id|cliente|venda))",
    )
    for pattern in cluster_patterns:
        match = re.search(pattern, lower, flags=re.IGNORECASE)
        if match:
            collected.extend(re.findall(r"\d{1,6}", match.group(1)))
            if collected:
                break

    if not collected:
        single = _extract_delete_sale_id(raw)
        if single:
            collected = [single]
        else:
            idx = -1
            for kw in DELETE_KEYWORDS + CANCEL_DELETE_KEYWORDS:
                pos = lower.find(kw)
                if pos != -1 and (idx == -1 or pos < idx):
                    idx = pos
            if idx >= 0:
                collected = re.findall(r"\d{1,6}", raw[idx:])

    seen: set[str] = set()
    ordered: list[str] = []
    for raw_id in collected:
        sale_id = _format_sale_id_digits(raw_id)
        if sale_id not in seen:
            seen.add(sale_id)
            ordered.append(sale_id)
    return ordered


DELETE_KEYWORDS = (
    "apagar",
    "apaga",
    "excluir",
    "exclui",
    "deletar",
    "delete",
    "remover",
    "remove",
    "tirar da planilha",
    "tirar o registro",
    "limpar da planilha",
    "limpar o registro",
)

CANCEL_DELETE_KEYWORDS = (
    "cancelou",
    "cancelar a venda",
    "cancelar o pedido",
    "desistiu",
    "desistencia",
    "nao vai querer",
    "nao quer mais",
    "desistir da venda",
)


def _is_sale_delete_request(message: str) -> bool:
    norm = _normalize(message)
    if any(keyword in norm for keyword in DELETE_KEYWORDS):
        return True
    if any(keyword in norm for keyword in CANCEL_DELETE_KEYWORDS):
        if "dinheiro de volta" in norm or "devolv" in norm or "estorno" in norm:
            return False
        return True
    return False


def parse_delete_sale_message(message: str, reference_date: Optional[date] = None) -> tuple[DeleteSaleCommand, list[str]]:
    if reference_date is None:
        reference_date = date.today()
    raw = (message or "").strip()
    norm = _normalize(raw)
    sale_id = _extract_delete_sale_id(raw) or ""
    reason = "Remocao solicitada pelo usuario"
    if any(token in norm for token in ("cancelou", "cancelar", "desistiu", "desistencia", "nao vai querer")):
        reason = "Cliente cancelou / desistiu da venda"
    elif any(token in norm for token in ("apagar", "apaga", "excluir", "exclui", "deletar", "remover")):
        reason = "Exclusao solicitada pelo usuario"
    missing: list[str] = []
    if not sale_id:
        missing.append("ID VENDA")
    return (
        DeleteSaleCommand(
            sale_id=sale_id,
            reason=reason,
            ref_date=reference_date,
            remove_material=True,
        ),
        missing,
    )


def _extract_delivery_update_date(message: str, reference_date: date) -> Optional[date]:
    """Extrai nova data de entrega em mensagens de atualização (ex.: 'data do cliente id 002 muda para 5 de junho')."""
    norm = _normalize(message)
    context_tokens = (
        "data de entrega",
        "data entrega",
        "data do cliente",
        "entrega",
        "entregar",
        "prazo",
        "mudar",
        "alterar",
        "altera",
        "vai mudar",
    )
    if not any(tok in norm for tok in context_tokens):
        return None
    parsed = _extract_first_date_by_keywords(
        message,
        reference_date,
        keywords=("data de entrega", "data entrega", "data do cliente", "entrega", "entregar", "prazo", "dia", "data"),
    )
    if parsed:
        return parsed
    return _parse_pt_date(message, reference_date, full_text=message) or _date_from_month_mention(message, reference_date)


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
    id_pattern = (
        r"(?:id\s*(?:de\s*)?venda|codigo\s*(?:da\s*)?venda|cliente\s*id|id\s*cliente|cliente)\s*"
        r"([a-zA-Z0-9_-]{1,30})"
    )
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
    # Não usar "cliente Nome" sozinho — evita confundir código do cliente com ID VENDA.
    fragment_id_pattern = (
        r"(?:id\s*(?:de\s*)?venda|codigo\s*(?:da\s*)?venda|cliente\s*id|id\s*cliente)\s*"
        r"([a-zA-Z0-9_-]{1,30})"
    )
    for fragment in fragments:
        id_match = re.search(fragment_id_pattern, fragment, flags=re.IGNORECASE)
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
    # "pagou" sozinho (sem valor) significa quitar tudo.
    # Se tiver valor ("pagou 2500"), isso é pagamento parcial e deve ser tratado em outro fluxo.
    if re.search(r"\bpagou\b", norm):
        has_amount_after_pagou = _extract_amount_after_prefix(text, prefixes=[r"pagou"], max_gap_words=0)
        if not has_amount_after_pagou:
            return "pago"
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
    # Não usar substring ("pagou" contém "pago"). Exigimos palavra inteira.
    if re.search(r"\bpago\b", norm):
        return "pago"
    if re.search(r"\bpendente\b", norm):
        return "pendente"
    return None


def _extract_amount_after_prefix(text: str, prefixes: list[str], max_gap_words: int = 0) -> Optional[float]:
    norm_text = _normalize(text)
    for prefix in prefixes:
        gap = rf"(?:\s+\S+){{0,{max_gap_words}}}?" if max_gap_words > 0 else ""
        pattern = rf"(?:{prefix}){gap}\s*({MONEY_TOKEN})"
        match = re.search(pattern, norm_text, flags=re.IGNORECASE)
        if match:
            token = match.group(1)
            if _is_money_like(token):
                value = _parse_money_from_fragment(token)
                if value is not None and value > 0:
                    # Transcrição de áudio: "cinco mil" pode ser capturado só como "mil" (1000).
                    if token.strip().lower() == "mil":
                        word_fragment = _word_window_after_prefix(text, prefix)
                        word_value = _parse_money_from_fragment(word_fragment, prefer_leading=True)
                        if word_value is not None and word_value > value:
                            return word_value
                    return value
        if re.search(prefix, norm_text, flags=re.IGNORECASE):
            word_fragment = _word_window_after_prefix(text, prefix)
            word_value = _parse_money_from_fragment(word_fragment, prefer_leading=True)
            if word_value is not None and word_value > 0:
                return word_value
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
        if match:
            token = match.group(1)
            if _is_money_like(token):
                value = _parse_money_from_fragment(token)
                if value is not None and value > 0:
                    return value
        if re.search(prefix, norm_text, flags=re.IGNORECASE):
            word_fragment = _word_window_before_prefix(text, prefix)
            word_value = _parse_money_from_fragment(word_fragment)
            if word_value is not None and word_value > 0:
                return word_value
    return None


def _extract_total_value(text: str, numbers: list[float]) -> Optional[float]:
    norm = _normalize(text)
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
            r"valor\s+total",
            r"valor\s+(?:de\s+)?(?:da\s+)?venda\s*(?:foi|por)?",
            r"valor\s+(?:do\s+)?(?:orcamento|orcamento|total|venda)\s*(?:foi|por)?",
            r"fechei(?:\s+\w+){0,6}\s+por",
            r"venda\s+de",
            r"valor\s+fech(?:ei|ou)\s+por",
            r"valor\s+foi\s*",
            r"valor\s+ficou",
        ],
        max_gap_words=0,
    )
    if value:
        return value
    if not numbers:
        return None
    big = [number for number in numbers if number >= 100]
    # Se houver múltiplos valores grandes na mesma frase, preferimos o MAIOR como total,
    # principalmente quando o texto menciona pagamento/entrada (ex.: "pagou 15000, entrada 8000").
    if len(big) >= 2 and any(tok in norm for tok in ("pagou", "pagaram", "pagamos", "entrada", "restante", "saldo", "vai me pagar", "mil", "reais")):
        return max(big)
    return big[0] if big else numbers[0]


def _parse_money_after_position(text: str, start: int) -> Optional[float]:
    tail = text[start:].lstrip()
    tail = re.sub(r"^de\s+", "", tail, flags=re.IGNORECASE)
    chunk = re.split(
        r"\s+e\s+(?:o|a)\s+"
        r"|\s*,|\s*\.\s"
        r"|\s+(?:no|na|em)\s+(?:o|a)\s+"
        r"|\s+(?:o|a)\s+(?!restante\b)(?:cliente|vendi|vendemos|um\b|uma\b|banner|fachada|painel|placa|\w+\s+vendi\b)"
        r"|\s+o\s+restante|\s+restante",
        tail,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    direct = _parse_money_from_fragment(chunk, prefer_leading=True)
    if direct is not None and direct > 0:
        return direct
    words = chunk.split()
    stop_words = frozenset(
        {
            "a",
            "o",
            "eles",
            "ele",
            "ela",
            "pagou",
            "pagaram",
            "paguei",
            "restante",
            "saldo",
            "quando",
            "cliente",
            "fachada",
            "banner",
            "painel",
            "placa",
            "no",
            "na",
            "em",
        }
    )
    best: Optional[float] = None
    for n in range(1, min(len(words), 8) + 1):
        word_norm = _normalize(words[n - 1])
        if word_norm in stop_words and best is not None:
            break
        if word_norm == "e" and n >= 2 and _normalize(words[n - 2]) in {"mil", "dois", "tres", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez"}:
            pass
        elif word_norm in {"a", "o"} and n >= 2 and _normalize(words[n - 2]) in {"mil", "milhao", "milhão"}:
            break
        val = _parse_money_from_fragment(" ".join(words[:n]), prefer_leading=True)
        if val is not None and val > 0:
            best = val
        elif best is not None:
            break
    return best


def _extract_itemized_product_values(text: str) -> list[tuple[str, float]]:
    """
    Captura produtos com valor unitário, ex.:
    "a fachada vendi por cinco mil e o banner vendi por dois mil".
    """
    products: list[tuple[str, float]] = []
    product_word = (
        r"(?!pra|para|pro|por|vendi|vendemos|eles|elas|ele|ela|cliente|eu|aqui\b)"
        r"[A-Za-zÀ-ÖØ-öø-ÿ0-9/-]+"
    )
    product_chunk = rf"(({product_word}(?:\s+(?!pra|para|pro|,|vendi|eu\b){product_word}){{0,2}}))"
    patterns = [
        re.compile(
            rf"\b(?:o|a)\s+{product_chunk}\s+(?:ele\s+|eu\s+)?(?:ficou|fica|saiu)\s+(?:no\s+valor\s+de|em|por|a)\b",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:o|a)\s+{product_chunk}\s+(?:eu\s+)?vendi\s+(?:no\s+valor\s+de|por)\b",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"\bvendi\s+(?:um|uma|o|a)\s+{product_chunk}\s+(?:por|no\s+valor\s+de)\b",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:um|uma)\s+{product_chunk}\s+(?:no\s+valor\s+de|por|de)\s+",
            flags=re.IGNORECASE,
        ),
    ]
    seen_pairs: set[tuple[str, float]] = set()
    for pattern in patterns:
        for m in pattern.finditer(text):
            prod = _trim_product_name(m.group(1) or "")
            if not prod:
                continue
            norm_words = [_normalize(w) for w in prod.split() if w]
            if any(w in BAD_PRODUCT_WORDS for w in norm_words):
                continue
            val = _parse_money_after_position(text, m.end())
            if val is None or val <= 0:
                continue
            human_prod = _humanize_label(prod)
            pair = (_normalize(human_prod), float(val))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            products.append((human_prod, float(val)))
    return products


def _extract_itemized_products_and_total(text: str) -> tuple[list[str], Optional[float]]:
    """
    Captura casos como:
    "o painel eu vendi por 3 mil e o banner eu vendi por 5 mil"
    Retorna (produtos, total_somado) quando detectar itens claros.
    """
    pairs = _extract_itemized_product_values(text)
    products = [p for p, _v in pairs]
    values = [v for _p, v in pairs]
    if len(values) >= 2:
        return products, round(sum(values), 2)
    return products, None


def _payment_segment_for_product(text: str, product: str) -> str:
    """Recorta o trecho de pagamento que menciona um produto específico."""
    prod_rx = re.escape(_normalize(product))
    norm = _normalize(text)
    priority_patterns = (
        rf"(?:pagou|pagaram|paguei|pagamos)\s+[^.\n]{{0,35}}\s+(?:no|na|em)\s+(?:(?:o|a)\s+)?{prod_rx}\b",
        rf"(?:o|a)\s+{prod_rx}\b[^.\n]{{0,30}}?(?:ele|ela|eles|elas)?\s*(?:me\s+)?(?:pagou|pagaram|pago|paguei|pagamos)\s+[^.\n]{{0,35}}",
    )
    for pattern in priority_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()

    pay_start = len(norm)
    for verb in ("me pagaram", "me pagou", "pagaram", "pagamos", "pagou", "paguei"):
        idx = norm.find(verb)
        if idx != -1 and idx < pay_start:
            pay_start = idx
    if pay_start >= len(norm):
        return ""
    payment_text = text[pay_start:]
    fallback_patterns = (
        rf"(?:o|a)\s+{prod_rx}\b[^.\n]{{0,45}}?(?:me\s+)?(?:pagou|pagaram|pago|paguei|pagamos)\s+[^.\n]{{0,35}}",
        rf"\b{prod_rx}\b[^.\n]{{0,35}}?(?:me\s+)?(?:pagou|pagaram|pago|paguei|pagamos)\s+[^.\n]{{0,35}}",
    )
    for pattern in fallback_patterns:
        match = re.search(pattern, payment_text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def _extract_item_payment_for_product(
    text: str,
    product: str,
    total: float,
    reference_date: date,
) -> tuple[float, float, date, date]:
    """Retorna entrada, saldo, data da entrada e data do saldo para um item."""
    norm = _normalize(text)
    segment = _payment_segment_for_product(text, product)
    norm_seg = _normalize(segment) if segment else norm
    prod = _normalize(product)

    if segment and "a vista" in norm_seg:
        return total, 0.0, reference_date, reference_date

    if segment:
        pay_match = re.search(
            r"(?:me\s+)?(?:pagou|pagaram|pago|paguei|pagamos)\s+",
            segment,
            flags=re.IGNORECASE,
        )
        if pay_match:
            entry = _parse_money_after_position(segment, pay_match.end())
            if entry is not None and entry > 0:
                entry = min(float(entry), float(total))
                balance = round(max(float(total) - entry, 0.0), 2)
                balance_date = reference_date
                if any(
                    tok in norm
                    for tok in (
                        "restante",
                        "saldo",
                        "vai pagar",
                        "vao pagar",
                        "vão pagar",
                        "amanha",
                        "amanhã",
                    )
                ):
                    balance_date = reference_date + timedelta(days=1)
                return entry, balance, reference_date, balance_date
        if re.search(r"(?:me\s+)?(?:pagou|pagaram|pago|paguei|pagamos)", segment, flags=re.IGNORECASE):
            return 0.0, float(total), reference_date, reference_date + timedelta(days=1)
        return float(total), 0.0, reference_date, reference_date

    if any(tok in norm for tok in ("restante", "saldo", "vai pagar", "vao pagar", "vão pagar")):
        return 0.0, float(total), reference_date, reference_date + timedelta(days=1)

    return float(total), 0.0, reference_date, reference_date


def _multi_sale_shared_payment_hint(text: str) -> bool:
    norm = _normalize(text)
    hints = (
        "das duas vendas",
        "das duas",
        "as duas vendas",
        "os dois",
        "entregar os dois",
        "entrega dos dois",
        "entrada das",
        "entrada da",
        "referente ja entrada",
        "referente a entrada",
        "referente à entrada",
        "para as duas",
        "dos dois produtos",
        "dos dois servicos",
        "dos dois serviços",
    )
    if any(h in norm for h in hints):
        return True
    return bool(
        re.search(r"\b(?:pagou|paguei|me\s+pagou|pagaram)\b", norm)
        and re.search(r"\b(?:um|uma)\s+\w+.*\be\s+(?:um|uma)\s+\w+", norm)
    )


def _extract_shared_entry_for_multi_sale(
    text: str,
    grand_total: float,
    reference_date: date,
) -> tuple[float, date] | None:
    """Entrada única citada para várias vendas na mesma mensagem (ex.: pagou 5 mil das duas)."""
    if grand_total <= 0.01:
        return None
    norm = _normalize(text)
    if not _multi_sale_shared_payment_hint(text):
        return None

    entry: float | None = None
    for prefix in (
        r"me\s+pagou",
        r"pagou",
        r"paguei",
        r"pagaram",
        r"pagamos",
        r"entrada\s+(?:de\s+)?",
        r"deu\s+(?:uma\s+)?entrada",
    ):
        entry = _extract_amount_after_prefix(text, prefixes=[prefix], max_gap_words=5)
        if entry is not None and entry > 0:
            break

    if entry is None and re.search(r"\b(?:pagou|paguei|me\s+pagou|pagaram)\b", norm):
        for amount in sorted(_currency_candidates(text), reverse=True):
            if 0 < amount < grand_total:
                entry = float(amount)
                break

    if entry is None or entry <= 0:
        return None

    balance_date = reference_date
    if any(tok in norm for tok in ("amanha", "amanhã", "restante", "saldo", "vai me pagar", "vai pagar")):
        balance_date = max(reference_date + timedelta(days=1), balance_date)
    balance_date = _extract_first_date_by_keywords(
        text,
        reference_date,
        keywords=("restante", "saldo", "vai me pagar", "vai pagar", "entrega", "entregar"),
    ) or balance_date

    return min(float(entry), float(grand_total)), balance_date


def _allocate_shared_entry_across_items(
    items: list[tuple[str, float]],
    entry_total: float,
) -> list[tuple[float, float]]:
    """Divide entrada única entre itens proporcionalmente ao valor de cada venda."""
    grand_total = round(sum(total for _p, total in items), 2)
    entry_total = round(min(float(entry_total), grand_total), 2)
    if grand_total <= 0.01:
        return [(0.0, 0.0) for _ in items]

    allocations: list[tuple[float, float]] = []
    remaining_entry = entry_total
    for idx, (_product, total) in enumerate(items):
        if idx == len(items) - 1:
            entry = round(remaining_entry, 2)
        else:
            entry = round(entry_total * (float(total) / grand_total), 2)
            remaining_entry = round(remaining_entry - entry, 2)
        balance = round(max(float(total) - entry, 0.0), 2)
        allocations.append((entry, balance))
    return allocations


def _build_sale_parse_result(
    *,
    customer: str,
    product: str,
    total_value: float,
    entry_value: float,
    balance_value: float,
    sale_date: date,
    entry_date: date,
    balance_date: date,
    service_due_date: date | None,
    warnings: list[str] | None = None,
) -> ParseResult:
    payments: list[Payment] = []
    if entry_value > 0.01:
        payments.append(
            Payment(
                label="Entrada",
                value=round(float(entry_value), 2),
                due_date=entry_date,
                status="pago",
            )
        )
    if balance_value > 0.01:
        payments.append(
            Payment(
                label="Saldo",
                value=round(float(balance_value), 2),
                due_date=balance_date,
                status="pendente" if balance_date > sale_date else "pago",
            )
        )
    command = FinancialCommand(
        customer=customer,
        description=product,
        sale_date=sale_date,
        total_value=round(float(total_value), 2),
        payments=payments,
        product_id=product,
        service_due_date=service_due_date,
        warnings=warnings or [],
    )
    missing: list[str] = []
    if not customer:
        missing.append("Cliente")
    if not total_value:
        missing.append("Valor total da venda")
    return ParseResult(
        command=command,
        missing_fields=missing,
        detected_values={
            "cliente": command.customer or "-",
            "produto": command.product_id or "-",
            "valor_total": f"{command.total_value:.2f}" if command.total_value else "-",
            "qtd_pagamentos": str(len(command.payments)),
        },
        intent="sale",
    )


def parse_multi_sales_message(
    message: str,
    reference_date: Optional[date] = None,
) -> list[ParseResult] | None:
    """
    Várias vendas distintas para o mesmo cliente na mesma mensagem.
    Ex.: fachada 5 mil + banner 2 mil, cada um com pagamento diferente.
    """
    if reference_date is None:
        reference_date = date.today()
    raw = normalize_spoken_ids_in_text(message or "")
    if detect_intent(raw) != "sale":
        return None

    items = _extract_itemized_product_values(raw)
    if len(items) < 2:
        return None

    customer = _extract_customer(raw) or ""
    norm = _normalize(raw)
    sale_date = _extract_sale_date(raw, reference_date)
    service_due_date = _parse_pt_date(raw, reference_date, full_text=raw)
    if any(tok in norm for tok in ("amanha", "amanhã", "entreg", "entrega")):
        service_due_date = max(service_due_date or reference_date, reference_date + timedelta(days=1))

    grand_total = round(sum(total for _p, total in items), 2)
    shared_entry = _extract_shared_entry_for_multi_sale(raw, grand_total, reference_date)
    shared_allocations: list[tuple[float, float]] | None = None
    shared_balance_date: date | None = None
    if shared_entry is not None:
        shared_allocations = _allocate_shared_entry_across_items(items, shared_entry[0])
        shared_balance_date = shared_entry[1]

    results: list[ParseResult] = []
    for idx, (product, total) in enumerate(items):
        if shared_allocations is not None:
            entry, balance = shared_allocations[idx]
            entry_date = reference_date
            balance_date = shared_balance_date or reference_date
            payment_warnings = [
                "Venda separada gerada automaticamente a partir de varios produtos na mesma mensagem.",
                f"Entrada total de R$ {shared_entry[0]:.2f} dividida proporcionalmente entre as vendas.",
            ]
        else:
            entry, balance, entry_date, balance_date = _extract_item_payment_for_product(
                raw, product, total, reference_date
            )
            payment_warnings = [
                "Venda separada gerada automaticamente a partir de varios produtos na mesma mensagem."
            ]
        if service_due_date and balance > 0.01:
            balance_date = max(balance_date, service_due_date)
        item_due = service_due_date or (balance_date if balance > 0.01 else entry_date)
        results.append(
            _build_sale_parse_result(
                customer=customer,
                product=product,
                total_value=total,
                entry_value=entry,
                balance_value=balance,
                sale_date=sale_date,
                entry_date=entry_date,
                balance_date=balance_date,
                service_due_date=item_due,
                warnings=payment_warnings,
            )
        )
    return results if len(results) >= 2 else None


_SERVICE_COST_PREFIXES = (
    r"custo(?:\s+de)?",
    r"custos(?:\s+de)?",
    r"custou",
    r"teve\s+um\s+custo(?:\s+de)?",
    r"tive\s+um\s+custo(?:\s+de)?",
    r"houve\s+um\s+custo(?:\s+de)?",
)


def _is_service_cost_update(text: str) -> bool:
    """True quando o usuário informa custo de um serviço/venda já existente (não valor da venda)."""
    return bool(re.search(r"\bcust(?:o|os|ou)\b", _normalize(text), flags=re.IGNORECASE))


def _extract_service_cost_amount(text: str) -> Optional[float]:
    """Extrai valor citado junto de 'custo' (ex.: 'tive um custo de 800 reais')."""
    value = _extract_amount_after_prefix(
        text,
        prefixes=list(_SERVICE_COST_PREFIXES),
        max_gap_words=3,
    )
    if value:
        return value
    value = _extract_amount_after_prefix(
        text,
        prefixes=[r"(?:foi\s+)?gast(?:o|ou)\s+o\s+valor\s+de", r"valor\s+de", r"valor\s+foi\s+de"],
        max_gap_words=12,
    )
    if value:
        return value
    return _extract_amount_before_prefix(
        text,
        prefixes=[r"custo(?:\s+de)?", r"custos(?:\s+de)?"],
        max_gap_words=5,
    )


def _extract_material_cost(text: str) -> Optional[float]:
    """
    Extrai custo de material priorizando o trecho próximo a palavras-chave
    para evitar capturar "metade" da venda por engano.
    """
    if _is_service_cost_update(text):
        service_cost = _extract_service_cost_amount(text)
        if service_cost:
            return service_cost
    norm = _normalize(text)
    keyword_positions: list[int] = []
    material_keywords = (
        r"\bmaterial\b",
        r"\bmateria\s+prima\b",
        r"\bfornecedor\b",
        r"\bgastar\b",
        r"\bgasto\b",
        r"\bcusto\b",
        r"\bcustos\b",
        r"\bcustou\b",
        r"\bcompr(?:ar|ei)\s+(?:de\s+)?material\b",
        r"\bcompra\s+de\s+material\b",
    )
    for pattern in material_keywords:
        for match in re.finditer(pattern, norm, flags=re.IGNORECASE):
            keyword_positions.append(match.start())
    candidates: list[float] = []
    for idx in keyword_positions:
        snippet = _mask_id_number_spans(text[max(0, idx - 90) : idx + 110])
        for v in _currency_candidates(snippet):
            if v > 0:
                candidates.append(float(v))
        masked_window = _mask_id_number_spans(text[max(0, idx - 20) : idx + 120])
        for pattern in (
            r"(?:foi\s+)?gast(?:o|ou)\s+o\s+valor\s+de\s+(.{0,80})",
            r"valor\s+de\s+(.{0,80})",
            r"\bmaterial\b\s*(?:de\s+)?(.{0,80})",
        ):
            after_material = re.search(pattern, _normalize(masked_window), flags=re.IGNORECASE)
            if not after_material:
                continue
            word_value = _parse_money_from_fragment(after_material.group(1))
            if word_value is not None and word_value >= 10:
                candidates.append(float(word_value))
    gasto_value = _extract_amount_after_prefix(
        text,
        prefixes=[r"(?:foi\s+)?gast(?:o|ou)\s+o\s+valor\s+de", r"valor\s+de"],
        max_gap_words=12,
    )
    if gasto_value and gasto_value >= 10:
        candidates.append(float(gasto_value))
    if candidates:
        return max(candidates)
    return None


def _extract_payment_value(text: str, label: str, total: Optional[float], fallback_numbers: list[float]) -> Optional[float]:
    norm = _normalize(text)
    if "metade" in norm and total:
        entry_half_tokens = (
            "pagou",
            "pagaram",
            "pagamos",
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
        # Importante: priorizar "entrada ..." antes de "pagou ...".
        # Ex.: "pagou 15000, entrada 8 mil" => entrada deve ser 8000 (não 15000).
        prefixes = [
            r"entrada\s*(?:de|foi)?",
            r"deu\s+(?:uma\s+)?entrada\s*(?:de|foi)?",
            r"deu\s+",
            r"me\s+deu",
            r"me\s+pagou",
            r"me\s+pagaram",
            r"recebi",
            r"pagaram",
            r"pagamos",
            r"pagou",
        ]
    else:
        prefixes = [
            r"restante\s*(?:de|foi)?",
            r"resto\s*(?:de|foi)?",
            r"saldo\s*(?:de|foi)?",
            r"vao\s+pagar",
            r"vão\s+pagar",
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
    parsed = _parse_pt_date(forward, reference_date, full_text=text)
    if parsed:
        return parsed
    if stop_keywords:
        return None
    return _parse_pt_date(segment, reference_date, full_text=text)


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

    stop_keywords = (
        "restante",
        "saldo",
        "receber",
        "material",
        "fornecedor",
        "pagou",
        "metade",
        "vai me pagar",
        "vou receber",
        "entrada",
        "entrega",
        "entregar",
    )
    explicit_sale = _extract_first_date_by_keywords(
        text,
        reference_date,
        keywords=(
            "data da venda",
            "data de venda",
            "vendi em",
            "vendi dia",
            "vendi no dia",
            "fechei em",
            "fechei dia",
            "fechei no dia",
        ),
        stop_keywords=stop_keywords,
    )
    if explicit_sale:
        return explicit_sale

    just_sold_tokens = (
        "acabei de vender",
        "acabei de fazer uma venda",
        "fiz uma venda",
        "fiz um servico",
        "vendi ",
        "vendemos ",
        "fechei ",
        "fechamos ",
    )
    if any(tok in norm for tok in just_sold_tokens):
        return reference_date

    return reference_date


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
    if _extract_month_from_text(text):
        return True
    if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", norm):
        return True
    if re.search(r"\b(?:no\s+)?dia\s+\d{1,2}\b", norm):
        return True
    if re.search(r"\b(?:no\s+)?dia\s+(?:primeiro|primeira|segundo|segunda|terceiro|terceira)\b", norm):
        return True
    if re.search(r"\b\d{1,2}\s+de\s+[a-z]+\b", norm):
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


def recalculate_payments_for_total(command) -> bool:
    """Recalcula o saldo quando o valor total muda (ex.: correção 'valor: 5877,80')."""
    total = float(getattr(command, "total_value", None) or 0.0)
    if total <= 0:
        return False
    entry_val = 0.0
    balance_payment = None
    for payment in getattr(command, "payments", []) or []:
        label = str(getattr(payment, "label", "") or "").strip().lower()
        if label == "entrada":
            entry_val = float(getattr(payment, "value", 0.0) or 0.0)
        elif label == "saldo":
            balance_payment = payment
    if balance_payment is None:
        return False
    new_balance = round(max(total - entry_val, 0.0), 2)
    if abs(float(balance_payment.value or 0.0) - new_balance) < 0.005:
        return False
    balance_payment.value = new_balance
    return True


def should_replace_pending_preview(text: str) -> bool:
    """
    Detecta quando o usuário enviou uma mensagem completa nova (ex.: outra venda)
    em vez de uma correção pontual da prévia pendente (ex.: 'cliente: João').
    """
    raw = (text or "").strip()
    if len(raw) < 35:
        return False
    norm = _normalize(raw)
    sale_markers = (
        "vendi",
        "vender",
        "vendemos",
        "acabei de vender",
        "acabei de fazer uma venda",
        "fechei",
        "fechamos",
        "fiz uma venda",
        "fiz outra venda",
        "fiz um servico",
        "comprou",
        "compraram",
    )
    if not any(marker in norm for marker in sale_markers):
        return False
    detail_markers = (
        "valor",
        "pagou",
        "pagaram",
        "pagamos",
        "paguei",
        "entrada",
        "metade",
        "restante",
        "saldo",
        "por ",
        "r$",
        " mil",
    )
    return any(marker in norm for marker in detail_markers)


def parse_financial_message(message: str, reference_date: Optional[date] = None) -> ParseResult:
    if reference_date is None:
        reference_date = date.today()

    raw_text = message.strip()
    norm_text = _normalize(raw_text)
    numbers = _currency_candidates(raw_text)
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
            "compraram",
        )
    )
    if sale_creation_context:
        # Nova venda: ID VENDA só é gerado ao salvar na planilha.
        material_allocations: list[MaterialAllocation] = []
        sale_id = _extract_sale_id_from_text(raw_text)
    else:
        sale_id = _extract_target_sale_id_for_updates(raw_text)
        material_allocations = _extract_material_allocations(raw_text, reference_date)
        if not sale_id and material_allocations:
            sale_id = material_allocations[0].sale_id

    customer = _extract_customer(raw_text) or ""
    if sale_id and customer:
        cust_norm = _normalize(customer)
        sale_digits = re.sub(r"\D", "", str(sale_id))
        cust_digits = re.sub(r"\D", "", customer)
        if sale_digits and cust_digits and sale_digits == cust_digits:
            customer = ""
        elif sale_digits and cust_norm.startswith(sale_digits):
            customer = ""
    product_id = _extract_product(raw_text) or ""
    service_cost_update = bool(
        (not sale_creation_context) and sale_id and _is_service_cost_update(raw_text)
    )
    total_value = None if service_cost_update else _extract_total_value(raw_text, numbers)
    itemized_products, itemized_total = _extract_itemized_products_and_total(raw_text)
    if itemized_total is not None and not service_cost_update:
        total_value = itemized_total
    if len(itemized_products) >= 2:
        product_id = " + ".join(itemized_products)
    elif itemized_products and not product_id:
        product_id = itemized_products[0]
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
            "custo",
            "custos",
            "pagar",
        )
    ) or service_cost_update
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
    # Se o usuário disse explicitamente que pagou hoje (ex.: "metade hoje"),
    # a entrada deve ser considerada paga na data da venda.
    if "hoje" in norm_text and any(tok in norm_text for tok in ("pagou", "pagaram", "pagamos", "entrada", "metade")):
        entry_date = sale_date
    if re.search(r"\b(?:me\s+)?pag(?:ou|aram|amos)\b", norm_text) or re.search(r"\bpaguei\b", norm_text):
        entry_date = sale_date
    balance_segment = (
        _segment_near(raw_text, "restante")
        or _segment_near(raw_text, "resto")
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
    if ("amanha" in norm_text) and any(tok in norm_text for tok in ("restante", "resto", "saldo", "receber", "recebo", "vai me pagar", "vamos pagar", "vao pagar", "vão pagar")):
        balance_date = max(balance_date, reference_date + timedelta(days=1))

    balance_future_hint = _contains_future_balance_hint(balance_segment or "") or _contains_future_balance_hint(raw_text)
    if balance_segment and not _contains_explicit_date_hint(balance_segment) and balance_future_hint:
        balance_date = max(balance_date, sale_date + timedelta(days=1))

    # Se o texto menciona um mês (ex.: "junho") mas o trecho do saldo só tem "dia 30",
    # usar o mês informado em vez do mês atual.
    msg_month = _extract_month_from_text(raw_text)
    if msg_month and balance_segment:
        seg_norm = _normalize(balance_segment)
        if msg_month and not _extract_month_from_text(balance_segment):
            day_match = re.search(r"\bdia\s+(\d{1,2})\b", seg_norm)
            if day_match:
                balance_date = _build_date(int(day_match.group(1)), msg_month, reference_date)

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
    # Se o usuário informou quando vai pagar o restante ("restante dia 13/04"),
    # usamos isso também como Data de Entrega (padrão do fluxo do usuário).
    if service_due_date is None and balance_future_hint and balance_date:
        service_due_date = balance_date
    # Heurística: quando o cliente fala "amanha" e também menciona entrega,
    # consideramos amanhã como Data de Entrega.
    if service_due_date is None and ("amanha" in norm_text) and any(
        tok in norm_text for tok in ("entrega", "entregar", "servico", "serviço", "fazer o servico", "fazer o serviço")
    ):
        service_due_date = reference_date + timedelta(days=1)

    entry_value = _extract_payment_value(raw_text, "entrada", total_value, numbers)
    balance_value = _extract_payment_value(raw_text, "saldo", total_value, numbers)
    # Heurística: quando o texto traz "pagou X" e também "entrada Y",
    # mas o total capturado ficou menor que um pagamento (ex.: total=8000 e entrada=15000),
    # assumir que o maior valor é o TOTAL e o menor é a ENTRADA.
    # Isso evita o aviso e calcula corretamente o restante.
    if total_value and entry_value and entry_value > (total_value + 0.01):
        paid_context = ("entrada" in norm_text) or bool(re.search(r"\b(?:me\s+)?pag(?:ou|aram|amos)\b", norm_text))
        if paid_context and numbers:
            qualifying_totals = [n for n in numbers if n >= entry_value - 0.01]
            if qualifying_totals:
                candidate_total = max(qualifying_totals)
                total_value = candidate_total
                balance_value = round(max(total_value - entry_value, 0), 2)
                warnings.append(
                    "Ajuste automático: total alinhado ao valor da venda (ex.: 10 mil) e saldo recalculado."
                )
            elif paid_context:
                bigger = float(entry_value)
                smaller = float(total_value)
                total_value = bigger
                entry_value = smaller
                balance_value = None
                warnings.append(
                    "Ajuste automático: valor maior interpretado como total e o menor como entrada."
                )

    material_cost = _extract_material_cost(raw_text)
    if material_cost is None:
        material_cost = _extract_amount_after_prefix(
            raw_text,
            prefixes=[r"material", r"materia prima", r"mat[eé]ria prima"],
            max_gap_words=5,
        )
    if material_cost is None:
        material_cost = _extract_amount_after_prefix(raw_text, prefixes=[r"gastar", r"gasto"], max_gap_words=8)
    if material_cost is None and _is_service_cost_update(raw_text):
        material_cost = _extract_service_cost_amount(raw_text)
    if service_cost_update and material_cost:
        total_value = None
        product_id = ""
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
    if material_cost and sale_creation_context and not re.search(
        r"\b(?:material|materia\s+prima|fornecedor|gast(?:ar|o)\s+(?:de\s+)?material|compr(?:ar|ei)\s+(?:de\s+)?material)\b",
        norm_text,
        flags=re.IGNORECASE,
    ):
        material_cost = None
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
    if service_due_date is not None and service_due_date < sale_date:
        bumped = service_due_date.replace(year=sale_date.year + 1)
        if bumped <= sale_date:
            bumped = sale_date + timedelta(days=1)
        service_due_date = bumped
        warnings.append(
            f"Data de entrega ajustada para {service_due_date.strftime('%d/%m/%Y')} "
            "(não pode ser anterior à data da venda)."
        )
    material_expense_only = bool((material_allocations or material_cost) and (not sale_creation_context) and not total_value)
    if material_expense_only:
        # Para "gasto de material", precisamos do ID VENDA para vincular a linha correta em "Compras Matéria-Prima".
        # Gasto de material: só precisa do ID VENDA para vincular na planilha.
        if not sale_id and not material_allocations:
            missing.append("ID VENDA")
    else:
        # Fluxo de venda normal: exige nome do cliente e valor (produto é opcional).
        if not customer:
            missing.append("Cliente")
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
            "compraram",
        )
    )
    if (not sale_creation_context) and _is_sale_delete_request(message):
        return "sale_delete"
    sale_id = _extract_target_sale_id_for_updates(message) or _extract_delete_sale_id(message)
    multi_ids = extract_sale_ids_list_for_updates(message)
    if not sale_id and multi_ids:
        sale_id = multi_ids[0]
    status = _extract_status_value(message)
    material_cost = _extract_material_cost(message)
    if material_cost is None:
        material_cost = _extract_amount_after_prefix(
            message,
            prefixes=[
                r"material",
                r"materia prima",
                r"mat[eé]ria prima",
                r"adicionar(?:\s+o)?\s+valor\s+de\s+material",
                r"compra\s+de\s+material",
                r"gastar",
                r"gastei",
                r"gasto",
            ],
            max_gap_words=8,
        )
    material_allocations = _extract_material_allocations(message, date.today())
    delivery_date = _extract_delivery_update_date(message, date.today())
    payment_amount = _extract_amount_after_prefix(
        message,
        prefixes=[r"pagou", r"paguei", r"recebi", r"recebeu", r"entrada"],
        max_gap_words=0,
    )
    # Refund sempre ganha, mesmo que a mensagem tenha outros tokens.
    if (not sale_creation_context) and sale_id and _is_service_delivery_finalized(message) and not status and not (material_allocations or material_cost):
        return "delivery_finalize"
    if (not sale_creation_context) and sale_id and delivery_date and not status and not (material_allocations or material_cost):
        return "delivery_update"
    if (not sale_creation_context) and sale_id and (material_allocations or material_cost) and not status:
        return "material_update"
    if (not sale_creation_context) and sale_id and payment_amount and not status and not (material_allocations or material_cost) and not delivery_date:
        return "payment_update"
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
    sale_id = _extract_target_sale_id_for_updates(message) or _extract_sale_id_from_text(message)
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


_PREVIEW_CORRECTION_FIELD_RE = re.compile(
    r"(?i)\b("
    r"data\s+de\s+entrega"
    r"|data\s+entrega"
    r"|data\s+(?:da\s+)?venda"
    r"|nome\s+do\s+cliente"
    r"|id\s+cliente"
    r"|cliente(?:\s+id)?\s*[:=]"
    r"|produto"
    r"|valor\s+total"
    r"|valor"
    r"|entrada(?:\s+paga)?"
    r"|saldo"
    r"|restante"
    r"|resto"
    r"|entrega"
    r"|material(?:\s+estimado)?"
    r"|custo(?:\s+do\s+servi[cç]o)?"
    r"|custos?"
    r"|id\s+venda"
    r"|venda"
    r")\s*[:=]?\s*"
)

_NL_PREVIEW_CORRECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "cliente",
        re.compile(
            r"(?is)\b(?:o\s+)?(?:nome\s+)?(?:do\s+)?cliente\s+"
            r"(?:é|eh|e\s+é|sera|será|chama|se\s+chama|=|:)\s*"
            r"(.+?)(?=\s*,\s*|\s+(?:e\s+)?(?:o\s+)?produto\b|\s+valor\b|\s+entrada\b|\s+saldo\b|\s+restante\b|$)"
        ),
    ),
    (
        "produto",
        re.compile(
            r"(?is)\b(?:o\s+)?produto\s+"
            r"(?:é|eh|e\s+é|sera|será|=|:)\s*"
            r"(.+?)(?=\s*,\s*|\s+valor\b|\s+entrada\b|\s+saldo\b|\s+restante\b|\s+cliente\b|$)"
        ),
    ),
    (
        "valor",
        re.compile(
            r"(?is)\bvalor\s+total\s+"
            r"(?:é|eh|de|foi|sera|será|=|:)\s*"
            r"(.+?)(?=\s*,\s*|\s+entrada\b|\s+saldo\b|\s+restante\b|\s+metade\b|$)"
        ),
    ),
    (
        "entrada",
        re.compile(
            r"(?is)\b(?:a\s+)?entrada\s+"
            r"(?:é|eh|de|foi|sera|será|=|:)\s*"
            r"(.+?)(?=\s*,\s*|\s+saldo\b|\s+restante\b|\s+resto\b|$)"
        ),
    ),
    (
        "saldo",
        re.compile(
            r"(?is)\b(?:o\s+)?(?:saldo|restante|resto)\s+"
            r"(?:é|eh|de|foi|sera|será|=|:)\s*"
            r"(.+?)(?=\s*,\s*|\s+entrada\b|$)"
        ),
    ),
    (
        "valor",
        re.compile(
            r"(?is)\bfoi\s+"
            r"(.+?)(?=\s+mas\b|\s+mas\s+|\s+e\s+|\s+entrada\b|\s+saldo\b|\s+restante\b|\s+cliente\b|$)"
        ),
    ),
    (
        "entrada",
        re.compile(
            r"(?is)\b(?:deu|pagou|pagaram|paguei)\s+"
            r"(.+?)\s+de\s+entrada\b"
        ),
    ),
)


def _preview_correction_label_to_key(label: str) -> Optional[str]:
    label = label.lower().strip()
    if label.startswith("cliente") or label.startswith("nome do cliente") or label == "id cliente":
        return "cliente"
    if label.startswith("material"):
        return "material"
    if label.startswith("custo"):
        return "material"
    if label == "produto":
        return "produto"
    if label.startswith("valor"):
        return "valor"
    if label in ("entrada", "entrada paga"):
        return "entrada"
    if label in ("saldo", "restante", "resto"):
        return "saldo"
    if label.startswith("data") and "entrega" in label:
        return "data_entrega"
    if label.startswith("data") and "venda" in label:
        return "data_venda"
    if label == "entrega":
        return "data_entrega"
    if label == "id venda" or label == "venda":
        return "id_venda"
    return None


def _extract_nl_preview_correction_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, pattern in _NL_PREVIEW_CORRECTION_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = match.group(1).strip(" \t\n\r:-,")
        if value:
            fields.setdefault(key, value)
    return fields


def _extract_preview_correction_fields(text: str) -> dict[str, str]:
    """Extrai pares campo->valor (rótulos explícitos ou fala natural)."""
    raw = text.strip()
    if not raw:
        return {}
    fields: dict[str, str] = {}
    matches = list(_PREVIEW_CORRECTION_FIELD_RE.finditer(raw))
    for i, match in enumerate(matches):
        key = _preview_correction_label_to_key(match.group(1))
        if not key:
            continue
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        value = raw[start:end].strip(" \t\n\r:-,")
        if value:
            fields[key] = value
    for key, value in _extract_nl_preview_correction_fields(raw).items():
        fields.setdefault(key, value)
    return fields


def _preview_correction_rest(text: str, keyword: str) -> str:
    _, _, rest = text.partition(":")
    if not rest:
        rest = re.split(rf"(?i)\b{re.escape(keyword)}\b", text, maxsplit=1)[-1]
    return rest.strip(" :-,")


def _parse_correction_money(fragment: str, full_text: str) -> Optional[float]:
    parsed = _parse_money_from_fragment(fragment.strip())
    if parsed is not None and parsed > 0:
        return parsed
    parsed = parse_money_value(fragment)
    if parsed is not None and parsed > 0:
        return parsed
    numbers = _currency_candidates(fragment) or _currency_candidates(full_text)
    if numbers:
        return float(numbers[0])
    match = re.search(
        r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)",
        fragment,
    )
    if not match:
        return None
    raw_norm = match.group(1).replace(".", "").replace(" ", "").replace(",", ".")
    try:
        return float(raw_norm)
    except ValueError:
        return None


def _find_payment(command: FinancialCommand, label: str) -> Optional[Payment]:
    target = label.strip().lower()
    for payment in command.payments or []:
        if str(payment.label).strip().lower() == target:
            return payment
    return None


def _upsert_payment(
    command: FinancialCommand,
    label: str,
    value: float,
    *,
    due_date: Optional[date] = None,
    status: Optional[str] = None,
) -> bool:
    payment = _find_payment(command, label)
    if payment is None:
        ref = command.sale_date or date.today()
        default_status = "pago" if label == "entrada" else "pendente"
        command.payments.append(
            Payment(
                label=label.capitalize(),
                value=float(value),
                due_date=due_date or ref,
                status=status or default_status,
            )
        )
        return True
    payment.value = float(value)
    if due_date is not None:
        payment.due_date = due_date
    if status is not None:
        payment.status = status
    return True


def _payment_mentioned_in_text(norm: str, label: str) -> bool:
    if label == "entrada":
        return any(tok in norm for tok in ("entrada", "pagou", "pagaram", "paguei", "deu", "metade", "me deu", "recebi"))
    return any(tok in norm for tok in ("saldo", "restante", "resto", "receber", "vai me pagar", "vou receber"))


def _apply_preview_payment_corrections(
    text: str,
    command: FinancialCommand,
    fields: dict[str, str],
    reference_date: date,
) -> bool:
    """Atualiza entrada/saldo só nos campos citados na mensagem."""
    norm = _normalize(text)
    if not any(
        tok in norm
        for tok in ("entrada", "saldo", "restante", "resto", "metade", "pagou", "paguei", "receber")
    ):
        return False

    total = float(command.total_value or 0.0)
    numbers = _currency_candidates(text)
    updated = False

    for pay_label, field_key in (("entrada", "entrada"), ("saldo", "saldo")):
        if field_key not in fields and not _payment_mentioned_in_text(norm, pay_label):
            continue
        value: Optional[float] = None
        if field_key in fields:
            value = _parse_correction_money(fields[field_key], text)
        if value is None:
            value = _extract_payment_value(text, pay_label, total if total > 0 else None, numbers)
        if value is None or value <= 0:
            continue

        due: Optional[date] = None
        if pay_label == "entrada":
            due = _extract_first_date_by_keywords(
                fields.get("entrada", text),
                reference_date,
                keywords=("pagou", "entrada", "pago", "hoje"),
            )
            status = "pago" if any(tok in norm for tok in ("pagou", "paguei", "pago", "hoje")) else None
        else:
            due = _extract_first_date_by_keywords(
                fields.get("saldo", text),
                reference_date,
                keywords=("restante", "saldo", "receber", "vence", "entrega"),
            )
            status = "pendente" if _contains_future_balance_hint(text) else None

        _upsert_payment(command, pay_label, value, due_date=due, status=status)
        updated = True

    return updated


_BATCH_SALE_INDEX_WORDS = {
    "um": 0,
    "uma": 0,
    "1": 0,
    "primeira": 0,
    "primeiro": 0,
    "dois": 1,
    "duas": 1,
    "2": 1,
    "segunda": 1,
    "segundo": 1,
    "tres": 2,
    "três": 2,
    "3": 2,
    "terceira": 2,
    "terceiro": 2,
}


def resolve_batch_sale_index(text: str, batch: list[ParseResult]) -> int | None:
    """Identifica qual item do lote o usuário quer corrigir (venda 1, venda um, produto...)."""
    norm = _normalize(text)
    match = re.search(
        r"\bvenda\s+(um|uma|dois|duas|tres|tr[eê]s|\d+|primeir[ao]|segund[ao]|terceir[ao])\b",
        norm,
    )
    if match:
        token = match.group(1)
        if token.isdigit():
            idx = int(token) - 1
        else:
            idx = _BATCH_SALE_INDEX_WORDS.get(token)
        if idx is not None and 0 <= idx < len(batch):
            return idx
    for i, pr in enumerate(batch):
        product = _normalize(pr.command.product_id or "")
        if product and len(product) >= 3 and product in norm:
            return i
    return None


def _strip_batch_sale_prefix(text: str) -> str:
    return re.sub(
        r"(?is)^(?:na\s+)?venda\s+(?:um|uma|dois|duas|tres|tr[eê]s|\d+|primeir[ao]|segund[ao]|terceir[ao])\s*[:\-,]?\s*",
        "",
        text.strip(),
    ).strip()


def apply_batch_preview_corrections(
    text: str,
    batch: list[ParseResult],
    reference_date: Optional[date] = None,
) -> tuple[bool, list[ParseResult]]:
    """Aplica correção pontual em uma venda dentro de um lote pendente."""
    if reference_date is None:
        reference_date = date.today()
    if not batch:
        return False, batch
    idx = resolve_batch_sale_index(text, batch)
    if idx is None:
        return False, batch
    parse_result = batch[idx]
    correction_text = _strip_batch_sale_prefix(text)
    updated = apply_multi_field_corrections(
        correction_text,
        parse_result.command,
        parse_result,
        reference_date=reference_date,
    )
    if not updated:
        updated = apply_preview_corrections(
            correction_text,
            parse_result.command,
            reference_date=reference_date,
        )
    if not updated:
        return False, batch
    batch[idx] = parse_result
    return True, batch


def apply_multi_field_corrections(
    text: str,
    command: FinancialCommand,
    parse_result: Optional[ParseResult] = None,
    reference_date: Optional[date] = None,
) -> bool:
    """
    Aplica correções pontuais na prévia, campo a campo, sem bagunçar o restante.
    Ex.: 'Cliente: Ana, Produto: Banner, Valor total: 3000, Entrada: 1500, Saldo: 1500'.
    """
    if reference_date is None:
        reference_date = date.today()

    updated = False
    if parse_result is not None and parse_result.intent == "sale_delete":
        supplemental = extract_supplemental_sale_id(text)
        if supplemental:
            command.sale_id = supplemental
            dc = getattr(parse_result, "delete_command", None)
            if dc is not None:
                dc.sale_id = supplemental
            if "ID VENDA" in parse_result.missing_fields:
                parse_result.missing_fields = [
                    f for f in parse_result.missing_fields if f != "ID VENDA"
                ]
            updated = True

    fields = _extract_preview_correction_fields(text)
    if "cliente" in fields and not re.search(
        r"(?i)\b(?:cliente\s*[:=]|nome\s+do\s+cliente|o\s+nome\s+do\s+cliente|cliente\s+(?:é|eh|e\s+é|sera|será|chama))"
        ,
        text,
    ):
        fields.pop("cliente", None)
    if not fields:
        lower = text.strip().lower()
        if lower.startswith("cliente"):
            rest = _preview_correction_rest(text, "cliente")
            if rest:
                fields = {"cliente": rest}
        elif (
            "id venda" in lower
            or (lower.startswith("venda") and "data" not in lower)
            or re.search(r"\bid\s*[:\-]?\s*\d", lower)
        ):
            fields = {"id_venda": text}
        elif "material" in lower or "custo" in lower:
            keyword = "custo" if "custo" in lower else "material"
            rest = _preview_correction_rest(text, keyword)
            if rest:
                fields = {"material": rest}
        elif "produto" in lower:
            rest = _preview_correction_rest(text, "produto")
            if rest:
                fields = {"produto": rest}
        elif "valor" in lower:
            fields = {"valor": _preview_correction_rest(text, "valor") or text}

    if (
        not fields
        and not updated
        and not any(
            tok in _normalize(text)
            for tok in ("entrada", "saldo", "restante", "metade", "pagou", "paguei")
        )
    ):
        return updated

    touched_payments = "entrada" in fields or "saldo" in fields

    if "cliente" in fields:
        command.customer = fields["cliente"].strip()
        updated = True

    if "id_venda" in fields:
        supplemental = extract_supplemental_sale_id(fields["id_venda"])
        if supplemental:
            command.sale_id = supplemental
            updated = True
        else:
            m_id = re.search(r"\d+", fields["id_venda"])
            if m_id:
                digits = m_id.group(0)
                command.sale_id = digits.zfill(3) if len(digits) <= 3 else digits
                updated = True
        if updated and command.sale_id and command.material_allocations:
            for allocation in command.material_allocations:
                allocation.sale_id = str(command.sale_id).strip()

    if "material" in fields:
        parsed_material = _parse_correction_money(fields["material"], text)
        if parsed_material is not None and parsed_material > 0:
            command.material_cost = parsed_material
            command.material_date = command.material_date or command.sale_date or reference_date
            if command.material_allocations:
                for allocation in command.material_allocations:
                    allocation.amount = float(parsed_material)
            elif command.sale_id:
                command.material_allocations = [
                    MaterialAllocation(
                        sale_id=str(command.sale_id).strip(),
                        amount=float(parsed_material),
                        material_date=command.material_date or reference_date,
                    )
                ]
            updated = True

    if "produto" in fields:
        new_prod = fields["produto"]
        if new_prod:
            command.product_id = new_prod
            command.description = new_prod
            updated = True

    if "data_venda" in fields:
        parsed = _parse_pt_date(fields["data_venda"], reference_date, full_text=fields["data_venda"])
        if parsed:
            command.sale_date = parsed
            updated = True

    if "data_entrega" in fields:
        parsed = _parse_pt_date(fields["data_entrega"], reference_date, full_text=fields["data_entrega"])
        if parsed:
            command.service_due_date = parsed
            saldo = _find_payment(command, "saldo")
            if saldo is not None:
                saldo.due_date = parsed
            updated = True

    if "valor" in fields:
        parsed_value = _parse_correction_money(fields["valor"], text)
        if parsed_value is not None and parsed_value > 0:
            command.total_value = parsed_value
            if not touched_payments:
                recalculate_payments_for_total(command)
            updated = True

    if _apply_preview_payment_corrections(text, command, fields, reference_date):
        updated = True
        touched_payments = True

    if touched_payments and command.total_value and command.payments:
        payment_total = round(sum(float(p.value or 0) for p in command.payments), 2)
        total = round(float(command.total_value), 2)
        if abs(payment_total - total) >= 0.01:
            saldo = _find_payment(command, "saldo")
            entrada = _find_payment(command, "entrada")
            if saldo is not None and entrada is not None and "saldo" not in fields:
                saldo.value = round(max(total - float(entrada.value or 0), 0), 2)

    if updated and parse_result is not None:
        if (command.customer or "").strip() and "Cliente" in parse_result.missing_fields:
            parse_result.missing_fields = [
                f for f in parse_result.missing_fields if f != "Cliente"
            ]
        if getattr(command, "sale_id", None) and "ID VENDA" in parse_result.missing_fields:
            parse_result.missing_fields = [
                f for f in parse_result.missing_fields if f != "ID VENDA"
            ]
        dc = getattr(parse_result, "delete_command", None)
        if dc is not None and getattr(command, "sale_id", None):
            dc.sale_id = str(command.sale_id).strip()

    return updated


def apply_preview_corrections(
    message: str,
    command: FinancialCommand,
    reference_date: Optional[date] = None,
) -> bool:
    """
    Aplica correções pontuais na prévia (ex.: 'a data será em junho', 'entrega 30/06').
    Retorna True se algum campo foi atualizado.
    """
    if reference_date is None:
        reference_date = date.today()
    raw = message.strip()
    if not raw:
        return False
    norm = _normalize(raw)
    updated = False

    def _apply_delivery_date(parsed: Optional[date]) -> None:
        nonlocal updated
        if parsed is None:
            return
        command.service_due_date = parsed
        for payment in command.payments:
            if str(payment.label).strip().lower() == "saldo":
                payment.due_date = parsed
        updated = True

    preferred_day: Optional[int] = None
    if command.service_due_date:
        preferred_day = command.service_due_date.day
    else:
        for payment in command.payments:
            if str(payment.label).strip().lower() == "saldo" and payment.due_date:
                preferred_day = payment.due_date.day
                break

    date_hint_tokens = (
        "entrega",
        "entregar",
        "prazo",
        "data de entrega",
        "data entrega",
        "data",
        "venc",
        "saldo",
        "restante",
        "pagamento",
        "junho",
        "janeiro",
        "fevereiro",
        "marco",
        "abril",
        "maio",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    )
    has_date_hint = any(tok in norm for tok in date_hint_tokens) or re.search(r"\d{1,2}[/-]\d", raw)

    if has_date_hint:
        parsed = _parse_pt_date(raw, reference_date, full_text=raw)
        if parsed is None:
            parsed = _date_from_month_mention(raw, reference_date, preferred_day=preferred_day)
        if parsed:
            if any(tok in norm for tok in ("data da venda", "data de venda", "venda")) and not any(
                tok in norm for tok in ("entrega", "entregar", "prazo", "saldo", "restante")
            ):
                command.sale_date = parsed
                updated = True
            else:
                _apply_delivery_date(parsed)

    if not updated and _extract_month_from_text(raw):
        parsed = _date_from_month_mention(raw, reference_date, preferred_day=preferred_day)
        _apply_delivery_date(parsed)

    return updated


def parse_message(message: str, reference_date: Optional[date] = None) -> ParseResult:
    message = normalize_spoken_ids_in_text(message)
    financial_result = parse_financial_message(message, reference_date)
    intent = detect_intent(message)
    if intent == "delivery_finalize":
        if reference_date is None:
            reference_date = date.today()
        target_sale_id = _extract_target_sale_id_for_updates(message) or ""
        delivery_date = _parse_pt_date(message, reference_date, full_text=message) or reference_date
        missing: list[str] = []
        if not target_sale_id:
            missing.append("ID VENDA")
        return ParseResult(
            command=FinancialCommand(
                customer=_extract_customer(message) or "",
                description=f"Confirmar entrega da venda {target_sale_id or '-'}",
                sale_date=reference_date,
                total_value=0.0,
                payments=[],
                sale_id=target_sale_id or None,
                service_due_date=delivery_date,
                service_status="finalizado",
            ),
            missing_fields=missing,
            detected_values={
                "id_venda": target_sale_id or "-",
                "data_entrega": delivery_date.strftime("%d/%m/%Y"),
            },
            intent="delivery_finalize",
        )
    if intent == "delivery_update":
        if reference_date is None:
            reference_date = date.today()
        target_sale_id = _extract_target_sale_id_for_updates(message) or ""
        delivery_date = _extract_delivery_update_date(message, reference_date)
        missing: list[str] = []
        if not target_sale_id:
            missing.append("ID VENDA")
        if delivery_date is None:
            missing.append("Data de Entrega")
        return ParseResult(
            command=FinancialCommand(
                customer=_extract_customer(message) or "",
                description=f"Atualizar data de entrega da venda {target_sale_id or '-'}",
                sale_date=reference_date,
                total_value=0.0,
                payments=[],
                sale_id=target_sale_id or None,
                service_due_date=delivery_date,
            ),
            missing_fields=missing,
            detected_values={
                "id_venda": target_sale_id or "-",
                "data_entrega": delivery_date.strftime("%d/%m/%Y") if delivery_date else "-",
            },
            intent="delivery_update",
        )
    if intent == "material_update":
        # Reaproveita parse_financial_message; updates por ID VENDA não exigem nome do Cliente.
        financial_result.intent = "material_update"
        return financial_result
    if intent == "payment_update":
        if reference_date is None:
            reference_date = date.today()
        target_sale_id = _extract_target_sale_id_for_updates(message) or ""
        amount = _extract_amount_after_prefix(
            message,
            prefixes=[r"pagou", r"paguei", r"recebi", r"recebeu", r"entrada"],
            max_gap_words=0,
        )
        pay_date = _parse_pt_date(message, reference_date) or reference_date
        missing: list[str] = []
        if not target_sale_id:
            missing.append("ID VENDA")
        if amount is None:
            missing.append("Valor pago")
        return ParseResult(
            command=FinancialCommand(
                customer=_extract_customer(message) or "",
                description=f"Atualizar pagamento da venda {target_sale_id or '-'}",
                sale_date=reference_date,
                total_value=0.0,
                payments=[],
                sale_id=target_sale_id or None,
            ),
            missing_fields=missing,
            detected_values={
                "id_venda": target_sale_id or "-",
                "valor_pago": f"{float(amount):.2f}" if amount else "-",
                "data": pay_date.strftime("%d/%m/%Y"),
            },
            intent="payment_update",
        )
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
    if intent == "sale_delete":
        delete_cmd, missing = parse_delete_sale_message(message, reference_date)
        return ParseResult(
            command=FinancialCommand(
                customer="",
                description=delete_cmd.reason,
                sale_date=delete_cmd.ref_date,
                total_value=0.0,
                payments=[],
                sale_id=delete_cmd.sale_id or None,
            ),
            missing_fields=missing,
            detected_values={
                "id_venda": delete_cmd.sale_id or "-",
                "motivo": delete_cmd.reason,
            },
            intent="sale_delete",
            delete_command=delete_cmd,
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
