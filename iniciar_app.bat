@echo off
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

set "VENV_DIR=.venv_native"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

rem Se existir venv mas estiver quebrada (ex.: criada em outro PC), recria.
if exist "%PYTHON_EXE%" goto CHECK_VENV
goto CREATE_VENV

:CHECK_VENV
"%PYTHON_EXE%" -c "import sys; print(sys.executable)" >nul 2>&1
if errorlevel 1 goto RECREATE_VENV
goto INSTALL_DEPS

:RECREATE_VENV
echo [WARN] Ambiente virtual existente esta corrompido. Recriando...
rmdir /s /q "%VENV_DIR%" >nul 2>&1
goto CREATE_VENV

:CREATE_VENV
echo [INFO] Criando ambiente virtual em %PROJECT_DIR%%VENV_DIR% ...
py -3 -m venv "%VENV_DIR%"
if errorlevel 1 goto ERR_CREATE_VENV
goto INSTALL_DEPS

:INSTALL_DEPS
echo [INFO] Instalando/atualizando dependencias...
"%PYTHON_EXE%" -m pip install -U pip
if errorlevel 1 goto ERR_PIP
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto ERR_PIP
goto CHECK_WEBVIEW

:CHECK_WEBVIEW
echo [INFO] Verificando runtime nativo (pywebview)...
"%PYTHON_EXE%" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('webview') else 1)"
if errorlevel 1 goto RUN_BROWSER
goto RUN_DESKTOP

:RUN_DESKTOP
echo [INFO] Nao feche esta janela enquanto usar o sistema.
echo [INFO] Iniciando aplicacao nativa...
"%PYTHON_EXE%" launcher.py
goto END

:RUN_BROWSER
echo [WARN] pywebview nao esta disponivel. Abrindo no navegador (Streamlit)...
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"
"%PYTHON_EXE%" -m streamlit run app.py
goto END

:ERR_CREATE_VENV
echo [ERRO] Falha ao criar venv. Verifique se o Python esta instalado (py launcher).
goto END

:ERR_PIP
echo [ERRO] Falha no pip install.
goto END

:END
pause

