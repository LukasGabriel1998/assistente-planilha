# Docker no Ubuntu (Mini PC) — passo a passo completo

Guia **100% Linux** para rodar o Assistente Planilha no seu Mini PC com Ubuntu.

---

## O que você vai ter no final

```
Mini PC Ubuntu
    │
    ├── Docker (liga com o sistema)
    │
    └── Container assistente-planilha-bot
            │
            ├── Bot Telegram 24h
            ├── Reinicia sozinho se cair
            └── Atualiza quando você der git push (cron opcional)
```

**Importante:** tudo aqui usa caminhos Linux, comandos `bash` e `docker compose` — não depende do Windows nem do Cursor.

---

## PARTE 1 — Instalar Docker no Ubuntu (faça isso primeiro)

Abra o **Terminal** no Mini PC (ou conecte por SSH).

### Passo 1.1 — Atualizar o sistema

```bash
sudo apt update
sudo apt upgrade -y
```

### Passo 1.2 — Instalar Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
```

### Passo 1.3 — Rodar Docker sem `sudo`

```bash
sudo usermod -aG docker $USER
```

**Deslogue e logue de novo** (ou reinicie o Mini PC). Sem isso o comando `docker` pode dar erro de permissão.

### Passo 1.4 — Docker ligar com o Ubuntu

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

### Passo 1.5 — Testar

```bash
docker --version
docker compose version
docker run --rm hello-world
```

Se aparecer "Hello from Docker!", está instalado.

---

## PARTE 2 — Colocar o projeto no Mini PC

Faça isso **depois** que o bot estiver estável no seu PC e você tiver dado `git push` no GitHub.

### Passo 2.1 — Ferramentas extras

```bash
sudo apt install -y git git-lfs nano
git lfs install
```

### Passo 2.2 — Clonar o repositório

```bash
cd ~
git clone https://github.com/lordsofandroid-del/assistente-planilha.git
cd assistente-planilha
```

### Passo 2.3 — Baixar o modelo de áudio e a planilha (Git LFS)

```bash
git lfs pull
ls -lh models/model.bin
ls -lh "dist_novo/AssistentePlanilha/Planilha_Comunicacao_Visual - EDIT.xlsx"
```

O `model.bin` deve ter ~461 MB. A planilha deve ser um `.xlsx` válido (não um ponteiro LFS de poucos bytes).

### Passo 2.4 — Criar o `.env`

```bash
cp .env.example .env
nano .env
```

Edite e coloque seu token:

```env
TELEGRAM_BOT_TOKEN=seu_token_do_botfather
WORKBOOK_PATH=dist_novo/AssistentePlanilha/Planilha_Comunicacao_Visual - EDIT.xlsx
WHISPER_MODEL=small
WHISPER_LOCAL_MODEL_DIR=models
```

Salvar no nano: `Ctrl+O`, Enter, `Ctrl+X`.

### Passo 2.5 — Dar permissão aos scripts

```bash
chmod +x scripts/deploy.sh scripts/setup-server.sh
```

### Passo 2.6 — Subir o bot (setup completo)

Opção recomendada — sobe o bot, configura reinício e deploy automático:

```bash
./scripts/setup-server.sh
```

Ou manualmente:

```bash
docker compose up -d --build
```

### Passo 2.7 — Conferir se está rodando

```bash
docker compose ps
docker compose logs -f
```

Teste no Telegram. Para sair dos logs: `Ctrl+C`.

---

## PARTE 3 — Comandos do dia a dia (Ubuntu)

Todos os comandos abaixo, rode **dentro da pasta do projeto**:

```bash
cd ~/assistente-planilha
```

| O que fazer | Comando |
|-------------|---------|
| Ver se está rodando | `docker compose ps` |
| Ver logs ao vivo | `docker compose logs -f` |
| Parar o bot | `docker compose down` |
| Iniciar de novo | `docker compose up -d` |
| Reiniciar (sem atualizar código) | `docker compose restart` |
| **Atualizar manualmente** do GitHub | `./scripts/deploy.sh` |

---

## PARTE 4 — Reinício automático (queda de energia)

Já está configurado no `docker-compose.yml`:

```yaml
restart: unless-stopped
```

**O que acontece:**

1. Energia cai → Ubuntu desliga  
2. Energia volta → Ubuntu liga  
3. Docker inicia (porque você fez `systemctl enable docker`)  
4. Container do bot sobe sozinho  

Você **não** precisa abrir o Cursor nem rodar `python telegram_bot.py` de novo.

---

## PARTE 5 — Atualização automática após `git push`

**Sim, dá para fazer.** Quando você alterar o robô no Cursor e der `git push`, o Mini PC pode pegar a nova versão sozinho.

### Como funciona

```
Cursor (Windows)          GitHub              Mini PC Ubuntu
      │                      │                       │
  você edita                 │                       │
      │                      │                       │
  git push ──────────────► master                     │
                             │                       │
                             │    script verifica    │
                             │◄── a cada X minutos ──┤
                             │                       │
                             │    git pull + rebuild │
                             │──────────────────────►│
                             │                  bot atualizado
```

O Docker **não** monitora o Git sozinho — usamos o script `scripts/deploy.sh` que:

1. Verifica se há commit novo no GitHub  
2. Se houver: `git pull` + `docker compose up -d --build`  
3. Se não houver: não faz nada (bot continua rodando)

### Opção A — Cron (mais simples, recomendado)

O `setup-server.sh` já configura isso. Para fazer manualmente:

```bash
crontab -e
```

Adicione (troque o caminho se clonou em outro lugar):

```cron
*/5 * * * * /home/SEU_USUARIO/assistente-planilha/scripts/deploy.sh >> /home/SEU_USUARIO/assistente-planilha/logs/deploy.log 2>&1
```

**Fluxo no dia a dia:**

1. Você edita no Cursor  
2. `git add .` → `git commit -m "..."` → `git push`  
3. Em até 5 minutos o Mini PC atualiza sozinho  

### Opção B — Atualizar na hora (manual)

```bash
cd ~/assistente-planilha
./scripts/deploy.sh
```

---

## PARTE 6 — O que persiste vs o que atualiza

| Item | Onde fica | Atualiza com git pull? |
|------|-----------|------------------------|
| Código Python | Git → imagem Docker | Sim |
| `.env` (token) | Arquivo local no Mini PC | **Não** — você edita só no servidor |
| Planilha `.xlsx` | `dist_novo/AssistentePlanilha/` (volume) | Cuidado — mudanças locais podem conflitar |
| `models/model.bin` | Pasta `models/` (volume) | Só se mudar no Git (LFS) |

---

## Problemas comuns (Ubuntu)

| Problema | Solução |
|----------|---------|
| `permission denied` no docker | `sudo usermod -aG docker $USER` e relogar |
| `Cannot connect to the Docker daemon` | `sudo systemctl start docker` |
| Bot não responde | `docker compose logs -f` e confira `.env` |
| `model.bin` pequeno | `git lfs install && git lfs pull` |
| Erro ao salvar planilha | Feche LibreOffice/Excel se estiver com o arquivo aberto |
| Deploy não atualiza | Rode `./scripts/deploy.sh` manual e veja a saída |

Guia de deploy automático (detalhes): [`DEPLOY_AUTOMATICO.md`](DEPLOY_AUTOMATICO.md)
