# ARCHITECTURE — Sistema de Trading Defensivo

**Data:** 2026-04-14
**Status:** Especificacao V1

---

## Principio de integracao

Integrar ao repo existente (`crypto_ai_bot`) com **isolamento forte**:
- Codigo novo em namespace proprio (`defensive/`)
- Config com prefixo `DEFENSIVE_*`
- Tabelas DB proprias (`defensive_trades`, `defensive_decisions`)
- State file proprio (`defensive_state.json`)
- Backtest proprio e separado
- Sem herdar premissas de pump/scalp
- Reutilizar infraestrutura generica (regime, microestrutura, risk base, DB, audit)

---

## Estrutura de diretorios

```
crypto_ai_bot/
├── defensive/                          # NOVO — namespace isolado
│   ├── __init__.py                     # Exports publicos
│   ├── config.py                       # DefensiveConfig (parametros proprios)
│   ├── compression_detector.py         # Camada 1: detecta compressao real
│   ├── breakout_detector.py            # Camada 2: detecta tentativa de breakout
│   ├── trap_detector.py                # Camada 3: trap confirmation via microestrutura
│   ├── value_reference.py              # VWAP rolling, z-score, percentile (compartilhado)
│   ├── defensive_trader.py             # Orquestrador: pipeline completo CFER
│   ├── ravr_trader.py                  # Benchmark RAVR (value reversion simples)
│   └── signals.py                      # DefensiveSignal (estende Signal base)
│
├── backtest/                           # NOVO — backtest dedicado
│   ├── __init__.py
│   ├── data_loader.py                  # Ingestao + limpeza de dados historicos
│   ├── backtest_engine.py              # Motor de backtest generico
│   ├── metrics.py                      # Calculo de metricas (PF, Sharpe, DD, etc)
│   ├── walk_forward.py                 # Walk-forward validation
│   └── report.py                       # Geracao de relatorios comparativos
│
├── # EXISTENTES — reutilizados sem modificacao:
├── htf.py                              # Regime detection (5 regimes)
├── market_data.py                      # Coleta microestrutura (21 campos)
├── liquidation_feed.py                 # WebSocket liquidacoes real
├── signal_types.py                     # Signal, Direction, ScalpingConfig
├── execution_layer.py                  # Calculo ATR-based de entry/SL/TP
├── audit_helpers.py                    # Framework de auditoria
├── supervisor.py                       # Gerenciamento de processos
│
├── # EXISTENTES — modificacoes minimas:
├── main.py                             # +1 bloco: process_defensive()
├── config.py                           # +namespace DEFENSIVE_*
├── database.py                         # +tabelas defensive_trades, defensive_decisions
├── risk_manager.py                     # +parametrizacao de SL/RR maps (tirar hardcode)
├── dashboard_server.py                 # +endpoints /api/defensive/* (fase posterior)
│
├── docs/defensive/                     # Documentacao
│   ├── PROJECT_BRIEF.md
│   ├── STRATEGY_CANDIDATES.md
│   ├── RISK_FRAMEWORK.md
│   ├── ARCHITECTURE.md                 # Este documento
│   ├── BACKTEST_SPEC.md                # Fase seguinte
│   ├── ROADMAP_90_DAYS.md              # Fase seguinte
│   └── DECISIONS_LOG.md                # Fase seguinte
│
└── tests/
    ├── test_compression_detector.py    # NOVO
    ├── test_trap_detector.py           # NOVO
    ├── test_defensive_trader.py        # NOVO
    ├── test_ravr_trader.py             # NOVO
    ├── test_value_reference.py         # NOVO
    └── test_backtest_engine.py         # NOVO
```

---

## Responsabilidades por modulo

### Namespace `defensive/`

| Modulo | Responsabilidade | Input | Output |
|---|---|---|---|
| `config.py` | Parametros do sistema defensivo | Env vars DEFENSIVE_* | DefensiveConfig dataclass |
| `compression_detector.py` | Detecta compressao real (BB Width ↓, percentil, ATR ↓) | Candles 15m (DataFrame) | CompressionState (active, metrics) |
| `breakout_detector.py` | Detecta tentativa de breakout com volume | Candles 15m + CompressionState | BreakoutEvent (direction, volume_ratio) |
| `trap_detector.py` | Confirma trap via microestrutura (OI, liq, funding, basis) | Microstructure dict + BreakoutEvent | TrapResult (confirmed, score, evidence) |
| `value_reference.py` | Calcula VWAP rolling, z-score, percentile rank | Candles (qualquer TF) | ValueMetrics (vwap, z_score, percentile) |
| `defensive_trader.py` | Orquestra pipeline CFER: compression → breakout → trap → entry/exit | Todos os acima + regime | TradeDecision + position management |
| `ravr_trader.py` | Pipeline RAVR simplificado: regime → z-score → entry/exit | Candles + regime | TradeDecision (benchmark) |
| `signals.py` | Estende Signal com campos defensivos | — | DefensiveSignal dataclass |

