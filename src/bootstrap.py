# -*- coding: utf-8 -*-
"""Utilitarios compartilhados para preparar o projeto em qualquer maquina."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
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


def terminate_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
            return not pid_alive(pid)
        except Exception:
            return False
    try:
        os.kill(pid, 15)
        return True
    except OSError:
        return False


def stop_old_bot_instances(*, prefix: str = "Projeto") -> None:
    current_pid = os.getpid()
    stopped: list[int] = []

    if LOCK_FILE.is_file():
        try:
            raw = LOCK_FILE.read_text(encoding="utf-8").strip()
            lock_pid = int(raw.split()[0]) if raw else 0
        except Exception:
            lock_pid = 0
        if lock_pid and lock_pid != current_pid and is_telegram_bot_process(lock_pid):
            if terminate_pid(lock_pid):
                stopped.append(lock_pid)

    if os.name == "nt":
        ps_cmd = (
            f"$me = {current_pid}; "
            "Get-CimInstance Win32_Process | Where-Object { "
            "$_.ProcessId -ne $me -and $_.CommandLine -and "
            "$_.CommandLine -match '(?i)telegram_bot\\.py' "
            "} | ForEach-Object { $_.ProcessId }"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                cwd=str(PROJECT_DIR),
                capture_output=True,
                text=True,
                timeout=20,
            )
            for line in (proc.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    if pid != current_pid and terminate_pid(pid):
                        stopped.append(pid)
        except Exception:
            pass

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
    """Prepara tudo: venv, pip install, verificacao e .env."""
    activate_project_context()
    log(f"Pasta do projeto: {PROJECT_DIR}", prefix=prefix)
    py = ensure_venv(prefix=prefix)
    ensure_requirements(py, verbose=verbose, prefix=prefix)
    verify_imports(py, prefix=prefix)
    ensure_env_file(prefix=prefix)
    load_dotenv_into_os()
    ensure_workbook_path(prefix=prefix)
    log("Projeto pronto para rodar nesta maquina.", prefix=prefix)
    return py
