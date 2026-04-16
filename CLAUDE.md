# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Sua identidade

Voce e **socio tecnico** deste projeto. Nao e um assistente passivo — voce tem autonomia para:
- Propor melhorias baseadas em dados
- Corrigir bugs quando encontrar
- Questionar decisoes que parecem erradas
- Implementar mudancas com confianca (os testes rodam automaticamente via hook)

O dono do projeto e o **Gabriel** (dev principal). Comunique em **portugues brasileiro**, direto e sem enrolacao. Termos tecnicos em ingles (como no codigo).

## Regras de conduta

1. **Sempre leia antes de modificar** — nunca proponha mudancas em codigo que voce nao leu
2. **Incremental** — mudancas pequenas, testadas, uma de cada vez. Nunca reescrever modulos inteiros
3. **Backward compatible** — nunca quebrar trades em andamento ou estado existente
4. **Dados > opiniao** — baseie recomendacoes em dados do banco, nao em teoria
5. **Raspberry Pi** — recursos limitados (3.7GB RAM, SD card). Cuidado com operacoes pesadas (VACUUM, sorts grandes)
6. **Paper trading** — todo trading e virtual. Nao existe execucao real. Nao precisa ter medo de "perder dinheiro"
7. **Testes auto-executam** — ha um hook PostToolUse que roda `pytest` automaticamente a cada Write/Edit em `.py`. Nao rode testes manualmente apos editar — o hook ja cuida disso
8. **Nao commitar sem pedir** — so faca git commit quando o Gabriel pedir explicitamente

---

## Project Overview

Bot automatizado de trading de criptomoedas rodando 24/7 num Raspberry Pi 4. Todo trading e **virtual (paper)** — sem execucao real. Usa Binance Futures API para dados de mercado. Notificacoes e comandos via Telegram. **Foco atual: Momentum Pullback v1.1** — unica estrategia ativa. Pump e scalping aposentados temporariamente.

## Arquitetura

O bot roda como **servico systemd** (`cryptobot`) gerenciado por `supervisor.py`, que spawna e monitora 2 processos com auto-restart (backoff exponencial: 10s→30s→60s→120s→300s, max 10 restarts por bot):

1. **main.py** — Loop principal (ciclo de 5 min): busca candles da Binance, calcula indicadores, gera sinais, roda momentum paper
2. **dashboard_server.py** — Dashboard web Flask na porta 5000

### Subsistemas de Trading (todos paper)

| Sistema | Arquivo | Status |
|---|---|---|
| **Momentum Pullback** | `momentum/` + `paper_executor.py` | **Foco unico** — v1.1 baseline, params congelados, ATIVO |
| Pump Scanner | `pump_scanner.py` + `pump_trader.py` | Aposentado — infra preservada para reuso futuro |
| Scalping | `scalping_trader.py` + engines | Aposentado — nao integrado no main.py atual |
| Agent Trader | `trade_agents.py` | Desativado |
| Paper Trader | `paper_trader.py` | Desativado |
| Defensive CFER/RAVR | `defensive/` | Descontinuada — codigo preservado, sem uso ativo |
| V2.1b | scalping_trader.py (v2_1b) | Infraestrutura pronta, sem uso ativo |

### Fluxo de sinais

```
market.py (Binance candles)
  → indicators.py (SMA, RSI, volume)
    → strategy.py (score 0-5.5)
      → htf.py (1h trend filter + regime gate)

Momentum Pullback (ATIVO — v1.1 baseline, unica estrategia rodando):
  momentum/swing_detector.py (trend + swing detection via EMAs)
    → momentum/pullback_detector.py (retracement 30-70% + EMA slow respect)
      → momentum/momentum_trader.py (signal evaluation + sizing)
        → momentum/paper_executor.py (paper trading: posicoes, capital, DB persistence)
          → main.py (integrado via process_momentum_cycle a cada ciclo)
  Research pipeline (offline):
    → momentum/research_runner.py + research_db.py (backtesting + metricas)
    → momentum/robustness_check.py (walk-forward por periodo e regime)

Scalping (APOSENTADO — codigo preservado, nao integrado no main.py):
  scalping_data.py (candles multi-TF + indicadores)
    → market_data.py (microestrutura: funding, OI, liquidations, basis)
      → confluence.py (multi-engine scoring)
        → risk_manager.py (position sizing, avaliacao de risco)
          → execution_layer.py (SL/TP via ATR, TP multiplier por score)
            → scalping_trader.py (gerenciamento de posicoes)

Pump Scanner (APOSENTADO — removido do supervisor, infra preservada):
  pump_scanner.py (detecta pumps/dumps em 50 moedas)
    → pump_trader.py (trailing stop, timeout, gestao de posicoes)

Defensive (CFER/RAVR) — descontinuada, pipeline preservado:
  candles 15m → compression_detector.py → breakout_detector.py
    → trap_detector.py → value_reference.py → ravr_trader.py
```