### Namespace `backtest/`

| Modulo | Responsabilidade |
|---|---|
| `data_loader.py` | Carregar dados historicos (CSV/parquet), limpar, validar gaps |
| `backtest_engine.py` | Simular estrategia em dados historicos com custos realistas |
| `metrics.py` | Profit factor, Sharpe, Sortino, max DD, win rate, RR, etc |
| `walk_forward.py` | Divisao train/test, walk-forward validation, OOS metrics |
| `report.py` | Gerar relatorio comparativo CFER vs RAVR com breakdown |

---

## Fluxo de dados — modo live

```
                    COLETA (a cada ciclo 5min, main.py)
                    |
        ┌───────────┼───────────┐
        v           v           v
   market.py    market_data.py  htf.py
   (candles)    (microestrutura) (regime)
        |           |           |
        └───────────┼───────────┘
                    |
                    v
        ┌─── defensive_trader.process() ───┐
        |                                   |
        |  1. compression_detector          |
        |     └─ BB Width, ATR, volume      |
        |     └─ Output: CompressionState   |
        |                                   |
        |  2. breakout_detector             |
        |     └─ Price vs BB + volume spike |
        |     └─ Output: BreakoutEvent      |
        |                                   |
        |  3. trap_detector                 |
        |     └─ OI, liquidacoes, funding   |
        |     └─ Output: TrapResult         |
        |                                   |
        |  4. Regime + session filter       |
        |     └─ htf.get_htf_regime()       |
        |                                   |
        |  5. Risk gate                     |
        |     └─ risk_manager (reutilizado) |
        |                                   |
        |  6. Entry decision                |
        |     └─ execution_layer (SL/TP)    |
        |                                   |
        |  7. Position management           |
        |     └─ SL/TP1/TP2/timeout/regime  |
        |                                   |
        └──────────────┬────────────────────┘
                       |
              ┌────────┼────────┐
              v        v        v
          database  state.json  telegram
          (trades,  (posicoes)  (alertas)
          decisions)
```

---

## Regra critica: mesma signal engine para backtest e live

O backtest e o live DEVEM usar exatamente os mesmos modulos de sinal:

```
compression_detector.py  → MESMO codigo em backtest e live
breakout_detector.py     → MESMO codigo em backtest e live
trap_detector.py         → MESMO codigo em backtest e live
defensive_trader.py      → MESMO codigo em backtest e live
ravr_trader.py           → MESMO codigo em backtest e live
```

O que DIFERE entre backtest e live:
- **Data source:** backtest recebe DataFrame pre-carregado; live recebe dados de API
- **Execution:** backtest simula fill com slippage; live executa (paper ou real)
- **Timing:** backtest itera candle por candle; live espera ciclo de 5min

**NAO criar logica de estrategia duplicada.** Se a signal engine mudar, deve mudar nos dois modos. O backtest_engine.py e apenas um wrapper que alimenta dados historicos ao mesmo pipeline.

---

## Fluxo de dados — modo backtest

```
        data_loader.py
        (CSV historico → DataFrame limpo)
            |
            v
        backtest_engine.py
        (iteracao candle por candle)
            |
            ├── Para cada candle:
            |   ├── compression_detector.update(candle)      # MESMO modulo do live
            |   ├── breakout_detector.update(candle, comp)   # MESMO modulo do live
            |   ├── trap_detector.update(candle, bo, micro*) # MESMO modulo do live
            |   ├── regime = htf.get_regime(candle_htf)      # MESMO modulo do live
            |   ├── risk_check(state)                        # MESMO modulo do live
            |   └── Se sinal valido: abrir/fechar posicao simulada
            |
            v
        metrics.py
        (PF, Sharpe, DD, WR, breakdown por regime/sessao/direcao)
            |
            v
        walk_forward.py
        (split train/test, multiplas janelas, OOS aggregation)
            |
            v
        report.py
        (comparativo CFER vs RAVR, tabelas, graficos)

* microstructure no backtest: precisa de dados historicos de OI, funding, etc.
  Se nao disponivel, backtest roda sem trap layer (RAVR-like) e trap e validada
  apenas em forward test / paper trading.
```

