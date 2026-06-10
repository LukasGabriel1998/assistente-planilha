@echo off
setlocal

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"
set "VENV_DIR=.venv_native"

if not exist "%VENV_DIR%\Scripts\python.exe" (
  set "VENV_DIR=.venv"
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [ERRO] Ambiente virtual nao encontrado. Execute: python run_project.py --setup-only
  pause
  exit /b 1
)
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

echo [INFO] Baixando modelo de transcricao (small) para uso local...
@'
from pathlib import Path
from faster_whisper.utils import download_model

root = Path("models")
root.mkdir(parents=True, exist_ok=True)
path = download_model("small", output_dir=str(root))
print("MODEL_PATH=", path)
'@ | "%PYTHON_EXE%" -

if errorlevel 1 (
  echo [ERRO] Falha ao baixar modelo local.
  pause
  exit /b 1
)

echo [OK] Modelo local preparado.
pause
