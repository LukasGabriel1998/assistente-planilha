# Inicia a API HTTP para integracao com n8n
$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$VenvPython = Join-Path $ProjectDir ".venv_native\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
}
if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERRO] Ambiente virtual nao encontrado. Execute iniciar_app.bat primeiro."
    exit 1
}

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + `
    [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "[INFO] Iniciando API n8n em http://127.0.0.1:8765 (docs em /docs)"
& $VenvPython n8n_api.py
