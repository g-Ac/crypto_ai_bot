# H1 — Pair Trading BTC/ETH (EXP-004)

```
Status:             Draft / Awaiting owner approval
Experiment ID:      EXP-004
Family:             Cross-asset statistical arbitrage (new family)
Stage:              HYPOTHESIS → BACKTEST (pending approval)
Hypothesis origin:  Gap-filling para regimes onde momentum v1.1 nao opera
Depends on:         momentum v1.1 em producao estavel (nao interfere com v1.1)
Owner approval:     Required antes de iniciar BACKTEST
Created:            2026-04-21
```

Spec de governanca e design para a primeira estrategia complementar ao Momentum Pullback v1.1. Objetivo: preencher o gap operacional deixado pelo momentum (regimes VOLATILE/RANGING, 52% do tempo) com um sinal estruturalmente novo de stat arb cross-asset.

---

## 1. Contexto e motivacao

### Por que uma estrategia complementar agora

Momentum v1.1 foi aprovada como baseline robusta (3/3 testes PASS em 2026-04-15). Desde entao, 3 tentativas de refinamento parametrico (BE50, PB25, hourly sizing) foram NO-GO — o consenso e que v1.1 esta em otimo local. Auditoria rodada em 2026-04-21 sobre 6 dias / 16 trades em paper confirma:

- DD atual −2.3% (abaixo do holdout historico de −8%)
- PF 0.68 proximo do holdout adverso (0.72)
- 51% das decisoes bloqueadas por regime (VOLATILE dominando)
- 43.8% das saidas sao timeout (mercado sem conviccao direcional)

Nao ha evidencia de degradacao estrutural — ha evidencia de que momentum deixa 52% do tempo em standby. Uma estrategia complementar operando nesse gap e a rota natural de evolucao.

### Por que pair trading BTC/ETH

- **Familia nunca tentada neste projeto** (registry limpo)
- **Opera em qualquer regime** — edge depende de co-movimento, nao de direcao de mercado
- **Reusa infra existente** (pipeline de candles, audit framework, DB)
- **Custo de implementacao moderado** — modulo isolado, sem dependencia de dados ao vivo fragil
- **Backtest viavel** — dados historicos disponiveis via Binance REST

### Registry — por que EXP-004 e estruturalmente nova

Mean reversion single-asset (CFER, RAVR) esta DEAD. EXP-004 difere estruturalmente:

- **Cross-asset** (nao single-asset): mede co-movimento entre dois ativos, nao desvio em um unico
- **Spread de retornos** (nao spread de preco): fundamento matematico distinto (estacionaridade natural vs suposta)
- **Foco em co-movimento** (nao em nivel absoluto): hipotese opera sobre correlacao, nao sobre VWAP/BB

Por essas tres dimensoes, EXP-004 passa pelo filtro "nao-tuning-do-que-morreu" do registry.

---

## 2. Hipotese formal

> Em timeframe 15m, quando o z-score do cumulative return spread BTC/ETH em janela rolante de 96 candles (24h) atinge `|z| >= 2.0`, ha probabilidade elevada do spread retornar a `|z| <= 0.5` dentro de 24 horas, gerando edge via trade pair simultaneo (long o underperformer, short o outperformer).

**Observacao epistemica:** sem intuicao forte do owner sobre por que deveria funcionar — e exploratoria, estamos testando se o pattern existe. Isso eleva o bar de validacao: backtest marginal sera lido como evidencia de ausencia de edge, nao como sinal fraco a refinar.

---

## 3. Escopo

### In v1

- **1 par**: BTCUSDT / ETHUSDT
- **1 timeframe**: 15m
- **1 sinal**: cumulative return spread z-score
- **1 pool de capital**: US$ 1.000 dedicado, isolado do momentum
- **1 posicao concorrente** (max_concurrent_positions = 1)
- **Sem regime filter** (regime-agnostico; regime gravado para analise posterior)
- **Telegram minimo**: inclui em `/posicoes`, dispara msg de open/close
- **Daily report**: 1 linha adicional (N trades, PnL, WR do pair)
- **Circuit breaker proprio**: pausa em DD >= 5% do pool

