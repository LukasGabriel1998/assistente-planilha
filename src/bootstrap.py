# -*- coding: utf-8 -*-
"""Utilitarios internos de setup (venv, libs, Whisper, .env).

Setup: run_project.py | Telegram: telegram_bot.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
VENV_DIR = PROJECT_DIR / ".venv_native"
LOCK_FILE = PROJECT_DIR / ".telegram_bot.lock"
REQUIREMENTS = PROJECT_DIR / "requirements.txt"
ENV_FILE = PROJECT_DIR / ".env"
ENV_EXAMPLE = PROJECT_DIR / ".env.example"

# Pacotes criticos verificados apos o pip install.
REQUIRED_IMPORTS: tuple[tuple[str, str], ...] = (
    ("streamlit", "streamlit"),
    ("openpyxl", "openpyxl"),
    ("dateparser", "dateparser"),
    ("requests", "requests"),
    ("fastapi", "fastapi"),
    ("faster_whisper", "faster-whisper"),
    ("numpy", "numpy"),
)


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def log(msg: str, *, prefix: str = "Projeto") -> None:
    print(f"[{prefix}] {msg}", flush=True)


def python_works(exe: Path) -> bool:
    if not exe.is_file():
        return False
    try:
        proc = subprocess.run(
            [str(exe), "-c", "import sys; sys.exit(0)"],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            timeout=30,
        )
        return proc.returncode == 0
    except Exception:
        return False


def find_bootstrap_python() -> list[str]:
    candidates: list[list[str]] = []
    if sys.executable:
        candidates.append([sys.executable])
    if shutil.which("py"):
        candidates.append(["py", "-3"])
    if shutil.which("python3"):
        candidates.append(["python3"])
    if shutil.which("python"):
        candidates.append(["python"])
    return candidates[0] if candidates else [sys.executable]


def activate_project_context() -> None:
    os.chdir(PROJECT_DIR)
    project = str(PROJECT_DIR)
    if project not in sys.path:
        sys.path.insert(0, project)


def ensure_venv(*, prefix: str = "Projeto") -> Path:
    py = venv_python()
    if python_works(py):
        log("Ambiente virtual OK (.venv_native).", prefix=prefix)
        return py

    if VENV_DIR.exists():
        log("Ambiente virtual quebrado — recriando .venv_native ...", prefix=prefix)
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    log("Criando ambiente virtual (.venv_native) ...", prefix=prefix)
    bootstrap = find_bootstrap_python()
    proc = subprocess.run([*bootstrap, "-m", "venv", str(VENV_DIR)], cwd=str(PROJECT_DIR))
    if proc.returncode != 0 or not python_works(py):
        raise SystemExit(
            "Nao foi possivel criar .venv_native.\n"
            "Instale Python 3.12+ em https://www.python.org/downloads/ e tente de novo."
        )
    log("Ambiente virtual criado.", prefix=prefix)
    return py


def ensure_requirements(py: Path, *, verbose: bool = True, prefix: str = "Projeto") -> None:
    log("Baixando/atualizando bibliotecas (requirements.txt) ...", prefix=prefix)
    log("A primeira vez pode demorar alguns minutos.", prefix=prefix)

    pip_flags = [] if verbose else ["-q"]
    subprocess.run(
        [str(py), "-m", "pip", "install", *pip_flags, "-U", "pip"],
        cwd=str(PROJECT_DIR),
        check=True,
    )
    if not REQUIREMENTS.is_file():
        raise SystemExit(f"Arquivo nao encontrado: {REQUIREMENTS}")

    subprocess.run(
        [str(py), "-m", "pip", "install", *pip_flags, "-r", str(REQUIREMENTS)],
        cwd=str(PROJECT_DIR),
        check=True,
    )
    log("Bibliotecas instaladas.", prefix=prefix)


def verify_imports(py: Path, *, prefix: str = "Projeto") -> None:
    log("Verificando bibliotecas principais ...", prefix=prefix)
    missing: list[str] = []
    for mod, label in REQUIRED_IMPORTS:
        proc = subprocess.run(
            [str(py), "-c", f"import {mod}"],
            cwd=str(PROJECT_DIR),
            capture_output=True,
        )
        if proc.returncode != 0:
            missing.append(label)
    if missing:
        raise SystemExit(f"Faltando bibliotecas: {', '.join(missing)}")
    log("Todas as bibliotecas principais OK.", prefix=prefix)


MIN_PYTHON = (3, 12)
# Arquivos LFS do Git costumam ter poucos bytes; model.bin real tem centenas de MB.
MIN_MODEL_BIN_BYTES = 1_000_000


def check_python_version(*, prefix: str = "Projeto") -> None:
    if sys.version_info < MIN_PYTHON:
        major, minor = MIN_PYTHON
        raise SystemExit(
            f"Python {sys.version_info.major}.{sys.version_info.minor} detectado. "
            f"Este projeto precisa de Python {major}.{minor}+.\n"
            "Instale em https://www.python.org/downloads/ e tente de novo."
        )
    log(
        f"Python {sys.version_info.major}.{sys.version_info.minor} OK.",
        prefix=prefix,
    )


def _is_valid_model_bin(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return path.stat().st_size >= MIN_MODEL_BIN_BYTES
    except OSError:
        return False


def _whisper_model_ready(model_size: str) -> Path | None:
    local_dir = PROJECT_DIR / "models"
    candidates = [
        local_dir / "model.bin",
        local_dir / f"faster-whisper-{model_size}" / "model.bin",
        local_dir / model_size / "model.bin",
    ]
    if local_dir.is_dir():
        for model_file in local_dir.rglob("model.bin"):
            candidates.append(model_file)

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if _is_valid_model_bin(candidate):
            return candidate
    return None


def ensure_git_lfs_assets(*, prefix: str = "Projeto") -> None:
    """Baixa arquivos grandes do repositorio quando o clone veio sem Git LFS."""
    if not (PROJECT_DIR / ".git").is_dir():
        return
    if shutil.which("git") is None:
        log("Git nao encontrado — pulando git lfs pull.", prefix=prefix)
        return
    if _whisper_model_ready(os.getenv("WHISPER_MODEL", "small").strip() or "small"):
        return

    proc = subprocess.run(
        ["git", "lfs", "version"],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        log(
            "Git LFS nao instalado — apos clone, instale Git LFS ou o modelo sera baixado depois.",
            prefix=prefix,
        )
        return

    log("Baixando arquivos grandes do repositorio (git lfs pull) ...", prefix=prefix)
    pull = subprocess.run(
        ["git", "lfs", "pull"],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if pull.returncode == 0:
        log("Git LFS concluido.", prefix=prefix)
    else:
        err = (pull.stderr or pull.stdout or "").strip()
        log(f"Git LFS pull falhou{': ' + err if err else ''}.", prefix=prefix)


def ensure_whisper_model(py: Path, *, prefix: str = "Projeto") -> None:
    model_size = os.getenv("WHISPER_MODEL", "small").strip() or "small"
    existing = _whisper_model_ready(model_size)
    if existing is not None:
        log(f"Modelo de audio local OK ({existing}).", prefix=prefix)
        return

    log(
        f"Baixando modelo Whisper ({model_size}) — pode demorar (~150-500 MB) ...",
        prefix=prefix,
    )
    download_code = (
        "from pathlib import Path\n"
        "import os\n"
        "from faster_whisper.utils import download_model\n"
        'model_size = os.getenv("WHISPER_MODEL", "small").strip() or "small"\n'
        'root = Path("models")\n'
        "root.mkdir(parents=True, exist_ok=True)\n"
        "path = download_model(model_size, output_dir=str(root))\n"
        'print("MODEL_PATH=", path)\n'
    )
    proc = subprocess.run(
        [str(py), "-c", download_code],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(
            "Falha ao baixar modelo de audio (Whisper).\n"
            f"Detalhe: {detail or 'erro desconhecido'}"
        )

    downloaded = _whisper_model_ready(model_size)
    if downloaded is None:
        raise SystemExit(
            "Download do modelo Whisper terminou, mas model.bin nao foi encontrado em models/."
        )
    log(f"Modelo de audio baixado: {downloaded}", prefix=prefix)


def print_setup_report(*, prefix: str = "Projeto") -> None:
    log("--- Resumo do setup ---", prefix=prefix)

    if python_works(venv_python()):
        log("  OK: ambiente virtual e bibliotecas", prefix=prefix)
    else:
        log("  ATENCAO: ambiente virtual incompleto", prefix=prefix)

    workbook = os.getenv("WORKBOOK_PATH", "").strip().strip('"').strip("'")
    if workbook and Path(workbook).is_file():
        log(f"  OK: planilha ({workbook})", prefix=prefix)
    else:
        log("  ATENCAO: planilha .xlsx nao encontrada — copie ou ajuste WORKBOOK_PATH no .env", prefix=prefix)

    model_size = os.getenv("WHISPER_MODEL", "small").strip() or "small"
    model_path = _whisper_model_ready(model_size)
    if model_path is not None:
        log(f"  OK: modelo de audio ({model_path.name})", prefix=prefix)
    else:
        log("  ATENCAO: modelo de audio ausente", prefix=prefix)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "COLOQUE_SEU_TOKEN_AQUI":
        log(
            "  ATENCAO: TELEGRAM_BOT_TOKEN nao configurado no .env (necessario para o bot)",
            prefix=prefix,
        )
    else:
        log("  OK: token do Telegram configurado", prefix=prefix)


def print_ready_message(*, prefix: str = "Projeto") -> None:
    """Mensagem final apos setup — orienta qual arquivo rodar em seguida."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_ready = bool(token and token != "COLOQUE_SEU_TOKEN_AQUI")
    py = venv_python()

    log("", prefix=prefix)
    if telegram_ready and python_works(py):
        log("Tudo pronto para o Telegram.", prefix=prefix)
        log("Proximo passo: abra telegram_bot.py e clique em Run (▶).", prefix=prefix)
    elif not telegram_ready:
        log("Setup concluido, mas falta configurar o Telegram.", prefix=prefix)
        log(f"1) Abra o .env e cole o TELEGRAM_BOT_TOKEN", prefix=prefix)
        log("2) Depois abra telegram_bot.py e clique em Run (▶).", prefix=prefix)
    else:
        log("Setup concluido com avisos — revise o resumo acima.", prefix=prefix)
        log("Depois rode telegram_bot.py (Run ▶).", prefix=prefix)

    log("App desktop (opcional): launcher.py", prefix=prefix)
    log("API n8n (opcional): n8n_api.py", prefix=prefix)


