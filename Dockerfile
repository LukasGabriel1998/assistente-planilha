FROM python:3.11-slim-bookworm

WORKDIR /app

# ffmpeg — necessário para processar áudio (pacote av / Whisper)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git git-lfs \
    && git lfs install \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Planilha e modelos ficam em volumes (docker-compose) para persistir dados
ENV PYTHONUNBUFFERED=1 \
    WORKBOOK_PATH="dist_novo/AssistentePlanilha/Planilha_Comunicacao_Visual - EDIT.xlsx" \
    WHISPER_LOCAL_MODEL_DIR=models

CMD ["python", "telegram_bot.py"]
