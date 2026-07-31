# -*- coding: utf-8 -*-
"""Parser híbrido — fallback via LLM quando as regras não entendem a frase."""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from typing import Any

import requests

from .models import (
    DeleteSaleCommand,
    FinancialCommand,
    MaterialAllocation,
    Payment,
    StatusUpdateCommand,
)
from .parser import ParseResult

_VALID_INTENTS = frozenset(
    {
        "sale",
        "material_update",
        "status_update",
        "payment_update",
        "delivery_update",
        "delivery_finalize",
        "sale_delete",
        "refund",
        "mixed_update",
    }
)

_SYSTEM_PROMPT = """Você extrai comandos de vendas e finanças em português brasileiro para uma planilha de comunicação visual.
Responda APENAS com JSON válido (sem markdown), no formato:
{
  "intent": "sale|material_update|status_update|payment_update|delivery_update|delivery_finalize|sale_delete|refund",
  "customer": "nome do cliente ou vazio",
  "product": "produto/serviço (banner, fachada, placa...) ou vazio",
  "sale_id": "ID da venda (ex. 003) ou vazio",
  "total_value": 0.0,
  "entrada": 0.0,
  "saldo": 0.0,
  "sale_date": "YYYY-MM-DD ou null",
  "entrada_date": "YYYY-MM-DD ou null",
  "saldo_date": "YYYY-MM-DD ou null",
  "delivery_date": "YYYY-MM-DD ou null",
  "material_cost": 0.0,
  "payment_amount": 0.0,
  "status": "pago|pendente ou null",
  "delete_reason": "motivo se for exclusão"
}
Use null para campos desconhecidos. Valores monetários em número (ex.: 2500.0).
Datas relativas (hoje, amanhã, dia 15) devem ser resolvidas para a data de referência.
Exemplos de intent:
- venda nova com cliente e valores → sale
- gastei material na id 012 → material_update
- id 004 pagou → status_update com status pago
- id 005 recebeu 1500 → payment_update
- entrega foi hoje id 003 → delivery_finalize
- apaga id venda 002 → sale_delete"""


def llm_fallback_enabled() -> bool:
    if os.getenv("LLM_FALLBACK_ENABLED", "0").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return bool(os.getenv("LLM_API_KEY", "").strip())


def _api_config() -> tuple[str, str, str]:
    base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    key = os.getenv("LLM_API_KEY", "").strip()
    return base, model, key


def _parse_date_value(raw: Any, reference: date) -> date | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    import dateparser

    parsed = dateparser.parse(
        text,
        languages=["pt"],
        settings={
            "RELATIVE_BASE": datetime(reference.year, reference.month, reference.day),
            "PREFER_DAY_OF_MONTH": "first",
        },
    )
    return parsed.date() if parsed else None


def _coerce_float(raw: Any) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace("R$", "").replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _extract_json(text: str) -> dict[str, Any] | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def try_llm_parse(
    text: str,
    *,
    reference_date: date | None = None,
    partial: dict[str, str] | None = None,
    last_sale_id: str | None = None,
) -> ParseResult | None:
    """Tenta interpretar a frase via LLM. Retorna None se desligado ou falhar."""
    if not llm_fallback_enabled():
        return None

    reference = reference_date or date.today()
    base, model, key = _api_config()
    if not key:
        return None

    user_parts = [f"Data de referência: {reference.isoformat()}", f"Frase: {text}"]
    if last_sale_id:
        user_parts.append(f"Último ID VENDA no chat: {last_sale_id}")
    if partial:
        user_parts.append(f"Campos já conhecidos: {json.dumps(partial, ensure_ascii=False)}")

    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_parts)},
        ],
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45,
        )
        if response.status_code != 200:
            return None
        body = response.json()
        content = (
            ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        )
        data = _extract_json(content)
        if not data:
            return None
        return _parse_result_from_llm_dict(
            data,
            reference,
            partial=partial,
            last_sale_id=last_sale_id,
        )
    except Exception:
        return None