### Fora do v1 (para v2 se v1 provar edge)

- Multi-par (BTC/SOL, ETH/SOL, etc.)
- Beta-adjusted sizing
- Regime filter como gate de entrada
- Parcial TP1 / breakeven
- Integracao completa com dashboard HTML (paginas dedicadas)
- Filtro de correlacao como gate
- Cointegration (Engle-Granger)
- Interacao com momentum (ex: skip se momentum tem BTC long oposto)

### Fora permanentemente

- Execucao real (paper-only pelo ciclo inteiro ate decisao final de release)
- Alavancagem > 1x

---

## 4. Parametros congelados

Apos calibracao em BACKTEST e robustez PASS, esses valores congelam. Mudanca = volta para BACKTEST (regra registry).

| Parametro | Valor inicial | Observacao |
|---|---|---|
| `symbols` | ("BTCUSDT", "ETHUSDT") | Fixo |
| `timeframe` | "15m" | Fixo |
| `window_candles` | 96 (24h) | Janela do cumulative spread |
| `zscore_window_candles` | 96 (24h) | Janela do rolling z-score — revisitar se z instavel |
| `entry_z` | 2.0 | Entry threshold (\|z\|) |
| `entry_max_z` | 2.9 | Entry guard: se \|z\| ja >= 3.0, nao entra |
| `exit_tp_z` | 0.5 | Take profit |
| `exit_sl_z` | 3.0 | Stop loss |
| `time_stop_candles` | 96 (24h) | Time-based exit |
| `capital_per_leg_usd` | 500.0 | Notional por perna |
| `total_capital_usd` | 1000.0 | Pool dedicado |
| `max_concurrent_positions` | 1 | |
| `circuit_breaker_dd_pct` | 5.0 | Pausa entradas novas |
| `fees_taker_pct` | 0.04 | Por leg, por lado (entry+exit = 0.16% round-trip) |
| `slippage_pct` | 0.0 | Paper; analise de sensibilidade no backtest |

---

## 5. Componentes

Cada modulo tem responsabilidade unica e e testavel em isolamento.

### `pair_trading/config.py`

`PairConfig` como dataclass. Le env vars para override (`PAIR_TRADER_ENABLED`, `PAIR_CAPITAL_USD`, etc.). Valida invariantes na criacao (`entry_z > 0`, `exit_tp_z < entry_z < exit_sl_z`, `capital_per_leg_usd * 2 == total_capital_usd`).

### `pair_trading/spread_calculator.py`

Funcao pura. Input: dois arrays numpy (BTC close, ETH close) de tamanho >= 192, alinhados por timestamp. Output: `SpreadSnapshot` com:
- `timestamp`, `cum_spread`, `rolling_mean`, `rolling_std`, `z_score`
- `correlation` (corr 15m de returns sobre 96 candles — logado mas nao usado como gate no v1)
- `is_valid: bool` (False se NaN/Inf/std=0)

Sem I/O. Sem estado. Testado com fixtures sinteticos.

### `pair_trading/pair_trader.py`

Funcao pura. Input: `SpreadSnapshot` + `Optional[PairPosition]`. Output: `PairDecision` (enum + metadata).

Enum `PairAction`: `NO_ACTION`, `OPEN_LONG_BTC_SHORT_ETH`, `OPEN_SHORT_BTC_LONG_ETH`, `CLOSE_TP`, `CLOSE_SL`, `CLOSE_TIMEOUT`, `HOLD`.

`PairDecision` inclui `blocked_by: Optional[str]` com motivo (`"z_below_threshold"`, `"z_above_entry_guard"`, `"invalid_zscore"`, `"insufficient_history"`, `"api_failure"`, `"circuit_breaker"`, `"position_already_open"`, `"waiting_for_new_candle"`).

Prioridade de exit quando multiplas condicoes: `SL > TIMEOUT > TP`.

### `pair_trading/paper_executor.py`

