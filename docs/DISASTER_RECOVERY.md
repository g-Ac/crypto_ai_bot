# Disaster Recovery — crypto_ai_bot

> **Se o backup está só no mesmo SD da Pi, ele não existe para disaster recovery.**
> Backup local no mesmo SD é cache operacional, não disaster recovery.

Cenário assumido: **o SD card morreu hoje.** Este documento reconstrói o sistema
sem depender de memória humana. Atualizado em 2026-06-15.

## 1. O que sobrevive / o que morre

| Sobrevive (fora da Pi) | Morre com o SD |
|---|---|
| Código, scripts, docs, registry, systemd units — GitHub (`g-Ac/crypto_ai_bot`) | `runtime/baseline/bot.db` (inclui dados k_* perecíveis, irrecuperáveis da API após ~30d) |
| Obsidian vault — git separado | JSONs de estado operacional (`momentum_state.json`, `paper_state.json`, `bot_control.json`) |
| | `.env` (secrets — Telegram, Anthropic) |
| | crontab (mitigado: versionado em `ops/crontab.current`) |
| | Backups locais em `/home/pi/backups/` |

**Mitigação:** `scripts/backup_runtime_bundle.sh` empacota tudo que morre (exceto
`.env` — ver §5). Enquanto o bundle não sair da Pi (offsite), o risco continua.

## 2. Fonte de verdade do estado operacional

`bot.db` sozinho **não** reconstrói o estado. O mínimo indispensável é:

```text
.env                                  (secrets — restore manual, ver §5)
runtime/baseline/bot.db               (trades, decisions, dados k_*)
runtime/baseline/momentum_state.json  (posições/estado da estratégia ativa)
runtime/baseline/paper_state.json     (capital paper)
runtime/baseline/bot_control.json     (pausa/controle)
systemd units                         (versionados em systemd/)
crontab                               (versionado em ops/crontab.current)
docs/EXPERIMENT_REGISTRY.md           (no git)
```

## 3. Inventário de runtime (o que precisa voltar)

| Item | Tipo | Função |
|---|---|---|
| `cryptobot.service` | systemd, enabled | supervisor → `main.py` (loop 5min) + `dashboard_server.py` (porta 5000). Dashboard e Telegram vivem DENTRO dele |
| `liquidation-collector.service` | systemd, enabled | WebSocket Bybit → tabela `k_liquidations` |
| `k-collector-backup.timer` | systemd, 04:00 diário | `scripts/backup_bot_db.sh` (db local, rotação 7d) |
| `k-collector-report.timer` | systemd, 09:00 diário | relatório k_collector via Telegram |
| `k-collector-watchdog.timer` | systemd, hourly :35 | detecta staleness do k_collector |
| `liquidation-watchdog.timer` | systemd, a cada 30min | detecta feed Bybit mudo >90min → reinicia `liquidation-collector` (via regra sudoers) + alerta Telegram |
| `options-watchdog.timer` | systemd, hourly :40 | detecta staleness de `k_options_features` (EXP-019, cadeia Deribit sem backfill) → re-roda `options_collector` + alerta Telegram |
| vault sync | cron, */30min | `~/obsidian-vault/sync-pull.sh` |
| `daily_monitor.py` | cron, 4x/dia | monitor momentum via Telegram |
| `shadow_simulator.py` | cron, 4x/dia | shadow outcomes |
| `k_collector.py` | cron, hourly :05 | coleta ratios/klines Binance |

Crontab completo: `ops/crontab.current` (re-exportar com `scripts/export_crontab.sh`).

## 4. Backup

- **Diário automático (db):** `k-collector-backup.timer` → `backup_bot_db.sh` →
  `/home/pi/backups/bot.db.<ts>.gz` (sqlite3 `.backup` online, rotação 7 dias).
- **Bundle completo (DR):** `scripts/backup_runtime_bundle.sh` → tar.gz em
  `/home/pi/backups/bundles/` com db + JSONs de estado + crontab + units instalados
  + metadata git + checksums. Rodar após qualquer mudança operacional relevante.
- **Offsite (OBRIGATÓRIO, ver §8):** copiar o bundle para fora da Pi ao menos 1x/semana.
  Com `OFFSITE_DEST` definido (ex.: `user@host:/path`), o próprio
  `backup_runtime_bundle.sh` faz `scp` ao final.