---

## Decision audit log (obrigatorio)

Cada ciclo de avaliacao — trade ou nao — DEVE registrar um record na tabela `defensive_decisions` com:

```
Campos de estado do pipeline:
  compression_active      — compressao estava ativa?
  compression_percentile  — percentil da BB Width
  breakout_detected       — houve breakout?
  breakout_direction      — UP / DOWN / null
  trap_confirmed          — trap confirmada?
  trap_score              — score total
  trap_evidence           — JSON: quais evidencias dispararam
  trap_available          — JSON: quais dados estavam disponiveis
  trap_missing            — JSON: quais dados faltaram
  reclaim_detected        — reclaim do range?

Campos de contexto:
  regime                  — regime do HTF
  session                 — asia/europe/us/dead
  outcome                 — 'trade', 'no_compression', 'no_breakout', 'no_trap',
                            'no_reclaim', 'regime_blocked', 'risk_blocked',
                            'cooldown', 'session_blocked', 'daily_limit',
                            'data_quality_kill', 'latency_kill', 'in_position'

Campos de risco:
  daily_loss_pct          — perda acumulada no dia
  weekly_loss_pct         — perda acumulada na semana
  consecutive_losses      — losses seguidos
  open_positions          — posicoes abertas

Campos de microestrutura:
  oi_change_1h_pct, funding_rate, basis_spread_pct

Campos de versionamento:
  config_version          — hash da DefensiveConfig usada
  param_version           — versao do parametro set (ex: "v1.0")
  git_sha                 — commit hash do codigo em execucao
```

O motivo do no-trade e TAO IMPORTANTE quanto o motivo do trade. O funil de decisao (scalping_decisions existente) ja provou seu valor — o defensive_decisions segue o mesmo principio.

---

## Feature availability flags

Cada ciclo verifica quais dados de microestrutura estao disponiveis antes de executar o pipeline:

```python
@dataclass
class FeatureAvailability:
    oi_available: bool = False       # OI data fresh (< 5 min)
    liq_available: bool = False      # Liquidation data fresh
    liq_is_proxy: bool = False       # True = aggTrades, False = WebSocket real
    funding_available: bool = False  # Funding rate fresh
    ls_ratio_available: bool = False # L/S ratio fresh
    basis_available: bool = False    # Basis spread fresh
    candles_15m_available: bool = False
    candles_5m_available: bool = False
    regime_available: bool = False
    
    @property
    def min_viable(self) -> bool:
        """Minimo para operar: candles + regime + pelo menos 2 fontes de micro"""
        micro_count = sum([self.oi_available, self.liq_available,
                          self.funding_available, self.basis_available])
        return (self.candles_15m_available and self.regime_available
                and micro_count >= 2)
```

Se `min_viable = False`, o ciclo e bloqueado com `outcome = "data_quality_kill"`.
Registrado no decision log com detalhes de quais features faltaram.

---

## Versionamento de config e logica

Cada execucao (backtest ou live) registra:

```python
execution_metadata = {
    "config_hash": hashlib.md5(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()[:8],
    "param_version": config.param_version,  # ex: "v1.0", "v1.1-ablation-no-oi"
    "git_sha": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip(),
    "strategy": config.strategy,  # "cfer" ou "ravr"
    "timestamp": datetime.utcnow().isoformat(),
}
```

Isso permite:
- Rastrear qual config produziu cada trade/decision
- Comparar resultados entre versoes de parametros
- Detectar se backtest e live estao rodando configs diferentes
- Reproduzir resultados historicos

---

## Interfaces entre modulos

### DefensiveConfig

