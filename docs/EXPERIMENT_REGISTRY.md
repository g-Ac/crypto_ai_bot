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
| **Estagio** | HYPOTHESIS → BACKTEST (em implementacao Phase 1) |
| **Hipotese** | Em TF 15m, quando z-score do cumulative return spread BTC/ETH em janela de 96 candles (24h) atinge \|z\| >= 2.0, ha probabilidade elevada de reversao a \|z\| <= 0.5 em ate 24h, gerando edge via trade pair (long o underperformer, short o outperformer) |
| **Timeframe** | 15m |
| **Ativos** | BTCUSDT, ETHUSDT |
| **Periodo planejado** | 90d backtest + 30d holdout OOS |
| **Data de criacao** | 2026-04-21 |
| **Aprovacao** | Pending (aguarda resultado do primeiro backtest) |

**Motivacao:** Gap-filling para regimes onde momentum v1.1 nao opera (VOLATILE + RANGING, ~52% do tempo). Familia "cross-asset stat arb" nunca testada neste projeto.

**Diferenciacao vs familias DEAD:**
- Nao e CFER/RAVR porque e cross-asset e opera em spread de retornos, nao em desvio single-asset de indicador tecnico
- Nao e breakout 5m porque timeframe e logica sao distintos
- Nao e scalping porque nao usa microestrutura (funding/liquidation/basis)

**Referencia:**
- `docs/superpowers/specs/2026-04-21-h1-pair-trading-design.md`
- `docs/superpowers/plans/2026-04-21-h1-pair-trading-backtest.md` (Phase 1)

---

## Indice Rapido

| ID | Nome | Familia | Estagio | PF (melhor) | Decisao |
|---|---|---|---|---|---|
| EXP-001 | CFER v0.2 | Defensive | DEAD | 0.43 | Hipotese nao existe |
| EXP-002 | RAVR v2 | Defensive | DEAD | 0.90 | Edge insuficiente |
| EXP-003 | Momentum v1.1 | Momentum | PAPER (impl.) | 1.48 | Baseline oficial (B1) |
| EXP-004 | Pair BTC/ETH v1.0 | Cross-asset stat arb | HYPOTHESIS → BACKTEST | — | Aguardando primeiro backtest |

---

## Convencoes

- **EXP-NNN**: ID sequencial, nunca reutilizado
- **Versao**: `familia-vX.Y` (X = mudanca estrutural, Y = ajuste de parametro)
- **Datas**: formato ISO `YYYY-MM-DD`
- **Metricas obrigatorias**: trades, PF, WR, max drawdown, PnL total, periodo
- **Postmortem obrigatorio**: ao marcar DEAD ou CLOSED, documentar motivo e evidencia
- **Parametros**: listar os valores exatos usados — nao "defaults do config"
