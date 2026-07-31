# -*- coding: utf-8 -*-
"""Relatório da planilha em PDF com gráfico de totais."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from .telegram_images import format_brl

_DEJAVU_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
)
_DEJAVU_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
)


def _first_existing_path(candidates: tuple[str, ...]) -> str | None:
    for path in candidates:
        if Path(path).is_file():
            return path
    return None


def _configure_pdf_fonts(pdf) -> str:
    regular = _first_existing_path(_DEJAVU_REGULAR)
    bold = _first_existing_path(_DEJAVU_BOLD)
    if regular and bold:
        pdf.add_font("App", "", regular)
        pdf.add_font("App", "B", bold)
        return "App"
    return "Helvetica"


def _category_rows(stats: dict[str, float | int | str]) -> list[tuple[str, float, str]]:
    return [
        ("Vendas (total)", float(stats.get("total_vendas") or 0), "#3B82F6"),
        ("Entradas recebidas", float(stats.get("total_pago") or 0), "#10B981"),
        ("A receber", float(stats.get("total_pendente") or 0), "#F59E0B"),
        ("Matéria-prima", float(stats.get("total_mat") or 0), "#8B5CF6"),
        ("Gastos fixos", float(stats.get("total_fixos") or 0), "#F97316"),
        ("Lucro", float(stats.get("lucro") or 0), "#059669"),
    ]


def _render_chart_png(
    rows: list[tuple[str, float, str]],
    *,
    title: str,
    width: int = 900,
    height: int = 420,
) -> str | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    labels = [r[0] for r in rows]
    values = [r[1] for r in rows]
    colors = [r[2] for r in rows]

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#FFFFFF")
    bars = ax.bar(labels, values, color=colors, edgecolor="white", linewidth=0.8)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.set_ylabel("R$")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.xticks(rotation=28, ha="right")
    for bar, value in zip(bars, values):
        if value > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                format_brl(value).replace("R$ ", ""),
                ha="center",
                va="bottom",
                fontsize=8,
            )
    fig.tight_layout()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.close()
    fig.savefig(tmp.name, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return tmp.name


def build_planilha_report_pdf(
    stats: dict[str, float | int | str],
    *,
    user_name: str = "",
    generated_at: date | None = None,
) -> str | None:
    """Gera PDF temporário. Retorna caminho ou None se dependências faltarem."""
    try:
        from fpdf import FPDF
    except ImportError:
        return None

    month_label = str(stats.get("mes_label") or "Mês atual")
    rows = _category_rows(stats)
    chart_path = _render_chart_png(
        rows,
        title=f"Situação da planilha — {month_label}",
    )
    when = (generated_at or date.today()).strftime("%d/%m/%Y")
    full_name = (user_name or "").strip()
    name = full_name.split()[0] if full_name else "Usuário"

    pdf = FPDF()
    font = _configure_pdf_fonts(pdf)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font(font, "B", 18)
    pdf.cell(0, 12, f"Relatório da planilha — {month_label}", ln=True)
    pdf.set_font(font, size=11)
    pdf.cell(0, 8, f"Gerado em {when} para {full_name or name}", ln=True)
    pdf.ln(4)

    pdf.set_font(font, "B", 12)
    pdf.cell(0, 8, "Resumo geral", ln=True)
    pdf.set_font(font, size=11)
    pdf.cell(0, 7, f"Total de vendas: {format_brl(float(stats.get('total_vendas') or 0))}", ln=True)
    pdf.cell(0, 7, f"Entradas recebidas: {format_brl(float(stats.get('total_pago') or 0))}", ln=True)
    pdf.cell(0, 7, f"A receber (pendente): {format_brl(float(stats.get('total_pendente') or 0))}", ln=True)
    pdf.cell(0, 7, f"Compras matéria-prima: {format_brl(float(stats.get('total_mat') or 0))}", ln=True)
    pdf.cell(0, 7, f"Gastos fixos: {format_brl(float(stats.get('total_fixos') or 0))}", ln=True)
    pdf.cell(0, 7, f"Lucro: {format_brl(float(stats.get('lucro') or 0))}", ln=True)
    pdf.ln(3)

    mes_total = float(stats.get("mes_total") or 0)
    if mes_total > 0:
        pdf.set_font(font, "B", 12)
        pdf.cell(0, 8, f"Vendas do mês ({month_label})", ln=True)
        pdf.set_font(font, size=11)
        pdf.cell(
            0,
            7,
            f"Vendas no mês: {int(stats.get('mes_vendas') or 0)} | "
            f"Total: {format_brl(mes_total)} | "
            f"Pago: {format_brl(float(stats.get('mes_pago') or 0))} | "
            f"Pendente: {format_brl(float(stats.get('mes_pendente') or 0))}",
            ln=True,
        )
        pdf.ln(3)

    if chart_path and Path(chart_path).is_file():
        pdf.ln(4)
        pdf.set_font(font, "B", 12)
        pdf.cell(0, 8, "Gráfico por categoria", ln=True)
        pdf.ln(2)
        pdf.image(chart_path, w=180)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    pdf.output(tmp.name)

    if chart_path:
        try:
            Path(chart_path).unlink(missing_ok=True)
        except Exception:
            pass
    return tmp.name


def collect_planilha_stats() -> dict[str, Any] | None:
    from .spreadsheet_factory import get_spreadsheet_service, spreadsheet_is_ready

    if not spreadsheet_is_ready():
        return None
    service = get_spreadsheet_service()
    return service.get_summary_stats()