## 5. Secrets (.env)

O `.env` **nunca** entra em bundle, repo ou backup em texto puro. O bundle grava
apenas os **nomes** das chaves (`env_keys.txt`) para conferência no restore.

**Obrigação do operador:** manter cópia do conteúdo do `.env` em local seguro fora
da Pi (password manager). São ~9 chaves (Telegram token/chat, Anthropic key, flags).
Sem essa cópia, o restore exige re-gerar tokens nos provedores.

## 6. Procedimento de restore (ordem segura)

Nada sobe automaticamente. Serviços só iniciam manualmente após healthcheck (§7).

```bash
# 1. SO novo (Raspberry Pi OS 64-bit), usuário pi, rede ok
sudo apt update && sudo apt install -y git python3-venv sqlite3 curl

# 2. Código
git clone git@github.com:g-Ac/crypto_ai_bot.git ~/crypto_ai_bot
cd ~/crypto_ai_bot && git checkout <branch de produção — ver memória/registry>

# 3. Ambiente
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Secrets — MANUAL, a partir do local seguro (§5)
nano .env    # conferir contra env_keys.txt do bundle

# 5. Estado operacional — a partir do bundle offsite mais recente
bash scripts/restore_runtime_bundle.sh /caminho/runtime_bundle_<ts>.tar.gz
# (valida checksums, restaura db + JSONs; NÃO inicia nada, NÃO mexe no crontab)

# 6. systemd units (instala TUDO parado — sem enable --now do cryptobot)
sudo cp systemd/cryptobot.service systemd/liquidation-collector.service /etc/systemd/system/
sudo bash systemd/install_systemd_units.sh        # 5 timers: k-collector (3) + liquidation-watchdog + options-watchdog, + sudoers
sudo systemctl daemon-reload
sudo systemctl enable cryptobot liquidation-collector   # enable SEM start

# 7. Crontab (revisar antes de aplicar!)
crontab ops/crontab.current

# 8. Validação
bash scripts/healthcheck.sh --full

# 9. Start manual — somente com healthcheck limpo
sudo systemctl start liquidation-collector
sudo systemctl start cryptobot
bash scripts/healthcheck.sh    # re-validar com serviços de pé
```

## 7. Comportamento pós-restore (lei)

- O sistema volta **parado/modo seguro**. Nada live pode ser ativado por restore
  (hoje não existe caminho live no código — e restore jamais deve criar um).
- Serviços só sobem manualmente após `healthcheck.sh`.
- Posições no `momentum_state.json` restaurado podem estar obsoletas vs mercado:
  revisar e, se houver órfãs, rodar `python close_orphan_trades.py`.
- **Gap de coleta é informação, não silêncio:** registrar no vault/registry a janela
  sem dados (k_*, liquidações) com início e fim.

## 8. Lacunas conhecidas

- [ ] **Offsite automático não configurado** — bundle ainda nasce no mesmo SD.
      P0: configurar `OFFSITE_DEST` (Tailscale → PC) ou rclone para nuvem, 1x/semana.
- [ ] Cópia segura do `.env` fora da Pi depende de disciplina do operador (§5).
- [ ] Modelos `.gguf` e build do `llama.cpp` não são cobertos (AI gate desativada;
      re-baixáveis/re-compiláveis — opcional no recovery).
- [ ] `deploy.sh` não inclui `scripts/*.sh`, `systemd/` e `ops/` no auto-stage —
      commits desses paths são manuais.

## 9. Checklist final do restore

- [ ] `healthcheck.sh --full` sem FAIL
- [ ] `.env` restaurado e conferido contra `env_keys.txt`
- [ ] `bot.db` com tabelas críticas e contagens plausíveis
- [ ] JSONs de estado presentes; posições órfãs reconciliadas
- [ ] 2 services + 5 timers instalados e enabled (+ sudoers do liquidation-watchdog)
- [ ] Crontab aplicado e revisado
- [ ] Gap de coleta registrado no vault
- [ ] Serviços iniciados manualmente e `/api/status` respondendo
- [ ] Novo `backup_runtime_bundle.sh` rodado no sistema restaurado
