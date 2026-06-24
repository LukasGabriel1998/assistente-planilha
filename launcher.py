from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

from src.bootstrap import relaunch_in_project_venv

relaunch_in_project_venv()

import argparse
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
import urllib.request

from streamlit import config as st_config
from streamlit.web import bootstrap
from src.workbook_paths import default_workbook_path
try:
    import webview
except Exception:  # pragma: no cover - optional desktop runtime
    webview = None

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
except Exception:  # pragma: no cover - depends on target machine runtime
    tk = None
    filedialog = None
    messagebox = None


APP_TITLE = "Assistente Financeiro"
WINDOW_BG = "#0F172A"
CARD_BG = "#111827"
TEXT_MAIN = "#F8FAFC"
TEXT_SOFT = "#93C5FD"
MINT = "#14B8A6"
ORANGE = "#FB923C"
RED = "#F43F5E"
APP_WINDOW_TITLE = "Assistente de Planilha por Audio"
WINDOWS_APP_ID = "com.p26.assistenteplanilha"

# Mantem referência viva para o handle de ícone carregado no Win32.
_WINDOWS_ICON_HANDLE = None


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return (base / relative).resolve()


def app_runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_default_workbook() -> str:
    runtime_dir = app_runtime_dir()
    return default_workbook_path([runtime_dir, runtime_dir.parent, Path.cwd(), Path.cwd().parent])


def find_available_port(start: int = 8501, max_tries: int = 40) -> int:
    for port in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Nao foi possivel encontrar porta livre para iniciar o app.")


def _set_windows_app_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except Exception:
        pass


def _apply_windows_icon_by_title(window_title: str, icon_path: Path) -> bool:
    """Aplica ícone .ico em janela Win32 pelo título (canto superior e barra de tarefas)."""
    if os.name != "nt" or not icon_path.exists():
        return False
    try:
        user32 = ctypes.windll.user32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040

        hwnd = user32.FindWindowW(None, window_title)
        if not hwnd:
            return False

        global _WINDOWS_ICON_HANDLE
        _WINDOWS_ICON_HANDLE = user32.LoadImageW(
            None,
            str(icon_path),
            IMAGE_ICON,
            0,
            0,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )
        if not _WINDOWS_ICON_HANDLE:
            return False

        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, _WINDOWS_ICON_HANDLE)
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, _WINDOWS_ICON_HANDLE)
        return True
    except Exception:
        return False


def _wait_and_apply_windows_icon(window_title: str, icon_path: Path, timeout_sec: int = 20) -> None:
    deadline = time.time() + max(1, int(timeout_sec))
    while time.time() < deadline:
        if _apply_windows_icon_by_title(window_title, icon_path):
            return
        time.sleep(0.25)


def wait_http_ready(port: int, timeout_sec: int = 90) -> bool:
    deadline = time.time() + timeout_sec
    health_urls = [
        f"http://127.0.0.1:{port}/_stcore/health",
        f"http://127.0.0.1:{port}",
    ]
    while time.time() < deadline:
        for url in health_urls:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return True
            except Exception:
                pass
        time.sleep(0.5)
    return False


def desktop_window_supported() -> bool:
    return webview is not None


def run_desktop_window(port: int) -> None:
    if webview is None:
        raise RuntimeError("pywebview nao esta instalado.")

    _set_windows_app_id()
    icon_path = resource_path("assets/p26.ico")
    if os.name == "nt" and icon_path.exists():
        threading.Thread(
            target=_wait_and_apply_windows_icon,
            args=(APP_WINDOW_TITLE, icon_path, 20),
            daemon=True,
        ).start()

    url = f"http://127.0.0.1:{port}"
    webview.create_window(
        APP_WINDOW_TITLE,
        url=url,
        width=1280,
        height=860,
        min_size=(1024, 720),
    )
    webview.start(debug=False)


