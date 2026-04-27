# Experiment Registry

Registro formal de todas as hipoteses de trading testadas neste projeto.
Cada entrada documenta o ciclo de vida completo: da hipotese ate a decisao final.

---

## Lifecycle

```
HYPOTHESIS → BACKTEST → ROBUSTNESS → PAPER → LIVE → CLOSED
                ↓            ↓          ↓       ↓
               DEAD         DEAD       DEAD    DEAD
```

| Estagio | Significado |
|---|---|
| HYPOTHESIS | Hipotese formulada, ainda nao testada |
| BACKTEST | Backtest inicial rodou, metricas coletadas |
| ROBUSTNESS | Testes de robustez (walk-forward, holdout, regime breakdown) |
| PAPER | Paper trading ao vivo com capital virtual |
| LIVE | Trading real (futuro — nao aplicavel ainda) |
| CLOSED | Encerrada apos periodo completo com postmortem |
| DEAD | Encerrada por falta de edge, em qualquer estagio |

**Regras:**
- Transicoes sao forward-only (nao se ressuscita uma estrategia DEAD)
- Cada transicao exige evidencia documentada
- Parametros congelam ao entrar em PAPER (mudanca = volta para BACKTEST)
- Postmortem obrigatorio ao marcar DEAD ou CLOSED

---

## Registro de Experimentos

### EXP-001: CFER (Compression → Failed Expansion → Reversion)

| Campo | Valor |
|---|---|
| **Familia** | Defensive (mean reversion) |
| **Versao final** | v0.2 |
| **Estagio** | DEAD (no BACKTEST) |
| **Hipotese** | Em consolidacao, quando preco comprime (BB Width cai 6+ candles), tenta breakout com volume mas falha e reclaim dentro de 3 candles, traders presos forcam reversao previsivel |
| **Timeframe** | 15m |
| **Ativos** | BTCUSDT, ETHUSDT |
| **Periodo de teste** | 6 meses (~17.280 candles por ativo) |
| **Data de criacao** | 2026-04-14 |
| **Data de morte** | 2026-04-14 |
| **Decisao** | Hipotese nao existe em forma operavel. Familia encerrada |

**Metricas v0.1:**

| Metrica | BTC | ETH |
|---|---|---|
| Trades | 0 | 0 |
| Motivo | Compressao e volume spike sao mutuamente exclusivos em 15m | — |

Auditoria: 609 candles com compressao ativa, close saiu da BB 7 vezes (1.1%), nenhuma com volume spike (max 1.20x vs threshold 1.5x).

**Metricas v0.2** (separacao temporal — compressao como estado previo):

| Metrica | BTC | ETH |
|---|---|---|
| Trades | 93 | 88 |
| Profit Factor | 0.39 | 0.43 |
| Win Rate | 24.7% | 30.7% |
| Max Drawdown | -18.7% | -21.4% |
| PnL Total | -17.9% | -20.6% |
| Walk-forward | 1/3 positivo (marginal) | 0/3 positivo |

**Motivo da morte:** WR ~28% exigiria RR >= 2.6 para breakeven; RR real ficou muito abaixo. v0.1 morreu por falta de amostra (0 trades), v0.2 morreu por falta de edge (181 trades, todos negativos).

**Referencia:** `docs/defensive/DECISIONS_LOG.md` (D11, D13)

---

### EXP-002: RAVR (Regime-Aware Value Reversion)

| Campo | Valor |
|---|---|
| **Familia** | Defensive (mean reversion) |
| **Versao final** | v2 (5 variantes de exit) |
| **Estagio** | DEAD (no BACKTEST) |
| **Hipotese** | Em regime RANGING/WEAK_TREND, quando preco desvia >= 2 desvios padrao do VWAP 24h (z-score >= 2.0), a probabilidade de reversao ao VWAP e maior que continuacao |
| **Timeframe** | 15m |
| **Ativos** | BTCUSDT, ETHUSDT |
| **Periodo de teste** | 6 meses |
| **Data de criacao** | 2026-04-14 |
| **Data de morte** | 2026-04-15 |
| **Decisao** | Hipotese parcialmente correta (preco reverte ao VWAP), mas edge insuficiente para operar. 5 variantes de exit testadas, nenhuma com PF >= 1.0. Familia encerrada |

**Metricas v1** (entry + exit baseline):

| Metrica | Combinado |
|---|---|
| Trades | 694 |
| PnL | Negativo |
| Observacao | Entry promissora — preco move na direcao certa. Exit quebrado — target VWAP completo e ambicioso demais |

**Metricas v2** (entry congelada, 5 variantes de exit):

