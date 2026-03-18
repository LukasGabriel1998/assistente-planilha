@echo off
cd /d "%~dp0"
title Assistente Planilha por Audio

set "PYTHON_EXE="
if exist ".venv_native\Scripts\python.exe" (
    set "PYTHON_EXE=.venv_native\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

if "%PYTHON_EXE%"=="" (
    echo Ambiente virtual nao encontrado. Execute iniciar_app.bat primeiro.
    pause
    exit /b 1
)

echo.
echo Iniciando o Assistente... A janela nativa vai abrir em instantes.
echo Para encerrar: feche esta janela ou pressione Ctrl+C.
echo.

"%PYTHON_EXE%" launcher.py

pause
