# EXP-005 — Momentum Universe Expansion (design spec)

**Data:** 2026-04-27
**Familia:** Momentum (extensao do v1.1 baseline)
**Estagio:** HYPOTHESIS (design fechado, plano e execucao a seguir)
**Predecessor:** [EXP-003 Momentum v1.1 baseline](./2026-04-15-paper-readiness-framework.md), EXP-004 DEAD postmortem
**Autor:** Gabriel + Kairos (sessao de brainstorming 2026-04-27)

---

## 1. Hipotese (H-C')

> **Adicionar um universo liquido pre-congelado ao Momentum Pullback v1.1 melhora o baseline BTC/ETH em walk-forward, com PF agregado superior ao baseline, DD relativo controlado, estabilidade entre folds aceitavel, e sem dependencia excessiva de um unico simbolo ou um unico fold.**

A pergunta operacional verdadeira:

> Vale trocar BTC/ETH-only por BTC/ETH + universo expandido?

Nao e:

> Existe algum bucket bonito depois de olhar os dados?

**Travas de seguranca a priori:**

1. PASS nao pode depender de um unico simbolo (leave-one-out por simbolo).
2. PASS nao pode depender de um unico fold (leave-one-out por fold, tolera 1 outlier).
3. Buckets (majors / high-beta / infra) sao raio-X diagnostico, **nao criterio de selecao pos-hoc**.
4. Regras de selecao secundaria (ex: top-k, dropar bucket vencedor) ficam de fora do GO/NO-GO. Se aplicaveis, viram EXP-006 separado.

**Output operacional se PASS:** bot opera o universo expandido completo (S-B alocacao) em paper trading. Promocao para producao depende de N dias de paper-trading com performance estavel (escopo de outro experimento).

**Output operacional se FAIL:** EXP-005 marcado DEAD. v1.1 BTC/ETH-only mantem-se como baseline ativa. Postmortem com evidencia detalhada.

---

## 2. Universo

### 2.1 Candidatos (13 simbolos)

| Bucket | Simbolos |
|---|---|
| Core / Majors | BTCUSDT, ETHUSDT, SOLUSDT |
| High-beta liquidos | XRPUSDT, DOGEUSDT, BNBUSDT, ADAUSDT |
| Infra / DeFi | LINKUSDT, AVAXUSDT, SUIUSDT, AAVEUSDT, LTCUSDT, NEARUSDT |

Universo final apos preflight pode ser 11-13 simbolos dependendo de disponibilidade de 455d em fapi (Binance USD-M Futures).

### 2.2 Bucket assignment (a priori, congelado)

```python
BUCKET_ASSIGNMENT = {
    "BTCUSDT": "core", "ETHUSDT": "core", "SOLUSDT": "core",
    "XRPUSDT": "high_beta", "DOGEUSDT": "high_beta",
    "BNBUSDT": "high_beta", "ADAUSDT": "high_beta",
    "LINKUSDT": "infra", "AVAXUSDT": "infra", "SUIUSDT": "infra",
    "AAVEUSDT": "infra", "LTCUSDT": "infra", "NEARUSDT": "infra",
}
```

Buckets sao congelados antes de qualquer backtest. Nao podem ser ajustados apos ver resultados.

### 2.3 Preflight (artefato congelado)

`scripts/run_expansion_preflight.py` faz:

1. Para cada candidato, fetcha primeiro kline disponivel em fapi (`/fapi/v1/klines` com `startTime=0, limit=1`).
2. Computa `eligible_455d = (today - first_kline) >= 455 dias`.
3. Escreve `research/expansion_v1_preflight.json`:

```json
{
  "frozen_at": "2026-04-27T15:00:00Z",
  "required_days": 455,
  "universe": ["BTCUSDT", "ETHUSDT", ...],
  "ineligible": {
    "SUIUSDT": {"first_kline": "2024-10-15", "days_available": 559}
  },
  "candidates_checked": 13,
  "universe_size": 12
}
```