| Variante | BTC PF | BTC WR | BTC PnL | ETH PF | ETH WR | ETH PnL |
|---|---|---|---|---|---|---|
| v2a (controle) | 0.75 | 38.8% | -25.38% | 0.90 | 42.5% | -12.3% |
| v2b (TP1 parcial + BE) | 0.62 | 35.9% | -37.03% | 0.84 | 40.7% | -16.96% |
| v2c (TP1=1R + BE) | 0.65 | 39.2% | -33.43% | 0.78 | 42.7% | -26.06% |
| v2d (z-score decay) | 0.66 | 40.5% | -33.44% | 0.82 | 44.5% | -19.5% |
| v2e (smart timeout) | 0.65 | 39.9% | -32.11% | 0.77 | 42.9% | -24.76% |

**Achados criticos:**
- SL rate invariante ~47% em todas as variantes (o stop e atingido independente da estrategia de exit)
- Nenhuma variante atingiu PF >= 1.0
- Melhor resultado: v2a controle com ETH PF 0.90 — ainda submerso
- Conclusao: o problema nao era so o exit — o entry nao tem edge suficiente

**Motivo da morte:** "Encerrar RAVR como motor principal. Nao fazer v3, tuning fino, nem salvar mean reversion."

**Referencia:** `docs/defensive/DECISIONS_LOG.md` (D14), `data/backtest_runs/ravr_v2_summary.md`, `~/obsidian-vault/context/decisoes/2026-04-15-ravr-morta-bloco5.md`

---

### EXP-003: Momentum Pullback v1.1 (B1 — Baseline Oficial)

| Campo | Valor |
|---|---|
| **Familia** | Momentum (trend continuation) |
| **Versao** | v1.1 (parametros congelados) |
| **Estagio** | ROBUSTNESS → PAPER (em implementacao) |
| **Hipotese** | Em tendencia confirmada (EMAs alinhadas, crossover >= 5 candles), pullback de 30-70% do impulso que respeita EMA slow e depois fecha alem da EMA fast tende a continuar na direcao original |
| **Timeframe** | 15m |
| **Ativos** | BTCUSDT, ETHUSDT |
| **Periodo de teste** | 120 dias (Dez 2025 — Abr 2026) |
| **Data de criacao** | 2026-04-15 |
| **Data de robustez** | 2026-04-15 |
| **Decisao** | Robustez confirmada 3/3 PASS. Aprovada para paper com condicoes do Paper Readiness Framework |

**Parametros congelados (v1.1):**

| Parametro | Valor |
|---|---|
| EMA fast | 20 |
| EMA slow | 50 |
| Trend age min | 5 candles |
| Pullback min/max | 30% / 70% |
| Swing lookback | 5 |
| SL floor | 0.5% *(v1.0 era 0.3%)* |
| TP2 RR mult | 1.5 |
| Timeout | 16 candles (4h) |

**Evolucao v1.0 → v1.1:** Unica mudanca: `sl_floor_pct` de 0.3% para 0.5%. Stop mais largo previne stop-outs prematuros em pullbacks choppy.

**Robustez — 3 testes:**

**Teste 1: Consistencia Mensal — PASS**

| Mes | v1.0 PF | v1.1 PF | v1.0 WR | v1.1 WR | v1.0 SL% | v1.1 SL% |
|---|---|---|---|---|---|---|
| 1 (Jan-Fev) | 1.17 | 1.18 | 52.3% | 53.3% | 25.7% | 23.4% |
| 2 (Fev-Mar) | 1.02 | 1.03 | 52.3% | 52.9% | 30.7% | 29.9% |
| 3 (Mar-Abr) | 1.46 | 1.48 | 55.9% | 57.3% | 22.9% | 21.4% |

v1.1 venceu todos os 3 meses com deltas pequenos mas consistentes.

**Teste 2: Holdout Out-of-Sample (30 dias pre-janela) — PASS (MARGINAL)**

| Metrica | v1.0 | v1.1 |
|---|---|---|
| PF | 0.73 | 0.72 |
| WR | 47.7% | 48.3% |
| PnL | -7.57% | -8.16% |
| SL% | 30.7% | 28.7% |

Ambas perderam no holdout (mercado adverso Dez-Jan). v1.1 nao melhorou PnL mas mostrou melhor controle de drawdown (-2% SL).

**Teste 3: Regime Breakdown — PASS**

| Regime | v1.0 Trades | v1.0 PF | v1.1 Trades | v1.1 PF |
|---|---|---|---|---|
| TRENDING | 367 | 1.03 | 365 | 1.03 |
| WEAK_TREND | 36 | 3.64 | 33 | 3.94 |

Sem colapso por regime. Edge concentrado em WEAK_TREND (PF 3.94), TRENDING borderline (PF 1.03).

**Riscos identificados (nao sao bloqueantes):**
- Delta incremental (~1% WR, 0.01 PF) — melhoria nao dramatica
- Edge concentrado em WEAK_TREND (33 trades PF 3.94) enquanto TRENDING e borderline (365 trades PF 1.03)
- Holdout neutro — nenhuma vantagem em adversidade

