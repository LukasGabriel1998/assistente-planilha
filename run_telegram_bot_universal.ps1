# Universal runner do bot Telegram (sem caminhos fixos).
# - Assume que o bot fica na mesma pasta do projeto (onde este script está).
# - Cria o venv e instala requirements se necessário.
# - Faz "reset" (encerra instancias antigas + remove lock) para rodar no Cloud.

param(
  [switch]$NoInstall
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

function Write-Info([string]$msg) {
  Write-Host $msg -ForegroundColor Cyan
}

function Find-PythonExe {
  if (Test-Path ".\.venv_native\Scripts\python.exe") { return ".\.venv_native\Scripts\python.exe" }
  if (Test-Path ".\.venv\Scripts\python.exe") { return ".\.venv\Scripts\python.exe" }
  # fallback: python do sistema
  return "python"
}

function Ensure-Venv {
  if (Test-Path ".\.venv_native\Scripts\python.exe") { return }

  $venvDir = ".venv_native"
  Write-Info "[Telegram] Criando venv em $venvDir ..."

  $launcher = "py"
  $found = $false
  foreach ($ver in @("3.13","3.12","3.14","3")) {
    try {
      # testa se py -<ver> existe
      & $launcher "-$ver" "-c" "import sys; print(sys.version)" *> $null
      if ($LASTEXITCODE -eq 0) {
        & $launcher "-$ver" "-m" "venv" $venvDir
        if (Test-Path ".\$venvDir\Scripts\python.exe") { $found = $true; break }
      }
    } catch {
      # tenta próxima versão
    }
  }

  if (-not $found) {
    # fallback sem py launcher
    if (Test-Path "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe") {
      & "python" "-m" "venv" $venvDir
    } else {
      & "python" "-m" "venv" $venvDir
    }
  }

  if (-not (Test-Path ".\.venv_native\Scripts\python.exe")) {
    throw "Falha ao criar .venv_native. Instale Python e/ou use o modo manual."
  }
}

function Ensure-Requirements {
  $pythonExe = Find-PythonExe
  Write-Info "[Telegram] Instalando requisitos (requirements.txt) ..."
  & $pythonExe "-m" "pip" "install" "-U" "pip"
  & $pythonExe "-m" "pip" "install" "-r" "requirements.txt"
}

Ensure-Venv

if (-not $NoInstall) {
  Ensure-Requirements
}

$pythonExe = Find-PythonExe

# reset (encerrar processos antigos)
Write-Info "[Telegram] Reset/Start: limpando instancias antigas..."
try {
  $pids = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*telegram_bot.py*" } |
    Select-Object -ExpandProperty ProcessId

  if ($pids) {
    foreach ($pid in $pids) {
      try { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue } catch { }
    }
    Write-Host "[Telegram] Processos antigos encerrados." -ForegroundColor Green
  } else {
    Write-Host "[Telegram] Nenhuma instancia antiga encontrada." -ForegroundColor DarkYellow
  }
} catch {
  Write-Host "[Telegram] Aviso: nao foi possivel encerrar instancias antigas." -ForegroundColor DarkYellow
}

$lockPath = Join-Path $ProjectDir ".telegram_bot.lock"
if (Test-Path $lockPath) {
  Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
  Write-Host "[Telegram] Lock removido: .telegram_bot.lock" -ForegroundColor Green
}

Write-Info "[Telegram] Iniciando bot..."
Write-Host ("[Telegram] Usando python: {0}" -f $pythonExe) -ForegroundColor Gray

try {
  & $pythonExe "telegram_bot.py"
} finally {
  if (Test-Path $lockPath) {
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
  }
}

