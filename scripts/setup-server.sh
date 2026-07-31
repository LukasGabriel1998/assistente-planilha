#!/usr/bin/env bash
# Configura o Mini PC para rodar o bot 24h via Docker:
# - sobe o container agora
# - garante Docker no boot (apos queda de energia)
# - agenda deploy automatico a cada 5 min (git push -> atualiza sozinho)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

DEPLOY_INTERVAL_MIN="${DEPLOY_INTERVAL_MIN:-5}"

echo "=== Setup servidor — Assistente Planilha ==="
echo "Pasta: $PROJECT_DIR"
echo ""

if [[ ! -f .env ]]; then
  echo "Erro: .env nao encontrado. Copie de .env.example e configure o token."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Erro: Docker nao instalado. Veja docs/DOCKER_UBUNTU.md"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Erro: Docker daemon nao esta rodando."
  echo "Tente: sudo systemctl start docker"
  exit 1
fi

mkdir -p "$PROJECT_DIR/dist_novo/AssistentePlanilha" "$PROJECT_DIR/models" "$PROJECT_DIR/logs"
chmod +x "$PROJECT_DIR/scripts/deploy.sh"

echo "[1/4] Garantindo Docker ativo no boot do Ubuntu..."
if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl enable docker 2>/dev/null || true
  sudo systemctl start docker 2>/dev/null || true
  echo "      Docker: $(systemctl is-active docker 2>/dev/null || echo 'ativo')"
else
  echo "      systemctl indisponivel — pule se nao for Ubuntu com systemd."
fi

echo "[2/4] Subindo bot no Docker (restart: unless-stopped)..."
docker compose up -d --build
docker compose ps
echo ""

echo "[3/4] Testando deploy.sh (sem rebuild se ja estiver atualizado)..."
"$PROJECT_DIR/scripts/deploy.sh" || true
echo ""

echo "[4/4] Configurando deploy automatico (cron a cada ${DEPLOY_INTERVAL_MIN} min)..."
CRON_LINE="*/${DEPLOY_INTERVAL_MIN} * * * * \"$PROJECT_DIR/scripts/deploy.sh\" >> \"$PROJECT_DIR/logs/deploy.log\" 2>&1"
(
  crontab -l 2>/dev/null | grep -v "scripts/deploy.sh" || true
  echo "$CRON_LINE"
) | crontab -

echo ""
echo "=== Pronto ==="
echo ""
echo "Cron instalado:"
crontab -l | grep deploy.sh || true
echo ""
echo "O bot roda sozinho no Docker — pode fechar o Cursor."
echo "Se a energia cair e o PC reiniciar, o bot sobe de novo automaticamente."
echo ""
echo "Para atualizar o bot depois de editar no Cursor:"
echo "  1. git add . && git commit -m \"...\" && git push"
echo "  2. Em ate ${DEPLOY_INTERVAL_MIN} min o Mini PC atualiza sozinho"
echo ""
echo "Comandos uteis:"
echo "  docker compose ps"
echo "  docker compose logs -f"
echo "  tail -f \"$PROJECT_DIR/logs/deploy.log\""
echo "  ./scripts/deploy.sh   # atualizar na hora, sem esperar o cron"