**Condicoes para paper:**
- Parametros v1.1 congelados indefinidamente
- Mudanca em parametros = volta para BACKTEST
- Smoke test 24-48h obrigatorio antes de launch oficial
- Circuit breaker ativo (drawdown > threshold = pausa)
- Relatorio diario com PnL, trades, regime

**Referencia:** `~/obsidian-vault/context/decisoes/2026-04-15-momentum-v1_1-robustez-confirmada.md`, `momentum/config.py`, `docs/superpowers/specs/2026-04-15-paper-readiness-framework.md`

---

### EXP-004: Pair Trading BTC/ETH (H1)

| Campo | Valor |
|---|---|
| **Familia** | Cross-asset statistical arbitrage (nova familia) |
| **Versao** | v1.0 (params em `pair_trading/config.py`) |
| **Estagio** | **DEAD (no BACKTEST)** — falhou GO/NO-GO em 5/7 criterios |
| **Hipotese** | Em TF 15m, quando z-score do cumulative return spread BTC/ETH em janela de 96 candles (24h) atinge \|z\| >= 2.0, ha probabilidade elevada de reversao a \|z\| <= 0.5 em ate 24h, gerando edge via trade pair (long o underperformer, short o outperformer) |
| **Timeframe** | 15m |
| **Ativos** | BTCUSDT, ETHUSDT |
| **Periodo testado** | 90d (2026-01-15 → 2026-04-15) + 30d holdout (2025-12-16 → 2026-01-15) |
| **Data de criacao** | 2026-04-21 |
| **Data do postmortem** | 2026-04-27 |

**Motivacao original:** Gap-filling para regimes onde momentum v1.1 nao opera (VOLATILE + RANGING, ~52% do tempo). Familia "cross-asset stat arb" nunca testada neste projeto.

**Diferenciacao vs familias DEAD:**
- Nao e CFER/RAVR porque e cross-asset e opera em spread de retornos, nao em desvio single-asset de indicador tecnico
- Nao e breakout 5m porque timeframe e logica sao distintos
- Nao e scalping porque nao usa microestrutura (funding/liquidation/basis)

#### Postmortem

**Resultado do BACKTEST (90d main):** n=159, PF=0.32, WR=31.4%, PnL=-25.66%, DD=25.93%.
**Holdout 30d (OOS):** n=58, PF=0.08, WR=12.1%, PnL=-11.01%. Pior que main — sem reversion para ser explorada.
**Slippage sensitivity:** PF 0.32 → 0.08 (slip 0.05%) → 0.02 (slip 0.10%). Estrategia ja perdedora a slip=0; degradacao monotonica.
**Look-ahead diagnostic:** shift=0 PnL=-21.2% vs shift=1 PnL=-25.66%. Gap 17% (abaixo do limiar 20% pra suspeitar de leak). Ambos negativos: hipotese morre nos dados, nao por bug.

**Robustness (4 testes — 3 falham):**
- Test 1 monthly_consistency: PFs mensais [0.41, 0.25, 0.28], n_positive_pf=0 (precisa >=2/3) — ❌
- Test 2 holdout_oos: PF=0.083 < threshold 0.8 — ❌
- Test 3 regime_breakdown: regime UNKNOWN com 159 trades, PF=0.32 < floor 0.5 — ❌
- Test 4 correlation_bucket: passa por trivialidade (todos os trades caem em bucket "low") — ⚠️

**GO/NO-GO formal — 5 falhas de 7 criterios:**
- `pf_main` (0.32 < 1.2)
- `win_rate` (31.4 < 45)
- `max_drawdown` (25.9 > 15)
- `random_baseline` (0.32 < random p95=1.43 — **random trader supera nossa estrategia 4.5x**)
- `slippage_sensitivity` (PF 0.02 a slip 0.10%, < min 1.0)

**Sinal adicional:** `buy_hold_btc_pf = 0.0` e `buy_hold_eth_pf = 0.0` — BTC e ETH foram flat-or-down no periodo de 90d (Jan-Apr 2026). Regime adverso para mean reversion via spread.

**Conclusao:** A hipotese de que |z|>=2.0 do spread cumulativo BTC/ETH em 24h reverte em 24h **nao se sustenta nos dados** de 2026-Q1. A penalizacao de 4 fees+slippage por ciclo (long BTC + short ETH + close BTC + close ETH) torna o break-even inviavel mesmo se houver sinal direcional fraco. Random trader p95 supera por 4.5x — isto e ruido pior que aleatorio.

**Decisao:** EXP-004 marcado DEAD. Nao avancar para PAPER. Familia "cross-asset stat arb" descontinuada nesta forma. Possiveis variantes futuras (janela diferente, threshold diferente, multi-asset) ficam desencorajadas sem nova hipotese mecanica forte.

