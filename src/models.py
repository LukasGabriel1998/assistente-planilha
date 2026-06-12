from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

Intent = Literal["sale", "refund", "status_update"]


@dataclass
class RefundCommand:
    """Comando de cancelamento/devolução: estornar uma venda."""
    customer: str
    amount: float
    reason: str
    ref_date: date


@dataclass
class DeleteSaleCommand:
    """Comando para remover um registro de venda (e material vinculado) da planilha."""
    sale_id: str
    reason: str
    ref_date: date
    remove_material: bool = True


@dataclass
class Payment:
    label: str
    value: float
    due_date: date
    status: str = "pago"


@dataclass
class StatusUpdateCommand:
    sale_id: str
    status: str
    ref_date: date
    customer: Optional[str] = None


@dataclass
class MaterialAllocation:
    sale_id: str
    amount: float
    material_date: date
    description: Optional[str] = None


@dataclass
class FinancialCommand:
    customer: str
    description: str
    sale_date: date
    total_value: float
    payments: list[Payment]
    product_id: Optional[str] = None
    sale_id: Optional[str] = None
    material_cost: Optional[float] = None
    material_date: Optional[date] = None
    material_supplier: Optional[str] = None
    material_allocations: list[MaterialAllocation] = field(default_factory=list)
    fixed_cost: Optional[float] = None
    fixed_cost_label: Optional[str] = None
    fixed_cost_date: Optional[date] = None
    service_due_date: Optional[date] = None
    service_status: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
