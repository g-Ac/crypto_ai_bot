# Crypto AI Bot

Bot de trading automatico de criptomoedas rodando 24/7 em Raspberry Pi 4.
Combina analise tecnica, microestrutura de mercado (funding, OI, liquidacoes, basis)
e IA (Claude Haiku) para detectar oportunidades e simular trades com notificacoes via Telegram.

**Todo o capital e virtual** — nenhum trade real e executado (paper trading).

## Arquitetura

```
supervisor.py (systemd: cryptobot)
├── main.py              Loop principal (ciclo 5 min)
├── pump_scanner.py      Scanner de pump/dump (ciclo 60s, 50 moedas)
└── dashboard_server.py  Dashboard web Flask (:5000)
```

### Fluxo de sinais

```
market.py (Binance candles)
  → indicators.py (SMA, RSI, volume)
    → strategy.py (score 0-5.5)
      → htf.py (1h trend + regime gate)
        → subsistemas de trading

Scalping adiciona:
  market_data.py (microestrutura: funding, OI, liquidations, basis)
    → confluence.py (3 engines scoring)
      → risk_manager.py (position sizing, SL/TP)
```

## Sistemas de Trading

| Sistema | Status | Performance |
|---|---|---|
| **Pump Scanner** | ATIVO (carro-chefe) | +40.71% (133 trades) |
| **Scalping** | ATIVO (em validacao) | +0.43% (14 trades) |
| **Agent Trader** | Desativado | -21.07% (40 trades) |
| **Paper Trader** | Desativado | -4.74% (4 trades) |
| **V2.1b** | Infraestrutura pronta | Aguardando dados |

### Scalping — 3 Motores de Microestrutura

| Motor | Arquivo | O que analisa |
|---|---|---|
| M1 Funding | `funding_engine.py` | Taxa de funding como proxy de crowding |
| M2 Liquidation/OI | `liquidation_engine.py` | Cascatas de liquidacao + open interest |
| M3 Basis | `basis_engine.py` | Spread futures-spot como proxy de sentimento |

Confluencia: 2/3 motores alinhados = medio, 3/3 = alto, solo override se score >= 55.

## Setup

```bash
# Clonar e instalar
git clone <repo-url> ~/crypto_ai_bot
cd ~/crypto_ai_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # producao
pip install -r requirements-dev.txt    # dev (inclui pytest)

# Configurar secrets
cp .env.example .env  # editar com suas chaves
```

## Disaster Recovery

> Backup local no mesmo SD é cache operacional, não disaster recovery.

Status (2026-06-09):

- Runtime local backup: **operacional** (timer diário + bundle)
- Restore verification: **operacional** (`--verify-only` validado)
- Healthcheck: **operacional**
- Offsite backup: **pendente — obrigatório para DR completo**
- `.env` recovery: **manual**, via password manager (fora da Pi)

Filosofia do projeto: `docs/CONSTITUTION.md`. Runbook completo de reconstrução
(SD morreu): `docs/DISASTER_RECOVERY.md`.

```bash
bash scripts/backup_runtime_bundle.sh           # bundle DR: db + estado + crontab + units
bash scripts/restore_runtime_bundle.sh <tar.gz> # restore conservador (não inicia nada)
bash scripts/export_crontab.sh                  # versiona crontab em ops/crontab.current
bash scripts/healthcheck.sh [--full]            # PASS/WARN/FAIL consolidado
```

Backup diário automático do `bot.db` via `k-collector-backup.timer` (04:00).
O bundle deve sair da Pi (offsite) — ver `docs/DISASTER_RECOVERY.md` §4 e §8.

### Variaveis de ambiente (.env)

```
BINANCE_API_KEY=...
BINANCE_SECRET_KEY=...
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
ANTHROPIC_API_KEY=...
```

### Variaveis de runtime

```
BOT_ID=baseline                    # identifica instancia
SCALPING_SYMBOLS=BTCUSDT,ETHUSDT   # pares do scalping
PAPER_TRADER_ENABLED=false
AGENT_TRADER_ENABLED=false
V2_1B_PAPER_ENABLED=false
```

## Uso

```bash
# Producao (gerencia 3 processos)
python supervisor.py

# Dev/debug
python main.py                  # loop principal
python pump_scanner.py          # pump scanner isolado
python dashboard_server.py      # dashboard isolado

# Dual instance (A/B test)
python run_dual_supervisors.py
```

### Servico systemd