**Codigo preservado:** `pair_trading/` modulo permanece no repo como referencia + testes (757 testes verdes). Nao integrado ao main loop.

**Referencia:**
- `docs/superpowers/specs/2026-04-21-h1-pair-trading-design.md`
- `docs/superpowers/plans/2026-04-21-h1-pair-trading-backtest.md` (Phase 1)
- `research/pair_v1_robustness.json` (artefato deste backtest)
- `~/obsidian-vault/context/decisoes/2026-04-27-h1-pair-trading-dead.md`

---

### EXP-005: Momentum Universe Expansion (BTC/ETH → ~12 simbolos)

| Campo | Valor |
|---|---|
| **Familia** | Momentum (extensao do v1.1 baseline) |
| **Versao** | v1.0 (params congelados do v1.1; sizing S-B novo) |
| **Estagio** | HYPOTHESIS → BACKTEST (em implementacao Phase 1) |
| **Hipotese (H-C')** | Adicionar um universo liquido pre-congelado ao Momentum Pullback v1.1 melhora o baseline BTC/ETH em walk-forward, com PF agregado superior, DD relativo controlado, estabilidade entre folds aceitavel, e sem dependencia excessiva de um unico simbolo ou um unico fold. |
| **Timeframe** | 15m |
| **Universo candidato (13 simbolos)** | BTC, ETH, SOL, XRP, DOGE, BNB, ADA, LINK, AVAX, SUI, AAVE, LTC, NEAR (USDT-M perpetuals); universo final apos preflight pode ser 11-13 |
| **Periodo planejado** | 365d main + 90d holdout (~455d total por simbolo) |
| **Sizing** | S-B: capital pool fixo dividido por \|universo\|; max_positions = N |
| **GO/NO-GO** | 10 criterios bloqueantes (PF main >=1.25; >1.10x baseline v1.1; DD <=1.30x baseline; 9/12 folds positivos; LOO simbolo todos > baseline; LOO fold tolera 1 outlier; holdout PF>1.0 e >0.9x main; sem simbolo destrutivo PF<0.5 com n>=60; sobreviver slippage 0.10% universal). C3-normalized e BH equal-weight bloqueantes. |
| **Aprovacao** | Pending (aguarda backtest operacional) |
| **Data de criacao** | 2026-04-27 |

**Motivacao:** Memory `feedback_v1_frozen_at_local_optimum` indica que melhoria do v1.1 vem de mais dados ou estrategia complementar, nao de param tuning (3 NO-GOs em tuning). Universe expansion e o eixo natural.

**Diferenciacao vs EXP-004:** EXP-004 testou cross-asset stat-arb (pair trading) e morreu. EXP-005 testa generalizacao da MESMA mecanica (Momentum Pullback v1.1) para mais simbolos. Sem reuso de codigo do EXP-004 (archived branch).

**Trava metodologica:** Buckets (core/high_beta/infra) sao raio-X diagnostico, NAO criterio de selecao pos-hoc. Se EXP-005 falhar e algum bucket parecer bom, vira EXP-006 separado (Signal Selection / Portfolio Router) com hipotese nova.

**Referencia:**
- `docs/superpowers/specs/2026-04-27-exp-005-universe-expansion-design.md`
- `docs/superpowers/plans/2026-04-27-exp-005-universe-expansion-plan.md`

---

## Indice Rapido

| ID | Nome | Familia | Estagio | PF (melhor) | Decisao |
|---|---|---|---|---|---|
| EXP-001 | CFER v0.2 | Defensive | DEAD | 0.43 | Hipotese nao existe |
| EXP-002 | RAVR v2 | Defensive | DEAD | 0.90 | Edge insuficiente |
| EXP-003 | Momentum v1.1 | Momentum | PAPER (impl.) | 1.48 | Baseline oficial (B1) |
| EXP-004 | Pair BTC/ETH v1.0 | Cross-asset stat arb | DEAD (no BACKTEST) | 0.32 | Falhou 5/7 criterios; random trader supera 4.5x |
| EXP-005 | Momentum Universe v1.0 | Momentum (extensao) | HYPOTHESIS → BACKTEST | — | Aguardando backtest operacional |

---

## Convencoes

- **EXP-NNN**: ID sequencial, nunca reutilizado
- **Versao**: `familia-vX.Y` (X = mudanca estrutural, Y = ajuste de parametro)
- **Datas**: formato ISO `YYYY-MM-DD`
- **Metricas obrigatorias**: trades, PF, WR, max drawdown, PnL total, periodo
- **Postmortem obrigatorio**: ao marcar DEAD ou CLOSED, documentar motivo e evidencia
- **Parametros**: listar os valores exatos usados — nao "defaults do config"