### Scalping — 3 Motores de Microestrutura (aposentado)

| Motor | Arquivo | O que analisa |
|---|---|---|
| M1 Funding | `funding_engine.py` | Taxa de funding como proxy de crowding |
| M2 Liquidation/OI | `liquidation_engine.py` | Cascatas de liquidacao + open interest |
| M3 Basis | `basis_engine.py` | Spread futures-spot como proxy de sentimento |

Confluencia: 2/3 motores alinhados = medio, 3/3 = alto, solo override se 1 motor com score >= 55 (sizing reduzido 30%/2x). Nao roda atualmente — infra preservada para potencial reuso.

### Defensive — Descontinuada (codigo preservado)

CFER/RAVR foram descontinuadas (mean reversion nao provou edge). Codigo em `defensive/` preservado para referencia. Config em `defensive/config.py`, enums em `defensive/enums.py`, models em `defensive/models.py`. Docs: `docs/defensive/`.

### Momentum Pullback — Paper Trading (v1.1 baseline)

Hipotese: em tendencia confirmada, pullback de 30-70% que respeita EMA slow e depois retoma (close past EMA fast) tende a continuar. v1.1 confirmada como baseline robusta (3/3 testes de robustez PASS). Integrado ao main loop via `paper_executor.py` (process_momentum_cycle). Config em `momentum/config.py` (`MomentumConfig`) e `config.py` (`MOMENTUM_*`). Research pipeline offline em `research_runner.py`, `research_db.py`, `research_report.py`, `robustness_check.py`. Parametros v1.1 congelados — nao alterar. **ATIVO** (`MOMENTUM_TRADER_ENABLED=true`).

### Engines 1m e 5m (experimentais)

Sistemas multi-engine de curto prazo (codigo preservado, sem uso ativo no main loop):

| Diretório | Conteúdo |
|---|---|
| `engines_1m/` | MomentumBurst 1m (ATR/volume/body), base Engine1m |
| `engines_5m/` | Breakout 5m engine |
| `breakout/` | Paper executor para breakout 5m |
| `config_1m.py` | Config do sistema 1-min |
| `indicators_1m.py` | EMAs, ATR, BB, RSI, VWAP para 1-min |
| `indicators_5m.py` | Indicadores 5-min |
| `market_1m.py` | Fetch de candles 1-min (live + historico) |
| `risk_calculator_1m.py` | Position sizing fee-aware para 1-min |
| `backtest_1m.py` | Backtest candle-by-candle 1-min |

### Camadas intermediarias

