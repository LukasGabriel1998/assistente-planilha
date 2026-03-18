from __future__ import annotations

import os
from pathlib import Path

SUPPORTED_WORKBOOK_EXTS = (".xlsx", ".xlsm", ".xltx", ".xltm")
WORKBOOK_SEARCH_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".venv_native",
    ".tmp_native",
    "__pycache__",
    "build",
    "models_cache",
}


def is_workbook_candidate(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.startswith("~$"):
        return False
    if path.suffix.lower() not in SUPPORTED_WORKBOOK_EXTS:
        return False
    return True


def iter_workbook_candidates(root: Path):
    if not root.exists():
        return
    preferred_dir = root / "dist_novo"
    if preferred_dir.exists():
        for ext in SUPPORTED_WORKBOOK_EXTS:
            for candidate in preferred_dir.rglob(f"*{ext}"):
                if is_workbook_candidate(candidate):
                    yield candidate
    for current_root, dirnames, filenames in os.walk(root):
        current_path = Path(current_root)
        if current_path == preferred_dir:
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in WORKBOOK_SEARCH_EXCLUDE_DIRS]
        for filename in filenames:
            candidate = current_path / filename
            if is_workbook_candidate(candidate):
                yield candidate


def _sorted_unique_candidates(candidates: list[Path]) -> list[Path]:
    unique_candidates = {candidate.resolve(): candidate.resolve() for candidate in candidates}
    items = list(unique_candidates.values())
    items.sort(
        key=lambda path: (
            0 if "planilha_comunicacao_visual - edit" in path.name.lower() else 1,
            0 if "dist_novo" in {part.lower() for part in path.parts} else 1,
            -path.stat().st_mtime,
            len(path.parts),
        )
    )
    return items


def default_workbook_path(search_roots: list[Path]) -> str:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in search_roots:
        resolved_root = root.resolve()
        if resolved_root in seen or not resolved_root.exists():
            continue
        seen.add(resolved_root)
        candidates.extend(iter_workbook_candidates(resolved_root))
    if not candidates:
        return ""
    return str(_sorted_unique_candidates(candidates)[0])


def resolve_workbook_path(path_text: str) -> Path:
    raw = (path_text or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("Informe o caminho da planilha.")

    path = Path(raw).expanduser()
    if not path.exists():
        raise FileNotFoundError("Planilha/pasta nao encontrada no caminho informado.")

    if path.is_dir():
        candidates: list[Path] = []
        for ext in SUPPORTED_WORKBOOK_EXTS:
            candidates.extend([p for p in path.glob(f"*{ext}") if is_workbook_candidate(p)])
        if not candidates:
            for ext in SUPPORTED_WORKBOOK_EXTS:
                candidates.extend([p for p in path.rglob(f"*{ext}") if is_workbook_candidate(p)])
        if not candidates:
            raise FileNotFoundError(
                "Nenhuma planilha valida encontrada nessa pasta. Use .xlsx, .xlsm, .xltx ou .xltm."
            )
        return _sorted_unique_candidates(candidates)[0]

    if path.suffix.lower() not in SUPPORTED_WORKBOOK_EXTS:
        raise ValueError("Formato invalido. Use .xlsx, .xlsm, .xltx ou .xltm.")
    if path.name.startswith("~$"):
        raise ValueError(
            "Arquivo temporario do Excel detectado (~$...). "
            "Selecione o arquivo principal da planilha."
        )
    return path