Este JSON e **write-once** e versionado em git. Backtests subsequentes leem este JSON; nao re-rodam o preflight. Se preflight precisa rodar de novo (ex: novos simbolos), gera arquivo novo (`expansion_v2_preflight.json`).

### 2.4 Fallback (informativo, nao automatico)

Se preflight remover muitos simbolos e Gabriel quiser substitutos, candidatos secundarios em ordem de preferencia: DOTUSDT, BCHUSDT, UNIUSDT, TRXUSDT. **Substituicao e decisao manual** — nunca acontece automaticamente apos ver resultados de backtest.

---

## 3. Alocacao de capital (S-B)

**Princıpio:** capital total fixo, dividido por |universo|, max_positions = N. Mesma exposicao agregada do baseline atual.

```
capital_pool_usdt = BOT_PORTFOLIO_TARGET_CAPITAL  # mesmo valor do baseline live
slot_size_per_symbol = capital_pool_usdt / len(universe)

# Risk per trade reproduz o framework do v1.1:
# v1.1 atual usa risco de X% do capital do simbolo por trade (ver momentum/momentum_trader.py
# e momentum/paper_executor.py:_calculate_position_size). EXP-005 reproduz o mesmo X%
# aplicado sobre slot_size_per_symbol em vez de capital total do BTCUSDT individual.
risk_per_trade_usdt = slot_size_per_symbol * RISK_FRACTION_V11
max_positions = len(universe)
```

`RISK_FRACTION_V11` e congelado: e a mesma fracao usada por `_calculate_position_size` no v1.1 atual em `momentum/paper_executor.py`. EXP-005 nao introduz parametro novo de risco; apenas escala o slot.

**Trava de instrumentacao:** se 8 simbolos abrem sinal simultaneamente, cada um usa **sua fatia (1/N)**, nao 8x o size atual. Backtest precisa instrumentar `peak_concurrent_positions` e validar que `total_allocated <= capital_pool_usdt` em todo timestamp.

**Comparacao justa:** baseline C3-normalized (BTC/ETH) usa **o mesmo framework S-B** com `universe=["BTCUSDT","ETHUSDT"]`, nao live-style sizing. C3-live (live-style) e reportado em paralelo apenas para transparencia, nao e bloqueante.

**S-C top-k selection (max_positions = 2 com seleção dinâmica) e diagnostic only.** Nao tem direito de resgatar PASS do EXP-005. Se EXP-005 falhar e S-C parecer bom, vira EXP-006: Signal Selection / Portfolio Router.

---

## 4. Janela e walk-forward (W-C)

| Parametro | Valor |
|---|---|
| Main window | **365 dias** (avaliacao primaria) |
| Holdout | **90 dias** precedente (OOS no passado) |
| Walk-forward | **12 folds mensais** dentro da main window |
| Total fapi history requerido | **~455 dias completos** por simbolo |

Walk-forward serve para analise de **estabilidade entre folds** (v1.1 tem params congelados; nao ha treino). Cada fold e avaliado independentemente; estabilidade exige >=9/12 folds com PF > 1.0.

Holdout 90d (anterior a main) detecta regime change/drift. Nao e usado para tuning — apenas para confirmar que a main window nao foi um periodo anormalmente bom.

---

## 5. Slippage e custos (SL-B)

Slippage e penalidade conservadora por execucao, **definida a priori por bucket**. Nao tenta reconstruir microestrutura historica.

| Bucket | Slippage por leg |
|---|---|
| Core / Majors | **0.03%** |
| High-beta liquidos | **0.07%** |
| Infra / DeFi | **0.05%** |

