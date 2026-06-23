# -*- coding: utf-8 -*-
"""
Lógica compartilhada de processamento de comandos (planilha).
Usado pelo bot Telegram.
"""
from __future__ import annotations

import os
from dataclasses import asdict
from datetime import date
from pathlib import Path
from .excel_store import SpreadsheetService, DATA_START_ROW
from .parser import parse_message, ParseResult, _is_service_delivery_finalized, _is_delivery_explicitly_pending, _parse_pt_date
from .models import StatusUpdateCommand
from .workbook_paths import default_workbook_path, resolve_workbook_path

SUMMARY_KEYWORDS = (
    "resumo", "planilha", "como está", "como esta",
    "mostrar planilha", "resumo da planilha", "preenchimento", "situação", "situacao",
)

STATUS_KEYWORDS = (
    "status",
)

PREVIEW_KEYWORDS = (
    "previa", "prévia", "preview", "pendencias", "pendências", "entregas", "prazo", "prazos",
)


def sale_id_from_parse_result(parse_result: ParseResult) -> str | None:
    """Extrai o ID VENDA de um ParseResult para memória de contexto do chat."""
    dc = getattr(parse_result, "delete_command", None)
    if dc and getattr(dc, "sale_id", None):
        return str(dc.sale_id).strip()
    su = getattr(parse_result, "status_update_command", None)
    if su and getattr(su, "sale_id", None):
        return str(su.sale_id).strip()
    cmd = parse_result.command
    if getattr(cmd, "sale_id", None):
        return str(cmd.sale_id).strip()
    detected = (parse_result.detected_values or {}).get("id_venda")
    if detected and str(detected).strip() not in ("", "-"):
        return str(detected).strip()
    return None


def _format_currency_pt(value: float) -> str:
    txt = f"{float(value or 0):,.2f}"
    txt = txt.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {txt}"


def _load_sale_context_for_preview(sale_id: str) -> dict[str, str | float] | None:
    """Lê cliente, produto e valores da planilha para enriquecer prévias de atualização."""
    sale_id = str(sale_id or "").strip()
    if not sale_id:
        return None
    workbook_path = get_default_workbook()
    if not workbook_path or not Path(workbook_path).exists():
        return None
    try:
        service = SpreadsheetService(workbook_path)
        wb = service._open_workbook(data_only=True)
        try:
            sales_name = service._resolve_sheet_name(wb, "TOTAL DE VENDAS DE 2026")
            ws_sales = wb[sales_name]
            snapshot = service._sale_snapshot(ws_sales, sale_id)
            if not snapshot:
                return None
            sales_cols = service._sales_columns(ws_sales)
            col_sale_id = sales_cols["id venda"]
            total_pago = 0.0
            total_pendente = 0.0
            for row in range(DATA_START_ROW, min(ws_sales.max_row + 1, service.MAX_DATA_ROW)):
                if str(ws_sales[f"{col_sale_id}{row}"].value or "").strip() == sale_id:
                    total_pago = service._to_float(
                        ws_sales[f"{sales_cols['total de vendas (pago)']}{row}"].value
                    )
                    total_pendente = service._to_float(
                        ws_sales[f"{sales_cols['valor (pendente)']}{row}"].value
                    )
                    break
            return {
                "customer": snapshot.get("customer") or "",
                "product": snapshot.get("description") or "",
                "sale_date": snapshot.get("sale_date") or "",
                "total_value": total_pago + total_pendente,
                "total_pago": total_pago,
                "total_pendente": total_pendente,
            }
        finally:
            wb.close()
    except Exception:
        return None


def get_default_workbook() -> str:
    """Retorna o caminho da planilha (env WORKBOOK_PATH ou busca em cwd/pai)."""
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


