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


def _is_debug_session() -> bool:
    if sys.gettrace() is not None:
        return True
    if "debugpy" in sys.modules:
        return True
    return any("debugpy" in str(arg) for arg in sys.argv)


def _venv_site_packages() -> Path | None:
    if sys.platform == "win32":
        candidate = VENV_DIR / "Lib" / "site-packages"
    else:
        candidate = (
            VENV_DIR
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages"
        )
    return candidate if candidate.is_dir() else None


def _use_venv_packages_in_place() -> bool:
    """Permite rodar com debug (F5) mesmo se o interpretador errado estiver selecionado."""
    site = _venv_site_packages()
    if site is None:
        return False
    site_str = str(site)
    if site_str not in sys.path:
        sys.path.insert(0, site_str)
    return True


def relaunch_in_project_venv() -> None:
    """Garante que scripts de entrada rodem com o Python do .venv_native."""
    configure_stdio()
    venv_py = venv_python()
    if not venv_py.is_file():
        return

    try:
        if Path(sys.executable).resolve() == venv_py.resolve():
            return
    except Exception:
        pass

    if _is_debug_session():
        if _use_venv_packages_in_place():
            return
        log(
            "Ambiente virtual encontrado, mas pacotes ainda nao instalados. "
            "Rode run_project.py antes de iniciar o bot.",
        )
        raise SystemExit(1)

    log(f"Usando ambiente virtual: {venv_py}")
    proc = subprocess.run([str(venv_py), *sys.argv], cwd=str(PROJECT_DIR))
    raise SystemExit(proc.returncode)


def configure_stdio() -> None:
    """Evita UnicodeEncodeError no terminal Windows (cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def log(msg: str, *, prefix: str = "Projeto") -> None:
    text = f"[{prefix}] {msg}"
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding), flush=True)


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


def _dedupe_python_candidates(candidates: list[list[str]]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    unique: list[list[str]] = []
    for cmd in candidates:
        key = tuple(cmd)
        if key in seen:
            continue
        seen.add(key)
        unique.append(cmd)
    return unique


def find_bootstrap_python_candidates() -> list[list[str]]:
    """Lista Pythons do sistema para tentar criar o venv (ordem de preferencia)."""
    candidates: list[list[str]] = []
    if sys.executable:
        candidates.append([sys.executable])

    if shutil.which("py"):
        candidates.append(["py", "-3"])
        for minor in range(14, 11, -1):
            candidates.append(["py", f"-3.{minor}"])
        try:
            proc = subprocess.run(
                ["py", "-0p"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    if "-V:" not in line:
                        continue
                    version = line.split("-V:", 1)[1].split()[0].strip()
                    if version:
                        candidates.append(["py", f"-{version}"])
                    parts = line.split()
                    if parts and (parts[-1].endswith(".exe") or "python" in parts[-1].lower()):
                        candidates.append([parts[-1]])
        except Exception:
            pass

    if shutil.which("python3"):
        candidates.append(["python3"])
    if shutil.which("python"):
        candidates.append(["python"])

    deduped = _dedupe_python_candidates(candidates)
    return deduped if deduped else ([sys.executable] if sys.executable else [])


def bootstrap_python_works(bootstrap: list[str]) -> bool:
    try:
        proc = subprocess.run(
            [*bootstrap, "-c", "import sys; sys.exit(0)"],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            timeout=30,
        )
        return proc.returncode == 0
    except Exception:
        return False


def python_has_module(bootstrap: list[str], module: str) -> bool:
    try:
        proc = subprocess.run(
            [*bootstrap, "-c", f"import {module}"],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            timeout=30,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _run_bootstrap(
    bootstrap: list[str], args: list[str], *, capture: bool = False
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    kwargs: dict = {"cwd": str(PROJECT_DIR), "timeout": 300}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run([*bootstrap, *args], **kwargs)


def create_venv_with(bootstrap: list[str]) -> tuple[bool, str]:
    """Tenta criar .venv_native com venv ou, em fallback, virtualenv."""
    last_err = ""

    if python_has_module(bootstrap, "venv"):
        proc = _run_bootstrap(bootstrap, ["-m", "venv", str(VENV_DIR)], capture=True)
        if proc.returncode == 0 and python_works(venv_python()):
            return True, ""
        last_err = ((proc.stderr or proc.stdout or "").strip()) or f"venv falhou (codigo {proc.returncode})"
    else:
        last_err = "modulo venv ausente"

    if not python_has_module(bootstrap, "pip"):
        _run_bootstrap(bootstrap, ["-m", "ensurepip", "--default-pip"], capture=True)

    if python_has_module(bootstrap, "pip"):
        _run_bootstrap(bootstrap, ["-m", "pip", "install", "virtualenv"], capture=True)
        if python_has_module(bootstrap, "virtualenv"):
            proc = _run_bootstrap(
                bootstrap, ["-m", "virtualenv", str(VENV_DIR)], capture=True
            )
            if proc.returncode == 0 and python_works(venv_python()):
                return True, ""
            detail = (proc.stderr or proc.stdout or "").strip()
            last_err = detail or last_err or f"virtualenv falhou (codigo {proc.returncode})"

    return False, last_err


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
    errors: list[str] = []
    for bootstrap in find_bootstrap_python_candidates():
        label = " ".join(bootstrap)
        if not bootstrap_python_works(bootstrap):
            errors.append(f"{label}: Python nao respondeu")
            continue
        ok, detail = create_venv_with(bootstrap)
        if ok:
            log(f"Ambiente virtual criado ({label}).", prefix=prefix)
            return py
        if detail:
            errors.append(f"{label}: {detail}")

    detail = "\n".join(f"  - {line}" for line in errors) if errors else "  - nenhum Python utilizavel"
    raise SystemExit(
        "Nao foi possivel criar .venv_native.\n"
        f"Tentativas:\n{detail}\n\n"
        "Instale Python 3.12+ completo em https://www.python.org/downloads/\n"
        "(marque 'Add python.exe to PATH' e 'pip') e tente de novo."
    )


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
        log("Proximo passo: abra telegram_bot.py e clique em Run.", prefix=prefix)
    elif not telegram_ready:
        log("Setup concluido, mas falta configurar o Telegram.", prefix=prefix)
        log(f"1) Abra o .env e cole o TELEGRAM_BOT_TOKEN", prefix=prefix)
        log("2) Depois abra telegram_bot.py e clique em Run.", prefix=prefix)
    else:
        log("Setup concluido com avisos — revise o resumo acima.", prefix=prefix)
        log("Depois rode telegram_bot.py (Run).", prefix=prefix)

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
    configure_stdio()
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
