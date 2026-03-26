# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import hashlib
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any
import html
import os

import streamlit as st

from src.excel_store import SHEET_FIXED, SHEET_MATERIAL, SHEET_SALES, SpreadsheetService
from src.models import FinancialCommand, MaterialAllocation, Payment, RefundCommand, StatusUpdateCommand
from src.parser import parse_message
from src.transcription import TranscriptionError, transcribe_audio
from src.workbook_paths import default_workbook_path, resolve_workbook_path as _resolve_workbook_path


def _load_dotenv() -> None:
    for base in (Path(__file__).resolve().parent, Path.cwd()):
        env_file = base / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip()
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    # Se o arquivo tiver chaves repetidas, queremos que a última
                    # prevaleça (evita problema de configurações ficarem vazias).
                    os.environ[k] = v
            break


_load_dotenv()


def _default_workbook_path() -> str:
    env_path = os.getenv("WORKBOOK_PATH", "").strip()
    if env_path:
        try:
            return str(_resolve_workbook_path(env_path))
        except Exception:
            pass

    # Procura na pasta do exe (ex.: dist_novo\AssistentePlanilha) e na pasta pai (dist_novo)
    roots = [Path.cwd()]
    if Path.cwd().parent.exists():
        roots.append(Path.cwd().parent)
    return default_workbook_path(roots)