```python
@dataclass
class DefensiveConfig:
    # Habilitacao
    enabled: bool = False
    strategy: str = "cfer"  # "cfer" ou "ravr"
    
    # Capital e risco
    initial_capital: float = 1000.0
    max_risk_pct: float = 0.5       # 0.5% por trade
    max_positions: int = 1
    max_leverage: int = 3
    max_sl_pct: float = 2.5
    min_rr: float = 2.0
    
    # Compressao
    compression_lookback: int = 100  # periodos para percentil
    compression_percentile: int = 20 # threshold de compressao
    compression_min_decline: int = 6 # candles consecutivos de queda BB
    
    # Breakout
    breakout_volume_mult: float = 1.5  # volume spike minimo
    breakout_reclaim_window: int = 3   # candles para reclaim
    
    # Trap
    trap_min_score: int = 30           # score minimo de trap
    trap_oi_threshold_pct: float = 0.3 # OI expansion minima
    trap_liq_threshold_usd: float = 50000  # liquidacao minima (BTC)
    
    # RAVR (benchmark)
    ravr_zscore_threshold: float = 2.0
    ravr_vwap_period: int = 96  # candles (96 * 15m = 24h)
    
    # Limites diarios/semanais
    max_daily_loss_pct: float = 1.5
    max_weekly_loss_pct: float = 3.0
    max_daily_trades: int = 3
    cooldown_after_consecutive_losses: int = 2
    
    # Sessao
    blocked_sessions: list = field(default_factory=lambda: [])  # ex: ["dead"]
    elevated_sessions: list = field(default_factory=lambda: ["asia", "dead"])
    elevated_trap_score: int = 45  # threshold mais alto em sessoes elevadas
    
    # Gestao
    tp1_partial_pct: float = 50.0    # % para fechar em TP1
    breakeven_buffer_pct: float = 0.05
    timeout_candles: int = 12        # 12 * 15m = 3h
    
    # Timeframes
    signal_timeframe: str = "15m"
    execution_timeframe: str = "5m"
    regime_timeframe: str = "1h"
    
    # Custos (backtest)
    fee_per_side: float = 0.04       # 0.04%
    slippage_normal: float = 0.02    # 0.02%
    slippage_failed_breakout: float = 0.05  # 0.05% (mais alto)
    
    # Symbols
    symbols: list = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
```

### Signal estendido

```python
@dataclass
class DefensiveSignal(Signal):
    # Herdado: direction, strength, timestamp, source, symbol, price,
    #          entry_price, sl_price, tp1_price, tp2_price, metadata, reason, valid
    
    # Campos adicionais defensivos
    strategy: str = ""          # "cfer" ou "ravr"
    compression_percentile: float = 0.0
    compression_candles: int = 0
    breakout_direction: str = ""  # "UP" ou "DOWN"
    breakout_volume_ratio: float = 0.0
    trap_score: int = 0
    trap_evidence: list = field(default_factory=list)  # ["oi_trap", "liq_trap", ...]
    z_score: float = 0.0         # para RAVR
    vwap_distance_pct: float = 0.0
    regime: str = ""
    session: str = ""
```

### Estruturas intermediarias

```python
@dataclass
class CompressionState:
    active: bool = False
    bb_width_current: float = 0.0
    bb_width_percentile: float = 0.0
    consecutive_decline: int = 0
    atr_declining: bool = False
    volume_stable: bool = False
    since: str = ""  # timestamp de inicio da compressao

@dataclass
class BreakoutEvent:
    detected: bool = False
    direction: str = ""    # "UP" ou "DOWN"
    price: float = 0.0
    volume_ratio: float = 0.0
    bb_level: float = 0.0  # nivel da BB que foi rompida
    timestamp: str = ""
    candle_index: int = 0

@dataclass
class TrapResult:
    confirmed: bool = False
    score: int = 0
    evidence: list = field(default_factory=list)  # quais traps dispararam
    oi_expanded: bool = False
    oi_declining: bool = False
    liq_in_breakout_dir: float = 0.0
    funding_crowded: bool = False
    basis_diverged: bool = False
```

---

## Integracoes com modulos existentes

### main.py — novo bloco

```python
# Em main.py, apos o bloco de scalping:
# ---- Defensive Trading ----
if DEFENSIVE_ENABLED:
    try:
        from defensive.defensive_trader import process_defensive
        defensive_result = process_defensive(
            symbol=symbol,
            candles_15m=candles_15m,      # fetch adicional
            candles_5m=candles_5m,        # ja disponivel
            microstructure=micro_data,     # ja coletado
            regime=regime,                 # ja calculado
            config=defensive_config,
        )
    except Exception as e:
        logger.error(f"Defensive error: {e}")
```

### config.py — novo namespace

```python
# DEFENSIVE TRADING
DEFENSIVE_ENABLED = os.environ.get("DEFENSIVE_ENABLED", "false").lower() == "true"
DEFENSIVE_SYMBOLS = (
    [s.strip().upper() for s in os.environ.get("DEFENSIVE_SYMBOLS", "").split(",") if s.strip()]
    if os.environ.get("DEFENSIVE_SYMBOLS", "").strip()
    else ["BTCUSDT", "ETHUSDT"]
)
DEFENSIVE_INITIAL_CAPITAL = float(os.environ.get("DEFENSIVE_INITIAL_CAPITAL", "1000"))
DEFENSIVE_STRATEGY = os.environ.get("DEFENSIVE_STRATEGY", "cfer")  # "cfer" ou "ravr"
```

