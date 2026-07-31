#!/usr/bin/env bash
# Atualiza o bot a partir do GitHub e reinicia o container Docker.
# Uso no Mini PC Ubuntu:
#   ./scripts/deploy.sh
#   ./scripts/deploy.sh /caminho/para/assistente-planilha
set -euo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJECT_DIR"

DEPLOY_BRANCH="${DEPLOY_BRANCH:-master}"
LOCK_FILE="$PROJECT_DIR/logs/deploy.lock"
LOG_DIR="$PROJECT_DIR/logs"
LAST_COMMIT_FILE="$LOG_DIR/.last_deploy_commit"

mkdir -p "$LOG_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "Deploy ja em execucao. Ignorando."
  exit 0
fi

log "=== Deploy Assistente Planilha ==="
log "Pasta: $PROJECT_DIR"
log "Branch: $DEPLOY_BRANCH"

if [[ ! -f docker-compose.yml ]]; then
  log "Erro: docker-compose.yml nao encontrado."
  exit 1
fi

if [[ ! -f .env ]]; then
  log "Erro: .env nao encontrado. Copie de .env.example e configure o token."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  log "Erro: Docker nao instalado."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  log "Erro: Docker daemon nao esta rodando. Inicie com: sudo systemctl start docker"
  exit 1
fi

git fetch origin "$DEPLOY_BRANCH" 2>/dev/null || git fetch origin

REMOTE_REF="origin/$DEPLOY_BRANCH"
if ! git rev-parse --verify "$REMOTE_REF" >/dev/null 2>&1; then
  log "Erro: branch remota $REMOTE_REF nao encontrada."
  exit 1
fi

LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse "$REMOTE_REF")"

if [[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]]; then
  log "Nenhuma atualizacao no GitHub ($LOCAL_HEAD). Container continua como esta."
  docker compose ps
  exit 0
fi

if [[ -f "$LAST_COMMIT_FILE" ]] && [[ "$(cat "$LAST_COMMIT_FILE")" == "$REMOTE_HEAD" ]]; then
  log "GitHub ja foi aplicado nesta versao ($REMOTE_HEAD). Pulando rebuild."
  docker compose ps
  exit 0
fi

log "Nova versao: $LOCAL_HEAD -> $REMOTE_HEAD"
log "Atualizando repositorio..."
git pull --ff-only origin "$DEPLOY_BRANCH"
git lfs pull 2>/dev/null || true

log "Reconstruindo e reiniciando container..."
docker compose up -d --build --remove-orphans

echo "$REMOTE_HEAD" > "$LAST_COMMIT_FILE"
log "Deploy concluido. Commit ativo: $REMOTE_HEAD"
docker compose ps
log "Logs: docker compose logs -f --tail=50"