```bash
sudo systemctl status cryptobot
sudo systemctl restart cryptobot
sudo systemctl stop cryptobot
journalctl -u cryptobot -f              # logs ao vivo
journalctl -u cryptobot --since "1h"    # ultima hora
```

## Testes e CI

```bash
# Rodar testes (200 tests)
python -m pytest tests/ --tb=short -q

# CI completo (pytest + py_compile)
bash ci.sh

# CI com notificacao Telegram
bash ci.sh --notify
```

O hook `pre-push` roda `ci.sh` automaticamente antes de cada push.

## Deploy

```bash
bash deploy.sh
```

Fluxo: commit → push GitHub → pull no Pi (ff-only) → health check → restart systemd.

## Dashboard

Acessivel em `http://<ip-do-pi>:5000`

| Pagina | Rota |
|---|---|
| Home | `/` |
| Trades | `/trades` |
| Funil de decisao | `/scalping/funnel` |
| Equity curve | `/equity` |

### API endpoints

| Endpoint | Descricao |
|---|---|
| `GET /api/status` | Status geral |
| `GET /api/trades` | Trades com filtros (?system, ?days, ?regime, ?session) |
| `GET /api/equity` | Equity curve por sistema |
| `GET /api/funnel` | Funil de decisao scalping |
| `GET /api/scalping/audit` | Audit log do scalping |
| `GET /api/scalping/outcomes` | Outcomes do scalping |

## Comandos Telegram

| Comando | Acao |
|---|---|
| `/status` | Resumo geral dos sistemas |
| `/posicoes` | Posicoes abertas |
| `/capital` | Capital detalhado por sistema |
| `/performance` | Win rate, P&L e trades do dia |
| `/saude` | CPU, RAM, disco, temperatura, uptime |
| `/pausar` | Para de abrir novas posicoes |
| `/retomar` | Volta a operar |
| `/relatorio` | Relatorio completo do dia |
| `/ajuda` | Lista comandos |

## Alertas proativos

O bot envia alertas automaticos via Telegram:
- **Drawdown** >= 3% no dia
- **Zero trades** em 24h (ambos sistemas parados)
- **Erros repetidos** >= 5 na ultima hora (critical)

Cada alerta tem dedup in-memory com cooldown para evitar spam.

## Estrutura

```
crypto_ai_bot/
├── main.py                 # Loop principal (5 min)
├── supervisor.py           # Gerencia 3 processos + crash alerts
├── config.py               # Parametros de trading
├── runtime_config.py       # Config de instancia (BOT_ID, paths)
│
├── strategy.py             # Sinais tecnicos (score 0-5.5)
├── indicators.py           # SMA, RSI, volume, body ratio
├── htf.py                  # Tendencia 1h + regime gate
├── market.py               # Binance candles API
├── market_data.py          # Microestrutura (funding, OI, liq, basis)
│
├── scalping_trader.py      # Orquestrador scalping
├── funding_engine.py       # M1: Funding Rate
├── liquidation_engine.py   # M2: Liquidation Cascade + OI
├── basis_engine.py         # M3: Basis Spread
├── confluence.py           # Score de confluencia (3 motores)
├── risk_manager.py         # Position sizing, SL/TP
│
├── pump_scanner.py         # Scanner de pumps (50 moedas)
├── pump_trader.py          # Executor pump (trailing stop)
├── paper_trader.py         # Executor paper (desativado)
├── trade_agents.py         # Agent trader (desativado)
│
├── telegram_notifier.py    # Envio HTML, retry, rate limiting
├── telegram_commands.py    # 9 comandos bidirecionais
├── proactive_alerts.py     # Drawdown, zero trades, erros
├── daily_report.py         # Relatorio diario + circuit breaker
│
├── dashboard_server.py     # Dashboard Flask (:5000)
├── diagnose_funnel.py      # Funil de decisao (CLI + API)
├── database.py             # SQLite WAL mode
│
├── ci.sh                   # CI basico (pytest + py_compile)
├── deploy.sh               # Deploy automatico
├── requirements.txt        # Deps producao
├── requirements-dev.txt    # Deps dev (pytest)
│
├── tests/                  # 200 testes (pytest)
├── templates/              # HTML (dashboard, equity, funnel)
├── runtime/                # Dados por instancia (DB, logs)
└── docs/                   # Documentacao
```

## Requisitos

- Raspberry Pi 4 (3.7GB RAM, ARM64)
- Python 3.13
- SQLite 3.x (WAL mode)
- Binance Futures API (dados de mercado)
- Anthropic API (Claude Haiku para AI gate)
- Telegram Bot API (notificacoes)
