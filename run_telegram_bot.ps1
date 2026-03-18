# Inicia o bot do Telegram (lê TELEGRAM_BOT_TOKEN e WORKBOOK_PATH do .env).
# Configure TELEGRAM_BOT_TOKEN no .env com o token do @BotFather.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
if (Test-Path ".\.venv_native\Scripts\python.exe") {
  .\.venv_native\Scripts\python.exe telegram_bot.py
} elseif (Test-Path ".\.venv\Scripts\python.exe") {
  .\.venv\Scripts\python.exe telegram_bot.py
} else {
  python telegram_bot.py
}
