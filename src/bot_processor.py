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
from .parser import parse_message, ParseResult
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
        return f"Erro: {error}"
    if intent == "refund" and actions:
        a = actions[0]
        return f"Estorno registrado. Planilha: {a.get('sheet', '')} linha {a.get('row', '')}."
    if intent == "status_update" and actions:
        a = actions[0]
        return f"Status atualizado. ID VENDA {a.get('sale_id', '')} na planilha."
    if not actions:
        return "Nenhuma alteracao na planilha."
    parts = []
    for a in actions:
        label = a.get("label", "")
        amount = a.get("amount", 0)
        row = a.get("row", "")
        sheet = a.get("sheet", "")
        if amount and label:
            parts.append(f"{label}: R$ {amount:,.2f} (linha {row})")
        else:
            parts.append(f"Registrado em {sheet} linha {row}")
    return "Planilha atualizada. " + (" | ".join(parts[:3]) if parts else "OK")


def build_preview(parse_result: ParseResult) -> str:
    """Monta texto de prévia do que será salvo na planilha (para o usuário confirmar ou editar)."""
    # Prévia específica para atualização de status (ex.: "ID VENDA 004 pagou")
    if parse_result.intent == "status_update" and getattr(parse_result, "status_update_command", None) is not None:
        su = parse_result.status_update_command
        workbook_path = get_default_workbook()
        if not workbook_path or not Path(workbook_path).exists():
            return (
                "📋 *Prévia – atualização de status*\n\n"
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
                "📋 *Prévia – atualização de status*\n\n"
                f"ID VENDA: {su.sale_id}\n"
                f"Novo status de valor: {su.status.upper()}.\n\n"
                "Responda *SIM* para atualizar na planilha ou *NÃO* para cancelar."
            )

        snapshot = service._sale_snapshot(ws_sales, su.sale_id)
        if not snapshot:
            return (
                "📋 *Prévia – atualização de status*\n\n"
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

        lines: list[str] = ["📋 *Prévia – atualizar status da venda:*", ""]
        lines.append(f"• ID VENDA: {snapshot['sale_id']}")
        lines.append(f"• Cliente: {snapshot.get('customer') or '-'}")
        lines.append(f"• Produto: {snapshot.get('description') or '-'}")
        lines.append(f"• Data da venda: {snapshot.get('sale_date') or '-'}")
        if total_geral > 0:
            lines.append(f"• Valor total: R$ {total_geral:,.2f}")
            lines.append(f"  → Pago: R$ {total_pago:,.2f} | Pendente: R$ {total_pendente:,.2f}")
        else:
            lines.append("• Valor total: -")
        lines.append(f"• Status atual: {snapshot.get('payment_status') or '-'}")
        lines.append(f"• Novo status de valor: {su.status.upper()}.")
        lines.append("\nResponda *SIM* para salvar na planilha ou *NÃO* para cancelar.\n")
        lines.append("Dica: para corrigir apenas um campo, pode dizer, por exemplo, 'Produto: Fachada nova'.")
        return "\n".join(lines)

    # Prévia padrão (venda/estorno/misto)
    cmd = parse_result.command
    lines = ["📋 *Prévia – confira antes de salvar:*", ""]
    lines.append(f"• Cliente: {cmd.customer or '-'}")
    lines.append(f"• Produto: {cmd.product_id or '-'}")
    if getattr(cmd, "sale_id", None):
        lines.append(f"• ID VENDA: {cmd.sale_id}")
    elif cmd.material_cost:
        lines.append("• ID VENDA: -")
    if getattr(cmd, "sale_date", None):
        lines.append(f"• Data da venda: {cmd.sale_date.strftime('%d/%m/%Y')}")
    else:
        lines.append("• Data da venda: -")
    lines.append(f"• Valor total: R$ {cmd.total_value:,.2f}" if cmd.total_value else "• Valor total: -")
    if cmd.payments:
        for p in cmd.payments:
            due_txt = p.due_date.strftime("%d/%m/%Y") if getattr(p, "due_date", None) else "-"
            lines.append(f"  → {p.label}: R$ {p.value:,.2f} ({p.status}) - vence em {due_txt}")

    # Data de entrega: prefere campo explícito; caso não exista, usa a data do "Saldo"/restante.
    delivery_date = getattr(cmd, "service_due_date", None)
    if delivery_date is None and cmd.payments:
        saldo_due = next((p.due_date for p in cmd.payments if str(p.label).strip().lower() == "saldo" and getattr(p, "due_date", None)), None)
        delivery_date = saldo_due
    if delivery_date is not None:
        lines.append(f"• Data de Entrega: {delivery_date.strftime('%d/%m/%Y')}")
    # Mostrar custos de material e fixo quando presentes (igual ao app)
    if cmd.material_cost:
        lines.append(f"• Material estimado: R$ {cmd.material_cost:,.2f}.")
    if cmd.fixed_cost:
        lines.append(f"• Gasto fixo estimado: R$ {cmd.fixed_cost:,.2f}.")
    if cmd.warnings:
        lines.append("")
        for w in cmd.warnings:
            lines.append(f"⚠️ {w}")
    lines.append("")
    lines.append(
        "Responda *SIM* para salvar na planilha ou *NÃO* para cancelar. "
        "Para corrigir apenas um campo, envie por exemplo 'Cliente: Fulano', 'Produto: Fachada nova' ou 'Valor: 1500'."
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
        if cmd.service_due_date is not None:
            service.update_sale_delivery_date(parse_result.status_update_command.sale_id, cmd.service_due_date)
    elif parse_result.intent == "refund" and parse_result.refund_command is not None:
        action = service.apply_refund(
            parse_result.refund_command, original_text=original_text, origin=origin
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
        workbook_path = get_default_workbook()
        if not workbook_path or not Path(workbook_path).exists():
            return "Planilha nao encontrada. Configure WORKBOOK_PATH no .env."
        service = SpreadsheetService(workbook_path)
        import re

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
        return "Faltam dados: " + ", ".join(parse_result.missing_fields) + ". Revise e tente de novo."

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
    else:
        actions = service.apply_command(cmd=cmd, original_text=text, origin=origin)

    actions_dict = [asdict(a) for a in actions]
    return format_reply(parse_result.intent, actions_dict, error=None)
