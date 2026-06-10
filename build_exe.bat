@echo off
setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"
set "APP_NAME=AssistentePlanilha"
set "DIST_DIR=dist_novo"
set "WORK_DIR=build_novo"
set "APP_DIR=%DIST_DIR%\%APP_NAME%"
set "OUT_EXE=%APP_DIR%\%APP_NAME%.exe"
set "WORKBOOK_STAGE=%PROJECT_DIR%_build_workbook_source.xlsx"
set "WORKBOOK_SOURCE="
set "WORKBOOK_OUTPUT_NAME="
set "VENV_DIR=.venv_native"

if not exist "%VENV_DIR%\Scripts\python.exe" (
  set "VENV_DIR=.venv"
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  set "VENV_DIR=..\.venv_native"
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  set "VENV_DIR=..\.venv"
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [ERRO] Ambiente virtual nao encontrado. Execute: python run_project.py --setup-only
  pause
  exit /b 1
)
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PYINSTALLER_EXE=%VENV_DIR%\Scripts\pyinstaller.exe"

echo [INFO] Python usado no build:
"%PYTHON_EXE%" -c "import sys; print(sys.version)"
echo.

echo [INFO] Garantindo PyInstaller...
if not exist "%PYINSTALLER_EXE%" (
  "%PYTHON_EXE%" -m pip install pyinstaller
  if errorlevel 1 (
    echo [ERRO] Falha ao instalar PyInstaller.
    pause
    exit /b 1
  )
)

echo [INFO] Limpando builds anteriores...
if exist "%DIST_DIR%" (
  rem A planilha fica ao lado do exe: dist_novo\AssistentePlanilha\*.xlsx
  for %%F in ("%APP_DIR%\*.xlsx") do (
    if not defined WORKBOOK_SOURCE (
      copy /Y "%%~fF" "%WORKBOOK_STAGE%" >nul
      set "WORKBOOK_SOURCE=%WORKBOOK_STAGE%"
      set "WORKBOOK_OUTPUT_NAME=%%~nxF"
    )
  )
  for %%F in ("%APP_DIR%\*.xlsm") do (
    if not defined WORKBOOK_SOURCE (
      copy /Y "%%~fF" "%WORKBOOK_STAGE%" >nul
      set "WORKBOOK_SOURCE=%WORKBOOK_STAGE%"
      set "WORKBOOK_OUTPUT_NAME=Planilha.xlsm"
    )
  )
)
if not defined WORKBOOK_SOURCE (
  for %%F in (*.xlsx) do (
    if not defined WORKBOOK_SOURCE (
      copy /Y "%%~fF" "%WORKBOOK_STAGE%" >nul
      set "WORKBOOK_SOURCE=%WORKBOOK_STAGE%"
      set "WORKBOOK_OUTPUT_NAME=%%~nxF"
    )
  )
)
rem workbook_stage_done (nao usado mais)
rem workbook_stage_done (nao usado mais)

if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

set "EXTRA_MODELS_ARG="
if exist "models" (
  set "EXTRA_MODELS_ARG=--add-data models;models"
  echo [INFO] Incluindo pasta local de modelos de audio no executavel.
)

set "WEBVIEW_COLLECT_ARG="
"%PYTHON_EXE%" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('webview') else 1)"
if not errorlevel 1 (
  set "WEBVIEW_COLLECT_ARG=--collect-all webview"
  echo [INFO] pywebview encontrado. O build vai incluir janela nativa.
) else (
  echo [ERRO] pywebview nao encontrado neste ambiente.
  echo [DICA] Para gerar o executavel nativo, instale Python 3.13 ou 3.12 e rode: python run_project.py --setup-only
  echo [DICA] No Python 3.14 o pywebview/pythonnet pode falhar na instalacao dependendo do ambiente.
  pause
  exit /b 1
)

echo [INFO] Gerando executavel...
"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name "%APP_NAME%" ^
  --distpath "%DIST_DIR%" ^
  --workpath "%WORK_DIR%" ^
  --icon "assets\\p26.ico" ^
  --add-data "app.py;." ^
  --add-data "src;src" ^
  --add-data "assets;assets" ^
  --collect-all streamlit ^
  --collect-all altair ^
  --collect-all pydeck ^
  --collect-all pandas ^
  --collect-all numpy ^
  --collect-all openpyxl ^
  --collect-all dateparser ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all tokenizers ^
  --collect-all onnxruntime ^
  --collect-all huggingface_hub ^
  --collect-all av ^
  %WEBVIEW_COLLECT_ARG% ^
  %EXTRA_MODELS_ARG% ^
  launcher.py

if errorlevel 1 (
  echo [ERRO] Build falhou.
  pause
  exit /b 1
)

if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"

set "COPIED_WORKBOOK="
if defined WORKBOOK_SOURCE if exist "%WORKBOOK_SOURCE%" (
  if not defined WORKBOOK_OUTPUT_NAME for %%F in ("%WORKBOOK_SOURCE%") do set "WORKBOOK_OUTPUT_NAME=%%~nxF"
  copy /Y "%WORKBOOK_SOURCE%" "%APP_DIR%\%WORKBOOK_OUTPUT_NAME%" >nul
  set "COPIED_WORKBOOK=%WORKBOOK_OUTPUT_NAME%"
  rem Mantem compatibilidade com clientes que usam o nome antigo da planilha.
  if /I "%WORKBOOK_OUTPUT_NAME%"=="Planilha.xlsx" (
    copy /Y "%APP_DIR%\%WORKBOOK_OUTPUT_NAME%" "%APP_DIR%\Planilha_Comunicacao_Visual - EDIT.xlsx" >nul
  )
)
if exist "%WORKBOOK_STAGE%" del /q "%WORKBOOK_STAGE%"

> "%DIST_DIR%\INICIAR_ASSISTENTE.bat" (
  echo @echo off
  echo setlocal
  echo cd /d "%%~dp0"
  echo start "" "%%~dp0%APP_NAME%\%APP_NAME%.exe"
)

echo.
echo [OK] Build concluido.
echo [OK] Executavel: %OUT_EXE%
echo [OK] Atalho de inicializacao: %DIST_DIR%\INICIAR_ASSISTENTE.bat
if defined COPIED_WORKBOOK (
  echo [OK] Planilha copiada para o build: %APP_DIR%\!COPIED_WORKBOOK!
) else (
  echo [AVISO] Nenhuma planilha .xlsx foi copiada para %DIST_DIR%.
)
pause