Mantem estado mutavel (capital, posicao aberta, historico de equity). Recebe `PairDecision`, executa virtualmente, persiste em DB e `pair_state.json`.

Mirrors `momentum/paper_executor.py` em estrutura. Diferenca principal: cada posicao e **dual-leg**. P&L calculado como soma ponderada das duas pernas.

### `pair_trading/research_runner.py`

Backtest offline. Mesmo padrao de `momentum/research_runner.py`. Grava em `research/pair_*.db`. Suporta walk-forward e robustez via `robustness_check.py` (compartilhado ou espelhado).

### Integracao em `main.py`

```python
# Apos process_momentum_cycle
if PAIR_CONFIG.enabled:
    process_pair_cycle(PAIR_CONFIG, pair_state, candles_btc, candles_eth)
```

Uma linha. Flag `PAIR_TRADER_ENABLED` default `false`. Ativa apos aprovacao de paper.

---

## 6. Data flow

### Cadencia

Main loop roda a cada 5 min. Pair opera em 15m — processa apenas quando ha candle novo fechado.

```
SE ultimo_candle_btc.close_time == ultimo_candle_eth.close_time
   AND close_time > last_processed_close_time
   AND close_time < now_ms:
    processa
SENAO:
    skip (grava blocked_by = "waiting_for_new_candle")
```

### Fetch

- Busca 200 candles 15m de BTCUSDT e ETHUSDT
- Fetch paralelo (2 threads) para minimizar skew temporal
- Alinha por timestamp (drop nao-matching)
- Se interseccao < 192 candles → `blocked_by = "insufficient_history"`

### Calculo

```
cum_spread(t) = log(BTC(t) / BTC(t-96)) - log(ETH(t) / ETH(t-96))

rolling_mean = media(cum_spread[-96:])
rolling_std  = std(cum_spread[-96:])

z(t) = (cum_spread(t) - rolling_mean) / rolling_std

correlation = corr(BTC_returns_15m, ETH_returns_15m) sobre 96 candles
```

### Decisao

```
SE posicao aberta:
    SE |z| >= sl_z → CLOSE_SL  (prioridade 1)
    SE candles_held >= time_stop → CLOSE_TIMEOUT  (prioridade 2)
    SE |z| <= tp_z → CLOSE_TP  (prioridade 3)
    SENAO → HOLD
SENAO (sem posicao):
    SE not circuit_breaker_active AND entry_z <= |z| <= entry_max_z:
        SE z > 0 → OPEN_SHORT_BTC_LONG_ETH
        SE z < 0 → OPEN_LONG_BTC_SHORT_ETH
    SENAO → NO_ACTION com blocked_by
```

### Persistencia

**`pair_decisions`** (1 linha por ciclo — inclui ciclos skipped):

`id, timestamp, z_score, cum_spread, rolling_mean, rolling_std, correlation, btc_regime, action_taken, blocked_by, position_id (FK)`

**`pair_trades`** (1 linha por trade fechado — ambas pernas juntas):

`id, entry_time, exit_time, direction, entry_btc, entry_eth, exit_btc, exit_eth, entry_z, exit_z, exit_reason, pnl_btc_pct, pnl_eth_pct, pnl_total_pct, pnl_usd, candles_held, capital_at_entry, btc_regime_entry, session_entry`

**`pair_equity`** (1 linha por ciclo — serie temporal):

`id, timestamp, capital, realized_pnl, unrealized_pnl, peak_equity, drawdown_pct, circuit_breaker_active`

**`pair_state.json`** (atomico via tempfile + os.replace, gravado a cada ciclo):

`{last_processed_close_time, open_position: null | {...}, peak_equity, circuit_breaker_active}`

### Recovery pos-restart

```
1. Le pair_state.json
2. Se JSON corrompido → trata como sem posicao aberta + ALERTA proactive
3. Se posicao aberta: carrega entry_time, prices, direction
4. Reconcilia com DB (ultima linha pair_trades): se conflito → confia no DB + ALERTA
5. Continua gestao normal no proximo ciclo
```

---

## 7. Error handling e circuit breaker