def ensure_env_file(*, prefix: str = "Projeto") -> None:
    if ENV_FILE.is_file():
        return
    if ENV_EXAMPLE.is_file():
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)
        log(".env criado a partir de .env.example.", prefix=prefix)
    else:
        log("Aviso: .env nao encontrado.", prefix=prefix)


def ensure_workbook_path(*, prefix: str = "Projeto") -> None:
    """Define WORKBOOK_PATH automaticamente se estiver vazio ou invalido nesta maquina."""
    current = os.getenv("WORKBOOK_PATH", "").strip().strip('"').strip("'")
    if current and Path(current).is_file():
        return

    from src.workbook_paths import default_workbook_path

    found = default_workbook_path([PROJECT_DIR])
    if not found:
        log("Nenhuma planilha .xlsx encontrada na pasta do projeto.", prefix=prefix)
        return

    os.environ["WORKBOOK_PATH"] = found
    log(f"Planilha detectada automaticamente: {found}", prefix=prefix)

    if ENV_FILE.is_file():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        updated = False
        for i, line in enumerate(lines):
            if line.strip().startswith("WORKBOOK_PATH="):
                lines[i] = f"WORKBOOK_PATH={found}"
                updated = True
                break
        if not updated:
            lines.append(f"WORKBOOK_PATH={found}")
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_dotenv_into_os() -> None:
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ[key] = value


