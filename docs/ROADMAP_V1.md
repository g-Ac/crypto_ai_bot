# Roadmap: Alpha Avancado → V1 Funcional

> Plano criado em 2026-04-13. Evolucao gradual, sem pressa. ~8-10 semanas a 1-2h/dia.

---

## FASE 0: Parar a Hemorragia (Semana 1) ✅
> Esforco: 2-3 horas + 48h validacao — **Concluido 2026-04-13**

### 0.0 Desativar Agent Trader ✅
- **Arquivo**: `.env` → `AGENT_TRADER_ENABLED=false`
- **Motivo**: -21.07% em 40 trades. Haiku nao agrega alpha
- **Done**: Nenhum trade novo em agent_trades apos restart (16:25 2026-04-13)

### 0.1 Fix liquidacoes invertidas ✅
- **Arquivo**: `market_data.py:235-241` (funcao `_get_proxy_liquidations`)
- **Fix**: `if is_maker_buyer: vol_short += notional` / `else: vol_long += notional`
- **Teste**: `tests/test_market_data.py` — 6 testes (mock aggTrades, threshold, mixed, api failure)
- **Done**: 6/6 testes verdes

### 0.2 Fix win/loss com TP1 parcial ✅
- **Arquivo**: `scalping_trader.py:663-671` (funcao `_check_open_positions`)
- **Fix**: `total_trade_pnl_usd = pnl_usd + tp1_pnl_usd`, win/loss pelo total
- **Teste**: `tests/test_scalping_trader.py` — 5 testes (TP1+breakeven win, loss, normal, pnl accounting)
- **Done**: 5/5 testes verdes

### 0.3 Lock no scalping_state.json ✅
- **Arquivo**: `risk_manager.py:33-68` (load/save_scalping_state)
- **Fix**: `threading.Lock` global + `tempfile` + `os.replace` atomico
- **Teste**: `tests/test_risk_manager.py` — 5 testes (lock exists, concurrent saves/reads, atomic, default)
- **Done**: 5/5 testes verdes, 0 corrupcoes em testes de concorrencia

---

## FASE 1: Fundacao (Semanas 2-3) ✅
> Esforco: 1-2 semanas — **Concluido 2026-04-13**

### 1.1 Pytest funcional no Pi ✅
- pytest ja esta no venv. Garantir `python -m pytest tests/ -v` roda com 0 falhas
- **Done**: 173 testes verdes (2026-04-13)

### 1.2 Fix ATR off-by-one ✅
- **Arquivo**: `risk_manager.py:115`
- Guard ja estava `< 22` — corrigido anteriormente
- **Done**: Comportamento correto verificado

### 1.3 Centralizar URLs da Binance ✅
- **Arquivos**: 10+ ficheiros com `api.binance.com` hardcoded
- Criadas 5 constantes em `config.py`: `BINANCE_SPOT_KLINES_URL`, `BINANCE_SPOT_TICKER_URL`, `BINANCE_SPOT_TICKER_24HR_URL`, `BINANCE_FUTURES_KLINES_URL`, `BINANCE_FUTURES_BALANCE_URL`
- Substituido em: market.py, pump_trader.py, pump_scanner.py, dashboard_server.py, close_orphan_trades.py, trade_agents.py, paper_trader.py, backtest.py, backtest_pump.py, risk_manager.py
- **Done**: Apenas `config.py` (definicoes) e `market_data.py` (base URLs compostas) contem URLs hardcoded (2026-04-13)

### 1.4 File handle leak no supervisor ✅
- **Arquivo**: `supervisor.py`
- `log_files` dict ja gere lifecycle: close em morte, restart, KeyboardInterrupt e shutdown critico
- **Done**: Sem leak — verificado em todos os caminhos (2026-04-13)

### 1.5 label_scalping_outcomes no try/except ✅
- **Arquivo**: `main.py:316-324`
- Ja estava em try/except com print de erro
- **Done**: Ja implementado (verificado 2026-04-13)

### 1.6 Cobertura de testes minima ✅
- **Ficheiros de teste**: 12 (test_indicators, test_strategy, test_htf, test_daily_report + 8 existentes)
- **Total**: 173 testes cobrindo: indicators, strategy, htf, daily_report, confluence, execution_layer, funding_engine, liquidation_engine, basis_engine, market_data, risk_manager, scalping_trader
- **Done**: Pipeline completo coberto — sinais → regime → confluence → risk → execution (2026-04-13)

---

## FASE 2: Inteligencia (Semanas 4-7) — Parcial
> Esforco: 2-4 semanas (inclui tempo de observacao)

### 2.1 Diagnostico da confluence pass rate ✅
- Causa raiz: dados de microestrutura NULL em 99.4% das decisoes historicas (coleta so comecou 2026-04-13 16:26)
- Quando dados fluem, confluence bloqueia 100% porque thresholds dos motores nao correspondem a condicoes normais
- **Done**: Relatorio de funnel com causa raiz identificada (2026-04-13)

### 2.2 Calibracao de thresholds dos motores ✅
- 5 steps aplicados + 3 fixes de robustez:
  1. Cache prev_basis para M3 velocity (`scalping_trader.py`)
  2. Solo override na confluence: 1 motor com score >= 55 -> sizing SOLO 30%/2x (`confluence.py`)
  3. Thresholds M1 reduzidos: zona neutra -0.003%/0.005%, moderado 0.008%/-0.005% (`funding_engine.py`)
  4. Cascata sem OI: liq > $200K dispara sem confirmacao OI (`liquidation_engine.py`)
  5. Dead zone gate 80 -> 60 (`basis_engine.py`)
