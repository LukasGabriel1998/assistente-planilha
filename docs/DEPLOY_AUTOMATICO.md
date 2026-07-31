# Deploy automático — git push → Mini PC atualiza

## Resposta rápida

**Sim.** Você edita no Cursor, dá `git push`, e o Mini PC pode baixar e reiniciar o bot **sem você entrar no servidor toda vez**.

O Docker em si não "escuta" o GitHub. Usamos o script `scripts/deploy.sh` + **cron** (verificação a cada poucos minutos).

---

## Fluxo completo

```
┌─────────────────┐     git push      ┌─────────────┐
│  PC Windows     │ ───────────────►  │   GitHub    │
│  Cursor + dev   │                   │  (master)   │
└─────────────────┘                   └──────┬──────┘
                                             │
                              cron (5 min)   │  git fetch
                                             ▼
                                    ┌─────────────────┐
                                    │  Mini PC Ubuntu │
                                    │  deploy.sh      │
                                    │  docker rebuild │
                                    └─────────────────┘
```

---

## Método 1 — Cron (recomendado)

### Setup automático

```bash
chmod +x ~/assistente-planilha/scripts/setup-server.sh
./scripts/setup-server.sh
```

Isso sobe o bot, configura Docker no boot e agenda o cron a cada 5 minutos.

### Setup manual do cron

```bash
chmod +x ~/assistente-planilha/scripts/deploy.sh
mkdir -p ~/assistente-planilha/logs
crontab -e
```

Adicione (troque `lucas` pelo seu usuário):

```cron
*/5 * * * * /home/lucas/assistente-planilha/scripts/deploy.sh >> /home/lucas/assistente-planilha/logs/deploy.log 2>&1
```

### No Windows, seu fluxo fica:

```powershell
git add .
git commit -m "Melhoria no menu de entrada"
git push
```

Em até 5 minutos o Mini PC aplica.

### Ver se o deploy rodou:

```bash
tail -f ~/assistente-planilha/logs/deploy.log
```

---

## O que o `deploy.sh` faz

1. `git fetch` — pergunta ao GitHub se há novidade na branch `master`  
2. Se **não** há mudança → sai sem reiniciar (bot continua)  
3. Se **há** mudança → `git pull` + `git lfs pull` + `docker compose up -d --build`  

O `--build` reconstrói a imagem com o código novo. O container reinicia com a versão atualizada.

---

## Método 2 — Deploy manual (sem cron)

```bash
cd ~/assistente-planilha
./scripts/deploy.sh
```

---

## Perguntas frequentes

### O bot fica offline durante o update?

Por alguns segundos, sim — enquanto o container reconstrói e reinicia. Para um bot de Telegram isso é normal e rápido.

### Preciso mexer no `.env` a cada update?

Não. O `.env` fica **só no Mini PC** e não vai no GitHub. Só edite se mudar token ou caminho da planilha.

### E a planilha Excel?

Fica em `dist_novo/AssistentePlanilha/` montada como volume. Os dados que o bot grava **permanecem** após update.

### Posso usar intervalo menor que 5 minutos?

Sim. Rode o setup com intervalo customizado:

```bash
DEPLOY_INTERVAL_MIN=2 ./scripts/setup-server.sh
```

Ou edite o cron manualmente (`*/2` = a cada 2 minutos).

### O cron ja esta configurado?

No Mini PC:

```bash
crontab -l | grep deploy.sh
tail -20 logs/deploy.log
```

Se nao aparecer nada, rode `./scripts/setup-server.sh` uma vez no Mini PC.

---

## Checklist antes de ativar o cron

- [ ] Bot roda com `docker compose up -d`  
- [ ] `.env` configurado no Mini PC  
- [ ] `git lfs pull` baixou o `model.bin` e a planilha  
- [ ] `scripts/deploy.sh` executa sem erro  
- [ ] Testou um `git push` e `./scripts/deploy.sh` manual  
