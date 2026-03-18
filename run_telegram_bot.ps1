# Inicia o bot do Telegram (lê TELEGRAM_BOT_TOKEN e WORKBOOK_PATH do .env).
# "Reset" automático: mata instâncias antigas, remove o lock e sobe novamente.
# Assim, quando você colar o comando no Cloud ele volta limpo.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "[Telegram] Reset/Start: limpando instancias antigas..." -ForegroundColor Cyan
try {
  $pids = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*telegram_bot.py*" } |
    Select-Object -ExpandProperty ProcessId
  if ($pids) {
    $pids | ForEach-Object {
      try { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } catch { }
    }
    Write-Host "[Telegram] Processos antigos encerrados." -ForegroundColor Green
  } else {
    Write-Host "[Telegram] Nenhuma instancia antiga encontrada." -ForegroundColor DarkYellow
  }
} catch {
  Write-Host "[Telegram] Aviso: nao foi possivel encerrar alguns processos antigos." -ForegroundColor DarkYellow
}

$lockPath = Join-Path $ScriptDir ".telegram_bot.lock"
if (Test-Path $lockPath) {
  Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
  Write-Host "[Telegram] Lock removido: .telegram_bot.lock" -ForegroundColor Green
}

Write-Host "[Telegram] Iniciando bot..." -ForegroundColor Cyan

$pythonExe = ""
if (Test-Path ".\.venv_native\Scripts\python.exe") {
  $pythonExe = ".\.venv_native\Scripts\python.exe"
} elseif (Test-Path ".\.venv\Scripts\python.exe") {
  $pythonExe = ".\.venv\Scripts\python.exe"
} else {
  $pythonExe = "python"
}

Write-Host ("[Telegram] Usando python: {0}" -f $pythonExe) -ForegroundColor Gray

try {
  # Rodar no mesmo console para permitir Ctrl+C parar.
  & $pythonExe "telegram_bot.py"
} finally {
  # Em geral a própria aplicação remove o lock via atexit, mas isso garante em casos abruptos.
  if (Test-Path $lockPath) {
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
  }
}