### database.py — novas tabelas

```sql
CREATE TABLE IF NOT EXISTS defensive_trades (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    strategy            TEXT NOT NULL,  -- 'cfer' ou 'ravr'
    direction           TEXT NOT NULL,  -- 'LONG' ou 'SHORT'
    entry_price         REAL NOT NULL,
    exit_price          REAL,
    sl_price            REAL NOT NULL,
    tp1_price           REAL NOT NULL,
    tp2_price           REAL,
    position_size_usd   REAL NOT NULL,
    leverage            INTEGER NOT NULL,
    regime              TEXT,
    session             TEXT,
    
    -- Resultado
    pnl_pct             REAL,
    pnl_usd             REAL,
    exit_reason         TEXT,  -- 'tp1', 'tp2', 'sl', 'timeout', 'regime_shift'
    duration_candles    INTEGER,
    capital_after       REAL,
    
    -- CFER specifics
    compression_percentile  REAL,
    compression_candles     INTEGER,
    breakout_direction      TEXT,
    breakout_volume_ratio   REAL,
    trap_score              INTEGER,
    trap_evidence           TEXT,  -- JSON array
    
    -- RAVR specifics
    z_score                 REAL,
    vwap_distance_pct       REAL,
    
    -- Microestrutura snapshot
    oi_change_1h_pct        REAL,
    funding_rate             REAL,
    basis_spread_pct         REAL,
    liquidation_vol_long     REAL,
    liquidation_vol_short    REAL,
    
    -- Audit
    param_version           TEXT,
    git_sha                 TEXT
);

CREATE TABLE IF NOT EXISTS defensive_decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    cycle_id            TEXT,
    symbol              TEXT NOT NULL,
    strategy            TEXT NOT NULL,
    
    -- Resultado da avaliacao
    outcome             TEXT NOT NULL,  -- 'trade', 'no_compression', 'no_breakout',
                                       -- 'no_trap', 'no_reclaim', 'regime_blocked',
                                       -- 'risk_blocked', 'cooldown', 'session_blocked',
                                       -- 'daily_limit', 'in_position',
                                       -- 'data_quality_kill', 'latency_kill'
    
    -- Estado do pipeline
    compression_active  INTEGER,  -- 0/1
    compression_percentile REAL,
    breakout_detected   INTEGER,  -- 0/1
    breakout_direction  TEXT,
    trap_confirmed      INTEGER,  -- 0/1
    trap_score          INTEGER,
    trap_evidence       TEXT,     -- JSON: ["oi_trap", "liq_trap"]
    trap_available      TEXT,     -- JSON: ["oi", "liq", "funding", "basis"]
    trap_missing        TEXT,     -- JSON: ["ls_ratio"]
    reclaim_detected    INTEGER,  -- 0/1
    
    -- Contexto
    regime              TEXT,
    session             TEXT,
    
    -- Para RAVR benchmark
    z_score             REAL,
    vwap_distance_pct   REAL,
    
    -- Risk state
    daily_loss_pct      REAL,
    weekly_loss_pct     REAL,
    consecutive_losses  INTEGER,
    open_positions      INTEGER,
    
    -- Microestrutura
    oi_change_1h_pct    REAL,
    funding_rate        REAL,
    basis_spread_pct    REAL,
    
    -- Versionamento
    config_version      TEXT,     -- hash da DefensiveConfig
    param_version       TEXT,     -- ex: "v1.0"
    git_sha             TEXT      -- commit hash
);
```

### risk_manager.py — parametrizacao

A unica mudanca necessaria no risk_manager existente e mover os SL/RR maps de hardcoded para config:

```python
# ANTES (hardcoded):
max_sl_map = {
    "volume_breakout": 0.8,
    "liquidation_cascade": 2.5,
    ...
}

# DEPOIS (config-driven):
max_sl_map = config.max_sl_map  # dict passado via DefensiveConfig ou ScalpingConfig
```

Isso permite que cada subsistema defina seus proprios limites de SL/RR sem modificar o risk_manager.

---

## Pontos de extensao futura

