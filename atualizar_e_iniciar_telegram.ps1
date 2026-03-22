# Atualiza o projeto do GitHub e inicia o bot do Telegram (venv + requirements automaticos).
# Uso: clique com botao direito > Executar com PowerShell, ou no terminal:
#   powershell -NoProfile -ExecutionPolicy Bypass -File ".\atualizar_e_iniciar_telegram.ps1"
#
# Opcional: passar o token na linha de comando (grava no .env antes de subir):
#   .\atualizar_e_iniciar_telegram.ps1 -TelegramToken "123456:ABC..."

param(
  [string]$TelegramToken
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "[Telegram] Pasta do projeto: $ScriptDir" -ForegroundColor Gray

if (-not (Test-Path (Join-Path $ScriptDir ".git"))) {
  Write-Host "[Telegram] Aviso: esta pasta nao parece ser um repositorio Git (.git nao encontrado). Pulando git pull." -ForegroundColor Yellow
} else {
  Write-Host "[Telegram] Atualizando do GitHub (git pull)..." -ForegroundColor Cyan
  git pull
  if ($LASTEXITCODE -ne 0) {
    throw "git pull falhou (codigo $LASTEXITCODE). Corrija o Git e tente de novo."
  }
}

$runner = Join-Path $ScriptDir "run_telegram_bot_universal.ps1"
if (-not (Test-Path $runner)) {
  throw "Nao encontrei run_telegram_bot_universal.ps1 em: $ScriptDir"
}

Write-Host "[Telegram] Iniciando runner universal..." -ForegroundColor Cyan
if ($TelegramToken) {
  & $runner -TelegramToken $TelegramToken
} else {
  & $runner
}