**Sensitivity sweep universal:** `slippage = 0.10%` aplicado uniformemente em todos os simbolos (criterio #10 do GO/NO-GO). Decisao final exige sobreviver ao sweep universal de 0.10%.

Fees: mesmo modelo do v1.1 atual (taker fee Binance Futures padrao). Aplicado por leg (entry + exit).

---

## 6. GO/NO-GO criterios (10 itens — todos bloqueantes)

PASS iff **todos** os 10 satisfeitos. Falha em qualquer um → NO-GO.

| # | Criterio | Threshold | Comparador |
|---|---|---|---|
| 1 | PF agregado main 365d (S-B) | `>= 1.25` | absoluto |
| 2 | PF main vs **C3-normalized** (baseline v1.1 BTC/ETH com mesmo S-B) | `> 1.10 × baseline_pf` | melhoria material |
| 3 | Total return e DD vs **C2** (BH equal-weight do universo, custo zero) | `total_return > C2_return` E `max_dd <= C2_dd` | BH baseline generoso |
| 4 | DD agregado main vs DD baseline (C3-normalized) | `<= 1.30 × baseline_dd` | nao piora >30% relativo |
| 5 | Estabilidade entre folds | `n_folds_with_pf > 1.0 >= 9/12` | 75% folds positivos |
| 6 | Leave-one-out por simbolo | Todos os 12 cenarios (remover 1 simbolo) mantem `agg_pf > C3_baseline_pf` | no-single-symbol-dependency |
| 7 | Leave-one-out por fold | `>= 11/12` cenarios (remover 1 fold) mantem `agg_pf > C3_baseline_pf` | no-single-fold-dependency, tolera 1 outlier |
| 8 | Holdout 90d OOS | `pf_holdout > 1.0` E `pf_holdout > 0.9 × pf_main` | nao colapsa OOS |
| 9 | Simbolo destrutivo | Nenhum simbolo com `n_trades >= 60` E `pf < 0.5` | nenhum simbolo sabota o agregado |
| 10 | Slippage sensitivity universal 0.10% | `pf_main_slip010 >= 1.0` | nao colapsa em pessimismo |

### 6.1 Comparadores reportados (mesmo se nao bloqueantes)

- **C1:** cash (sempre `pf=1.0, dd=0`). Sanity check.
- **C2:** BH equal-weight do universo elegivel, custo zero, sem rebalance mensal (apenas inicial). Bloqueante via #3.
- **C3-normalized:** v1.1 com S-B framework, `universe=["BTCUSDT","ETHUSDT"]`, mesmo `capital_pool`. Bloqueante via #2 e #4.
- **C3-live:** v1.1 com sizing live-style (capital alocado como em producao). Reportado para transparencia — **nao bloqueante**.
- **Bonus:** BH BTC individual, BH ETH individual (transparencia adicional).

### 6.2 Diagnosticos reportados (nao bloqueiam, alimentam EXP-006+)

- **Bucket breakdown** (core/high_beta/infra): n, PF, WR, DD por bucket. Raio-X.
- **Direction breakdown** (long/short): n, PF, WR por direcao.
- **Regime breakdown** (TRENDING/WEAK_TREND/VOLATILE/RANGING): n, PF por regime.
- **Exit reason breakdown** (SL/TP1/TP2/TIMEOUT/TRAIL): distribuicao.
- **S-C top-k selection simulation:** mesmos sinais, mas max_positions=2 com criterio de selecao (score, recencia). **Diagnostic only.**

---

## 7. Arquitetura

### 7.1 Estrutura de diretorios

```
momentum/expansion/                 # novo subdir, isolado
  __init__.py
  config.py                         # ExpansionConfig frozen dataclass
  preflight.py                      # checagem de elegibilidade fapi
  data_loader.py                    # fetch + alinhamento de candles 15m
  capital_pool.py                   # S-B allocation pure
  signal_engine_adapter.py          # adapter fino para evaluate_momentum_pullback
  walk_forward.py                   # particionamento 12 folds + run por fold
  leave_one_out.py                  # LOO por simbolo + por fold
  comparators.py                    # C1, C2, C3-normalized, C3-live
  metrics.py                        # PF/WR/DD/total_return reescritos do zero
  go_no_go.py                       # 10 criterios → veredicto
  research_db.py                    # schema expansion_*
  research_runner.py                # orquestrador + run_portfolio_backtest pure

scripts/
  run_expansion_preflight.py        # CLI: gera preflight JSON
  run_expansion_backtest.py         # CLI: main + holdout
  run_expansion_robustness.py       # CLI: walk-forward + LOO
  evaluate_expansion_go_no_go.py    # CLI: 10 criterios → veredicto

tests/
  test_expansion_*.py               # TDD por modulo
```

**Permissao explicita:** `walk_forward.py` e `leave_one_out.py` podem ser consolidados em `robustness.py` se ambos ficarem pequenos (<150 linhas combinados). Decisao na implementacao.

### 7.2 Principios de design

1. **Isolamento total.** Se EXP-005 morrer, removivel em 1 PR (delete `momentum/expansion/`).
2. **Nao toca core v1.1.** `momentum_trader.py`, `swing_detector.py`, `pullback_detector.py`, `paper_executor.py` ficam intocados. v1.1 em producao continua rodando BTC/ETH no main loop durante todo o experimento.
3. **Mesma engine de sinal.** `signal_engine_adapter.py` chama `evaluate_momentum_pullback` (API publica do core) sem fork. Se v1.1 mudar, EXP-005 quebra alto e claro.
4. **DBs separados.** `research/expansion_v1_365d.db` etc. Nao polui `momentum_trades`/`momentum_decisions`.
5. **No code reuse from EXP-004 archived branch.** Pecas genericas (metrics, baselines) sao reescritas do zero. EXP-004 e referencia conceitual, nao dependencia.
6. **Funcao pura no centro.** `run_portfolio_backtest(config, candles_by_symbol) -> ExpansionResult` e pura: sem Binance, sem SQLite, sem arquivos. CLI e DB ficam em volta.

### 7.3 Componentes — responsabilidades

| Modulo | Responsabilidade | Dependencias |
|---|---|---|
| `config.py` | `ExpansionConfig` frozen: universe, periodos, capital pool, slippage map por bucket, 10 thresholds. | nenhuma |
| `preflight.py` | `run_preflight(symbols, required_days=455) -> PreflightResult` — fetch first kline em fapi por simbolo. CLI separado escreve JSON congelado. | Binance API |
| `data_loader.py` | Carrega 455d por simbolo elegivel via paginated fetch. Alinha por timestamp fechado. Detecta gap > threshold. | Binance API |
| `capital_pool.py` | `allocate_position_size(pool, n_universe, entry, sl) -> size` — funcao pura. Risk-based sizing escalado por 1/N. | nenhuma |
| `signal_engine_adapter.py` | Adapter fino que injeta `momentum_trader.evaluate_momentum_pullback` no backtest. **Engine nao e forkada.** | momentum/momentum_trader |
| `walk_forward.py` | `partition_into_folds(candles, n_folds, period) -> list[FoldData]` — pure. Run por fold. | nenhuma |
| `leave_one_out.py` | `loo_by_symbol(trades, universe)` e `loo_by_fold(fold_results)` — puras. Recomputa metricas removendo 1 elemento. | nenhuma |
| `comparators.py` | C1 cash, C2 BH equal-weight (custo zero), C3-normalized (chama `run_portfolio_backtest` com universo reduzido), C3-live (transparencia). | momentum/expansion (auto-import) |
| `metrics.py` | `compute_portfolio_metrics(trades) -> PortfolioMetrics`. Reescrito. | nenhuma |
| `go_no_go.py` | `evaluate_expansion(...)` recebe metrics + LOO + comparators + slippage + holdout → 10 criterios → PASS/FAIL + failure list. | nenhuma |
| `research_db.py` | Schema: `expansion_trades`, `expansion_decisions`, `expansion_folds`, `expansion_runs` (meta). | sqlite3 |
| `research_runner.py` | **Orquestrador** (com side effects). Le preflight JSON, fetcha candles, chama `run_portfolio_backtest` (pura), persiste DB. | tudo acima |

### 7.4 Funcao pura central

```python
def run_portfolio_backtest(
    *,
    config: ExpansionConfig,
    candles_by_symbol: dict[str, pd.DataFrame],
    signal_fn: Callable | None = None,   # default: signal_engine_adapter
    regime_fn: Callable | None = None,
) -> ExpansionResult:
    """Pure: recebe candles em memoria, retorna trades + decisions + portfolio_state.

    No I/O. No side effects. No network. Determinístico para mesmo input.
    """
```

`ExpansionResult` e dataclass: `trades`, `decisions`, `final_capital_pool`, `peak_concurrent_positions`, `metrics`.

---

## 8. Data flow

```
[0] PREFLIGHT (executado UMA vez, isolado)
    13 candidates → fapi.klines first available
    → research/expansion_v1_preflight.json (CONGELADO, write-once)

[1] BACKTEST RUN
    1.1 Le preflight JSON → ExpansionConfig(universe=eligible_list, ...)
    1.2 Fetch 455d candles (paginated por simbolo) → candles_by_symbol em memoria
    1.3 Validation: alinhamento + detecao de gap > 0.5%. Falha → ABORT (universo precisa ser re-preflighted)
    1.4 MAIN 365d: trades_main = run_portfolio_backtest(config, candles_main)
    1.5 HOLDOUT 90d: trades_holdout = run_portfolio_backtest(config, candles_holdout)
    1.6 WALK-FORWARD (12 folds): fold_results = [run_portfolio_backtest(config, fold) for fold in folds]
    1.7 LEAVE-ONE-OUT: loo_symbol + loo_fold
    1.8 COMPARATORS: C1 cash + C2 BH eqw + C3-normalized + C3-live
    1.9 SLIPPAGE SENSITIVITY: config_010 com slippage 0.10% universal → metrics_slip010
    1.10 GO/NO-GO: evaluate_expansion(...) → veredicto
    1.11 PERSIST: DB + JSON robustness (escrita atomica via temp + rename)
```

**Pontos criticos:**
- Preflight e stateless e write-once.
- `run_portfolio_backtest` e executada ~16x por run (1 main + 1 holdout + 12 folds + 1 C3-normalized + 1 slippage). Cache de candles compartilhado.
- C3-normalized usa **mesma** `run_portfolio_backtest` com universo reduzido. Apples-to-apples.
- DB e JSON escritos so no fim. Falha durante o run = sem estado parcial.
- Execucao **serial e deterministica** por padrao. Paralelismo permitido em CLI futuro **sem alterar outputs**.

---

## 9. Error handling & edge cases

| Cenario | Tratamento |
|---|---|
| Binance API failure (network, 5xx) | Retry com backoff exponencial (3 tentativas: 1s, 5s, 15s). Se falhar: ABORT run. DB e JSON nao escritos. |
| Simbolo sem 455d completos | Preflight marca `eligible=false`. Nao entra no `expansion_v1_preflight.json`. |
| Simbolo com gap > 0.5% dos candles esperados | **Run validation falha e aborta com relatorio.** Exige atualizar o preflight artifact (regerar JSON versionado). Nao dropa silenciosamente. Relatorio (stderr + retorno do CLI): `{"validation": "failed", "reason": "gap_threshold_exceeded", "symbol": "X", "expected_candles": N, "actual_candles": M, "gap_pct": ...}`. |
| Simbolo sem candle em timestamp T | Naquele candle, simbolo nao gera decisao. Loop continua nos demais. **Sem forward-fill de OHLC.** |
| Capital pool exhausted | Sinal logged como `blocked_by="no_capital"` em `expansion_decisions`. Nao abre posicao. Nao e erro fatal. |
| Sinais simultaneos > N simbolos | Logica S-B garante: cada um pega `1/N` do pool, soma <= 100%. Sem race. |
| `evaluate_momentum_pullback` exception (run oficial) | **ABORT.** Skips silenciosos enviesam o resultado. Em modo diagnostico/teste, pode logar e continuar. |
| `run_portfolio_backtest` recebe input invalido | `ValueError` no inicio (preconditions check). Funcao pura, falha rapida. |
| Preflight com 0 elegiveis | ABORT com mensagem explicita. JSON degenerado **nao escrito**. |
| DB write falha (disk full, lock) | ABORT limpo. JSON robustness **nao escrito**. |
| JSON write | Escrita atomica: arquivo temp + `os.rename()` ao final. |

**Look-ahead diagnostic (recomendado, opcional):** rodar com `execution_shift=0` extra. Comparar `total_pnl_pct` com main. Gap > 20% → investigar engine de sinal por leak.

---

## 10. Testing strategy

TDD por modulo (red → green) em cada task do plano. Cada modulo tem testes unitarios antes da implementacao.

| Arquivo de teste | Cobertura |
|---|---|
| `test_expansion_config.py` | Frozen, defaults, bucket assignment completo, slippage map valido, thresholds. |
| `test_expansion_preflight.py` | Mock Binance: eligible/ineligible classificados; JSON serializavel. |
| `test_expansion_data_loader.py` | Alinhamento de timestamps, deteccao de gap, threshold 0.5%, abort em gap excessivo. |
| `test_expansion_capital_pool.py` | Allocation 1/N, soma <= pool, edge case N=1, N=12. Risk-based sizing escalado. |
| `test_expansion_signal_adapter.py` | Snapshot/integration: adapter chama core sem modificar resultado de `evaluate_momentum_pullback`. |
| `test_expansion_run_portfolio_backtest.py` | Funcao pura: candles sinteticos co-movimentando + idiosincraticos. Cenarios: 0 sinais, 1 trade, sinais concorrentes, capital esgotado. |
| `test_expansion_walk_forward.py` | Particionamento mensal, fold boundaries nao sobrepoem, soma de trades por fold = trades da janela. |
| `test_expansion_leave_one_out.py` | LOO por simbolo: remover BTC e recomputar. LOO por fold idem. |
| `test_expansion_comparators.py` | C1 sempre 1.0/0; C2 BH equal-weight com cenario sintetico **custo zero**; C3-normalized chama backtest com universo reduzido. |
| `test_expansion_metrics.py` | PF/WR/DD/total_return em datasets conhecidos. |
| `test_expansion_go_no_go.py` | 10+ scenarios, um por criterio falhando, um onde todos passam. Boundary tests (PF=1.25, fold=9/12). |
| `test_expansion_no_lookahead.py` | Fixture onde sinal so existiria se candle futuro vazasse. Confirma que `execution_shift=1` produz resultado distinto e correto. |
| `test_expansion_reproducibility.py` | Mesmo input/config/preflight → mesmo hash de trades/metrics. Protege contra dict ordering, sort instavel, nao determinismo. |
| `test_expansion_smoke_integration.py` | End-to-end com 3 simbolos sinteticos, 30d, sem network. **Inclui caso de candles desalinhados/gap** para provar abort precoce. |

**Nao-testes (validacao manual):**
- Preflight real (chama fapi) e validado via CLI manual.
- Backtest 365d real e Task operacional do plano (analoga a Task 22 do EXP-004).

---

## 11. Output operacional

### 11.1 Se PASS

1. Atualizar `docs/EXPERIMENT_REGISTRY.md`: EXP-005 estagio = `BACKTEST → ROBUSTNESS PASS`.
2. Escrever Phase 2 plan: integracao de `momentum/expansion/` ao main loop como modo opcional gateado por env var (ex: `MOMENTUM_UNIVERSE_MODE=expanded`).
3. Comecar paper trading com universo expandido em instancia A/B (`run_dual_supervisors.py`) ou nova instancia BOT_ID.
4. Definir criterios de promocao para producao em experimento separado (escopo fora deste spec).

### 11.2 Se FAIL

1. Atualizar `docs/EXPERIMENT_REGISTRY.md`: EXP-005 estagio = `DEAD (no BACKTEST)` com postmortem inline.
2. Escrever postmortem em `~/obsidian-vault/context/decisoes/2026-MM-DD-exp-005-universe-expansion-dead.md`. Estrutura analoga ao postmortem do EXP-004.
3. Manter v1.1 BTC/ETH-only como baseline ativa.
4. Codigo de `momentum/expansion/` permanece no branch arquivado (ou removido), por escolha. Decisao analoga ao EXP-004 archive.
5. Diagnosticos do run podem alimentar EXP-006 (se houver hipotese mecanica nova baseada nos buckets ou outros sinais).

### 11.3 Estrutura de artefatos

```
research/
  expansion_v1_preflight.json       # universo congelado (write-once)
  expansion_v1_365d.db              # main + holdout + folds (sqlite WAL)
  expansion_v1_robustness.json      # metricas + LOO + comparators + GO/NO-GO verdict
  expansion_v1_diagnostics.json     # bucket/direction/regime/exit_reason breakdowns + S-C top-k

docs/superpowers/
  specs/2026-04-27-exp-005-universe-expansion-design.md   # este documento
  plans/2026-04-27-exp-005-universe-expansion-plan.md     # plano de implementacao (a escrever apos aprovacao do spec)
```

---

## 12. Sequencia de tasks (resumo, plano detalhado e proximo passo)

A escrever em `plans/2026-04-27-exp-005-universe-expansion-plan.md` apos aprovacao deste spec. Estrutura esperada (analoga a Phase 1 do EXP-004):

1. Scaffolding `momentum/expansion/__init__.py`
2. `ExpansionConfig` + tests
3. `metrics.py` + tests (reescrito do zero)
4. `capital_pool.py` + tests (S-B allocation pure)
5. `signal_engine_adapter.py` + snapshot tests
6. `data_loader.py` + tests (gap detection, alignment)
7. `preflight.py` + tests (mock Binance)
8. `comparators.py` C1/C2 + tests
9. `run_portfolio_backtest()` pure + extensive tests
10. `comparators.py` C3-normalized + C3-live + tests
11. `walk_forward.py` particionamento + tests
12. `walk_forward.py` run por fold + tests
13. `leave_one_out.py` por simbolo + tests
14. `leave_one_out.py` por fold + tests
15. `research_db.py` schema + CRUD + tests
16. `research_runner.py` orquestrador + tests com mocks
17. `go_no_go.py` 10 criterios + tests
18. CLI `run_expansion_preflight.py`
19. CLI `run_expansion_backtest.py`
20. CLI `run_expansion_robustness.py`
21. CLI `evaluate_expansion_go_no_go.py`
22. End-to-end smoke integration test
23. Adicionar EXP-005 ao EXPERIMENT_REGISTRY (HYPOTHESIS entry)
24. **Operacional:** rodar preflight real → backtest 365d real → robustness → GO/NO-GO → veredicto + commit final

Estimativa: ~24 tasks (margem +/- 2 dependendo de consolidacao opcional walk_forward+leave_one_out → robustness.py). Escopo similar ao EXP-004 que teve 22 tasks.

---

## 13. Princıpios de operacao do experimento

1. **Disciplina TDD em cada task:** red → green → reviewer (implementer + spec/quality reviewer per task).
2. **Subagent-driven development per task:** mesmo padrao do EXP-004.
3. **Commits atomicos por task** com mensagens descritivas. Nao acumular.
4. **Sem desvio do spec sem atualizar o spec.** Se um implementer encontrar inconsistencia, atualizar este documento antes de mergear o codigo.
5. **Rastreabilidade:** cada task referencia secao/numero deste spec.
6. **Sem pressa:** EXP-004 levou 22 tasks ate o veredicto. EXP-005 levara similar. Vale mais um veredicto solido que velocidade.

---

## 14. Referencias

- [EXP-003 Momentum v1.1 baseline](./2026-04-15-paper-readiness-framework.md)
- [EXP-004 H1 Pair Trading design](./2026-04-21-h1-pair-trading-design.md) (DEAD; conceitual reference apenas)
- [EXP-004 postmortem](~/obsidian-vault/context/decisoes/2026-04-27-h1-pair-trading-dead.md)
- Memory: `~/.claude/projects/-home-pi/memory/project_exp_005_universe_expansion.md` (criterios formais a priori)
- Memory: `~/.claude/projects/-home-pi/memory/feedback_close_before_open.md` (regra de selar antes de abrir)
- `momentum/momentum_trader.py:69` — `evaluate_momentum_pullback` (API publica reusada via adapter)
- `momentum/research_runner.py` — referencia para padrao de orquestrador no projeto

---

**Status:** design fechado, aguardando aprovacao final de Gabriel antes de escrever o plano de implementacao.