def format_reply(intent: str, actions: list, error: str | None = None) -> str:
    """Monta mensagem curta de resposta."""
    if error:
        return f"⚠️ *Não consegui concluir.*\n\n{error}"
    if intent == "delivery_update" and actions:
        a = actions[0]
        return f"✅ *Data de entrega atualizada!*\n\nID VENDA: {a.get('sale_id', '')}\nPlanilha atualizada com sucesso."
    if intent == "delivery_finalize" and actions:
        a = actions[0]
        return f"✅ *Entrega confirmada!*\n\nID VENDA: {a.get('sale_id', '')}\nData de entrega atualizada e marcada como entregue (verde)."
    if intent == "payment_update" and actions:
        a = actions[0]
        return f"✅ *Pagamento registrado!*\n\nID VENDA: {a.get('sale_id', '')}\nPlanilha atualizada com sucesso."
    if intent == "refund" and actions:
        a = actions[0]
        return f"✅ *Estorno registrado!*\n\nAba: {a.get('sheet', '')}\nLinha: {a.get('row', '')}"
    if intent == "sale_delete" and actions:
        a = actions[0]
        return (
            f"✅ *Registro apagado da planilha!*\n\n"
            f"ID VENDA: {a.get('sale_id', '')}\n"
            f"Os dados da venda (e material vinculado) foram removidos."
        )
    if intent == "status_update" and actions:
        a = actions[0]
        return f"✅ *Status atualizado!*\n\nID VENDA: {a.get('sale_id', '')}\nPlanilha atualizada com sucesso."
    if not actions:
        return "ℹ️ Nenhuma alteração foi feita na planilha."
    parts = []
    for a in actions:
        label = a.get("label", "")
        amount = a.get("amount", 0)
        row = a.get("row", "")
        sheet = a.get("sheet", "")
        if amount and label:
            parts.append(f"• {label}: {_format_currency_pt(amount)} (linha {row})")
        else:
            parts.append(f"• Registrado em {sheet} linha {row}")
    return "✅ *Registrado com sucesso!*\n\n" + "\n".join(parts[:5])


def build_missing_fields_message(
    missing_fields: list[str],
    intent: str | None = None,
) -> str:
    """Resposta amigável quando faltam campos obrigatórios."""
    unique = list(dict.fromkeys(missing_fields))
    fields_txt = ", ".join(unique)

    intent_intros = {
        "sale": (
            "Ah, legal! Entendi que você fez uma venda. "
            "Me manda mais algumas informações pra gente registrar na planilha:"
        ),
        "mixed_update": (
            "Beleza! Quase lá — me manda mais alguns detalhes pra atualizar a planilha:"
        ),
        "material_update": (
            "Entendi! Só preciso de mais alguns dados sobre a matéria-prima:"
        ),
        "refund": "Ok, vi que é um estorno. Me ajuda com mais algumas informações:",
        "status_update": (
            "Beleza! Só faltam alguns dados pra eu atualizar o status na planilha:"
        ),
        "delivery_update": (
            "Entendi que é uma alteração de entrega. Me manda o que ainda falta:"
        ),
        "delivery_finalize": (
            "Beleza! Quase consigo registrar a entrega — me manda o que ainda falta:"
        ),
        "payment_update": (
            "Entendi o pagamento! Me manda o que ainda falta pra registrar:"
        ),
        "sale_delete": (
            "Entendi que você quer excluir uma venda. Me manda o que ainda falta:"
        ),
    }
    intro = intent_intros.get(
        intent or "",
        "Beleza! Me manda mais algumas informações pra gente atualizar a planilha:",
    )
    return (
        f"{intro}\n\n"
        f"*Faltam:* {fields_txt}\n\n"
        "Pode mandar tudo numa mensagem — quando souber, é só enviar."
    )


