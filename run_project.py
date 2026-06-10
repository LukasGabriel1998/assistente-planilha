#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run universal do projeto — 1 clique instala tudo e inicia.

Use no Cursor/VS Code: abra este arquivo e clique em Run (▶).
Funciona em qualquer maquina: detecta a pasta, cria venv, baixa bibliotecas
e sobe Telegram e/ou App.

Exemplos:
  python run_project.py                 # setup + Telegram
  python run_project.py --setup-only    # so instala (sem iniciar nada)
  python run_project.py --app           # setup + App desktop
  python run_project.py --all           # setup + App + Telegram
  python run_project.py --n8n-api       # setup + API n8n
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from src.bootstrap import (
    ensure_workbook_path,
    load_dotenv_into_os,
    log,
    setup_project,
    stop_old_bot_instances,
    validate_telegram_token,
)

PROJECT_ROOT = Path(__file__).resolve().parent


def _run_script(py: Path, script: str) -> int:
    target = PROJECT_ROOT / script
    if not target.is_file():
        raise SystemExit(f"Arquivo nao encontrado: {target}")
    proc = subprocess.run([str(py), str(target)], cwd=str(PROJECT_ROOT))
    return int(proc.returncode)


def _start_background(py: Path, script: str) -> subprocess.Popen:
    target = PROJECT_ROOT / script
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_CONSOLE
    return subprocess.Popen(
        [str(py), str(target)],
        cwd=str(PROJECT_ROOT),
        creationflags=creationflags,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Setup automatico + execucao do projeto.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--setup-only",
        action="store_true",
        help="So baixa/instala bibliotecas (nao inicia Telegram nem App).",
    )
    group.add_argument(
        "--app",
        action="store_true",
        help="Instala tudo e abre o App (launcher.py).",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Instala tudo e abre App + Telegram juntos.",
    )
    group.add_argument(
        "--telegram",
        action="store_true",
        help="Instala tudo e inicia o Telegram (padrao).",
    )
    group.add_argument(
        "--n8n-api",
        action="store_true",
        help="Instala tudo e inicia a API n8n (n8n_api.py).",
    )
    parser.add_argument(
        "--quiet-pip",
        action="store_true",
        help="Menos saida do pip (instalacao silenciosa).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    verbose = not args.quiet_pip

    log("=== Setup automatico (nova maquina / 1 clique) ===")
    py = setup_project(verbose=verbose)

    if args.setup_only:
        log("Setup concluido. Use Run de novo ou rode com --telegram / --app / --all.")
        return

    load_dotenv_into_os()
    ensure_workbook_path()

    if args.all:
        log("Abrindo App em segundo plano ...")
        _start_background(py, "launcher.py")
        stop_old_bot_instances(prefix="Telegram")
        validate_telegram_token()
        log("Iniciando Telegram ... (Ctrl+C para parar)")
        code = _run_script(py, "telegram_bot.py")
        raise SystemExit(code)

    if args.app:
        log("Iniciando App ... (feche a janela para encerrar)")
        code = _run_script(py, "launcher.py")
        raise SystemExit(code)

    if args.n8n_api:
        log("Iniciando API n8n em http://127.0.0.1:8765 (Ctrl+C para parar)")
        code = _run_script(py, "n8n_api.py")
        raise SystemExit(code)

    # Padrao: Telegram
    stop_old_bot_instances(prefix="Telegram")
    validate_telegram_token()
    log("Iniciando Telegram ... (Ctrl+C para parar)")
    code = _run_script(py, "telegram_bot.py")
    raise SystemExit(code)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Encerrado por Ctrl+C.")
        raise SystemExit(0)
