<# 
Reinicia o bot do Telegram em três passos:
1) Encerra qualquer processo python com telegram_bot.py
2) Remove o arquivo de trava .telegram_bot.lock (se existir)
3) Inicia o bot usando a venv .venv_native
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "[reset_bot] Encerrando instancias antigas do bot..." -ForegroundColor Yellow
try {
  $pids = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*telegram_bot.py*" } | Select-Object -ExpandProperty ProcessId
  if ($pids) {
    Stop-Process -Id $pids -Force -ErrorAction SilentlyContinue
    Write-Host "[reset_bot] Processos finalizados: $($pids -join ', ')." -ForegroundColor Green
  } else {
    Write-Host "[reset_bot] Nenhum processo telegram_bot.py em execucao." -ForegroundColor DarkYellow
  }
} catch {
  Write-Host "[reset_bot] Nao foi possivel encerrar processos (talvez nenhum estivesse rodando)." -ForegroundColor DarkYellow
}

$lockPath = Join-Path $ScriptDir ".telegram_bot.lock"
if (Test-Path $lockPath) {
  Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
  Write-Host "[reset_bot] Arquivo de trava .telegram_bot.lock removido." -ForegroundColor Green
} else {
  Write-Host "[reset_bot] Nenhum arquivo .telegram_bot.lock encontrado." -ForegroundColor DarkYellow
}

Write-Host "[reset_bot] Iniciando bot do Telegram..." -ForegroundColor Cyan
if (Test-Path ".\.venv_native\Scripts\python.exe") {
  .\.venv_native\Scripts\python.exe telegram_bot.py
} elseif (Test-Path ".\.venv\Scripts\python.exe") {
  .\.venv\Scripts\python.exe telegram_bot.py
} else {
  python telegram_bot.py
}

