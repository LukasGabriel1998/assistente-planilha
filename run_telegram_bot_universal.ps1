# Universal runner do bot Telegram (sem caminhos fixos).
# - Assume que o bot fica na mesma pasta do projeto (onde este script está).
# - Cria o venv e instala requirements se necessário.
# - Faz "reset" (encerra instancias antigas + remove lock) para rodar no Cloud.

param(
  [switch]$NoInstall,
  [string]$TelegramToken
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$envPath = Join-Path $ProjectDir ".env"
$envExamplePath = Join-Path $ProjectDir ".env.example"
if (-not (Test-Path $envPath)) {
  if (Test-Path $envExamplePath) {
    Copy-Item $envExamplePath $envPath -Force
    Write-Host "[Telegram] .env nao existia. Copiei .env.example -> .env. Preencha TELEGRAM_BOT_TOKEN." -ForegroundColor Yellow
  } else {
    Write-Host "[Telegram] Aviso: nem .env nem .env.example foram encontrados. Configure TELEGRAM_BOT_TOKEN e WORKBOOK_PATH." -ForegroundColor DarkYellow
  }
}

# Se o token nao foi preenchido no .env (ou veio vazio), permite setar via parametro
# (ou via variavel de ambiente) para rodar em qualquer maquina com 1 comando.
$tokenToUse = $TelegramToken
if (-not $tokenToUse) { $tokenToUse = $env:TELEGRAM_BOT_TOKEN }

if ($tokenToUse -and ($tokenToUse.Trim().Length -gt 0) -and (Test-Path $envPath)) {
  $lines = Get-Content $envPath -Encoding UTF8
  $found = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*TELEGRAM_BOT_TOKEN\s*=') {
      $lines[$i] = "TELEGRAM_BOT_TOKEN=$tokenToUse"
      $found = $true
    }
  }
  if (-not $found) {
    $lines = @($lines) + @("TELEGRAM_BOT_TOKEN=$tokenToUse")
  }
  Set-Content $envPath -Value $lines -Encoding UTF8
  Write-Host "[Telegram] TELEGRAM_BOT_TOKEN configurado no .env (valor fornecido via parametro/ENV)." -ForegroundColor Green
} elseif (Test-Path $envPath) {
  Write-Host "[Telegram] TELEGRAM_BOT_TOKEN nao foi fornecido (token vazio). Verifique o arquivo .env." -ForegroundColor DarkYellow
}

function Write-Info([string]$msg) {
  Write-Host $msg -ForegroundColor Cyan
}

function Get-FirstExistingPath([string[]]$candidates) {
  foreach ($p in $candidates) {
    if (Test-Path $p) { return $p }
  }
  return $null
}

function Test-PythonExe([string]$exePath) {
  if (-not (Test-Path $exePath)) { return $false }
  $oldPref = $ErrorActionPreference
  try {
    $ErrorActionPreference = "SilentlyContinue"
    # Testa se o "python.exe" do venv realmente funciona (e nao esta apontando
    # para um Python antigo que foi removido).
    & $exePath "-c" "import sys; sys.exit(0)" *> $null
    return ($LASTEXITCODE -eq 0)
  } finally {
    $ErrorActionPreference = $oldPref
  }
}

function Find-PythonExe {
  if (Test-PythonExe ".\.venv_native\Scripts\python.exe") { return ".\.venv_native\Scripts\python.exe" }
  if (Test-PythonExe ".\.venv\Scripts\python.exe") { return ".\.venv\Scripts\python.exe" }
  # fallback: python do sistema
  return "python"
}

function Ensure-Venv {
  $venvDir = ".venv_native"
  $venvPython = ".\$venvDir\Scripts\python.exe"

  # Se o venv existir e funcionar, nao precisa recriar.
  if (Test-PythonExe $venvPython) { return }

  # Se existir mas estiver quebrado, removemos para recriar do zero.
  try { Remove-Item ".\$venvDir" -Recurse -Force -ErrorAction SilentlyContinue } catch { }

  Write-Info "[Telegram] Criando venv em $venvDir ..."

  $found = $false

  # Preferir o launcher "py" com a versão padrão (3.x) para evitar tentar versões inexistentes.
  if (Get-Command "py" -ErrorAction SilentlyContinue) {
    try {
      & py "-3" "-c" "import sys; print(sys.version)" *> $null
      if ($LASTEXITCODE -eq 0) {
        & py "-3" "-m" "venv" $venvDir *> $null
        $found = Test-PythonExe ".\$venvDir\Scripts\python.exe"
      }
    } catch {
      # ignora e tenta fallback
    }
  }

  # Fallback: usar python direto se existir no PATH.
  if (-not $found) {
    if (Get-Command "python" -ErrorAction SilentlyContinue) {
      & python "-m" "venv" $venvDir *> $null
      $found = Test-PythonExe ".\$venvDir\Scripts\python.exe"
    }
  }

  if (-not $found) {
    # Garante que o usuário não fica preso num venv "meio criado".
    try { Remove-Item ".\$venvDir" -Recurse -Force -ErrorAction SilentlyContinue } catch { }
    throw "Falha ao criar/validar .venv_native. Instale Python e/ou use o modo manual."
  }
}

function Ensure-Requirements {
  $pythonExe = ".\.venv_native\Scripts\python.exe"
  if (-not (Test-PythonExe $pythonExe)) {
    throw "Venv .venv_native nao esta funcional. Rode o script com um Python instalado (ou apague .venv_native)."
  }

  # requirements.txt pode estar no diretorio do projeto ou uma pasta acima
  # (dependendo de como o repo foi copiado).
  $parentDir = Split-Path -Parent $ProjectDir
  $reqPath = Get-FirstExistingPath @(
    (Join-Path $ProjectDir "requirements.txt"),
    (Join-Path $parentDir "requirements.txt")
  )

  if (-not $reqPath) {
    throw "Nao encontrei `requirements.txt`. Procurei em: `"$ProjectDir`" e `"$parentDir`""
  }

  Write-Info "[Telegram] Instalando requisitos (requirements.txt): $reqPath"
  & $pythonExe "-m" "pip" "install" "-U" "pip"
  if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar pip." }

  & $pythonExe "-m" "pip" "install" "-r" $reqPath
  if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar requirements." }
}

Ensure-Venv

# Ativa o venv na sessao atual (nao e necessario para rodar o bot, pois
# o script ja usa o python do venv diretamente, mas ajuda a garantir que a
# ambiente do processo esta consistente com o esperado).
$activateScript = ".\.venv_native\Scripts\Activate.ps1"
if (Test-Path $activateScript) {
  try { . $activateScript } catch { }
}

if (-not $NoInstall) {
  Ensure-Requirements
}

$pythonExe = ".\.venv_native\Scripts\python.exe"
if (-not (Test-PythonExe $pythonExe)) {
  throw "Venv .venv_native nao esta funcional. Apague a pasta .venv_native e rode novamente, ou instale o Python correto."
}

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

