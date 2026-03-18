# Assistente de Planilha por Audio (MVP)

Projeto para cliente leigo, com foco em simplicidade:

1. Gravar audio, enviar audio ou digitar texto.
2. O assistente interpreta a mensagem financeira em portugues.
3. Mostra um resumo claro do que entendeu.
4. Voce confirma e salva.
5. A planilha e atualizada e o liquido previsto aparece na tela.

## O que foi entregue

- `app.py`: interface visual principal (Streamlit).
- `src/parser.py`: interpreta texto livre (cliente, venda, entrada, saldo, material, datas).
- `src/transcription.py`: transcricao local com `faster-whisper`.
- `src/excel_store.py`: escrita segura no Excel e historico em `Log_Agente`.
- `iniciar_app.bat`: atalho 1 clique para abrir o app.
- `launcher.py`: interface desktop para cliente leigo.
- `build_exe.bat`: gera executavel para distribuicao.
- `empacotar_cliente.bat`: gera arquivo ZIP pronto para envio.
- `preparar_modelo_audio.bat`: baixa modelo local de transcricao para uso sem depender de download no primeiro audio.

## Rodar com 1 clique (Windows)

1. Abra a pasta do projeto.
2. Dê duplo clique em `iniciar_app.bat`.
3. Mantenha a janela do terminal aberta.
4. Abra `http://127.0.0.1:8501`.

Esse script:

- cria `.venv` se nao existir;
- instala dependencias;
- inicia o Streamlit sem prompt de email.
- fixa a porta em `8501`.

## Gerar executavel para cliente

1. Execute `build_exe.bat`.
2. Aguarde o final do build.
3. Entregue a pasta `dist_novo\AssistentePlanilha` para o cliente.
4. Opcional: execute `empacotar_cliente.bat` para criar `dist_novo\AssistentePlanilha.zip`.

Para experiencia melhor com audio no cliente:

1. Execute `preparar_modelo_audio.bat` antes do build.
2. Depois execute `build_exe.bat`.
3. O build inclui automaticamente a pasta `models` se ela existir.

Arquivos importantes da entrega:

- `dist_novo\AssistentePlanilha\AssistentePlanilha.exe`
- `dist_novo\AssistentePlanilha\INICIAR_CLIENTE.bat`
- planilha `.xlsx` (copiada automaticamente se existir no projeto)

Fluxo do cliente:

1. Duplo clique em `INICIAR_CLIENTE.bat` (ou no `.exe`).
2. Selecionar planilha.
3. Clicar `Iniciar Sistema`.
4. Abrir no navegador e usar `Gravar audio`.

## Rodar manualmente

```powershell
cd "C:\caminho\para\Robo-agente-planilha"
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Fluxo ideal para cliente leigo

1. Escolher `Gravar audio`.
2. Falar naturalmente. Exemplo:
   `fiz uma venda de 2000, entrou metade hoje, saldo dia 30, vou gastar uns 800 de material`
3. Clicar em `Interpretar comando`.
4. Conferir os campos principais.
5. Clicar em `Salvar na planilha`.
6. Ler o resultado na tela:
   `Planilha atualizada. Liquido previsto desta venda: ...`

## Abas usadas da planilha

- `TOTAL DE VENDAS DE 2026`
- `Compras Materia-Prima` (o sistema tambem encontra variacao com acento)
- `Gastos Fixos`
- `Log_Agente` (criada automaticamente se nao existir)

## Correcao de erro

- Antes de salvar: ajuste os campos na tela.
- Depois de salvar: ative `Mostrar painel avancado` e use `Correcao rapida de linha`.

## Telegram

Arquivo: `telegram_bot.py`

Passos:

1. Copiar `.env.example` para `.env`.
2. Definir `TELEGRAM_BOT_TOKEN` (token do @BotFather).
3. Rodar `run_telegram_bot.ps1` (ou `python telegram_bot.py`).

## Limites deste MVP

- Parser por regras: cobre muitos casos, mas nao 100% das falas.
- Sempre revisar antes de salvar quando houver alerta de campos faltando.
- Transcricao local pode ficar mais lenta no primeiro uso.
