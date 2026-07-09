# Docker — Assistente Planilha no Mini PC

> **Guia completo para Ubuntu (Linux):** [`DOCKER_UBUNTU.md`](DOCKER_UBUNTU.md)  
> **Atualização automática após git push:** [`DEPLOY_AUTOMATICO.md`](DEPLOY_AUTOMATICO.md)

Guia focado em rodar o **bot do Telegram 24h** no Ubuntu, sem depender do Cursor.

## Visão geral

```
Seu PC (desenvolvimento)          Mini PC Ubuntu (produção)
─────────────────────────         ─────────────────────────
Cursor + testes                   Docker + docker compose
       │                                    │
       ▼                                    ▼
   git push  ──────────────────►  git clone + docker compose up
       │                                    │
       ▼                                    ▼
    GitHub                          Bot rodando 24h
                                    (reinicia sozinho)
```

O bot usa **long polling** do Telegram — não precisa abrir porta no roteador nem Nginx.

---

## Fase A — Agora no Mini PC (só instalar Docker)

Conecte no Mini PC (SSH ou monitor) e rode:

```bash
# 1. Atualizar sistema
sudo apt update && sudo apt upgrade -y

# 2. Instalar Docker (script oficial)
curl -fsSL https://get.docker.com | sudo sh

# 3. Seu usuário poder rodar docker sem sudo
sudo usermod -aG docker $USER
# Faça logout e login de novo para valer

# 4. Docker Compose (plugin já vem no pacote docker.io moderno)
docker compose version

# 5. Docker iniciar com o Ubuntu (geralmente já vem habilitado)
sudo systemctl enable docker
sudo systemctl start docker
```

### Portainer (opcional — interface gráfica)

```bash
docker volume create portainer_data
docker run -d \
  -p 9000:9000 \
  --name portainer \
  --restart=unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest
```

Acesse no navegador: `http://IP-DO-MINI-PC:9000`

---

## Fase B — Aqui no PC de desenvolvimento (antes de migrar)

1. Terminar e testar o bot localmente (`python telegram_bot.py`).
2. Commit + push no GitHub.
3. (Opcional) Testar Docker na sua máquina antes de levar pro Mini PC:

```bash
# Na pasta do projeto
docker compose build
docker compose up
```

Ctrl+C para parar. Para rodar em segundo plano: `docker compose up -d`.

---

## Fase C — Subir no Mini PC

```bash
# 1. Git LFS (modelo de áudio e planilha)
sudo apt install git-lfs -y
git lfs install

# 2. Clonar
git clone https://github.com/lordsofandroid-del/assistente-planilha.git
cd assistente-planilha

# 3. Baixar model.bin e planilha (Git LFS)
git lfs pull

# 4. Configurar ambiente
cp .env.example .env
nano .env   # coloque TELEGRAM_BOT_TOKEN

# 5. Subir o bot
docker compose up -d --build

# 6. Ver logs
docker compose logs -f
```

### Comandos úteis

| Ação | Comando |
|------|---------|
| Ver status | `docker compose ps` |
| Ver logs | `docker compose logs -f` |
| Parar | `docker compose down` |
| Reiniciar | `docker compose restart` |
| Atualizar código | `git pull && docker compose up -d --build` |
| Setup completo (bot + cron) | `./scripts/setup-server.sh` |

---

## Reinício automático

Três camadas (redundância boa):

1. **`restart: unless-stopped`** no `docker-compose.yml` — container volta se o processo cair ou o Docker reiniciar.
2. **Docker habilitado no boot** — `sudo systemctl enable docker`.
3. Após queda de energia — quando o Ubuntu ligar, o Docker sobe e os containers com `unless-stopped` voltam.

---

## Problemas comuns

**Planilha travada** — não abra o `.xlsx` no Excel no Mini PC enquanto o bot roda.

**model.bin pequeno ou ausente** — rode `git lfs pull` na pasta do projeto.

**Bot não responde** — `docker compose logs -f` e confira `TELEGRAM_BOT_TOKEN` no `.env`.

**Sem áudio** — confira se `models/model.bin` existe e se o container tem espaço em disco (~500 MB livres).