- **Execution layer**: `execution_layer.py` — calcula SL/TP baseado em ATR, ajusta TP multiplier por score de confluencia
- **Liquidation feed**: `liquidation_feed.py` — WebSocket background thread (wss://fstream.binance.com), agrega liquidacoes reais por simbolo em janela rolante de 15min. Substitui proxies baseadas em aggTrades
- **Basis confidence**: `basis_confidence.py` — ajusta strength do sinal por basis spread (V2.1b). Bonus +10% quando basis confirma direcao, penalty -15% quando contradiz
- **Alertas proativos**: `proactive_alerts.py` — checks a cada ciclo (drawdown >= 3%, zero trades 24h, erros repetidos). Dedup com cooldown
- **Diagnose funnel**: `diagnose_funnel.py` — diagnostico do funil de decisoes (blocked_by, regime, sessao, taxa de passagem). CLI + importavel pelo dashboard
- **Validation auditor**: `validation_auditor.py` — analise offline de edge por sistema de trading. CLI com `--days` e `--output-dir`
- **Pattern memory**: `pattern_memory_desk.py` — agrega padroes de sucesso/falha dos trade reviews offline
- **Research lab**: `scalping_research.py` — scorer historico por familia de setup, export de dataset (JSON/JSONL/CSV)

### Telegram

- `telegram_notifier.py` — envio de mensagens, alertas de sistema, circuit breaker
- `telegram_commands.py` — handler de comandos (`/status`, `/posicoes`, `/pausar`, etc.) + estado de pausa

### Infraestrutura

- **Database**: SQLite WAL mode (`bot.db`) via `database.py`
- **Runtime isolation**: `runtime_config.py` — multiplas instancias (baseline vs v2) com DB, logs, estado e portas separados. Via `BOT_ID` env var
- **Dual instance**: `run_dual_supervisors.py` — A/B test lado a lado
- **AI Gate**: `ai_gate_local.py` — LLM local via llama.cpp. **DESATIVADA** (`SCALPING_DISABLE_AI_GATE=true`)
- **Circuit breaker**: `daily_report.py` — para trading se perda diaria > 5% ou > 20 trades
- **Proactive alerts**: `proactive_alerts.py` — detecta problemas antes que se agravem (drawdown, inatividade, erros)
- **Audit framework**: `audit_helpers.py` + `audit_data.py` + `signal_types.py` — 51 campos por trade + 32 por decision
- **Scripts**: `scripts/research_matrix.py` (grid search parametrico), `scripts/tuning_matrix.py` (tuning), `scripts/verify_and_benchmark.sh`, `scripts/fase3_*.py` (validacao de engines), `scripts/backtest_breakout_5m.py`
- **Research data**: `research/` — databases SQLite de resultados de matrix runs (matrix_v1.db, etc.)

---

## Comandos

### Rodar o bot
```bash
cd ~/crypto_ai_bot
source .venv/bin/activate
python supervisor.py            # producao (gerencia 2 processos: main + dashboard)
python main.py                  # loop principal (dev/debug)
python pump_scanner.py          # pump scanner isolado
python dashboard_server.py      # dashboard isolado
python run_dual_supervisors.py  # dual instance A/B test
```

### Servico systemd
```bash
sudo systemctl status cryptobot
sudo systemctl restart cryptobot
sudo systemctl stop cryptobot
journalctl -u cryptobot -f      # logs ao vivo
journalctl -u cryptobot --since "1 hour ago" --no-pager  # ultima hora
```

### Testes
```bash
python -m pytest tests/ --tb=short -q           # todos (~683 testes)
python -m pytest tests/test_confluence.py -v      # arquivo especifico
python -m pytest tests/test_confluence.py::test_x -v  # teste unico
```

### Backtests
```bash
python backtest.py              # padrao
python backtest_scalping.py     # scalping
python backtest_parametric.py   # sweep parametrico
python backtest_pump.py         # pump strategy
python backtest_1m.py           # 1-min candle-by-candle
python scripts/backtest_breakout_5m.py  # breakout 5m
```

### Banco de dados (queries uteis)
```bash
# Performance momentum (sistema ativo)
sqlite3 runtime/baseline/bot.db "SELECT COUNT(*), ROUND(AVG(pnl_pct),4), ROUND(SUM(pnl_pct),4) FROM momentum_trades;"

# Funil de decisoes momentum
sqlite3 runtime/baseline/bot.db "SELECT blocked_by, COUNT(*) FROM momentum_decisions GROUP BY blocked_by ORDER BY COUNT(*) DESC;"

# Ultimas decisoes momentum
sqlite3 runtime/baseline/bot.db "SELECT id, timestamp, symbol, blocked_by FROM momentum_decisions ORDER BY id DESC LIMIT 5;"

# Performance scalping (aposentado — historico)
sqlite3 runtime/baseline/bot.db "SELECT COUNT(*), ROUND(AVG(pnl_pct),4), ROUND(SUM(pnl_pct),4) FROM scalping_trades;"
```

### CI e Deploy
```bash
bash ci.sh              # CI local: pytest + py_compile (17 arquivos criticos)
bash ci.sh --notify     # CI + notificacao Telegram
bash deploy.sh          # commit, push, pull no Pi (ff-only), health-check, restart
# pre-push hook roda ci.sh automaticamente antes de cada push
```

### Health check
```bash
python -c 'import main; import supervisor; import dashboard_server; print("OK")'
```

---

## Dashboard e API

Dashboard Flask em `http://<ip>:5000`. Rotas POST protegidas por HTTP Basic Auth (env vars `DASHBOARD_USER`/`DASHBOARD_PASS`; se vazias, auth desabilitada).

| Pagina | Rota |
|---|---|
| Home | `/` |
| Analytics | `/analytics` |
| System | `/system` |
| Equity curve | `/equity` |
| Comparador de runtimes | `/comparison` |
| Funil de decisoes | `/scalping/funnel` |
| Audit trail scalping | `/scalping/audit` |
| Replay rotulado scalping | `/scalping/outcomes` |
| Scorer historico | `/scalping/scorer` |
| **Pip-Boy dashboard** | `/pip/` — redesign retro-futurista com SSE partials |

### Pip-Boy Dashboard

Dashboard alternativo em `/pip/` com tema Pip-Boy (Fallout). Usa SSE (Server-Sent Events) para updates em tempo real via partials HTMX-like. Templates em `templates/pipboy/`, CSS em `static/css/pipboy.css`, JS em `static/js/pipboy.js`. Graficos ASCII via `ascii_charts.py`.

Partials SSE: `/pip/partial/{status_bar,equity,trades,daily_pnl,funnel,gauges,scorer,errors,health,processes}`

### API endpoints

| Endpoint | Descricao |
|---|---|
| `GET /api/status` | Status geral (auto-refresh AJAX) |
| `GET /api/trades` | Trades com filtros (`?system=`, `?days=`, `?regime=`, `?session=`) |
| `GET /api/logs` | Logs recentes de qualquer subsistema |
| `GET /api/compare` | Comparacao JSON entre runtimes |
| `GET /api/processes` | Status dos processos gerenciados pelo supervisor |
| `GET /api/equity` | Dados de equity curve |
| `GET /api/funnel` | Dados do funil de decisoes |
| `GET /api/microstructure/history` | Historico de microestrutura |
| `GET /api/microstructure/latest` | Snapshot mais recente de microestrutura |
| `GET /api/signal-subtypes` | Distribuicao de subtipos de sinal |
| `GET /api/ai-brain` | Status do AI gate |
| `GET /api/version` | Versao do bot |
| `GET /api/scalping/audit` | Trilha detalhada do scalping |
| `GET /api/scalping/outcomes` | Labels forward do scalping |
| `GET /api/scalping/outcomes/export` | Dataset JSON/JSONL/CSV |
| `GET /api/scalping/scorer` | Score historico por familia de setup |
| `GET /stream/logs` | SSE stream de logs em tempo real |
| `POST /pause` | Pausa o bot (requer auth) |
| `POST /resume` | Retoma o bot (requer auth) |

### Comandos Telegram

`/status`, `/posicoes`, `/capital`, `/performance`, `/saude`, `/pausar`, `/retomar`, `/relatorio`, `/ajuda`

---

## Configuracao

- `config.py` — Parametros de trading, thresholds, capital. Override via env vars (`BOT_*`, `SCALPING_*`)
- `runtime_config.py` — Config de instancia (BOT_ID, portas, paths, flags experimentais)
- `.env` — Secrets (API keys, Telegram token). **NUNCA commitar**

### Env vars importantes
```
BOT_ID=baseline                    # identifica instancia
SCALPING_SYMBOLS=BTCUSDT,ETHUSDT   # pares do scalping
SCALPING_DISABLE_AI_GATE=true      # AI gate desativada
PAPER_TRADER_ENABLED=false
AGENT_TRADER_ENABLED=false
V2_1B_PAPER_ENABLED=false
SCALPING_EXPERIMENTAL_FORCE_ENTRIES=true/false  # habilita tambem: ignore_risk, disable_ai_gate, disable_cooldown
MOMENTUM_TRADER_ENABLED=true       # habilita momentum paper trading no main loop
MOMENTUM_SYMBOLS=BTCUSDT,ETHUSDT   # pares do momentum
DEFENSIVE_INITIAL_CAPITAL=1000     # capital do subsistema defensive (descontinuado)
DEFENSIVE_SYMBOLS=BTCUSDT,ETHUSDT  # pares do defensive (descontinuado)
BOT_PORTFOLIO_TARGET_CAPITAL=35000 # escala capital proporcional entre sistemas (default sum: 35K)
BOT_SCALPING_INITIAL_CAPITAL=10000 # override individual por sistema (paper/agent/pump/scalping)
DASHBOARD_USER=user                # HTTP Basic Auth para rotas POST (vazio = sem auth)
DASHBOARD_PASS=pass
```

---

## Hooks e automacao

- **PostToolUse (Write/Edit em .py)**: roda `python -m pytest tests/ --tb=short -q` automaticamente. Nao precisa rodar testes manualmente — espere o resultado do hook
- **pre-push hook**: roda `ci.sh` antes de cada `git push`. Se falhar, o push e bloqueado
- **Restart apos deploy**: sempre `sudo systemctl restart cryptobot` apos mudancas em Python do backend. Validar via `curl http://localhost:5000/api/status`

---

## Dependencias

Python 3.13, venv em `.venv/`. Key deps: `anthropic`, `flask`, `numpy`, `pandas`, `ta`, `requests`, `python-dotenv`.
llama.cpp compilado em `llama.cpp/` para inferencia local (AI gate — atualmente desativada).

```bash
pip install -r requirements.txt        # producao
pip install -r requirements-dev.txt    # dev (inclui pytest)
```

---

## Skills disponiveis (slash commands)

### Custom commands (`.claude/commands/`)

| Comando | O que faz |
|---|---|
| `/monitor` | Check rapido: servico, temp, RAM, disco, decisions, erros |
| `/audit` | Auditoria completa com 4 agentes paralelos (performance, erros, saude, estrategia) |
| `/evolve` | Propoe a proxima melhoria baseada em dados (UMA coisa concreta) |
| `/fix` | Diagnostica e corrige problemas automaticamente |
| `/backtest-check` | Roda backtests e compara versoes |
| `/report` | Relatorio diario quantitativo (trades, funil, edge, saude) |
| `/security` | Auditoria de seguranca (secrets, rede, SQL, deps, sistema) |
| `/hygiene` | Verifica drift entre CLAUDE.md, codigo e configs |

### Built-in skills

| Comando | O que faz |
|---|---|
| `/simplify` | Review de codigo por qualidade e reuso (built-in Claude Code) |

---

## Banco de dados — tabelas principais

SQLite WAL mode em `runtime/<BOT_ID>/bot.db`. Tabelas-chave:

| Tabela | Descricao |
|---|---|
| `scalping_trades` | Trades finalizados do scalping (51 campos: audit completo com slippage, fees, regime, buckets) |
| `scalping_decisions` | Cada decisao do ciclo scalping (32 campos: funil completo com ablation, blocked_by, microestrutura) |
| `pump_trades` | Trades finalizados do pump scanner (12 campos basicos) |
| `scalping_audit_log` | Log detalhado de cada ciclo scalping |
| `scalping_outcome_labels` | Labels de outcome pos-trade |
| `momentum_trades` | Trades finalizados do momentum pullback (paper) |
| `momentum_decisions` | Decisoes do ciclo momentum (funil) |
| `market_microstructure` | Snapshots de microestrutura (funding, OI, basis) |
| `*_v2_1b` | Tabelas espelho para instancia V2.1b experimental |

Tabelas legadas (sistemas desativados): `paper_trades`, `agent_trades`, `ai_decisions`.

Roadmap de evolucao: `docs/ROADMAP_V1.md`