- Fixes: prev_basis_pct propagado para V2.1b, docstring atualizada, testes fortalecidos
- **Done**: 180 testes verdes, deploy pendente de restart (2026-04-13)

### 2.3 Regime gate refinamento ⏳
- **Arquivo**: `confluence.py:40-47` (dict `_REGIME_MOTORS`)
- Aguarda acumulacao de dados: regime so grava desde 2026-04-13, precisa de semanas com trades fechados
- **Done**: Cada regime tem win rate documentado

### 2.4 V2.1b ativacao gradual ⏳
- Infra 100% pronta, 0 trades ainda
- Pre-requisito: >= 50 trades V2.1b paper side-by-side
- **Done**: V2.1b com >= 50 trades, decisao documentada

---

## FASE 3: Observabilidade (Semanas 6-8, paralelo com Fase 2) ✅
> Esforco: 2-3 semanas — **Concluido 2026-04-13**

### 3.1 Relatorio de performance automatico ✅
- **Arquivos**: `daily_report.py` + `database.py` (3 queries novas)
- Secao de breakdown adicionada ao relatorio diario: funil (blocked_by), por regime, por sessao
- Queries: `get_scalping_decisions_summary()`, `get_scalping_trades_by_regime()`, `get_scalping_trades_by_session()`
- **Done**: 11 testes green (2026-04-13)

### 3.2 Funnel de decisao visualizado ✅
- **Arquivo reescrito**: `diagnose_funnel.py` (motores antigos → dados do banco M1/M2/M3)
- Modo CLI (`python diagnose_funnel.py --json`) + modulo importavel
- Endpoints: `GET /api/funnel` (JSON) + `GET /scalping/funnel` (pagina HTML)
- Template: `templates/scalping_funnel.html` (dark theme consistente)
- **Done**: 4 testes + pagina funcional (2026-04-13)

### 3.3 Dashboard enhancement ✅
- Equity curve: `GET /api/equity` (JSON) + `GET /equity` (Chart.js line chart)
- Chart.js CDN — PnL cumulativo por sistema (scalping, pump, total) com toggle 7d/30d/90d
- Trade log melhorado: filtros `?regime=` e `?session=` no `/api/trades?system=scalping`
- Templates: `templates/equity.html`
- **Done**: Endpoint + grafico interativo (2026-04-13)

### 3.4 Alertas proativos via Telegram ✅
- **Arquivo novo**: `proactive_alerts.py` + integracao no `main.py`
- 3 checks: drawdown >= 3% (cooldown 2h), zero trades 24h (cooldown 12h), erros repetidos >= 5/h (cooldown 1h)
- Dedup in-memory (mesmo padrao de circuit breaker)
- **Done**: 13 testes green (2026-04-13)

---

## FASE 4: V1 Release (Semanas 9-10)
> Esforco: 1-2 semanas + observacao

### 4.1 CI basico no Pi ✅
- Script `ci.sh`: venv → pytest (200 tests) → py_compile (12 arquivos criticos) → Telegram (--notify)
- Git hook `pre-push` roda ci.sh automaticamente — bloqueia push se falhar
- **Done**: CI green, hook ativo (2026-04-13)

### 4.2 V2 vs V2.1b decisao final
- >= 100 trades em cada, t-test no PnL, comparacao de Sharpe
- **Done**: Uma unica configuracao ativa

### 4.3 Requirements separados ✅
- `requirements.txt` (11 deps producao) + `requirements-dev.txt` (inclui pytest)
- deploy.sh atualizado para stage ambos os ficheiros
- **Done**: Split funcional (2026-04-13)

### 4.4 Documentacao V1 ✅
- README reescrito: arquitetura, fluxo de sinais, 3 motores, setup, CI, deploy, dashboard, alertas
- Estrutura de arquivos atualizada (61 .py files, templates, tests)
- **Done**: README V1 completo (2026-04-13)

### 4.5 Criterios de V1 Release
Todos devem ser verdade:
- [ ] 0 bugs criticos conhecidos
- [ ] Testes verdes (pytest passa)
- [ ] Scalping win rate >= 45%
- [ ] PnL positivo em >= 2 dos 4 sistemas (ultimo mes)
- [ ] Dashboard com equity curve
- [ ] Daily report automatico via Telegram
- [ ] Uptime >= 95%

---

## Timeline

| Fase | Esforco | Semanas | Status |
|------|---------|---------|--------|
| Fase 0 | 2-3h + 48h validacao | 1 | **Done** (2026-04-13) |
| Fase 1 | 1-2 semanas | 2-3 | **Done** (2026-04-13) |
| Fase 2 | 2-4 semanas | 4-7 | **Parcial** (2.1+2.2 done, 2.3+2.4 aguardam dados) |
| Fase 3 | 2-3 semanas | 6-8 | **Done** (2026-04-13) |
| Fase 4 | 1-2 semanas | 9-10 | **Parcial** (4.1+4.3+4.4 done, 4.2+4.5 aguardam dados) |

**Total: ~8-10 semanas a 1-2h/dia**
