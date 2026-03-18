@echo off
setlocal

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"
set "APP_NAME=AssistentePlanilha"
set "DIST_DIR=dist_novo"
set "OUT_EXE=%DIST_DIR%\%APP_NAME%.exe"
set "ZIP_PATH=%DIST_DIR%\%APP_NAME%.zip"
set "ZIP_STAGE=%DIST_DIR%\_zip_stage"

if not exist "%OUT_EXE%" (
  echo [ERRO] Executavel nao encontrado. Rode build_exe.bat primeiro.
  pause
  exit /b 1
)

if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"
if exist "%ZIP_STAGE%" rmdir /s /q "%ZIP_STAGE%"
mkdir "%ZIP_STAGE%"

copy /Y "%OUT_EXE%" "%ZIP_STAGE%\" >nul
for %%F in ("%DIST_DIR%\*.xlsx") do copy /Y "%%~fF" "%ZIP_STAGE%\" >nul

echo [INFO] Gerando arquivo ZIP para envio...
powershell -NoProfile -Command "Compress-Archive -Path '%ZIP_STAGE%\*' -DestinationPath '%ZIP_PATH%' -Force"

if errorlevel 1 (
  echo [ERRO] Falha ao gerar ZIP.
  if exist "%ZIP_STAGE%" rmdir /s /q "%ZIP_STAGE%"
  pause
  exit /b 1
)

if exist "%ZIP_STAGE%" rmdir /s /q "%ZIP_STAGE%"

echo [OK] Arquivo pronto: %ZIP_PATH%
pause
