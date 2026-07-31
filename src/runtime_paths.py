# -*- coding: utf-8 -*-
"""Caminhos de dados persistentes (sobrevivem a rebuild do Docker)."""
from __future__ import annotations

from pathlib import Path


def data_dir(project_dir: Path) -> Path:
    path = project_dir / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_file(project_dir: Path, name: str) -> Path:
    return data_dir(project_dir) / name
