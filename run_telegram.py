#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram — 1 clique, qualquer maquina.

Abra este arquivo e clique em Run (▶).
Na primeira vez: cria venv, baixa bibliotecas, detecta planilha e inicia o bot.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
VENV_PY = (
    PROJECT_DIR / ".venv_native" / "Scripts" / "python.exe"
    if os.name == "nt"
    else PROJECT_DIR / ".venv_native" / "bin" / "python"
)
_READY_FLAG = "RUN_TELEGRAM_READY"


def _log(msg: str) -> None:
    print(f"[Telegram] {msg}", flush=True)


def _venv_usable() -> bool:
    if not VENV_PY.is_file():
        return False
    proc = subprocess.run(
        [str(VENV_PY), "-c", "import requests, openpyxl, faster_whisper"],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        timeout=60,
    )
    return proc.returncode == 0


def _running_in_project_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == VENV_PY.resolve()
    except Exception:
        return False


def _needs_bootstrap() -> bool:
    if os.environ.get(_READY_FLAG) == "1":
        return False
    if _running_in_project_venv() and _venv_usable():
        return False
    return True


def _bootstrap_and_reexec() -> None:
    """Usa o Python disponivel na maquina para instalar tudo e reexecutar no venv."""
    if not _needs_bootstrap():
        return

    _log("Primeira execucao nesta maquina — preparando ambiente automaticamente...")
    _log("Isso pode demorar alguns minutos (baixando bibliotecas). Aguarde.")

    os.chdir(PROJECT_DIR)
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))

    setup_code = (
        "import sys; "
        f"sys.path.insert(0, {str(PROJECT_DIR)!r}); "
        "from src.bootstrap import setup_project; "
        "setup_project(verbose=True, prefix='Telegram')"
    )
    proc = subprocess.run([sys.executable, "-c", setup_code], cwd=str(PROJECT_DIR))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)

    if not VENV_PY.is_file():
        raise SystemExit(
            "Setup falhou: .venv_native nao foi criado.\n"
            "Instale Python 3.12+ em https://www.python.org/downloads/ "
            "(marque 'Add python.exe to PATH') e rode de novo."
        )

    env = os.environ.copy()
    env[_READY_FLAG] = "1"
    _log("Ambiente pronto. Iniciando bot...")
    result = subprocess.run([str(VENV_PY), str(Path(__file__).resolve())], cwd=str(PROJECT_DIR), env=env)
    raise SystemExit(result.returncode)


def _start_telegram() -> None:
    from src.bootstrap import (
        ensure_workbook_path,
        load_dotenv_into_os,
        log as blog,
        setup_project,
        stop_old_bot_instances,
        validate_telegram_token,
    )

    os.chdir(PROJECT_DIR)
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))

    blog("=== Telegram — pronto para rodar ===", prefix="Telegram")
    py = setup_project(verbose=False, prefix="Telegram")
    load_dotenv_into_os()
    ensure_workbook_path(prefix="Telegram")
    stop_old_bot_instances(prefix="Telegram")
    validate_telegram_token()

    bot = PROJECT_DIR / "telegram_bot.py"
    blog(f"Projeto: {PROJECT_DIR}", prefix="Telegram")
    blog("Bot ativo. Ctrl+C para parar.", prefix="Telegram")
    proc = subprocess.run([str(py), str(bot)], cwd=str(PROJECT_DIR))
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    try:
        _bootstrap_and_reexec()
        _start_telegram()
    except KeyboardInterrupt:
        _log("Encerrado por Ctrl+C.")
        raise SystemExit(0)
