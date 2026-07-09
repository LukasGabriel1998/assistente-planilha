# -*- coding: utf-8 -*-
"""
API HTTP para o n8n atualizar a planilha (WhatsApp, Telegram, webhooks).

Uso:
  python n8n_api.py

Endpoints principais:
  GET  /health
  POST /api/v1/message
  POST /api/v1/transcribe
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

from src.bootstrap import relaunch_in_project_venv

relaunch_in_project_venv()

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.n8n_service import (
    clear_session,
    handle_message,
    health_info,
    transcribe_audio_file,
)


def _load_dotenv() -> None:
    for base in (Path(__file__).resolve().parent, Path.cwd()):
        env_file = base / ".env"
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if (v.startswith('"') and v.endswith('"')) or (
                v.startswith("'") and v.endswith("'")
            ):
                v = v[1:-1]
            os.environ[k] = v
        break


_load_dotenv()

API_KEY = os.getenv("N8N_API_KEY", "").strip()
HOST = os.getenv("N8N_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.getenv("N8N_API_PORT", "8765"))

app = FastAPI(
    title="Assistente Planilha – API n8n",
    description="Pontes entre n8n (WhatsApp/Telegram) e a planilha Excel do projeto.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API key invalida (header X-API-Key).")


class MessageRequest(BaseModel):
    conversation_id: str = Field(
        ...,
        description="ID unico da conversa (ex.: telegram:123456 ou whatsapp:5511999999999)",
    )
    text: str = Field(..., description="Texto do usuario")
    channel: str = Field(default="n8n", description="whatsapp | telegram | n8n")
    action: str | None = Field(
        default=None,
        description="Opcional: confirm | cancel (senao detecta SIM/NAO no texto)",
    )


class MessageResponse(BaseModel):
    ok: bool
    conversation_id: str
    reply: str
    needs_confirmation: bool = False
    applied: bool = False
    preview: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, Any]:
    return health_info()


@app.post("/api/v1/message", response_model=MessageResponse)
def post_message(
    body: MessageRequest,
    _: None = Depends(_verify_api_key),
) -> MessageResponse:
    result = handle_message(
        body.conversation_id,
        body.text,
        channel=body.channel,
        action=body.action,
    )
    extra = {k: v for k, v in result.items() if k not in ("ok", "conversation_id", "reply", "needs_confirmation", "applied", "preview")}
    return MessageResponse(
        ok=bool(result.get("ok")),
        conversation_id=result.get("conversation_id", body.conversation_id),
        reply=result.get("reply", ""),
        needs_confirmation=bool(result.get("needs_confirmation")),
        applied=bool(result.get("applied")),
        preview=result.get("preview"),
        extra=extra,
    )


@app.delete("/api/v1/session/{conversation_id}")
def delete_session(
    conversation_id: str,
    _: None = Depends(_verify_api_key),
) -> dict[str, bool]:
    return {"cleared": clear_session(conversation_id)}


class TranscribeResponse(BaseModel):
    ok: bool
    text: str | None = None
    error: str | None = None


@app.post("/api/v1/transcribe", response_model=TranscribeResponse)
async def post_transcribe(
    file: UploadFile = File(...),
    _: None = Depends(_verify_api_key),
) -> TranscribeResponse:
    suffix = Path(file.filename or "audio.ogg").suffix or ".ogg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        out = transcribe_audio_file(tmp_path)
        return TranscribeResponse(
            ok=out.get("ok", False),
            text=out.get("text"),
            error=out.get("error"),
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def main() -> None:
    import uvicorn

    print(f"[n8n API] Planilha: {os.getenv('SPREADSHEET_BACKEND', 'excel')} / {os.getenv('GOOGLE_SHEETS_ID') or os.getenv('WORKBOOK_PATH', '(auto)')}")
    print(f"[n8n API] http://{HOST}:{PORT}  |  docs: http://{HOST}:{PORT}/docs")
    if API_KEY:
        print("[n8n API] Autenticacao: header X-API-Key")
    uvicorn.run(
        "n8n_api:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
