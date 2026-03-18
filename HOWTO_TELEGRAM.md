# Bot no Telegram – Planilha

O bot do Telegram usa a **mesma planilha** e a mesma lógica do app (vendas, estornos, status, resumo).

## 1. Criar o bot no Telegram

1. Abra o Telegram e procure por **@BotFather**.
2. Envie: `/newbot`
3. Siga as instruções: nome do bot (ex.: "Meu Robô Planilha") e username (ex.: `meu_robo_planilha_bot`).
4. O BotFather vai enviar um **token** (ex.: `7123456789:AAH...`). Copie esse token.

## 2. Configurar o projeto

1. No arquivo **`.env`** na pasta do projeto, adicione:
   ```env
   TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
   (substitua pelo token que o BotFather enviou)

2. Opcional: se a planilha não estiver na pasta do projeto, defina também:
   ```env
   WORKBOOK_PATH=C:\caminho\completo\para\sua_planilha.xlsx
   ```

## 3. Rodar o bot

1. Ative o ambiente virtual (se usar):
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
2. Execute:
   ```powershell
   python telegram_bot.py
   ```
3. No Telegram, abra o seu bot (pelo username que você criou) e envie uma mensagem.

**Não precisa de ngrok nem de abrir porta.** O script usa long polling e funciona atrás de qualquer rede.

## Comandos

- **Texto de venda/estorno/status**  
  Ex.: *"Vendi uma placa para o João por 2000"* → atualiza a planilha e o bot responde confirmando.

- **Resumo da planilha**  
  Palavras como: *resumo*, *status*, *planilha*, *como está* → o bot envia um resumo do preenchimento (vendas, matéria-prima, gastos fixos).

## Parar o bot

No terminal onde está rodando, pressione **Ctrl+C**.
