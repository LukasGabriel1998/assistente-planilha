# Comandos Docker — dois projetos lado a lado

Referência rápida para **assistente-planilha** e **Secret-rio_Sous_Tec** no mesmo PC.

---

## Identificação rápida

| | **assistente-planilha** | **Secret-rio (Assistente Line)** |
|---|---|---|
| Pasta do projeto | `PROJETOS DEV/assistente-planilha` | `PROJETOS DEV/Secret-rio_Sous_Tec` |
| Nome do container | `assistente-planilha-bot` | `assistente-line-bot` |
| Repositório GitHub | `lordsofandroid-del/assistente-planilha` | `LukasGabriel1998/Secret-rio_Sous_Tec` |
| Branch do deploy | `master` | `main` |
| Planilha (volume) | `dist_novo/AssistentePlanilha/` | `Planilha/` |

**Regra:** `docker compose` só age no projeto da **pasta onde você está**. Um não para o outro.

---

## Ver tudo de uma vez (qualquer pasta)

| O que fazer | Comando | O que mostra |
|-------------|---------|--------------|
| Listar **todos** os containers | `docker ps` | Os dois bots + Portainer (se tiver) |
| Listar inclusive parados | `docker ps -a` | Todos, rodando ou não |

Coluna **NAMES** = nome do container de cada projeto.

---

## Comandos por projeto (entre na pasta certa)

### assistente-planilha

```bash
cd "/home/lucas/Área de trabalho/PROJETOS DEV/assistente-planilha"
```

| O que fazer | Comando |
|-------------|---------|
| Bot está rodando? | `docker compose ps` |
| Ver logs do bot ao vivo | `docker compose logs -f` |
| Ver últimas 50 linhas dos logs | `docker compose logs --tail=50` |
| Parar **só este** bot | `docker compose down` |
| Subir / reiniciar com rebuild | `docker compose up -d --build` |
| Reiniciar sem rebuild | `docker compose restart` |
| Ver log do deploy automático | `tail -f logs/deploy.log` |
| Atualizar do GitHub na hora | `./scripts/deploy.sh` |
| Setup completo (bot + cron) | `./scripts/setup-server.sh` |

### Secret-rio (Assistente Line)

```bash
cd "/home/lucas/Área de trabalho/PROJETOS DEV/Secret-rio_Sous_Tec"
```

| O que fazer | Comando |
|-------------|---------|
| Bot está rodando? | `docker compose ps` |
| Ver logs do bot ao vivo | `docker compose logs -f` |
| Ver últimas 50 linhas dos logs | `docker compose logs --tail=50` |
| Parar **só este** bot | `docker compose down` |
| Subir / reiniciar com rebuild | `docker compose up -d --build` |
| Reiniciar sem rebuild | `docker compose restart` |
| Ver log do deploy automático | `tail -f logs/deploy.log` |
| Atualizar do GitHub na hora | `./scripts/deploy.sh` |
| Setup completo (bot + cron) | `./scripts/setup-server.sh` |

Os comandos são **iguais** — o que muda é a **pasta** (`cd`).

---

## Comandos pelo nome do container (sem mudar de pasta)

Útil quando você já sabe qual bot quer mexer.

| O que fazer | Planilha | Secret-rio (Line) |
|-------------|----------|-------------------|
| Ver logs ao vivo | `docker logs -f assistente-planilha-bot` | `docker logs -f assistente-line-bot` |
| Parar | `docker stop assistente-planilha-bot` | `docker stop assistente-line-bot` |
| Iniciar de novo | `docker start assistente-planilha-bot` | `docker start assistente-line-bot` |
| Reiniciar | `docker restart assistente-planilha-bot` | `docker restart assistente-line-bot` |

---

## Antes de parar algo — conferir onde está

```bash
pwd
```

| Se `pwd` mostrar… | `docker compose down` para… |
|-------------------|------------------------------|
| `.../assistente-planilha` | Só o bot da planilha |
| `.../Secret-rio_Sous_Tec` | Só o bot do Line |

---

## Fluxo do dia a dia (deploy automático)

| Passo | Planilha | Secret-rio |
|-------|----------|------------|
| 1. Editar no Cursor | pasta `assistente-planilha` | pasta `Secret-rio_Sous_Tec` |
| 2. Enviar pro GitHub | `git push` (branch `master`) | `git push` (branch `main`) |
| 3. Mini PC atualiza sozinho | cron roda `deploy.sh` desta pasta | cron roda `deploy.sh` da outra pasta |

Cada projeto tem seu **cron** e seu **log** em `logs/deploy.log` na própria pasta.

---

## Resumo visual

```
docker ps                          →  vê os DOIS bots

cd assistente-planilha             →  docker compose ...  →  só planilha-bot
cd Secret-rio_Sous_Tec             →  docker compose ...  →  só line-bot

docker logs -f assistente-planilha-bot   →  logs só da planilha
docker logs -f assistente-line-bot       →  logs só do Line
```
