$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ScriptDir

Write-Host "[Telegram] Parando instancias ativas..." -ForegroundColor Cyan

# 1) Tenta parar pelo PID salvo no lock
$lockPath = Join-Path $ScriptDir ".telegram_bot.lock"
if (Test-Path $lockPath) {
  try {
    $pidText = (Get-Content $lockPath | Select-Object -First 1).ToString().Trim()
    $pidValue = 0
    if ([int]::TryParse($pidText, [ref]$pidValue) -and $pidValue -gt 0) {
      try { Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue } catch { }
    }
  } catch { }
}

# 2) Mata qualquer processo com telegram_bot.py/run_telegram_bot.ps1 na linha de comando
try {
  $procs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and (
      $_.CommandLine -match "(?i)telegram_bot\.py" -or
      $_.CommandLine -match "(?i)run_telegram_bot\.ps1"
    )
  }
  foreach ($proc in $procs) {
    try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue } catch { }
  }
} catch { }

# 3) Remove lock
if (Test-Path $lockPath) {
  Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
}

Write-Host "[Telegram] Bot parado. (se houver)" -ForegroundColor Green