def validate_telegram_token() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "COLOQUE_SEU_TOKEN_AQUI":
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN nao configurado.\n"
            f"Abra o .env em:\n  {ENV_FILE}\n"
            "e cole o token do @BotFather."
        )


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def process_command_line(pid: int) -> str:
    if pid <= 0:
        return ""
    if os.name == "nt":
        try:
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
                ],
                cwd=str(PROJECT_DIR),
                capture_output=True,
                text=True,
                timeout=15,
            )
            return (proc.stdout or "").strip()
        except Exception:
            return ""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
    except Exception:
        return ""


def is_telegram_bot_process(pid: int) -> bool:
    return "telegram_bot.py" in process_command_line(pid).lower()


def terminate_pid(pid: int, *, kill_tree: bool = False) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name == "nt":
        try:
            args = ["taskkill", "/PID", str(pid), "/F"]
            if kill_tree:
                args.insert(2, "/T")
            subprocess.run(args, capture_output=True, timeout=15)
            return not pid_alive(pid)
        except Exception:
            return False
    try:
        os.kill(pid, 15)
        return True
    except OSError:
        return False


def stop_old_bot_instances(*, prefix: str = "Projeto") -> None:
    """Encerra instancia antiga registrada no lock e remove o arquivo."""
    current_pid = os.getpid()
    stopped: list[int] = []

    if LOCK_FILE.is_file():
        try:
            raw = LOCK_FILE.read_text(encoding="utf-8").strip()
            lock_pid = int(raw.split()[0]) if raw else 0
        except Exception:
            lock_pid = 0
        if lock_pid and lock_pid != current_pid and pid_alive(lock_pid):
            if terminate_pid(lock_pid):
                stopped.append(lock_pid)
                time.sleep(0.4)

    had_lock = LOCK_FILE.is_file()
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    if stopped:
        log(f"Instancias antigas encerradas: {', '.join(str(p) for p in sorted(set(stopped)))}", prefix=prefix)
    elif had_lock:
        log("Lock antigo removido.", prefix=prefix)


def setup_project(*, verbose: bool = True, prefix: str = "Projeto") -> Path:
    """Prepara tudo: Python, venv, pip, .env, planilha, modelo Whisper e Git LFS."""
    activate_project_context()
    check_python_version(prefix=prefix)
    log(f"Pasta do projeto: {PROJECT_DIR}", prefix=prefix)
    ensure_env_file(prefix=prefix)
    load_dotenv_into_os()
    ensure_git_lfs_assets(prefix=prefix)
    py = ensure_venv(prefix=prefix)
    ensure_requirements(py, verbose=verbose, prefix=prefix)
    verify_imports(py, prefix=prefix)
    ensure_workbook_path(prefix=prefix)
    ensure_whisper_model(py, prefix=prefix)
    print_setup_report(prefix=prefix)
    log("Projeto pronto para rodar nesta maquina.", prefix=prefix)
    return py