def build_preview(parse_result: ParseResult) -> str:
    """Monta texto de prévia do que será salvo na planilha (para o usuário confirmar ou editar)."""
    if parse_result.intent == "delivery_update":
        cmd = parse_result.command
        sale_id = getattr(cmd, "sale_id", None) or "-"
        due = getattr(cmd, "service_due_date", None)
        due_txt = due.strftime("%d/%m/%Y") if due is not None else "-"
        lines = ["📋 *Entendi assim: atualizar entrega*", ""]
        lines.append(f"🧾 ID VENDA: *{sale_id}*")
        lines.append(f"📅 Nova Data de Entrega: *{due_txt}*")
        lines.append("\nSe estiver correto, responda *SIM*. Para cancelar, responda *NÃO*.")
        return "\n".join(lines)
    if parse_result.intent == "delivery_finalize":
        cmd = parse_result.command
        sale_id = getattr(cmd, "sale_id", None) or "-"
        due = getattr(cmd, "service_due_date", None)
        due_txt = due.strftime("%d/%m/%Y") if due is not None else "-"
        lines = ["📋 *Entendi assim: confirmar entrega*", ""]
        lines.append(f"🧾 ID VENDA: *{sale_id}*")
        workbook_path = get_default_workbook()
        if workbook_path and Path(workbook_path).exists():
            try:
                service = SpreadsheetService(workbook_path)
                wb = service._open_workbook(data_only=True)
                try:
                    sales_name = service._resolve_sheet_name(wb, "TOTAL DE VENDAS DE 2026")
                    snapshot = service._sale_snapshot(wb[sales_name], str(sale_id))
                finally:
                    wb.close()
                if snapshot:
                    lines.append(f"👤 Cliente: *{snapshot.get('customer') or '-'}*")
                    lines.append(f"📦 Produto: *{snapshot.get('description') or '-'}*")
                    current_delivery = snapshot.get("delivery_date") or "-"
                    if current_delivery != "-":
                        lines.append(f"📅 Entrega atual na planilha: *{current_delivery}*")
            except Exception:
                pass
        lines.append(f"📅 Entrega será registrada em: *{due_txt}*")
        lines.append("_A célula de Data de Entrega ficará *verde* (serviço entregue) na planilha._")
        lines.append("\nSe estiver correto, responda *SIM*. Para cancelar, responda *NÃO*.")
        return "\n".join(lines)
    if parse_result.intent == "payment_update":
        sale_id = parse_result.detected_values.get("id_venda", "-")
        valor = parse_result.detected_values.get("valor_pago", "-")
        data = parse_result.detected_values.get("data", "-")
        lines = ["📋 *Entendi assim: registrar pagamento*", ""]
        lines.append(f"🧾 ID VENDA: *{sale_id}*")
        lines.append(f"💰 Valor pago: *{_format_currency_pt(float(str(valor).replace(',', '.') or 0)) if valor != '-' else '-'}*")
        lines.append(f"📅 Data: *{data}*")
        lines.append("\nSe estiver correto, responda *SIM*. Para corrigir, envie por texto. Para cancelar, responda *NÃO*.")
        return "\n".join(lines)

    # Prévia específica para atualização de status (ex.: "ID VENDA 004 pagou")
    if parse_result.intent == "status_update" and getattr(parse_result, "status_update_command", None) is not None:
        su = parse_result.status_update_command
        workbook_path = get_default_workbook()
        if not workbook_path or not Path(workbook_path).exists():
            return (
                "📋 *Entendi assim: atualizar status*\n\n"
                "Planilha nao encontrada para montar a previa. Configure WORKBOOK_PATH no .env."
            )
        service = SpreadsheetService(workbook_path)
        try:
            wb = service._open_workbook(data_only=True)
            try:
                sales_name = service._resolve_sheet_name(wb, "TOTAL DE VENDAS DE 2026")
                ws_sales = wb[sales_name]
            finally:
                wb.close()
        except Exception:
            # Fallback: preview simples só com o ID
            return (
                "📋 *Entendi assim: atualizar status*\n\n"
                f"🧾 ID VENDA: *{su.sale_id}*\n"
                f"🔁 Novo status: *{su.status.upper()}*\n\n"
                "Se estiver correto, responda *SIM*. Para cancelar, responda *NÃO*."
            )

        snapshot = service._sale_snapshot(ws_sales, su.sale_id)
        if not snapshot:
            return (
                "📋 *Entendi assim: atualizar status*\n\n"
                f"ID VENDA {su.sale_id} nao encontrado na aba de vendas.\n"
                "Responda *NÃO* para cancelar ou envie o ID correto."
            )

        # Buscar valores de pago/pendente diretamente da planilha
        sales_cols = service._sales_columns(ws_sales)
        row_vals = None
        col_sale_id = sales_cols["id venda"]
        for r in range(DATA_START_ROW, min(ws_sales.max_row + 1, service.MAX_DATA_ROW)):
            if str(ws_sales[f"{col_sale_id}{r}"].value or "").strip() == snapshot["sale_id"]:
                row_vals = r
                break
        total_pago = 0.0
        total_pendente = 0.0
        if row_vals is not None:
            total_pago = service._to_float(ws_sales[f"{sales_cols['total de vendas (pago)']}{row_vals}"].value)
            total_pendente = service._to_float(ws_sales[f"{sales_cols['valor (pendente)']}{row_vals}"].value)
        total_geral = total_pago + total_pendente

        lines: list[str] = ["📋 *Entendi assim: atualizar status*", ""]
        lines.append(f"🧾 ID VENDA: *{snapshot['sale_id']}*")
        lines.append(f"👤 Cliente: *{snapshot.get('customer') or '-'}*")
        lines.append(f"📦 Produto: *{snapshot.get('description') or '-'}*")
        lines.append(f"📅 Data da venda: *{snapshot.get('sale_date') or '-'}*")
        if total_geral > 0:
            lines.append(f"💰 Valor total: *{_format_currency_pt(total_geral)}*")
            lines.append(f"   Pago: {_format_currency_pt(total_pago)} | Pendente: {_format_currency_pt(total_pendente)}")
        else:
            lines.append("💰 Valor total: *-*")
        lines.append(f"🔎 Status atual: *{snapshot.get('payment_status') or '-'}*")
        delivery = snapshot.get("delivery_date") or "-"
        lines.append(f"📅 Data de entrega: *{delivery}*")
        if su.status.lower() == "pago" and delivery and delivery != "-":
            lines.append(
                "_Pagamento será marcado como pago. A entrega permanece amarela até você informar que foi entregue._"
            )
            lines.append(
                "_Depois, se já entregou, basta dizer: `entrega foi hoje` ou `para ele, entrega hoje`._"
            )
            lines.append(
                f"_No dia da entrega ({delivery}), lembretes automáticos às 6h e a cada 2h "
                f"(entrega e valor pendente, se houver)._"
            )
        lines.append(f"🔁 Novo status: *{su.status.upper()}*")
        lines.append("\nSe estiver correto, responda *SIM*. Para corrigir, envie por texto. Para cancelar, responda *NÃO*.")
        return "\n".join(lines)

    if parse_result.intent == "sale_delete" and getattr(parse_result, "delete_command", None) is not None:
        dc = parse_result.delete_command
        if not dc.sale_id and getattr(parse_result.command, "sale_id", None):
            dc.sale_id = str(parse_result.command.sale_id).strip()
        if not dc.sale_id:
            return (
                "📋 *Entendi assim: apagar registro da planilha*\n\n"
                "Não identifiquei qual venda apagar.\n"
                "Informe o *ID VENDA*, por exemplo: `id venda 003`.\n\n"
                "Para cancelar, responda *NÃO*."
            )
        sale_ctx = _load_sale_context_for_preview(dc.sale_id)
        if not sale_ctx:
            return (
                "📋 *Entendi assim: apagar registro da planilha*\n\n"
                f"ID VENDA *{dc.sale_id}* não encontrado na planilha.\n"
                "Confira o ID e tente de novo, ou responda *NÃO* para cancelar."
            )
        total_value = float(sale_ctx.get("total_value") or 0.0)
        total_pago = float(sale_ctx.get("total_pago") or 0.0)
        total_pendente = float(sale_ctx.get("total_pendente") or 0.0)
        lines = ["📋 *Entendi assim: apagar registro da planilha*", ""]
        lines.append(f"🧾 ID VENDA: *{dc.sale_id}*")
        lines.append(f"👤 Cliente: *{sale_ctx.get('customer') or '-'}*")
        lines.append(f"📦 Produto: *{sale_ctx.get('product') or '-'}*")
        lines.append(f"📅 Data da venda: *{sale_ctx.get('sale_date') or '-'}*")
        if total_value > 0:
            lines.append(f"💰 Valor total: *{_format_currency_pt(total_value)}*")
            lines.append(
                f"   Pago: {_format_currency_pt(total_pago)} | "
                f"Pendente: {_format_currency_pt(total_pendente)}"
            )
        else:
            lines.append("💰 Valor total: *-*")
        lines.append(f"🔎 Status atual: *{sale_ctx.get('payment_status') or '-'}*")
        if sale_ctx.get("delivery_date"):
            lines.append(f"📅 Data de entrega: *{sale_ctx['delivery_date']}*")
        lines.append("")
        lines.append(f"📝 Motivo: _{dc.reason}_")
        lines.append("")
        lines.append(
            "⚠️ *Este registro será removido da planilha* "
            "(venda, lembrete e material vinculado a este ID)."
        )
        lines.append(
            "\n*Quer mesmo apagar esses dados?* Responda *SIM* para confirmar ou *NÃO* para manter na planilha."
        )
        return "\n".join(lines)

    # Prévia padrão (venda/estorno/misto/atualização de material)
    cmd = parse_result.command
    sale_ctx = (
        _load_sale_context_for_preview(str(cmd.sale_id))
        if getattr(cmd, "sale_id", None)
        else None
    )
    customer = (cmd.customer or (sale_ctx or {}).get("customer") or "-").strip() or "-"
    product = (cmd.product_id or (sale_ctx or {}).get("product") or "-").strip() or "-"
    total_value = cmd.total_value or ((sale_ctx or {}).get("total_value") if sale_ctx else None)

    if parse_result.intent == "material_update":
        lines = ["📋 *Entendi assim: adicionar material*", ""]
    else:
        lines = ["📋 *Entendi assim:*", ""]
    lines.append(f"👤 Cliente: *{customer}*")
    lines.append(f"📦 Produto: *{product}*")
    if getattr(cmd, "sale_id", None):
        lines.append(f"🧾 ID VENDA: *{cmd.sale_id}*")
    elif cmd.material_cost:
        lines.append("🧾 ID VENDA: *-*")
    if getattr(cmd, "sale_date", None):
        if cmd.sale_date == date.today():
            lines.append(f"📅 Data da venda: *hoje ({cmd.sale_date.strftime('%d/%m/%Y')})*")
        else:
            lines.append(f"📅 Data da venda: *{cmd.sale_date.strftime('%d/%m/%Y')}*")
    elif sale_ctx and sale_ctx.get("sale_date"):
        lines.append(f"📅 Data da venda: *{sale_ctx['sale_date']}*")
    else:
        lines.append("📅 Data da venda: *-*")
    if total_value:
        lines.append(f"💰 Valor total: *{_format_currency_pt(float(total_value))}*")
        if sale_ctx and (sale_ctx.get("total_pago") or sale_ctx.get("total_pendente")):
            lines.append(
                f"   Pago: {_format_currency_pt(float(sale_ctx['total_pago']))} | "
                f"Pendente: {_format_currency_pt(float(sale_ctx['total_pendente']))}"
            )
    else:
        lines.append("💰 Valor total: *-*")
    if cmd.payments:
        for p in cmd.payments:
            due_txt = p.due_date.strftime("%d/%m/%Y") if getattr(p, "due_date", None) else "-"
            if (p.status or "").strip().lower() == "pago":
                lines.append(f"   {p.label}: *{_format_currency_pt(p.value)}* ({p.status}) - pago em {due_txt}")
            else:
                lines.append(f"   {p.label}: *{_format_currency_pt(p.value)}* ({p.status}) - vence em {due_txt}")

    # Data de entrega: prefere campo explícito; caso não exista, usa a data do "Saldo"/restante.
    delivery_date = getattr(cmd, "service_due_date", None)
    if delivery_date is None and cmd.payments:
        saldo_due = next((p.due_date for p in cmd.payments if str(p.label).strip().lower() == "saldo" and getattr(p, "due_date", None)), None)
        delivery_date = saldo_due
    if delivery_date is not None:
        lines.append(f"🚚 Data de Entrega: *{delivery_date.strftime('%d/%m/%Y')}*")
    # Mostrar custos de material e fixo quando presentes (igual ao app)
    if cmd.material_cost:
        lines.append(f"🧱 Material estimado: *{_format_currency_pt(cmd.material_cost)}*")
    if cmd.fixed_cost:
        lines.append(f"🏷️ Gasto fixo estimado: *{_format_currency_pt(cmd.fixed_cost)}*")
    if cmd.warnings:
        lines.append("")
        for w in cmd.warnings:
            lines.append(f"⚠️ {w}")
    lines.append("")
    lines.append(
        "Se estiver correto, responda *SIM* ou *OK* que eu salvo na planilha.\n"
        "Para corrigir, envie um ou mais campos na mesma mensagem, "
        "ex.: `Cliente: Adriel, Produto: Banner, Valor total: 3000, Entrada: 1500, Saldo: 1500`."
    )
    return "\n".join(lines)


