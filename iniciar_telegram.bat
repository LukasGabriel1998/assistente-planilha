@echo off
setlocal EnableDelayedExpansion

rem Inicia o bot Telegram em uma janela CMD visivel.
rem Duplo clique: abre janela sozinho.
rem
rem AGENDADOR DE TAREFAS (nao fechar na hora):
rem   Programa/script : C:\Windows\System32\cmd.exe
rem   Argumentos      : /k cd /d "%PROJECT_DIR%" ^&^& "%~f0" /janela
rem   Iniciar em       : (deixe vazio — o /k ja entra na pasta)
rem   Geral           : "Executar somente quando o usuario estiver conectado"
rem   Configuracoes   : desmarque "Encerrar tarefa se estiver em execucao por mais de..."
rem O /k mantem o CMD aberto; o /janela roda o bot e da pause se der erro.

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

set "VENV_PY=%PROJECT_DIR%.venv_native\Scripts\python.exe"
if not exist "%VENV_PY%" (
  set "VENV_PY=%PROJECT_DIR%.venv\Scripts\python.exe"
)

if exist "%VENV_PY%" (
  set "PYTHON_CMD=%VENV_PY%"
) else (
  where py >nul 2>&1
  if not errorlevel 1 (
    set "PYTHON_CMD=py"
    set "PYTHON_ARGS=-3"
  ) else (
    set "PYTHON_CMD=python"
    set "PYTHON_ARGS="
  )
)

rem Segunda chamada: roda dentro da janela CMD aberta
if /i "%~1"=="/janela" goto :run_bot

rem Primeira chamada: abre nova janela CMD e encerra (Agendador ve sucesso ao abrir a janela)
start "Bot Telegram - Assistente Planilha" cmd /k ""%~f0" /janela"
exit /b 0

:run_bot
title Bot Telegram - Assistente Planilha
color 0A
cls

echo.
echo ============================================================
echo   Bot Telegram - Assistente Planilha
echo ============================================================
echo   Pasta : %PROJECT_DIR%
echo   Python: %PYTHON_CMD% %PYTHON_ARGS%
echo   Inicio: %date% %time%
echo ============================================================
echo.
echo Aguarde... preparando ambiente e iniciando o robo.
echo Para parar: feche esta janela ou pressione Ctrl+C.
echo.

if exist "%PROJECT_DIR%.env" (
  echo   [OK] Arquivo .env encontrado
) else (
  echo   [!!] Arquivo .env NAO encontrado — configure TELEGRAM_BOT_TOKEN
)

if exist "%VENV_PY%" (
  echo   [OK] Ambiente Python: %VENV_PY%
) else (
  echo   [..] Ambiente virtual sera criado na primeira execucao
)

echo.

if not exist "logs" mkdir "logs"
echo [%date% %time%] Janela CMD aberta>> "logs\telegram_agendador.log"

if defined PYTHON_ARGS (
  "%PYTHON_CMD%" %PYTHON_ARGS% -u "%PROJECT_DIR%run_telegram.py"
) else (
  "%PYTHON_CMD%" -u "%PROJECT_DIR%run_telegram.py"
)

set "EXIT_CODE=!ERRORLEVEL!"
echo.
echo ============================================================
if !EXIT_CODE! equ 0 (
  echo   Bot encerrado normalmente.
) else (
  echo   Bot encerrado com erro. Codigo: !EXIT_CODE!
  echo   Verifique TELEGRAM_BOT_TOKEN no .env e o log em logs\telegram_agendador.log
)
echo ============================================================
echo.

echo [%date% %time%] Encerrado com codigo !EXIT_CODE!>> "logs\telegram_agendador.log"
pause
exit /b !EXIT_CODE!