### Falhas externas

| Evento | Acao |
|---|---|
| Binance timeout / 5xx | Retry 3x (1s, 3s, 10s). Se falhar → skip ciclo, `blocked_by = "api_failure"` |
| Rate limit 429 / 418 | Respeita `Retry-After`; fallback 60s. Log warning |
| Fetch BTC e ETH dessincronos | Alinha por timestamp. Se interseccao < 192 → `insufficient_history` |

### Falhas internas

| Evento | Acao |
|---|---|
| `z = NaN/Inf` | `blocked_by = "invalid_zscore"`. Nao abre nem fecha |
| `std = 0` | Mesmo que NaN |
| Candle com price/volume zero | Drop do candle |
| Candle nao fechado ("fake closed") | Descarta candle, usa penultimo |
| Menos de 192 candles validos | `blocked_by = "insufficient_history"` |

### Falhas de estado

| Evento | Acao |
|---|---|
| Crash mid-trade | state file gravado a cada ciclo → recovery carrega no restart |
| `pair_state.json` corrompido | Trata como sem posicao + alerta proactive |
| DB locked | Retry 3x com 100ms. Se falhar, log error + segue |
| Inconsistencia DB vs state file | Confia no DB, limpa state, alerta proactive |

### Circuit breaker

```
equity_atual = initial_capital + realized_pnl + unrealized_pnl
peak         = max(historico de equity)
dd_pct       = (peak - equity_atual) / peak * 100

SE dd_pct >= 5.0:
    estado = PAUSED
    alerta proactive Telegram
    todas entradas futuras bloqueadas com blocked_by = "circuit_breaker"
    posicao aberta segue ate TP/SL/timeout normal (nao forca fechamento)
    reset apenas via /resume manual ou edit explicito de pair_state.json
```

### Invariantes garantidas por assertion

- Nunca abre posicao com posicao ja aberta (`max_concurrent = 1`)
- Nunca abre com z-score invalido
- Nunca opera com < 192 candles validos
- Nunca grava trade com `entry_price` ou `exit_price` zero
- State sempre persistido antes de return do ciclo (mesmo em early-return por falha)

Violacao de qualquer invariante → assertion error → supervisor reinicia. Preferivel crashar a operar com estado corrompido.

### Alerting proativo

Extende `proactive_alerts.py` com 3 checks especificos:

| Check | Threshold | Cooldown |
|---|---|---|
| `pair_drawdown_warning` | DD >= 3% (antes do circuit breaker) | 2h |
| `pair_zero_trades_48h` | 0 trades em 48h | 12h |
| `pair_api_failures` | >= 5 falhas em 1h | 1h |

---

## 8. Testing

### Testes unitarios (auto-rodados pelo hook PostToolUse)

| Arquivo | Cobre |
|---|---|
| `test_pair_spread_calculator.py` | fixtures sinteticos (senoidal, drift, NaN, std=0, short history); valida z, mean, std, correlation |
| `test_pair_trader.py` | decisao em todos estados; prioridade SL > TIMEOUT > TP; entry guard \|z\| >= 3.0 nao entra |
| `test_pair_paper_executor.py` | capital tracking dual-leg, fees 0.16% RT, DB inserts, state atomico, recovery valida/corrompida |
| `test_pair_circuit_breaker.py` | DD 4% ativo, DD 6% PAUSED, posicao aberta segue, /resume volta |
| `test_pair_config.py` | env vars override, invariantes validadas, frozen apos load |
| `test_pair_integration_cycle.py` | ciclo completo com API mockada, 200 candles sinteticos, pipeline decisao→DB→state consistente |

Meta: 60 testes no modulo (proporcional aos 80 do momentum).

### Look-ahead protection

Decisao no candle T usa apenas dados ate fechamento de T. Entry/exit executa no T+1 open com T+1 open price. Teste diagnostico obrigatorio: backtest com `shift=0` (sem protecao, usa dados de T para decidir e executa no mesmo T) vs `shift=1` (correto). Criterios GO/NO-GO aplicam exclusivamente sobre `shift=1`. O `shift=0` serve de sanity check — se o PnL com `shift=0` for significativamente maior que com `shift=1` (gap > 20%), e indicio de que o sinal depende de informacao futura na construcao do z-score ou da decisao (data leak). Nesse caso, auditar `spread_calculator.py` antes de avancar.

