#!/usr/bin/env bash
# Atualiza o bot a partir do GitHub e reinicia o container Docker.
# Uso no Mini PC Ubuntu:
#   ./scripts/deploy.sh
#   ./scripts/deploy.sh /caminho/para/assistente-planilha
set -euo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJECT_DIR"

DEPLOY_BRANCH="${DEPLOY_BRANCH:-master}"

echo "=== Deploy Assistente Planilha ==="
echo "Pasta: $PROJECT_DIR"
echo "Branch: $DEPLOY_BRANCH"
echo ""

if [[ ! -f docker-compose.yml ]]; then
  echo "Erro: docker-compose.yml nao encontrado em $PROJECT_DIR"
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Erro: arquivo .env nao encontrado. Copie de .env.example e configure o token."
  exit 1
fi

git fetch origin "$DEPLOY_BRANCH" 2>/dev/null || git fetch origin

if git diff --quiet HEAD "origin/$DEPLOY_BRANCH" 2>/dev/null; then
  echo "Nenhuma atualizacao no GitHub. Container continua como esta."
  docker compose ps
  exit 0
fi

echo "Nova versao encontrada. Atualizando..."
git pull origin "$DEPLOY_BRANCH"
git lfs pull 2>/dev/null || true

echo "Reconstruindo e reiniciando container..."
docker compose up -d --build

echo ""
echo "Deploy concluido."
docker compose ps
echo ""
echo "Logs: docker compose logs -f --tail=50"
