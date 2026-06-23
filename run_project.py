#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prepara o projeto — clique em Run (▶) aqui antes de usar o sistema.

Instala/atualiza venv, bibliotecas, modelo Whisper, .env e planilha.
Nao inicia o Telegram nem o App; depois rode telegram_bot.py (ou launcher.py).

Exemplo:
  python run_project.py
"""
from __future__ import annotations

import argparse

from src.bootstrap import log, print_ready_message, setup_project


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepara o ambiente do projeto (venv, libs, Whisper, .env)."
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

    log("=== Preparando projeto (setup automatico) ===")
    setup_project(verbose=verbose)
    print_ready_message()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Encerrado por Ctrl+C.")
        raise SystemExit(0)