def apply_parse_result(
    parse_result: ParseResult,
    origin: str = "telegram",
    original_text: str = "",
    *,
    chat_id: str | None = None,
) -> str:
    """Aplica um ParseResult já validado na planilha e retorna a mensagem de resposta."""
    workbook_path = get_default_workbook()
    if not workbook_path or not Path(workbook_path).exists():
        return "Planilha nao encontrada. Configure WORKBOOK_PATH no .env."
    service = SpreadsheetService(workbook_path)
    actions: list = []
    cmd = parse_result.command
    if parse_result.intent == "delivery_finalize":
        if not getattr(cmd, "sale_id", None):
            return "Faltou o *ID VENDA* para confirmar a entrega. Ex.: `id venda 002 foi entregue`."
        sale_id = str(cmd.sale_id).strip()
        delivery_date = getattr(cmd, "service_due_date", None) or date.today()
        service.update_sale_delivery_date(sale_id, delivery_date)
        ok = service.finalize_service(sale_id)
        if not ok:
            return "Não achei essa venda na planilha para confirmar a entrega."
        return format_reply("delivery_finalize", [{"sale_id": sale_id, "sheet": "vendas"}], error=None)
    if parse_result.intent == "delivery_update":
        if not getattr(cmd, "sale_id", None):
            return "Faltou o *ID VENDA* para atualizar a entrega. Ex.: `id venda 003 entrega 10/04`."
        if getattr(cmd, "service_due_date", None) is None:
            return "Faltou a *Data de Entrega*. Ex.: `entrega 10/04`."
        sale_id = str(cmd.sale_id).strip()
        service.update_sale_delivery_date(sale_id, cmd.service_due_date)
        if _is_service_delivery_finalized(original_text) and not _is_delivery_explicitly_pending(original_text):
            service.finalize_service(sale_id)
            return format_reply("delivery_finalize", [{"sale_id": sale_id, "sheet": "vendas"}], error=None)
        return format_reply("delivery_update", [{"sale_id": sale_id, "sheet": "vendas"}], error=None)
    if parse_result.intent == "payment_update":
        sale_id = (parse_result.detected_values.get("id_venda") or "").strip()
        val_txt = (parse_result.detected_values.get("valor_pago") or "").strip()
        if not sale_id or sale_id == "-":
            return "Faltou o *ID VENDA* para registrar pagamento. Ex.: `id venda 005 recebeu 2500 hoje`."
        try:
            amount = float(val_txt.replace(",", "."))
        except Exception:
            amount = 0.0
        if amount <= 0:
            return "Faltou o *valor pago*. Ex.: `id venda 005 recebeu 2500 hoje`."
        # A data foi formatada em DD/MM/YYYY em detected_values; usamos hoje se falhar.
        pay_date = date.today()
        action = service.apply_partial_payment(
            sale_id,
            amount=amount,
            ref_date=pay_date,
            original_text=original_text,
            origin=origin,
        )
        if not action:
            return "Não consegui registrar esse pagamento (verifique se o ID VENDA existe e se há pendência)."
        return format_reply("payment_update", [asdict(action)], error=None)
    if parse_result.intent == "mixed_update" and parse_result.status_update_command is not None:
        status_action = service.update_sale_status(
            parse_result.status_update_command, original_text=original_text, origin=origin
        )
        actions.append(status_action)
        # Se o comando também trouxe prazo de entrega, grava na coluna Data de Entrega.
        if cmd.service_due_date is not None:
            service.update_sale_delivery_date(parse_result.status_update_command.sale_id, cmd.service_due_date)
        material_actions = service.apply_command(
            cmd=parse_result.command, original_text=original_text, origin=origin
        )
        actions.extend(material_actions)
    elif parse_result.intent == "status_update" and parse_result.status_update_command is not None:
        action = service.update_sale_status(
            parse_result.status_update_command, original_text=original_text, origin=origin
        )
        actions = [action]
        sale_id = parse_result.status_update_command.sale_id
        delivery_still_pending = _is_delivery_explicitly_pending(original_text)
        if cmd.service_due_date is not None and not delivery_still_pending:
            service.update_sale_delivery_date(sale_id, cmd.service_due_date)
        elif _is_service_delivery_finalized(original_text) and not delivery_still_pending:
            delivery_date = _parse_pt_date(original_text, date.today(), full_text=original_text) or date.today()
            service.update_sale_delivery_date(sale_id, delivery_date)
            service.finalize_service(sale_id)
            service.refresh_delivery_reminder(sale_id, chat_id=chat_id or "", mark_delivered=True)
        else:
            service.refresh_delivery_reminder(sale_id, chat_id=chat_id or "", mark_delivered=False)
    elif parse_result.intent == "refund" and parse_result.refund_command is not None:
        action = service.apply_refund(
            parse_result.refund_command, original_text=original_text, origin=origin
        )
        actions = [action]
    elif parse_result.intent == "sale_delete" and parse_result.delete_command is not None:
        action = service.delete_sale(
            parse_result.delete_command, original_text=original_text, origin=origin
        )
        actions = [action]
    else:
        actions = service.apply_command(
            cmd=parse_result.command, original_text=original_text, origin=origin, chat_id=chat_id
        )
    actions_dict = [asdict(a) for a in actions]
    return format_reply(parse_result.intent, actions_dict, error=None)