def run_streamlit_server(port: int, workbook: str) -> None:
    app_file = resource_path("app.py")
    if not app_file.exists():
        raise FileNotFoundError(f"Arquivo app.py nao encontrado em: {app_file}")

    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_SERVER_FILEWATCHERTYPE"] = "none"
    os.environ["STREAMLIT_SERVER_RUNONSAVE"] = "false"
    os.environ["STREAMLIT_RUNNER_FASTRERUNS"] = "false"
    if workbook.strip():
        os.environ["WORKBOOK_PATH"] = workbook.strip()

    # Forca opcoes de runtime para o processo servidor respeitar a porta escolhida.
    st_config.set_option("global.developmentMode", False)
    st_config.set_option("server.headless", True)
    st_config.set_option("server.port", int(port))
    st_config.set_option("server.address", "127.0.0.1")
    st_config.set_option("server.fileWatcherType", "none")
    st_config.set_option("server.runOnSave", False)
    st_config.set_option("browser.gatherUsageStats", False)
    st_config.set_option("runner.fastReruns", False)

    bootstrap.run(
        str(app_file),
        False,
        [],
        {
            "server.headless": True,
            "server.port": int(port),
            "server.address": "127.0.0.1",
            "server.fileWatcherType": "none",
            "server.runOnSave": False,
            "browser.gatherUsageStats": False,
            "runner.fastReruns": False,
        },
    )


def build_server_command(port: int, workbook: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [
            sys.executable,
            "--serve",
            "--port",
            str(port),
            "--workbook",
            workbook,
        ]
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--serve",
        "--port",
        str(port),
        "--workbook",
        workbook,
    ]


def build_desktop_command(port: int) -> list[str]:
    if getattr(sys, "frozen", False):
        return [
            sys.executable,
            "--desktop",
            "--port",
            str(port),
        ]
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--desktop",
        "--port",
        str(port),
    ]