def _init_state() -> None:
    defaults = {
        "raw_text": "",
        "source_kind": "texto",
        "assistant_reply": "",
        "customer": "",
        "product_id": "",
        "description": "",
        "sale_id": "",
        "sale_date": date.today(),
        "service_due_date": date.today(),
        "total_value": 0.0,
        "entry_value": 0.0,
        "entry_date": date.today(),
        "balance_value": 0.0,
        "balance_date": date.today(),
        "material_cost": 0.0,
        "material_date": date.today(),
        "material_supplier": "",
        "fixed_cost": 0.0,
        "fixed_cost_label": "Gasto fixo via audio",
        "fixed_cost_date": date.today(),
        "warnings": [],
        "missing_fields": [],
        "parsed_ready": False,
        "intent": "sale",
        "refund_command": None,
        "status_update_command": None,
        "last_recording_signature": "",
        "transcribed_text_draft": "",
        "audio_transcription_error": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _format_currency(value: float) -> str:
    txt = f"{float(value):,.2f}"
    txt = txt.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {txt}"


def _calc_net_value(cmd: FinancialCommand) -> float:
    return round(cmd.total_value - (cmd.material_cost or 0.0) - (cmd.fixed_cost or 0.0), 2)


def _hold_spinner(min_seconds: float = 0.45) -> None:
    time.sleep(min_seconds)


def _assistant_message(cmd: FinancialCommand, missing_fields: list[str]) -> str:
    parts = []
    if cmd.sale_id:
        parts.append(f"ID venda: {cmd.sale_id}.")
    if cmd.customer:
        parts.append(f"Cliente: {cmd.customer}.")
    if cmd.product_id:
        parts.append(f"Produto: {cmd.product_id}.")
    parts.append(f"Venda total: {_format_currency(cmd.total_value)}.")
    entry = next((p for p in cmd.payments if p.label.lower() == "entrada"), None)
    balance = next((p for p in cmd.payments if p.label.lower() == "saldo"), None)
    if entry:
        prefix = "Pendente: " if entry.status == "pendente" else ""
        parts.append(f"{prefix}Entrada: {_format_currency(entry.value)} em {entry.due_date.strftime('%d/%m/%Y')}.")
    if balance:
        prefix = "Pendente: " if balance.status == "pendente" else ""
        parts.append(f"{prefix}Saldo: {_format_currency(balance.value)} em {balance.due_date.strftime('%d/%m/%Y')}.")
    if cmd.material_cost:
        parts.append(f"Material estimado: {_format_currency(cmd.material_cost)}.")
    if cmd.fixed_cost:
        parts.append(f"Gasto fixo estimado: {_format_currency(cmd.fixed_cost)}.")
    parts.append(f"Liquido previsto desta venda: {_format_currency(_calc_net_value(cmd))}.")

    if missing_fields:
        parts.append("Campos para revisar: " + ", ".join(dict.fromkeys(missing_fields)) + ".")
    return " ".join(parts)


def _fill_state_from_command(
    cmd: FinancialCommand,
    missing_fields: list[str],
    raw_text: str,
    source_kind: str,
    intent: str = "sale",
    refund_command: Any = None,
    status_update_command: StatusUpdateCommand | None = None,
) -> None:
    customer_value = cmd.customer
    if (
        not customer_value
        and cmd.sale_id
        and (cmd.material_allocations or float(cmd.total_value or 0.0) <= 0)
    ):
        customer_value = cmd.sale_id
    st.session_state.raw_text = raw_text
    st.session_state.source_kind = source_kind
    st.session_state.customer = customer_value
    st.session_state.product_id = cmd.product_id or ""
    st.session_state.description = cmd.description
    st.session_state.sale_id = cmd.sale_id or ""
    st.session_state.sale_date = cmd.sale_date
    st.session_state.total_value = float(cmd.total_value or 0)

    entry = next((p for p in cmd.payments if p.label.lower() == "entrada"), None)
    balance = next((p for p in cmd.payments if p.label.lower() == "saldo"), None)
    st.session_state.entry_value = float(entry.value if entry else 0.0)
    st.session_state.entry_date = entry.due_date if entry else cmd.sale_date
    st.session_state.entry_status = entry.status if entry else "pago"
    st.session_state.balance_value = float(balance.value if balance else 0.0)
    st.session_state.balance_date = balance.due_date if balance else cmd.sale_date
    st.session_state.balance_status = balance.status if balance else "pago"
    # Data de entrega segue o mesmo padrão do Telegram:
    # 1) campo explícito do parser; 2) fallback para vencimento do saldo.
    if cmd.service_due_date is not None:
        st.session_state.service_due_date = cmd.service_due_date
    elif balance is not None and getattr(balance, "due_date", None):
        st.session_state.service_due_date = balance.due_date
    else:
        st.session_state.service_due_date = cmd.sale_date

    st.session_state.material_cost = float(cmd.material_cost or 0.0)
    st.session_state.material_date = cmd.material_date or cmd.sale_date
    st.session_state.material_supplier = cmd.material_supplier or ""
    st.session_state.material_allocations = [
        {
            "sale_id": allocation.sale_id,
            "amount": float(allocation.amount),
            "material_date": allocation.material_date,
            "description": allocation.description or "",
        }
        for allocation in cmd.material_allocations
    ]
    st.session_state.fixed_cost = float(cmd.fixed_cost or 0.0)
    st.session_state.fixed_cost_label = cmd.fixed_cost_label or "Gasto fixo via audio"
    st.session_state.fixed_cost_date = cmd.fixed_cost_date or cmd.sale_date
    st.session_state.warnings = list(cmd.warnings)
    st.session_state.missing_fields = list(dict.fromkeys(missing_fields))
    st.session_state.assistant_reply = _assistant_message(cmd, missing_fields)
    st.session_state.parsed_ready = True
    st.session_state.intent = intent
    st.session_state.refund_command = refund_command
    st.session_state.status_update_command = status_update_command
    if status_update_command is not None:
        st.session_state.manual_sale_id = status_update_command.sale_id
        st.session_state.manual_sale_status = status_update_command.status
        st.session_state.status_sale_id = status_update_command.sale_id
        st.session_state.status_value_update = status_update_command.status


def _build_command_from_ui() -> FinancialCommand:
    total = float(st.session_state.total_value or 0.0)
    entry_value = float(st.session_state.entry_value or 0.0)
    balance_value = float(st.session_state.balance_value or 0.0)
    sale_date = st.session_state.sale_date

    if total > 0 and entry_value > 0 and balance_value == 0:
        balance_value = round(max(total - entry_value, 0), 2)
    if total > 0 and balance_value > 0 and entry_value == 0:
        entry_value = round(max(total - balance_value, 0), 2)
    if total > 0 and entry_value == 0 and balance_value == 0:
        entry_value = total

    payments: list[Payment] = []
    if entry_value > 0:
        entry_status = st.session_state.get("entry_status", "pago")
        if st.session_state.entry_date > sale_date:
            entry_status = "pendente"
        payments.append(
            Payment(
                label="Entrada",
                value=entry_value,
                due_date=st.session_state.entry_date,
                status=entry_status,
            )
        )
    if balance_value > 0:
        balance_status = "pendente"
        if st.session_state.balance_date > sale_date:
            balance_status = "pendente"
        elif st.session_state.get("balance_status") == "pendente":
            balance_status = "pendente"
        payments.append(
            Payment(
                label="Saldo",
                value=balance_value,
                due_date=st.session_state.balance_date,
                status=balance_status,
            )
        )

    service_due_date = st.session_state.get("service_due_date")
    if service_due_date is None and balance_value > 0:
        service_due_date = st.session_state.balance_date

    return FinancialCommand(
        customer=st.session_state.customer.strip(),
        description=st.session_state.description.strip()
        or st.session_state.product_id.strip()
        or f"Servico para {st.session_state.customer.strip()}",
        sale_date=sale_date,
        total_value=total,
        payments=payments,
        product_id=st.session_state.product_id.strip() or None,
        sale_id=st.session_state.sale_id.strip() or None,
        material_cost=float(st.session_state.material_cost or 0.0) or None,
        material_date=st.session_state.material_date if st.session_state.material_cost > 0 else None,
        material_supplier=st.session_state.material_supplier.strip() or None,
        material_allocations=[
            MaterialAllocation(
                sale_id=str(item.get("sale_id", "")).strip(),
                amount=float(item.get("amount", 0.0) or 0.0),
                material_date=item.get("material_date") or sale_date,
                description=str(item.get("description", "")).strip() or None,
            )
            for item in st.session_state.get("material_allocations", [])
            if str(item.get("sale_id", "")).strip() and float(item.get("amount", 0.0) or 0.0) > 0
        ],
        fixed_cost=float(st.session_state.fixed_cost or 0.0) or None,
        fixed_cost_label=st.session_state.fixed_cost_label.strip() or None,
        fixed_cost_date=st.session_state.fixed_cost_date if st.session_state.fixed_cost > 0 else None,
        service_due_date=service_due_date,
    )


def _uploaded_to_bytes(uploaded: Any) -> bytes:
    if uploaded is None:
        return b""
    if hasattr(uploaded, "getvalue"):
        return uploaded.getvalue()
    if isinstance(uploaded, (bytes, bytearray)):
        return bytes(uploaded)
    return b""


def _name_from_upload(uploaded: Any, fallback: str = "gravacao.wav") -> str:
    name = getattr(uploaded, "name", "")
    if isinstance(name, str) and name.strip():
        return name
    return fallback


def _transcribe_payload_to_text(audio_payload: Any, model_size: str) -> str:
    audio_bytes = _uploaded_to_bytes(audio_payload)
    if not audio_bytes:
        raise ValueError("Grave ou envie um arquivo de audio antes de transcrever.")
    name = _name_from_upload(audio_payload)
    suffix = Path(name).suffix or ".wav"
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            temp_path = tmp.name
        return transcribe_audio(temp_path, model_size=model_size)
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass


def _resolve_logo_path() -> Path | None:
    explicit_logo = os.getenv("APP_LOGO_PATH", "").strip()
    if explicit_logo and Path(explicit_logo).exists():
        return Path(explicit_logo)

    asset_dirs = []
    for candidate_dir in [Path.cwd() / "assets", Path(__file__).resolve().parent / "assets"]:
        if candidate_dir.exists() and candidate_dir not in asset_dirs:
            asset_dirs.append(candidate_dir)

    name_candidates = [
        "logo_p26.png",
        "logo_p26.jpg",
        "logo_p26.jpeg",
        "logo_p26.webp",
        "logo_p26.bmp",
        "p26_logo.png",
        "p26_logo.jpg",
        "logo.png",
        "logo.jpg",
        "logo.jpeg",
        "logo.webp",
        "logo.bmp",
    ]
    for asset_dir in asset_dirs:
        for name in name_candidates:
            path = asset_dir / name
            if path.exists():
                return path

        for path in sorted(asset_dir.glob("*")):
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                continue
            normalized = path.name.lower()
            if ("logo" in normalized) or ("p26" in normalized):
                return path

        # Fallback: usa a primeira imagem encontrada em assets (exceto arquivos de icone).
        for path in sorted(asset_dir.glob("*")):
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                continue
            normalized = path.name.lower()
            if "icon" in normalized:
                continue
            return path
    return None


def _render_logo(path: Path, width_px: int = 180) -> None:
    suffix = path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime = mime_map.get(suffix)
    if not mime:
        return
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    st.markdown(
        (
            f'<img src="data:{mime};base64,{data}" '
            f'style="width:{width_px}px;max-width:100%;height:auto;display:block;margin:0 auto;" />'
        ),
        unsafe_allow_html=True,
    )

def main() -> None:
    logo_path = _resolve_logo_path()
    st.set_page_config(
        page_title="Assistente de Planilha por Audio",
        layout="wide",
        page_icon=str(logo_path) if logo_path else None,
    )
    _init_state()
    
    st.markdown(
        """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=Space+Grotesk:wght@500;700&display=swap');
    :root{
        --bg:#020617;
        --bg-elevated:#020617;
        --ink:#e5e7eb;
        --soft:#9ca3af;
        --accent:#22c55e;
        --accent-soft:rgba(34,197,94,0.16);
        --accent-strong:#22c55e;
        --danger:#ef4444;
        --card:#020617;
        --line:#1f2937;
    }
    .stApp{
        background:
          radial-gradient(circle at 10% 0%, rgba(34,197,94,0.16), transparent 45%),
          radial-gradient(circle at 100% 80%, rgba(56,189,248,0.18), transparent 40%),
          linear-gradient(135deg, #020617 0%, #020617 45%, #020617 100%);
        color:var(--ink);
    }
    .stApp, .stApp div, .stApp p, .stApp span, .stApp label{
        color:var(--ink);
    }
    [data-testid="stSidebar"]{
        background:linear-gradient(180deg,#020617,#020617);
        border-right:1px solid #1f2937;
    }
    .sidebar-logo-wrap{
        min-height:74px;
        display:flex;
        justify-content:center;
        align-items:center;
        margin:0 0 0.55rem 0;
    }
    h1,h2,h3{
        font-family:'Space Grotesk','Trebuchet MS','Segoe UI',sans-serif;
        color:var(--ink);
    }
    p, label, div{
        font-family:'Outfit','Segoe UI',sans-serif;
    }
    .hero{
        background:rgba(15,23,42,0.98);
        border:1px solid #1f2937;
        border-radius:18px;
        padding:20px 22px;
        margin-bottom:12px;
        box-shadow:0 18px 45px rgba(0,0,0,0.5);
        backdrop-filter:blur(18px);
    }
    .step{
        background:rgba(15,23,42,0.96);
        border:1px solid #111827;
        border-radius:14px;
        padding:12px 14px;
        min-height:90px;
        box-shadow:0 10px 30px rgba(0,0,0,0.4);
    }
    .summary{
        background:var(--accent-soft);
        border:1px solid rgba(34,197,94,0.45);
        border-radius:14px;
        padding:12px 14px;
    }
    .note{
        color:var(--soft);
        font-size:0.95rem;
    }
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stDateInput"] input,
    textarea{
        background-color:#020617 !important;
        color:var(--ink) !important;
        border-radius:10px !important;
        border:1px solid #1f2937 !important;
    }
    .stButton > button{
        background:linear-gradient(90deg,#22c55e,#16a34a) !important;
        color:#0b1120 !important;
        font-weight:700 !important;
        border:none !important;
        border-radius:999px !important;
        padding:0.6rem 1.2rem !important;
    }
    .stButton > button:hover{
        filter:brightness(1.08);
    }
    [data-testid="stRadio"] > div{
        background:rgba(15,23,42,0.96);
        padding:0.4rem 0.8rem;
        border-radius:999px;
        border:1px solid #111827;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )
    
    st.markdown(
        """
    <div class="hero">
      <h1>Assistente Financeiro por Audio</h1>
      <p class="note">Fale do seu jeito. O assistente interpreta, mostra o que entendeu e atualiza a planilha.</p>
    </div>
    """,
        unsafe_allow_html=True,
    )
    
    step_a, step_b, step_c = st.columns(3)
    step_a.markdown('<div class="step"><b>1) Envie audio ou texto</b><br/>Use microfone, arquivo ou digitação.</div>', unsafe_allow_html=True)
    step_b.markdown('<div class="step"><b>2) Revise o entendimento</b><br/>Campos principais ficam claros para confirmar.</div>', unsafe_allow_html=True)
    step_c.markdown('<div class="step"><b>3) Salve e veja o líquido</b><br/>A planilha é atualizada e o resultado aparece.</div>', unsafe_allow_html=True)
    
    with st.sidebar:
        if logo_path is not None:
            st.markdown('<div class="sidebar-logo-wrap">', unsafe_allow_html=True)
            _render_logo(logo_path, width_px=120)
            st.markdown("</div>", unsafe_allow_html=True)
    
        st.subheader("Configuração")
    
        # Caminho da planilha definido automaticamente (cliente não precisa digitar)
        if "workbook_path" not in st.session_state:
            st.session_state.workbook_path = _default_workbook_path()
    
        st.caption("Planilha .xlsx em uso")
        st.code(
            st.session_state.workbook_path or "Nenhuma planilha .xlsx encontrada na pasta do aplicativo.",
            language="text",
        )
        permitir_troca = st.toggle("Trocar planilha manualmente", value=False)
        if permitir_troca:
            caminho_manual = st.text_input(
                "Caminho da planilha .xlsx",
                value=st.session_state.workbook_path,
            )
            st.session_state.workbook_path = caminho_manual.strip().strip('"').strip("'")
            manual_candidate = Path(st.session_state.workbook_path) if st.session_state.workbook_path else None
            if manual_candidate and manual_candidate.exists() and manual_candidate.is_dir():
                try:
                    resolved = _resolve_workbook_path(str(manual_candidate))
                    st.session_state.workbook_path = str(resolved)
                    st.caption(f"Pasta detectada. Usando automaticamente: {resolved.name}")
                except Exception:
                    pass
    
        # Modelo de áudio simplificado para o cliente: sempre "small" (bom equilíbrio)
        st.caption("Modelo de áudio (voz → texto)")
        st.text("Usando: small (recomendado)")
        model_size = "small"
    
        save_direct = st.toggle("Salvar direto na planilha após interpretar", value=False)
        show_advanced = st.toggle("Mostrar painel avançado", value=False)
        st.caption("Se a planilha mudar de nome, atualize o caminho acima.")
    
    def _handle_audio_processing(audio_payload: Any, model_size: str) -> None:
        audio_bytes = _uploaded_to_bytes(audio_payload)
        if not audio_bytes:
            return
    
        st.audio(audio_bytes)
        audio_signature = hashlib.sha1(audio_bytes).hexdigest()
        audio_changed = st.session_state.get("last_recording_signature") != audio_signature
    
        if audio_changed:
            st.session_state.last_recording_signature = audio_signature
            try:
                with st.spinner("Transcrevendo áudio..."):
                    st.session_state.transcribed_text_draft = _transcribe_payload_to_text(
                        audio_payload=audio_payload,
                        model_size=model_size,
                    )
                st.session_state.audio_transcription_error = ""
            except (TranscriptionError, ValueError) as exc:
                st.session_state.audio_transcription_error = str(exc)
    
    
    def _render_audio_capture() -> Any:
        if hasattr(st, "audio_input"):
            return st.audio_input("Gravar audio")
    
        st.warning(
            "Esta versao do Streamlit nao tem gravacao direta por microfone. "
            "Use 'Enviar arquivo de audio'."
        )
        return None
    
    workbook_path = st.session_state.workbook_path
    
    st.markdown("### Entrada")
    entry_mode = st.radio(
        "Escolha como enviar",
        options=["Gravar audio", "Enviar arquivo de audio", "Digitar texto"],
        horizontal=True,
    )
    
    raw_text = ""
    source_kind = "texto"
    audio_payload: Any = None
    
    if entry_mode == "Gravar audio":
        source_kind = "audio"
        audio_payload = _render_audio_capture()
        if audio_payload:
            _handle_audio_processing(audio_payload, model_size)
    
    elif entry_mode == "Enviar arquivo de audio":
        source_kind = "audio"
        audio_payload = st.file_uploader("Audio (wav/mp3/m4a/ogg)", type=["wav", "mp3", "m4a", "ogg"])
        if audio_payload:
            _handle_audio_processing(audio_payload, model_size)
    
    if source_kind == "audio":
        if st.session_state.get("audio_transcription_error"):
            st.error(st.session_state.audio_transcription_error)
        raw_text = st.text_area(
            "Texto reconhecido (edite antes de interpretar)",
            key="transcribed_text_draft",
            height=130,
            placeholder="A transcrição do áudio aparecerá aqui para você revisar.",
        )
    else:
        source_kind = "texto"
        raw_text = st.text_area(
            "Mensagem livre",
            height=140,
            placeholder=(
                "Exemplo: Hoje vendi uma placa para a cliente Ana Flores por 3000, "
                "ela pagou metade agora e o restante dia 15. "
                "Depois voce pode falar: ID VENDA 1001, ja pagou tudo, atualiza para pago."
            ),
        )
    
    manual_process_click = st.button("Interpretar comando", type="primary", use_container_width=True)
    process_click = manual_process_click
    
    if process_click:
        try:
            with st.spinner("Interpretando comando..."):
                workbook_path = str(_resolve_workbook_path(workbook_path))
                st.session_state.workbook_path = workbook_path
    
                if source_kind == "audio":
                    raw_text = (st.session_state.transcribed_text_draft or "").strip()
                    if not raw_text:
                        raise ValueError(
                            "Grave ou envie o audio e revise o texto reconhecido antes de interpretar."
                        )
                else:
                    if not raw_text.strip():
                        raise ValueError("Digite a mensagem antes de interpretar.")
                    raw_text = raw_text.strip()
    
                result = parse_message(raw_text, reference_date=date.today())
                _fill_state_from_command(
                    result.command,
                    result.missing_fields,
                    raw_text,
                    source_kind,
                    intent=result.intent,
                    refund_command=result.refund_command,
                    status_update_command=result.status_update_command,
                )
            if result.intent == "refund":
                st.success("Entendi: pedido de estorno/cancelamento. Confira e confirme abaixo.")
            elif result.intent == "status_update":
                st.success("Entendi: voce quer atualizar uma venda existente pelo ID VENDA.")
            else:
                st.success("Entendi seu pedido. Confira os dados abaixo.")
        except (ValueError, FileNotFoundError, TranscriptionError) as exc:
            st.error(str(exc))
    
    
    if st.session_state.parsed_ready:
        is_status_update = getattr(st.session_state, "intent", "sale") == "status_update"
        is_mixed_update = getattr(st.session_state, "intent", "sale") == "mixed_update"
        status_update_cmd = getattr(st.session_state, "status_update_command", None)
        is_refund = getattr(st.session_state, "intent", "sale") == "refund"
        refund_cmd = getattr(st.session_state, "refund_command", None)
    
        if is_mixed_update and status_update_cmd is not None:
            st.markdown("### Atualizacao combinada")
            st.markdown(
                f'<div class="summary">'
                f"ID VENDA para status: <b>{html.escape(status_update_cmd.sale_id)}</b>. "
                f"Novo status: <b>{html.escape(status_update_cmd.status)}</b>."
                f"</div>",
                unsafe_allow_html=True,
            )
            material_allocations = st.session_state.get("material_allocations", [])
            if material_allocations:
                st.dataframe(
                    [
                        {
                            "ID VENDA": item["sale_id"],
                            "Valor material": _format_currency(item["amount"]),
                            "Data": item["material_date"].strftime("%d/%m/%Y"),
                        }
                        for item in material_allocations
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            if st.button("Confirmar atualizacao e material", type="primary", use_container_width=True):
                try:
                    workbook_path = str(_resolve_workbook_path(workbook_path))
                    st.session_state.workbook_path = workbook_path
                    with st.spinner("Atualizando planilha..."):
                        _hold_spinner()
                        service = SpreadsheetService(workbook_path)
                        status_action = service.update_sale_status(
                            StatusUpdateCommand(
                                sale_id=status_update_cmd.sale_id,
                                status=status_update_cmd.status,
                                ref_date=date.today(),
                                customer=status_update_cmd.customer,
                            ),
                            original_text=st.session_state.raw_text,
                            origin=st.session_state.source_kind,
                        )
                        material_actions = service.apply_command(
                            cmd=_build_command_from_ui(),
                            original_text=st.session_state.raw_text,
                            origin=st.session_state.source_kind,
                        )
                    st.success(
                        f"Venda {status_action.sale_id} atualizada para {status_update_cmd.status} "
                        f"e {len(material_actions)} lancamento(s) aplicado(s) na planilha."
                    )
                except Exception as exc:
                    st.error(f"Falha ao atualizar planilha: {exc}")
        elif is_status_update and status_update_cmd is not None:
            st.markdown("### Atualizacao por ID VENDA")
            st.markdown(
                f'<div class="summary">'
                f"ID VENDA: <b>{html.escape(status_update_cmd.sale_id)}</b>. "
                f"Novo status: <b>{html.escape(status_update_cmd.status)}</b>."
                f"</div>",
                unsafe_allow_html=True,
            )
            up_col1, up_col2 = st.columns(2)
            with up_col1:
                up_sale_id = st.text_input("ID VENDA", value=status_update_cmd.sale_id, key="status_sale_id")
            with up_col2:
                up_status = st.selectbox(
                    "Status de valor",
                    options=["pago", "pendente"],
                    index=0 if status_update_cmd.status == "pago" else 1,
                    key="status_value_update",
                )
    
            if st.button("Confirmar atualizacao", type="primary", use_container_width=True):
                try:
                    workbook_path = str(_resolve_workbook_path(workbook_path))
                    st.session_state.workbook_path = workbook_path
                    with st.spinner("Atualizando venda na planilha..."):
                        _hold_spinner()
                        service = SpreadsheetService(workbook_path)
                        action = service.update_sale_status(
                            StatusUpdateCommand(
                                sale_id=up_sale_id.strip(),
                                status=up_status,
                                ref_date=date.today(),
                                customer=status_update_cmd.customer,
                            ),
                            original_text=st.session_state.raw_text,
                            origin=st.session_state.source_kind,
                        )
                    moved_text = ""
                    if abs(action.amount) >= 0.01:
                        moved_text = f" Valor movido do pendente para pago: {_format_currency(action.amount)}."
                    st.success(f"Venda {action.sale_id} atualizada para {up_status}.{moved_text}")
                except Exception as exc:
                    st.error(f"Falha ao atualizar venda: {exc}")
        elif is_refund and refund_cmd is not None:
            st.markdown("### Estorno / cancelamento")
            st.markdown(
                f'<div class="summary">'
                f"Cliente: <b>{html.escape(refund_cmd.customer)}</b>. "
                f"Valor a estornar: <b>{_format_currency(refund_cmd.amount)}</b>. "
                f"Motivo: {html.escape(refund_cmd.reason)}."
                f"</div>",
                unsafe_allow_html=True,
            )
            if refund_cmd.amount <= 0:
                st.warning("Valor do estorno nao foi identificado. Informe o valor antes de confirmar.")
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                ref_amount = st.number_input(
                    "Valor do estorno (R$)",
                    min_value=0.0,
                    step=50.0,
                    value=float(refund_cmd.amount or 0),
                    key="refund_amount",
                )
            with col_r2:
                ref_confirm = st.button("Confirmar estorno na planilha", type="primary", use_container_width=True)
            if ref_confirm:
                try:
                    workbook_path = str(_resolve_workbook_path(workbook_path))
                    st.session_state.workbook_path = workbook_path
                    if ref_amount <= 0:
                        raise ValueError("Informe o valor do estorno.")
                    with st.spinner("Salvando estorno na planilha..."):
                        _hold_spinner()
                        service = SpreadsheetService(workbook_path)
                        ref_cmd = RefundCommand(
                            customer=refund_cmd.customer,
                            amount=ref_amount,
                            reason=refund_cmd.reason,
                            ref_date=refund_cmd.ref_date,
                        )
                        action = service.apply_refund(
                            ref_cmd,
                            original_text=st.session_state.raw_text,
                            origin=st.session_state.source_kind,
                        )
                    st.success(f"Estorno de {_format_currency(-action.amount)} registrado na planilha.")
                except Exception as exc:
                    st.error(f"Falha ao registrar estorno: {exc}")
        else:
            st.markdown("### Entendimento do assistente")
            safe_reply = html.escape(st.session_state.assistant_reply)
            st.markdown(f'<div class="summary">{safe_reply}</div>', unsafe_allow_html=True)
            material_allocations = st.session_state.get("material_allocations", [])
    
            if st.session_state.warnings:
                for warning in st.session_state.warnings:
                    st.warning(warning)
            if st.session_state.missing_fields:
                st.error("Campos faltando: " + ", ".join(st.session_state.missing_fields))
    
            if material_allocations and st.session_state.total_value <= 0:
                st.markdown("### Materiais por ID VENDA")
                st.dataframe(
                    [
                        {
                            "ID VENDA": item["sale_id"],
                            "Valor": _format_currency(item["amount"]),
                            "Data": item["material_date"].strftime("%d/%m/%Y"),
                        }
                        for item in material_allocations
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
    
            if save_direct and not st.session_state.missing_fields and st.session_state.total_value > 0 and st.session_state.customer:
                try:
                    workbook_path = str(_resolve_workbook_path(workbook_path))
                    st.session_state.workbook_path = workbook_path
                    cmd = _build_command_from_ui()
                    if cmd.payments:
                        with st.spinner("Salvando na planilha..."):
                            _hold_spinner()
                            service = SpreadsheetService(workbook_path)
                            actions = service.apply_command(
                                cmd=cmd,
                                original_text=st.session_state.raw_text,
                                origin=st.session_state.source_kind,
                            )
                        if actions:
                            net_value = _calc_net_value(cmd)
                            st.success(
                                "Planilha atualizada automaticamente. "
                                f"Liquido previsto: {_format_currency(net_value)}."
                            )
                            st.session_state.parsed_ready = False
                except Exception as exc:
                    st.error(f"Falha ao salvar direto: {exc}")
    
            st.markdown("### Confirmacao rapida")
            c1, c2, c3 = st.columns(3)
            c1.text_input("ID Cliente", key="customer")
            c2.text_input("ID produto", key="product_id")
            c3.date_input("Data da venda", key="sale_date", format="DD/MM/YYYY")
    
            c4, c5, c6 = st.columns(3)
            c4.number_input("Valor total (R$)", min_value=0.0, step=100.0, key="total_value")
            c5.number_input("Total de vendas (pago)", min_value=0.0, step=50.0, key="entry_value")
            c6.number_input("Valor (pendente)", min_value=0.0, step=50.0, key="balance_value")
    
            c7, c8, c9 = st.columns(3)
            c7.date_input("Data entrada", key="entry_date", format="DD/MM/YYYY")
            c8.date_input("Data saldo", key="balance_date", format="DD/MM/YYYY")
            c9.number_input("Custo material (R$)", min_value=0.0, step=50.0, key="material_cost")
            st.date_input("Data de entrega", key="service_due_date", format="DD/MM/YYYY")
    
            st.caption(
                "ID VENDA sera gerado automaticamente ao salvar. Use esse codigo depois para atualizar o status."
            )
    
            if show_advanced:
                st.markdown("### Campos avançados")
                a1, a2, a3 = st.columns(3)
                a1.text_input("Descricao", key="description")
                a2.date_input("Data material", key="material_date", format="DD/MM/YYYY")
                a3.text_input("Fornecedor material", key="material_supplier")
    
                a4, a5, a6 = st.columns(3)
                a4.number_input("Gasto fixo (R$)", min_value=0.0, step=50.0, key="fixed_cost")
                a5.text_input("Descricao gasto fixo", key="fixed_cost_label")
                a6.date_input("Data gasto fixo", key="fixed_cost_date", format="DD/MM/YYYY")
    
            save_click = st.button("Salvar na planilha", use_container_width=True, type="primary")
            if save_click:
                try:
                    workbook_path = str(_resolve_workbook_path(workbook_path))
                    st.session_state.workbook_path = workbook_path
                    cmd = _build_command_from_ui()
                    material_only = bool(
                        cmd.total_value <= 0
                        and (
                            (cmd.sale_id and cmd.material_cost and cmd.material_cost > 0)
                            or cmd.material_allocations
                        )
                    )
                    if not material_only:
                        if not cmd.customer:
                            raise ValueError("Cliente obrigatorio.")
                        if not (cmd.product_id or "").strip():
                            raise ValueError("ID produto obrigatorio.")
                        if cmd.total_value <= 0:
                            raise ValueError("Valor total deve ser maior que zero.")
                        if not cmd.payments:
                            raise ValueError("Informe ao menos entrada ou saldo.")
    
                    payment_total = round(sum(p.value for p in cmd.payments), 2)
                    if not material_only and abs(payment_total - cmd.total_value) >= 0.01:
                        st.warning(
                            f"Pagamentos somam {_format_currency(payment_total)} e total e {_format_currency(cmd.total_value)}."
                        )
    
                    with st.spinner("Salvando na planilha..."):
                        _hold_spinner()
                        service = SpreadsheetService(workbook_path)
                        actions = service.apply_command(
                            cmd=cmd,
                            original_text=st.session_state.raw_text,
                            origin=st.session_state.source_kind,
                        )
                    if not actions:
                        st.error("Nenhum lancamento foi gerado.")
                    else:
                        net_value = _calc_net_value(cmd)
                        sale_ids = [a.sale_id for a in actions if a.sale_id]
                        sale_id_text = f" ID VENDA: {sale_ids[0]}." if sale_ids else ""
                        st.success(
                            "Planilha atualizada. "
                            f"Liquido previsto desta venda: {_format_currency(net_value)}.{sale_id_text}"
                        )
                        st.dataframe(
                            [
                                {
                                    "Aba": a.sheet,
                                    "Linha": a.row,
                                    "Valor": _format_currency(a.amount),
                                    "Tipo": a.label,
                                    "ID VENDA": a.sale_id or "-",
                                }
                                for a in actions
                            ],
                            hide_index=True,
                            use_container_width=True,
                        )
    
                        p1, p2, p3 = st.columns(3)
                        with p1:
                            st.caption(SHEET_SALES)
                            st.dataframe(service.read_last_rows(SHEET_SALES, limit=5), hide_index=True, use_container_width=True)
                        with p2:
                            st.caption(SHEET_MATERIAL)
                            st.dataframe(service.read_last_rows(SHEET_MATERIAL, limit=5), hide_index=True, use_container_width=True)
                        with p3:
                            st.caption(SHEET_FIXED)
                            st.dataframe(service.read_last_rows(SHEET_FIXED, limit=5), hide_index=True, use_container_width=True)
                except Exception as exc:
                    st.error(f"Falha ao salvar: {exc}")
    
    st.markdown("---")
    st.caption(
        "Dica: se algo sair errado, envie novo áudio com correção ou use o painel avançado para ajustar antes de salvar."
    )
    
    if show_advanced:
        st.markdown("### Atualizar status por ID VENDA")
        st.caption("Use quando o cliente quitar o valor pendente e voce quiser marcar a venda como paga.")
    
        su1, su2 = st.columns(2)
        sale_id_fix = su1.text_input("ID VENDA para atualizar", key="manual_sale_id")
        sale_status_fix = su2.selectbox("Novo status", options=["pago", "pendente"], key="manual_sale_status")
    
        if st.button("Atualizar status da venda", use_container_width=True):
            try:
                workbook_path = str(_resolve_workbook_path(workbook_path))
                st.session_state.workbook_path = workbook_path
                if not sale_id_fix.strip():
                    raise ValueError("Informe o ID VENDA.")
                with st.spinner("Atualizando venda na planilha..."):
                    _hold_spinner()
                    service = SpreadsheetService(workbook_path)
                    action = service.update_sale_status(
                        StatusUpdateCommand(
                            sale_id=sale_id_fix.strip(),
                            status=sale_status_fix,
                            ref_date=date.today(),
                        ),
                        original_text="atualizacao manual por ID VENDA",
                        origin="correção-manual",
                    )
                moved_text = ""
                if abs(action.amount) >= 0.01:
                    moved_text = f" Valor movido para pago: {_format_currency(action.amount)}."
                st.success(f"Venda {action.sale_id} atualizada para {sale_status_fix}.{moved_text}")
            except Exception as exc:
                st.error(f"Falha ao atualizar status: {exc}")
    
        st.markdown("### Correcao rapida de linha")
        st.caption("Sobrescreve uma linha especifica sem abrir o Excel.")
    
        cc1, cc2, cc3, cc4, cc5 = st.columns(5)
        sheet_fix = cc1.selectbox("Aba", options=[SHEET_SALES, SHEET_MATERIAL, SHEET_FIXED], key="fix_sheet")
        row_fix = int(cc2.number_input("Linha", min_value=3, step=1, value=3, key="fix_row"))
        date_fix = cc3.date_input("Data", value=date.today(), format="DD/MM/YYYY", key="fix_date")
        party_fix = cc4.text_input("Cliente/Fornecedor", key="fix_party")
        amount_fix = cc5.number_input("Valor (R$)", min_value=0.0, step=50.0, key="fix_amount")
        desc_fix = st.text_input("Descricao", key="fix_desc")
        source_fix = st.text_input("Origem da correção", value="correção manual", key="fix_source")
    
        if st.button("Aplicar correção", use_container_width=True):
            try:
                workbook_path = str(_resolve_workbook_path(workbook_path))
                st.session_state.workbook_path = workbook_path
                if amount_fix <= 0:
                    raise ValueError("Valor deve ser maior que zero.")
                if not desc_fix.strip():
                    raise ValueError("Descricao obrigatoria.")
    
                with st.spinner("Aplicando correção na planilha..."):
                    _hold_spinner()
                    service = SpreadsheetService(workbook_path)
                    service.update_row(
                        sheet_name=sheet_fix,
                        row=row_fix,
                        ref_date=date_fix,
                        party=party_fix.strip(),
                        description=desc_fix.strip(),
                        amount=float(amount_fix),
                        original_text=source_fix.strip(),
                        origin="correção-manual",
                    )
                st.success("Correcao aplicada e registrada no historico.")
            except Exception as exc:
                st.error(f"Falha na correção: {exc}")


if __name__ == '__main__':
    main()