def process_command(command_text: str, origin: str = "telegram") -> str:
    """
    Processa um comando de texto: resumo da planilha ou venda/estorno/status.
    Retorna a mensagem de resposta a ser enviada ao usuário.
    Levanta exceção em caso de erro não tratado.
    """
    text = (command_text or "").strip()
    if not text:
        return "Mensagem vazia. Envie texto (ex.: vendi placa para Ana por 3000) ou digite Resumo."

    cmd_lower = text.lower()

    # Comando de status rápido do tipo:
    # "marca na planilha que o cliente ID 003 e 002 pagou"
    if (
        "pagou" in cmd_lower
        and ("marca" in cmd_lower or "atualiza" in cmd_lower)
        and ("id" in cmd_lower or "cliente" in cmd_lower)
    ):
        import re
        # Se houver um valor junto de "pagou" (ex.: "pagou 2500"),
        # isso é pagamento parcial e deve seguir o parser normal (payment_update),
        # não o atalho de "marcar como pago" total.
        if not re.search(r"\bpagou\b\s*(?:r\$\s*)?\d{2,}", cmd_lower):
            workbook_path = get_default_workbook()
            if not workbook_path or not Path(workbook_path).exists():
                return "Planilha nao encontrada. Configure WORKBOOK_PATH no .env."
            service = SpreadsheetService(workbook_path)

            ids: list[str] = []
            for m in re.findall(r"\d{1,6}", text):
                sid = m.zfill(3) if len(m) <= 3 else m
                if sid not in ids:
                    ids.append(sid)
            if not ids:
                return "Nao entendi quais IDs devem ser marcados como pagos. Diga, por exemplo: ID VENDA 001 pagou tudo."

            actions = []
            today = date.today()
            for sid in ids:
                su = StatusUpdateCommand(sale_id=sid, status="pago", ref_date=today)
                try:
                    action = service.update_sale_status(
                        su,
                        original_text=text,
                        origin=origin,
                    )
                    actions.append(asdict(action))
                except Exception:
                    continue
            if not actions:
                return "Nao consegui encontrar esses IDs na planilha para atualizar como pagos."
            return format_reply("status_update", actions, error=None)
    cmd_strip = cmd_lower.strip()
    # Resumo (visão geral)
    if any(cmd_strip.startswith(kw) for kw in SUMMARY_KEYWORDS):
        workbook_path = get_default_workbook()
        if not workbook_path or not Path(workbook_path).exists():
            return "Planilha nao encontrada. Configure WORKBOOK_PATH no .env ou coloque a planilha na pasta do app."
        try:
            service = SpreadsheetService(workbook_path)
            return service.get_planilha_summary()
        except Exception as e:
            return f"Erro ao gerar resumo: {e}"

    # Status: resumo da aba "Lucro Mensal e Anual" (usa get_planilha_summary)
    if any(cmd_strip.startswith(kw) for kw in STATUS_KEYWORDS):
        workbook_path = get_default_workbook()
        if not workbook_path or not Path(workbook_path).exists():
            return "Planilha nao encontrada. Configure WORKBOOK_PATH no .env."
        try:
            service = SpreadsheetService(workbook_path)
            return service.get_planilha_summary()
        except Exception as e:
            return f"Erro ao ler status: {e}"

    # Prévia (pendências e entregas)
    if any(cmd_strip.startswith(kw) for kw in PREVIEW_KEYWORDS):
        workbook_path = get_default_workbook()
        if not workbook_path or not Path(workbook_path).exists():
            return "Planilha nao encontrada. Configure WORKBOOK_PATH no .env."
        try:
            service = SpreadsheetService(workbook_path)
            return service.get_sales_preview()
        except Exception as e:
            return f"Erro ao gerar prévia: {e}"

    # Parse e atualização
    parse_result = parse_message(text, reference_date=date.today())
    cmd = parse_result.command

    if parse_result.missing_fields:
        return build_missing_fields_message(
            parse_result.missing_fields,
            parse_result.intent,
        )

    workbook_path = get_default_workbook()
    if not workbook_path or not Path(workbook_path).exists():
        return "Planilha nao encontrada. Configure WORKBOOK_PATH no .env."

    service = SpreadsheetService(workbook_path)
    actions: list = []

    if parse_result.intent == "mixed_update" and parse_result.status_update_command is not None:
        status_action = service.update_sale_status(
            parse_result.status_update_command,
            original_text=text,
            origin=origin,
        )
        actions.append(status_action)
        material_actions = service.apply_command(cmd=cmd, original_text=text, origin=origin)
        actions.extend(material_actions)
    elif parse_result.intent == "status_update" and parse_result.status_update_command is not None:
        action = service.update_sale_status(
            parse_result.status_update_command,
            original_text=text,
            origin=origin,
        )
        actions = [action]
    elif parse_result.intent == "refund" and parse_result.refund_command is not None:
        action = service.apply_refund(
            parse_result.refund_command,
            original_text=text,
            origin=origin,
        )
        actions = [action]
    elif parse_result.intent == "sale_delete" and parse_result.delete_command is not None:
        action = service.delete_sale(
            parse_result.delete_command,
            original_text=text,
            origin=origin,
        )
        actions = [action]
    else:
        actions = service.apply_command(cmd=cmd, original_text=text, origin=origin)

    actions_dict = [asdict(a) for a in actions]
    return format_reply(parse_result.intent, actions_dict, error=None)
