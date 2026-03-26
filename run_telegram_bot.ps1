# Inicia o bot do Telegram (lê TELEGRAM_BOT_TOKEN e WORKBOOK_PATH do .env).
# "Reset" automático: mata instâncias antigas, remove o lock e sobe novamente.
# Assim, quando você colar o comando no Cloud ele volta limpo.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Stop-TelegramBotProcesses {
  param(
    [int]$CurrentPid = $PID
  )
  $lockPath = Join-Path $ScriptDir ".telegram_bot.lock"
  if (Test-Path $lockPath) {
    try {
      $lockPidRaw = (Get-Content $lockPath -ErrorAction SilentlyContinue | Select-Object -First 1)
      $lockPid = 0
      if ([int]::TryParse(($lockPidRaw | Out-String).Trim(), [ref]$lockPid) -and $lockPid -gt 0) {
        if ($lockPid -ne $CurrentPid) {
          try { Stop-Process -Id $lockPid -Force -ErrorAction SilentlyContinue } catch { }
        }
      }
    } catch { }
  }

  try {
    $procs = Get-CimInstance Win32_Process |
      Where-Object {
        $_.ProcessId -ne $CurrentPid -and
        $_.CommandLine -and
        (
          $_.CommandLine -match "(?i)telegram_bot\.py" -or
          $_.CommandLine -match "(?i)run_telegram_bot\.ps1"
        )
      }

    if ($procs) {
      $killed = @()
      foreach ($proc in $procs) {
        try {
          Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
          $killed += [string]$proc.ProcessId
        } catch { }
      }
      if ($killed.Count -gt 0) {
        Write-Host ("[Telegram] Processos antigos encerrados: {0}" -f ($killed -join ", ")) -ForegroundColor Green
      } else {
        Write-Host "[Telegram] Nenhuma instancia antiga encontrada." -ForegroundColor DarkYellow
      }
    } else {
      Write-Host "[Telegram] Nenhuma instancia antiga encontrada." -ForegroundColor DarkYellow
    }
  } catch {
    Write-Host "[Telegram] Aviso: nao foi possivel encerrar alguns processos antigos." -ForegroundColor DarkYellow
  }
}

Write-Host "[Telegram] Reset/Start: limpando instancias antigas..." -ForegroundColor Cyan
Stop-TelegramBotProcesses -CurrentPid $PID

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
} elseif (Test-Path "..\.venv\Scripts\python.exe") {
  # Compatibilidade: em algumas entregas a venv fica na pasta pai do projeto.
  $pythonExe = "..\.venv\Scripts\python.exe"
} else {
  $pythonExe = "python"
}

Write-Host ("[Telegram] Usando python: {0}" -f $pythonExe) -ForegroundColor Gray

$child = $null
try {
  # Sobe como processo filho dedicado para facilitar kill limpo.
  $child = Start-Process -FilePath $pythonExe `
    -ArgumentList "telegram_bot.py" `
    -WorkingDirectory $ScriptDir `
    -NoNewWindow `
    -PassThru

  # Aguarda em foreground. Ctrl+C interrompe aqui no PowerShell.
  Wait-Process -Id $child.Id
} catch {
  # Ignora interrupção do console; o finally cuida do encerramento.
} finally {
  if ($child -and (Get-Process -Id $child.Id -ErrorAction SilentlyContinue)) {
    try {
      # Garante kill da árvore (evita processo órfão).
      taskkill /PID $child.Id /T /F | Out-Null
    } catch {
      try { Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue } catch { }
    }
  }

  # Em geral a própria aplicação remove o lock via atexit, mas isso garante em casos abruptos.
  if (Test-Path $lockPath) {
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
  }
}