| Ponto | Descricao | Quando |
|---|---|---|
| Novos pares | Adicionar SOL, DOGE, etc ao DEFENSIVE_SYMBOLS | Apos validacao em BTC/ETH |
| Novos timeframes | Testar 5m ou 1h como signal_timeframe | Apos backtest comparativo |
| Motor RAVR V1.1 | Ativar RAVR como segundo motor alem do CFER | Apos validacao CFER |
| AVDR | Implementar anchored VWAP como terceira estrategia | Se infra de VWAP melhorar |
| Dashboard | Paginas de funil, equity e metricas defensivas | Apos paper trading |
| Telegram commands | /defensive_status, /defensive_performance | Apos paper trading |
| ML trap scoring | Modelo treinado para scoring de trap (em vez de regras) | Muito futuro |

---

## Testes

### Unitarios (obrigatorios para cada modulo)

```
tests/test_compression_detector.py
  - test_compression_detected_when_bb_declining
  - test_no_compression_when_bb_stable
  - test_percentile_calculation
  - test_atr_confirmation

tests/test_breakout_detector.py  
  - test_breakout_up_detected
  - test_breakout_down_detected
  - test_no_breakout_without_volume
  - test_no_breakout_inside_bands

tests/test_trap_detector.py
  - test_oi_trap_detected
  - test_liquidation_trap_detected
  - test_crowding_trap_detected
  - test_no_trap_without_evidence
  - test_trap_scoring

tests/test_defensive_trader.py
  - test_full_cfer_pipeline_trade
  - test_full_cfer_pipeline_no_trade
  - test_regime_blocks_trade
  - test_cooldown_blocks_trade
  - test_position_management_tp1
  - test_position_management_sl
  - test_timeout_exit
  - test_regime_shift_exit

tests/test_ravr_trader.py
  - test_zscore_signal_long
  - test_zscore_signal_short
  - test_no_signal_below_threshold
  - test_volume_filter

tests/test_value_reference.py
  - test_vwap_calculation
  - test_zscore_calculation
  - test_percentile_rank

tests/test_backtest_engine.py
  - test_backtest_with_known_data
  - test_cost_calculation
  - test_slippage_application
  - test_walk_forward_split
```

### Integracao

```
tests/test_defensive_integration.py
  - test_main_loop_with_defensive_enabled
  - test_defensive_and_pump_coexist
  - test_circuit_breaker_stops_defensive
  - test_database_tables_created
```

---

## Logging

```python
# Padrao: loguru ou logging padrao Python
# Formato:
# [2026-04-14 10:30:00] [DEFENSIVE] [CFER] [BTCUSDT] compression detected: BB%=0.45, percentile=12
# [2026-04-14 10:45:00] [DEFENSIVE] [CFER] [BTCUSDT] breakout UP: close=65200, BB_upper=65150, vol_ratio=1.8
# [2026-04-14 11:00:00] [DEFENSIVE] [CFER] [BTCUSDT] trap confirmed: score=55 [oi_trap, crowding_trap]
# [2026-04-14 11:00:00] [DEFENSIVE] [CFER] [BTCUSDT] ENTRY SHORT @ 65050 | SL=65250 | TP1=64800 | TP2=64500

# Cada decision registrada no DB com outcome descritivo
# Cada trade registrado com snapshot completo de microestrutura
```

---

## Configuracao por arquivo

```bash
# .env (secrets e toggles)
DEFENSIVE_ENABLED=true
DEFENSIVE_SYMBOLS=BTCUSDT,ETHUSDT
DEFENSIVE_INITIAL_CAPITAL=1000
DEFENSIVE_STRATEGY=cfer

# Parametros finos em DefensiveConfig (config.py ou defensive/config.py)
# Nao em .env — sao muitos e devem ter defaults sensatos no codigo
```

---

## Resumo de modificacoes no codigo existente

| Arquivo | Tipo de mudanca | Linhas estimadas |
|---|---|---|
| `main.py` | Adicionar bloco `process_defensive()` | +20-30 |
| `config.py` | Adicionar namespace `DEFENSIVE_*` | +15-20 |
| `database.py` | Adicionar 2 tabelas + whitelist | +60-80 |
| `risk_manager.py` | Parametrizar SL/RR maps | +10-15 (refactor) |
| `signal_types.py` | (opcional) Adicionar DefensiveSignal | +20-30 |

Total de modificacoes em codigo existente: **~125-175 linhas**.
Codigo novo (defensive/ + backtest/ + tests/): **~2000-3000 linhas** estimadas.
