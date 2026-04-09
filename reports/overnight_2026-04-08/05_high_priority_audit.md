# Auditoria Itens ALTO — melhorias.md

Data: 2026-04-08

## Resultado Geral

**11/11 itens CORRIGIDOS.** Todos os itens de prioridade ALTO (A1–A11) foram resolvidos no codigo atual.

## Detalhes por Item

| Item | Descricao | Status | Evidencia |
|------|-----------|--------|-----------|
| A1 | Scalping usa API Spot em vez de Futures | CORRIGIDO | config.py:45 `USE_FUTURES_API = True`; config.py:49-51 usa `fapi.binance.com`; scalping_data.py respeita a config |
| A2 | Dashboard sem autenticacao | CORRIGIDO | dashboard_server.py:73 `_check_basic_auth()`; :85 `require_post_auth` decorator aplicado em POST endpoints |
| A3 | deploy.sh com `git add -A` e pull sem verificacao | CORRIGIDO | deploy.sh usa lista explicita de arquivos; safety net para secrets; `git pull --ff-only`; health check pre-restart; prompt de confirmacao |
| A4 | Backtest com logica duplicada do strategy.py | CORRIGIDO | backtest.py:14 `from strategy import _score_row`; :139 comentario "A4 FIX: single source of truth" |
| A5 | Backtest de apenas 30 dias | CORRIGIDO | config.py:89 `BACKTEST_DAYS = 180` |
| A6 | STOP_LOSS_MAP overfitted in-sample | CORRIGIDO | STOP_LOSS_MAP removido; config.py:100 `ATR_SL_MULTIPLIER = 1.5` com `ATR_SL_FLOOR_PCT = 2.0` — SL universal baseado em ATR |
| A7 | Pump trader sem limite de posicoes simultaneas | CORRIGIDO | pump_trader.py:18 importa `PUMP_MAX_POSITIONS`; :148 verifica `len(state["positions"]) >= PUMP_MAX_POSITIONS` |
| A8 | Dump detection efetivamente inoperante | CORRIGIDO | config.py:135 `PUMP_DUMP_RETRACE_PCT = 4.5` (1.5x trailing de 3%); deteccao por velocidade adicionada: 2% em 3 candles |
| A9 | Supervisor com MAX_RESTARTS=50 sem backoff | CORRIGIDO | supervisor.py:25 `MAX_RESTARTS = 10`; :26 `BACKOFF_STEPS = [10, 30, 60, 120, 300]` — backoff exponencial com cap 5min |
| A10 | Trade agent log sem try/except | CORRIGIDO | trade_agents.py:628-631 e :744-747 — ambas chamadas `log_trade()` envolvidas em try/except |
| A11 | Scalping ausente do /capital e relatorio diario | CORRIGIDO | daily_report.py:117-119 le `SCALPING_STATE_FILE` e inclui em `caps["Scalping"]` |

## Observacoes

1. **A1 — Nota parcial:** `market.py:20` ainda usa `api.binance.com` (Spot), usado pelo paper/agent trader. O scalping usa `scalping_data.py` que respeita `USE_FUTURES_API`. A migracao completa para Futures (item E6 do melhorias.md) ainda nao foi feita para todos os subsistemas.

2. **A3 — Deploy robusto:** O deploy.sh atual e significativamente mais seguro que o original, com 4 camadas de protecao: staging seletivo, bloqueio de secrets, ff-only pull, e health check Python.

3. **A8 — Duplo criterio:** Alem do retrace de magnitude (4.5%), agora existe deteccao por velocidade de queda (2% em 3 candles), tornando a deteccao de dump efetiva antes do trailing stop.

## Proximos Passos

Todos os itens ALTO estao resolvidos. Os proximos alvos sao:
- **Itens CRITICOS (C1–C7):** Verificar se tambem foram resolvidos
- **Itens MEDIO (M1–M12):** Priorizar M1 (backtest scalping — ja existe `backtest_scalping.py`) e M5 (fallback IA)