### Comparacao com baseline nulo

Backtest obrigatoriamente compara contra 3 baselines:

1. **Buy-and-hold BTC** (Sharpe, total return)
2. **Buy-and-hold ETH** (Sharpe, total return)
3. **Trade aleatorio** — mesma frequencia de entrada que o pair, mesma distribuicao de holding period, direcao sorteada com seed fixa (reprodutivel). Media sobre 100 runs para estimar a distribuicao

Criterio: **PF_pair deve superar TODOS os 3 baselines** com margem estatisticamente significativa. Especificamente:
- PF_pair > PF equivalente de buy-and-hold BTC e ETH (calculado sobre mesma janela)
- PF_pair > percentil 95 da distribuicao de PF do random trader (i.e., edge real, nao sorte)

Se nao superar qualquer um dos 3 → DEAD.

### Analise de sensibilidade a custos

Backtest repetido com slippage adicional de 0.05% e 0.10% por leg. Se edge colapsa em 0.10%, a estrategia e fragil a condicoes reais.

---

## 9. Pipeline de research e GO/NO-GO

### Fases e criterios

| Transicao | Criterios PASS | Se FAIL |
|---|---|---|
| HYPOTHESIS → BACKTEST | Codigo roda end-to-end; trades > 0 em 90d; logs limpos; look-ahead teste PASS | Debug (nao e NO-GO) |
| BACKTEST → ROBUSTNESS | PF >= 1.2; WR >= 45%; trades >= 60 em 90d; DD max <= 15%; bate 3 baselines nulos; nao colapsa em +0.05% slippage | **DEAD** — postmortem + proxima hipotese (H2) |
| ROBUSTNESS → PAPER | 4/4 testes de robustez PASS | **DEAD ou iteracao limitada** (apenas se houver razao especifica documentada) |
| PAPER → decisao final | Ambos: (a) `PF_paper >= 1.0` (viabilidade absoluta apos fees); (b) `PF_paper / PF_backtest in [0.7, 1.3]` (aderencia ao backtest, validando que nao foi overfit) | Diagnosticar qual falhou: (a) falha = estrategia nao gera edge real; (b) falha = backtest era otimista → investigar antes de matar |

### Testes de robustez (4)

**TEST 1 — Consistencia mensal.** Split 90d em 3 meses. PASS: PF >= 1.0 em 2 de 3 meses.

**TEST 2 — Holdout out-of-sample.** 30 dias anteriores a janela de calibracao (mercado nunca visto). PASS: PF >= 0.8.

**TEST 3 — Regime breakdown.** Classificar trades por regime BTC (via `htf.py`) no entry. PASS: nenhum regime com PF < 0.5 e n >= 20.

**TEST 4 — Correlacao breakdown (especifico pair).** Bucketar trades por correlacao no entry (0.3-0.5, 0.5-0.7, 0.7+). Se edge se concentra em alta correlacao → OK. Se edge se concentra em baixa correlacao → investigar (pode ser artefato).

### Kill criteria durante paper

- DD do pool >= 10% → pausa automatica, revisar
- Apos 40 trades: se PF_paper < 0.5 × PF_backtest → pausa, investigar overfitting
- Zero trades em 14 dias → parar, reavaliar thresholds

### Registro no EXPERIMENT_REGISTRY

Cada transicao (PASS ou FAIL) exige linha no registry (`docs/EXPERIMENT_REGISTRY.md`) com:
- DB path do backtest
- Numero de trades, PF, WR, DD, PnL
- Data da decisao
- Aprovacao explicita do owner

Se DEAD em qualquer estagio: postmortem obrigatorio em `~/obsidian-vault/context/decisoes/YYYY-MM-DD-h1-pair-trading-dead.md`.

---