def _parse_result_from_llm_dict(
    data: dict[str, Any],
    reference: date,
    *,
    partial: dict[str, str] | None = None,
    last_sale_id: str | None = None,
) -> ParseResult | None:
    intent = str(data.get("intent") or "").strip().lower()
    if intent not in _VALID_INTENTS:
        return None

    sale_id = str(data.get("sale_id") or (partial or {}).get("sale_id") or last_sale_id or "").strip()
    customer = str(data.get("customer") or (partial or {}).get("customer") or "").strip()
    product = str(data.get("product") or (partial or {}).get("product") or "").strip()

    if intent == "sale_delete":
        reason = str(data.get("delete_reason") or "Solicitado via chat").strip()
        if not sale_id:
            return None
        return ParseResult(
            intent="sale_delete",
            command=FinancialCommand(
                customer=customer,
                description=f"Exclusão venda {sale_id}",
                sale_date=reference,
                total_value=0.0,
                payments=[],
                sale_id=sale_id,
            ),
            missing_fields=[],
            delete_command=DeleteSaleCommand(
                sale_id=sale_id,
                reason=reason,
                ref_date=reference,
            ),
            detected_values={"id_venda": sale_id},
        )

    if intent == "status_update":
        status = str(data.get("status") or "pago").strip().lower()
        if not sale_id:
            return None
        su = StatusUpdateCommand(sale_id=sale_id, status=status, ref_date=reference, customer=customer or None)
        delivery_date = _parse_date_value(data.get("delivery_date"), reference)
        cmd = FinancialCommand(
            customer=customer or "",
            description=f"Status {status} — {sale_id}",
            sale_date=reference,
            total_value=0.0,
            payments=[],
            sale_id=sale_id,
            service_due_date=delivery_date,
        )
        return ParseResult(
            intent="status_update",
            command=cmd,
            missing_fields=[],
            status_update_command=su,
            detected_values={"id_venda": sale_id, "status": status},
        )

    if intent == "payment_update":
        amount = _coerce_float(data.get("payment_amount"))
        if amount <= 0:
            amount = _coerce_float(data.get("entrada"))
        if not sale_id or amount <= 0:
            return None
        pay_date = _parse_date_value(data.get("entrada_date"), reference) or reference
        return ParseResult(
            intent="payment_update",
            command=FinancialCommand(
                customer=customer or "",
                description=f"Pagamento {sale_id}",
                sale_date=reference,
                total_value=0.0,
                payments=[],
                sale_id=sale_id,
            ),
            missing_fields=[],
            detected_values={
                "id_venda": sale_id,
                "valor_pago": str(amount),
                "data": pay_date.strftime("%d/%m/%Y"),
            },
        )

    if intent in ("delivery_update", "delivery_finalize"):
        if not sale_id:
            return None
        delivery_date = _parse_date_value(data.get("delivery_date"), reference) or reference
        fin_intent = "delivery_finalize" if intent == "delivery_finalize" else "delivery_update"
        return ParseResult(
            intent=fin_intent,
            command=FinancialCommand(
                customer=customer or "",
                description=f"Entrega {sale_id}",
                sale_date=reference,
                total_value=0.0,
                payments=[],
                sale_id=sale_id,
                service_due_date=delivery_date,
                service_status="finalizado" if fin_intent == "delivery_finalize" else None,
            ),
            missing_fields=[],
            detected_values={
                "id_venda": sale_id,
                "data_entrega": delivery_date.strftime("%d/%m/%Y"),
            },
        )

    if intent == "material_update":
        material_cost = _coerce_float(data.get("material_cost"))
        if material_cost <= 0:
            return None
        if not sale_id:
            return None
        alloc_date = _parse_date_value(data.get("sale_date"), reference) or reference
        return ParseResult(
            intent="material_update",
            command=FinancialCommand(
                customer=customer or "",
                description=f"Material venda {sale_id}",
                sale_date=alloc_date,
                total_value=0.0,
                payments=[],
                sale_id=sale_id,
                material_cost=material_cost,
                material_date=alloc_date,
                material_allocations=[
                    MaterialAllocation(
                        sale_id=sale_id,
                        amount=material_cost,
                        material_date=alloc_date,
                    )
                ],
            ),
            missing_fields=[],
            detected_values={"id_venda": sale_id, "material": str(material_cost)},
        )

    # sale (padrão)
    total = _coerce_float(data.get("total_value"))
    entrada = _coerce_float(data.get("entrada"))
    saldo = _coerce_float(data.get("saldo"))
    if total <= 0 and (entrada > 0 or saldo > 0):
        total = entrada + saldo
    if total <= 0:
        return None

    sale_date = _parse_date_value(data.get("sale_date"), reference) or reference
    entrada_date = _parse_date_value(data.get("entrada_date"), reference) or sale_date
    saldo_date = _parse_date_value(data.get("saldo_date"), reference) or sale_date
    delivery_date = _parse_date_value(data.get("delivery_date"), reference)
    material_cost = _coerce_float(data.get("material_cost"))

    payments: list[Payment] = []
    if entrada > 0:
        payments.append(Payment("Entrada", entrada, entrada_date, "pago"))
    if saldo > 0:
        payments.append(Payment("Saldo", saldo, saldo_date, "pendente"))
    if not payments:
        payments.append(Payment("Total", total, sale_date, "pendente"))

    missing: list[str] = []
    if not customer:
        missing.append("Cliente")
    if not product:
        missing.append("Produto")

    cmd = FinancialCommand(
        customer=customer or "",
        description=product or "Venda",
        product_id=product or None,
        sale_date=sale_date,
        total_value=total,
        payments=payments,
        sale_id=sale_id or None,
        material_cost=material_cost if material_cost > 0 else None,
        material_date=sale_date if material_cost > 0 else None,
        service_due_date=delivery_date,
    )
    detected: dict[str, str] = {}
    if customer:
        detected["cliente"] = customer
    if product:
        detected["produto"] = product
    if sale_id:
        detected["id_venda"] = sale_id

    return ParseResult(
        intent="sale",
        command=cmd,
        missing_fields=missing,
        detected_values=detected,
    )