class LauncherUI:
    def __init__(self, *, auto_start: bool = True, workbook_override: str = "") -> None:
        _set_windows_app_id()
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("760x520")
        self.root.minsize(720, 480)
        self.root.configure(bg=WINDOW_BG)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        icon_path = resource_path("assets/p26.ico")
        if icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except Exception:
                pass

        self.port: int | None = None
        self.server_started = False
        self.server_process: subprocess.Popen | None = None
        self.desktop_process: subprocess.Popen | None = None
        self.auto_start = auto_start

        self.workbook_var = tk.StringVar(value=find_default_workbook())
        if workbook_override.strip():
            self.workbook_var.set(workbook_override.strip())
        self.status_var = tk.StringVar(value="Pronto para iniciar.")

        self._build_ui()
        if self.auto_start:
            self.root.after(250, self._auto_start_if_possible)

    def _build_ui(self) -> None:
        outer = tk.Frame(self.root, bg=WINDOW_BG, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        top_card = tk.Frame(outer, bg=CARD_BG, padx=20, pady=18)
        top_card.pack(fill="x", pady=(0, 12))

        tk.Label(
            top_card,
            text=APP_WINDOW_TITLE,
            bg=CARD_BG,
            fg=TEXT_MAIN,
            font=("Segoe UI Semibold", 18),
        ).pack(anchor="w")
        tk.Label(
            top_card,
            text="Cliente leigo: fale do seu jeito e confirme antes de salvar.",
            bg=CARD_BG,
            fg=TEXT_SOFT,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        line = tk.Frame(top_card, bg="#1F2937", height=1)
        line.pack(fill="x", pady=10)

        entry_row = tk.Frame(top_card, bg=CARD_BG)
        entry_row.pack(fill="x")
        tk.Label(
            entry_row,
            text="Planilha (.xlsx):",
            bg=CARD_BG,
            fg=TEXT_MAIN,
            font=("Segoe UI", 10),
        ).pack(side="left")
        tk.Entry(
            entry_row,
            textvariable=self.workbook_var,
            bg="#0B1220",
            fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN,
            relief="flat",
            width=62,
            font=("Consolas", 10),
        ).pack(side="left", padx=10, ipady=5)
        tk.Button(
            entry_row,
            text="Selecionar",
            command=self.pick_workbook,
            bg=ORANGE,
            fg="#111827",
            relief="flat",
            font=("Segoe UI Semibold", 9),
            padx=12,
            pady=4,
            cursor="hand2",
        ).pack(side="left")

        actions = tk.Frame(top_card, bg=CARD_BG)
        actions.pack(fill="x", pady=(12, 0))
        self.start_btn = tk.Button(
            actions,
            text="Iniciar Sistema",
            command=self.start_system,
            bg=MINT,
            fg="#052E2B",
            relief="flat",
            font=("Segoe UI Semibold", 11),
            padx=18,
            pady=8,
            cursor="hand2",
        )
        self.start_btn.pack(side="left")

        tk.Button(
            actions,
            text="Abrir Aplicativo",
            command=self.open_client,
            bg="#1D4ED8",
            fg="#E0ECFF",
            relief="flat",
            font=("Segoe UI Semibold", 10),
            padx=14,
            pady=8,
            cursor="hand2",
        ).pack(side="left", padx=8)

        self.status_label = tk.Label(
            actions,
            textvariable=self.status_var,
            bg=CARD_BG,
            fg=TEXT_SOFT,
            font=("Segoe UI", 10),
        )
        self.status_label.pack(side="left", padx=14)

        help_card = tk.Frame(outer, bg=CARD_BG, padx=20, pady=16)
        help_card.pack(fill="both", expand=True)
        tk.Label(
            help_card,
            text="Como usar",
            bg=CARD_BG,
            fg=TEXT_MAIN,
            font=("Segoe UI Semibold", 14),
        ).pack(anchor="w")
        tips = [
            "1) Clique em Iniciar Sistema.",
            "2) Na janela do aplicativo, escolha Gravar audio.",
            "3) Fale da venda, entrada, saldo e material.",
            "4) Revise o que a IA entendeu e clique em Salvar na planilha.",
            "5) Leia o liquido previsto no final do processo.",
        ]
        for tip in tips:
            tk.Label(help_card, text=tip, bg=CARD_BG, fg=TEXT_SOFT, font=("Segoe UI", 10)).pack(anchor="w", pady=2)

        footer = tk.Frame(help_card, bg="#0B1220", padx=12, pady=10)
        footer.pack(fill="x", pady=(16, 0))
        tk.Label(
            footer,
            text="Nao feche esta janela enquanto estiver usando o sistema.",
            bg="#0B1220",
            fg=RED,
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w")

    def set_status(self, text: str, color: str = TEXT_SOFT) -> None:
        self.status_var.set(text)
        self.status_label.configure(fg=color)
        self.root.update_idletasks()

    def pick_workbook(self) -> None:
        if filedialog is None:
            return
        chosen = filedialog.askopenfilename(
            title="Selecione a planilha",
            filetypes=[("Planilhas Excel", "*.xlsx"), ("Todos os arquivos", "*.*")],
        )
        if chosen:
            self.workbook_var.set(chosen)

    def _auto_start_if_possible(self) -> None:
        workbook = self.workbook_var.get().strip()
        if not workbook:
            self.set_status("Selecione a planilha e clique em Iniciar Sistema.", ORANGE)
            return
        if not Path(workbook).exists():
            self.set_status("Planilha padrao nao encontrada. Selecione manualmente.", ORANGE)
            return
        self.start_system()

    def start_system(self) -> None:
        if self.server_started:
            self.open_client()
            return

        workbook = self.workbook_var.get().strip()
        if not workbook:
            if messagebox:
                messagebox.showerror(APP_TITLE, "Selecione uma planilha .xlsx antes de iniciar.")
            return
        if not Path(workbook).exists():
            if messagebox:
                messagebox.showerror(APP_TITLE, "Planilha nao encontrada no caminho informado.")
            return

        self.start_btn.configure(state="disabled")
        self.set_status("Iniciando servidor...", ORANGE)
        threading.Thread(target=self._spawn_server_process, args=(workbook,), daemon=True).start()

    def _spawn_server_process(self, workbook: str) -> None:
        try:
            self.port = find_available_port(8501)
            command = build_server_command(self.port, workbook)
            creation_flags = 0
            if os.name == "nt":
                creation_flags = 0x08000000  # CREATE_NO_WINDOW

            self.server_process = subprocess.Popen(
                command,
                cwd=str(resource_path(".")),
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            if not wait_http_ready(self.port, timeout_sec=90):
                if self.server_process and self.server_process.poll() is None:
                    self.server_process.terminate()
                raise RuntimeError("Servidor nao respondeu a tempo. Tente iniciar novamente.")

            self.server_started = True
            self.root.after(0, lambda: self.set_status("Sistema iniciado com sucesso.", MINT))
            self.root.after(0, self.open_client)
        except Exception as exc:
            self.root.after(0, lambda: self.start_btn.configure(state="normal"))
            self.root.after(0, lambda: self.set_status(f"Erro: {exc}", RED))
            if messagebox:
                self.root.after(0, lambda: messagebox.showerror(APP_TITLE, f"Falha ao iniciar: {exc}"))

    def open_client(self) -> None:
        if not self.port:
            if messagebox:
                messagebox.showinfo(APP_TITLE, "Inicie o sistema primeiro.")
            return

        if self.desktop_process and self.desktop_process.poll() is None:
            self.set_status("Aplicativo nativo ja esta aberto.", MINT)
            return

        if not desktop_window_supported():
            self.set_status("Modo nativo indisponivel neste ambiente.", RED)
            if messagebox:
                messagebox.showerror(
                    APP_TITLE,
                    "O runtime nativo (pywebview) nao esta disponivel. "
                    "Reinstale as dependencias do aplicativo.",
                )
            return

        try:
            command = build_desktop_command(self.port)
            creation_flags = 0
            if os.name == "nt":
                creation_flags = 0x08000000  # CREATE_NO_WINDOW
            self.desktop_process = subprocess.Popen(
                command,
                cwd=str(resource_path(".")),
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.set_status("Aplicativo aberto em janela nativa.", MINT)
            return
        except Exception:
            self.desktop_process = None
            self.set_status("Nao foi possivel abrir o aplicativo nativo.", RED)

    def on_close(self) -> None:
        if self.desktop_process and self.desktop_process.poll() is None:
            try:
                self.desktop_process.terminate()
            except Exception:
                pass
        if self.server_process and self.server_process.poll() is None:
            try:
                self.server_process.terminate()
            except Exception:
                pass
        self.root.destroy()
        os._exit(0)

    def run(self) -> None:
        self.root.mainloop()


def pick_workbook_once(initial_path: str = "") -> str:
    if filedialog is None or tk is None:
        return initial_path.strip()

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        chosen = filedialog.askopenfilename(
            title="Selecione a planilha",
            initialdir=str(Path(initial_path).parent) if initial_path else str(app_runtime_dir()),
            filetypes=[("Planilhas Excel", "*.xlsx"), ("Todos os arquivos", "*.*")],
        )
        return chosen.strip() if chosen else ""
    finally:
        root.destroy()


def resolve_startup_workbook(workbook: str = "") -> str:
    candidate = workbook.strip() or find_default_workbook()
    if candidate and Path(candidate).exists():
        return candidate
    chosen = pick_workbook_once(candidate)
    if chosen and Path(chosen).exists():
        return chosen
    raise RuntimeError("Nenhuma planilha .xlsx foi selecionada para iniciar o aplicativo.")


def run_headless_fallback(workbook: str = "") -> None:
    if not desktop_window_supported():
        raise RuntimeError(
            "O runtime nativo (pywebview) nao esta instalado. "
            "Este aplicativo agora abre somente em modo nativo."
        )

    port = find_available_port(8501)
    workbook = resolve_startup_workbook(workbook)
    command = build_server_command(port, workbook)

    creation_flags = 0
    if os.name == "nt":
        creation_flags = 0x08000000  # CREATE_NO_WINDOW

    process = subprocess.Popen(
        command,
        cwd=str(resource_path(".")),
        creationflags=creation_flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not wait_http_ready(port, timeout_sec=90):
        try:
            process.terminate()
        except Exception:
            pass
        raise RuntimeError("Nao foi possivel iniciar o servidor local.")

    try:
        run_desktop_window(port)
        return
    finally:
        if process.poll() is None:
            process.terminate()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--workbook", type=str, default="")
    parser.add_argument("--manual", action="store_true")
    return parser.parse_known_args()[0]


if __name__ == "__main__":
    args = parse_args()
    if args.serve:
        run_streamlit_server(port=args.port, workbook=args.workbook)
        raise SystemExit(0)
    if args.desktop:
        run_desktop_window(args.port)
        raise SystemExit(0)

    workbook_override = args.workbook.strip()
    if args.manual:
        if tk is None:
            run_headless_fallback(workbook_override)
            raise SystemExit(0)
        try:
            LauncherUI(auto_start=False, workbook_override=workbook_override).run()
        except Exception:
            run_headless_fallback(workbook_override)
        raise SystemExit(0)

    if tk is None:
        run_headless_fallback(workbook_override)
        raise SystemExit(0)

    try:
        run_headless_fallback(workbook_override)
    except Exception:
        if messagebox:
            messagebox.showerror(APP_TITLE, "Falha ao iniciar o aplicativo nativo.")
        raise