## 10. Operacional

### Integracao com main.py

```python
# imports
from pair_trading.config import PairConfig
from pair_trading.paper_executor import process_pair_cycle

# init (uma vez)
PAIR_CONFIG = PairConfig.from_env()
pair_state = PairPaperExecutor(PAIR_CONFIG)

# loop principal, apos process_momentum_cycle
if PAIR_CONFIG.enabled:
    process_pair_cycle(pair_state, candles_btc, candles_eth)
```

Flag `PAIR_TRADER_ENABLED=false` default. Ativa apos aprovacao de paper.

### Runtime isolation

Pair respeita `BOT_ID` via `runtime_config.py`. DB em `runtime/<BOT_ID>/bot.db`, state em `runtime/<BOT_ID>/pair_state.json`, logs em `runtime/<BOT_ID>/logs/`.

### Telegram

`telegram_commands.py` adapta:
- `/posicoes`: mostra posicao pair ao lado de momentum
- `/status`: inclui pair PnL e DD no resumo
- `/performance`: 1 linha com N trades, WR, PF do pair

`telegram_notifier.py` adiciona:
- Mensagem no open/close de trade pair (formato similar ao momentum)

Pausa global (`/pausar`) respeitada pelo pair.

### Daily report

`daily_report.py` adiciona 1 linha no formato:

```
[PAIR] N={n} WR={wr}% PF={pf} PnL={pnl}% DD={dd}%
```

### Dashboard — v2

Sem paginas dedicadas no v1. Debug via `diagnose_funnel.py` CLI (adaptado para pair).

---

## 11. Decisoes abertas registradas (com justificativa)

Essas sao decisoes v1 que podem precisar reavaliacao em v2, dependendo do que backtest e paper mostrarem.

| Decisao | Valor v1 | Trigger para revisao |
|---|---|---|
| `zscore_window = 96` | Simetrico com cum_spread window | Se z ruidoso (std instavel no backtest) → aumentar para 192 ou 288 |
| Sem regime filter | Simplicidade | Se TEST 3 revelar regime com PF < 0.5 → adicionar filter em v2 |
| Sem correlation filter | Simplicidade | Se TEST 4 revelar edge concentrado em baixa corr → add filter |
| Sem funding cost | Negligible em 24h hold (~0.03%) | Se backtest vs paper divergirem e funding explicar gap |
| Equal notional sizing | BTC/ETH tem vol similar | Se backtest mostrar assimetria em P&L das pernas → beta-adjust em v2 |
| Circuit breaker manual reset | Forca owner a revisar causa | Se rodar > 6 meses estavel → considerar auto-reset apos 7d |

---

## 12. Referencias

- **Memoria e decisoes pre-H1**: 
  - `~/obsidian-vault/context/decisoes/2026-04-15-momentum-v1_1-robustez-confirmada.md`
  - Auditoria 2026-04-21 (sessao de brainstorming)
- **Padroes arquiteturais de referencia**:
  - `momentum/config.py`, `momentum/paper_executor.py`, `momentum/research_runner.py`
  - `docs/superpowers/specs/2026-04-15-paper-readiness-framework.md`
- **Registry**: `docs/EXPERIMENT_REGISTRY.md` (entrada EXP-004 a ser criada apos aprovacao)
- **Roadmap macro**: `docs/ROADMAP_V1.md` (fases 0-4 concluidas; H1 e evolucao pos-V1)

---

## 13. Proximos passos

1. Owner review deste spec (**bloqueante**)
2. Invocar skill `writing-plans` para gerar plano de implementacao detalhado com subtasks
3. Criar branch `feat/h1-pair-trading`
4. Implementar modulo (TDD — cada PR atomico, testado)
5. Criar entrada EXP-004 no registry apos primeiro backtest completo
6. Executar backtest + robustez
7. Se PASS: smoke test 24-48h em paper
8. Paper oficial 60 dias
9. Decisao final baseada em criterios objetivos

---

**Status atual:** spec escrita, aguardando review do owner. Nenhum codigo foi escrito ainda.
