# H1 Pair Trading — Implementation Plan (Phase 1: Backtest Ready)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the minimum viable pair trading module (BTC/ETH stat arb) sufficient to run BACKTEST + 4 ROBUSTNESS tests + GO/NO-GO evaluation against the spec at `docs/superpowers/specs/2026-04-21-h1-pair-trading-design.md`.

**Architecture:** New isolated module `pair_trading/` with pure functions for spread/decision logic, a research runner that simulates trades candle-by-candle, and CLI entry points for backtest/robustness. No paper executor, no main.py integration, no Telegram yet — those are Phase 2 (written only if this phase PASSes).

**Tech Stack:** Python 3.13, numpy, pandas, sqlite3, pytest, requests.

**Non-goals for this plan (deferred to Phase 2):**
- `pair_trading/paper_executor.py` (live paper trading, state file, DB persistence for live)
- `main.py` integration (`process_pair_cycle`)
- Telegram command/notification integration
- Daily report integration
- Proactive alerts extensions
- Dashboard integration

---

## File Structure

```
pair_trading/
  __init__.py                  # empty — marks package
  config.py                    # PairConfig dataclass
  spread_calculator.py         # cum_spread + z-score + correlation (pure)
  pair_trader.py               # decision logic: entry/exit (pure)
  historical_data.py           # fetch BTC/ETH historical candles (Binance REST)
  research_db.py               # SQLite schema + CRUD for pair_research tables
  research_runner.py           # backtest candle-by-candle simulation
  baselines.py                 # buy-and-hold + random trader baselines
  robustness_check.py          # 4 robustness tests
  go_no_go.py                  # reads backtest/robustness results, evaluates gates

scripts/
  run_pair_backtest.py         # CLI entry for backtest
  run_pair_robustness.py       # CLI entry for robustness suite
  evaluate_pair_go_no_go.py    # CLI that reads DB outputs and prints PASS/FAIL per spec gate

tests/
  test_pair_config.py
  test_pair_spread_calculator.py
  test_pair_trader.py
  test_pair_historical_data.py
  test_pair_research_db.py
  test_pair_research_runner.py
  test_pair_baselines.py
  test_pair_robustness.py
  test_pair_go_no_go.py

research/
  (output dir — research/pair_v1_90d.db etc. created by CLI)
```

**Design rationale:**
- Each `.py` has one responsibility and is tested in isolation.
- `spread_calculator.py` and `pair_trader.py` are pure functions → trivial to test with synthetic fixtures.
- `research_db.py` separated from `research_runner.py` so persistence can be swapped for tests.
- `baselines.py` kept separate because it's only used by robustness evaluation, not by live trading.
- `historical_data.py` isolated so network I/O can be mocked.

---

## Task 1: Module scaffolding + empty package

**Files:**
- Create: `pair_trading/__init__.py`
- Create: `tests/__init__.py` (verify it exists; if not, create empty)

- [ ] **Step 1: Verify tests/ already a package**

Run: `ls tests/__init__.py`
Expected: file exists (it should — momentum/ pattern confirms it).

- [ ] **Step 2: Create pair_trading package**

```bash
mkdir -p pair_trading
```

Create `pair_trading/__init__.py`:

```python
"""Pair Trading — cross-asset statistical arbitrage.

EXP-004 in docs/EXPERIMENT_REGISTRY.md.
Spec: docs/superpowers/specs/2026-04-21-h1-pair-trading-design.md

Phase 1 of implementation: backtest + robustness only.
Paper executor and live integration deferred to Phase 2.
"""
```

- [ ] **Step 3: Smoke test the import**

Run: `python -c "import pair_trading; print(pair_trading.__doc__)"`
Expected: prints the module docstring, no ImportError.

- [ ] **Step 4: Commit**

```bash
git add pair_trading/__init__.py
git commit -m "feat(pair): scaffold pair_trading package (EXP-004 phase 1)"
```

---

## Task 2: PairConfig

**Files:**
- Create: `pair_trading/config.py`
- Create: `tests/test_pair_config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pair_config.py`:

```python
"""Tests for PairConfig."""
import os
import pytest
from pair_trading.config import PairConfig


def test_defaults():
    cfg = PairConfig()
    assert cfg.symbols == ("BTCUSDT", "ETHUSDT")
    assert cfg.timeframe == "15m"
    assert cfg.window_candles == 96
    assert cfg.zscore_window_candles == 96
    assert cfg.entry_z == 2.0
    assert cfg.entry_max_z == 2.9
    assert cfg.exit_tp_z == 0.5
    assert cfg.exit_sl_z == 3.0
    assert cfg.time_stop_candles == 96
    assert cfg.capital_per_leg_usd == 500.0
    assert cfg.total_capital_usd == 1000.0
    assert cfg.max_concurrent_positions == 1
    assert cfg.circuit_breaker_dd_pct == 5.0
    assert cfg.fees_taker_pct == 0.04
    assert cfg.slippage_pct == 0.0
    assert cfg.param_version == "pair-trading-v1.0"
    assert cfg.enabled is False


def test_invariants_entry_thresholds():
    with pytest.raises(ValueError, match="entry_z"):
        PairConfig(entry_z=0)
    with pytest.raises(ValueError, match="exit_tp_z < entry_z"):
        PairConfig(exit_tp_z=2.5, entry_z=2.0)
    with pytest.raises(ValueError, match="entry_z < exit_sl_z"):
        PairConfig(entry_z=3.5, exit_sl_z=3.0)
    with pytest.raises(ValueError, match="entry_max_z"):
        PairConfig(entry_z=2.0, entry_max_z=1.9)


def test_invariant_capital():
    with pytest.raises(ValueError, match="capital"):
        PairConfig(capital_per_leg_usd=500, total_capital_usd=900)


def test_from_env(monkeypatch):
    monkeypatch.setenv("PAIR_TRADER_ENABLED", "true")
    monkeypatch.setenv("PAIR_CAPITAL_USD", "2000")
    cfg = PairConfig.from_env()
    assert cfg.enabled is True
    assert cfg.total_capital_usd == 2000.0
    assert cfg.capital_per_leg_usd == 1000.0  # recomputed to keep invariant


def test_from_env_boolean_parsing(monkeypatch):
    for v, expected in [("true", True), ("True", True), ("1", True),
                        ("false", False), ("0", False), ("", False)]:
        monkeypatch.setenv("PAIR_TRADER_ENABLED", v)
        assert PairConfig.from_env().enabled == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pair_config.py -v`
Expected: ModuleNotFoundError or 5 failing tests.

- [ ] **Step 3: Implement PairConfig**

Create `pair_trading/config.py`:

```python
"""Configuration for Pair Trading — EXP-004.

v1.0 parameters. Frozen after first backtest PASS per registry rules.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Tuple


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw == "":
        return default
    return raw in ("1", "true", "yes", "y", "t")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return default
    return float(raw)


@dataclass
class PairConfig:
    """Frozen v1.0 parameters for Pair Trading BTC/ETH."""

    # Symbols & timeframe
    symbols: Tuple[str, str] = ("BTCUSDT", "ETHUSDT")
    timeframe: str = "15m"

    # Spread / z-score windows (15m candles)
    window_candles: int = 96          # 24h
    zscore_window_candles: int = 96   # 24h

    # Entry / exit thresholds on |z|
    entry_z: float = 2.0
    entry_max_z: float = 2.9          # skip if already past SL zone
    exit_tp_z: float = 0.5
    exit_sl_z: float = 3.0

    # Time-based exit
    time_stop_candles: int = 96       # 24h

    # Capital (USD)
    capital_per_leg_usd: float = 500.0
    total_capital_usd: float = 1000.0
    max_concurrent_positions: int = 1

    # Safety
    circuit_breaker_dd_pct: float = 5.0

    # Costs
    fees_taker_pct: float = 0.04      # per leg, per side (entry+exit both legs = 0.16% RT)
    slippage_pct: float = 0.0         # paper assumption; sensitivity analysis in backtest

    # Versioning / activation
    param_version: str = "pair-trading-v1.0"
    enabled: bool = False             # default off; activated via env or explicit CLI

    def __post_init__(self) -> None:
        if self.entry_z <= 0:
            raise ValueError(f"entry_z must be > 0, got {self.entry_z}")
        if not (self.exit_tp_z < self.entry_z):
            raise ValueError(
                f"exit_tp_z < entry_z required, got {self.exit_tp_z} vs {self.entry_z}"
            )
        if not (self.entry_z < self.exit_sl_z):
            raise ValueError(
                f"entry_z < exit_sl_z required, got {self.entry_z} vs {self.exit_sl_z}"
            )
        if self.entry_max_z < self.entry_z:
            raise ValueError(
                f"entry_max_z >= entry_z required, got {self.entry_max_z} vs {self.entry_z}"
            )
        if abs(self.capital_per_leg_usd * 2 - self.total_capital_usd) > 1e-6:
            raise ValueError(
                f"capital: per_leg*2 must equal total, "
                f"got {self.capital_per_leg_usd}*2 != {self.total_capital_usd}"
            )

    @classmethod
    def from_env(cls) -> "PairConfig":
        """Construct from env vars, recomputing invariants.

        Supported overrides:
          PAIR_TRADER_ENABLED (bool)
          PAIR_CAPITAL_USD    (float) — total pool; per_leg auto-recomputed
        """
        enabled = _env_bool("PAIR_TRADER_ENABLED", default=False)
        total = _env_float("PAIR_CAPITAL_USD", default=1000.0)
        per_leg = total / 2.0
        return cls(
            enabled=enabled,
            total_capital_usd=total,
            capital_per_leg_usd=per_leg,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pair_config.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/config.py tests/test_pair_config.py
git commit -m "feat(pair): PairConfig dataclass with invariants and env override"
```

---

## Task 3: Spread calculator (cum_spread + z-score + correlation + guards)

**Files:**
- Create: `pair_trading/spread_calculator.py`
- Create: `tests/test_pair_spread_calculator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pair_spread_calculator.py`:

```python
"""Tests for spread_calculator."""
import numpy as np
import pytest
from pair_trading.spread_calculator import compute_snapshot, SpreadSnapshot


def _synthetic_prices(n, start=100.0, noise=0.0, seed=0, drift=0.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, noise, n)
    return start * np.exp(np.cumsum(rets))


def test_flat_prices_return_zero_zscore():
    btc = np.full(200, 50000.0)
    eth = np.full(200, 3000.0)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    # flat prices → cum_spread is 0, std is 0 → z is None (invalid)
    assert snap.is_valid is False


def test_divergent_prices_give_high_zscore():
    # BTC rises monotonically, ETH stays flat → spread grows
    btc = np.array([50000.0 * (1 + 0.001) ** i for i in range(200)])
    eth = np.full(200, 3000.0)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert snap.is_valid
    assert snap.z_score > 2.0  # BTC outperformed → positive z


def test_short_history_returns_invalid():
    btc = np.full(50, 50000.0)
    eth = np.full(50, 3000.0)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert snap.is_valid is False


def test_nan_in_prices_is_invalid():
    btc = np.full(200, 50000.0)
    btc[50] = np.nan
    eth = np.full(200, 3000.0)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert snap.is_valid is False


def test_zero_in_prices_is_invalid():
    btc = np.full(200, 50000.0)
    btc[50] = 0.0
    eth = np.full(200, 3000.0)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert snap.is_valid is False


def test_cum_spread_matches_log_ratio_diff():
    # cum_spread(t) == log(BTC(t)/BTC(t-W)) - log(ETH(t)/ETH(t-W))
    btc = _synthetic_prices(200, noise=0.01, seed=1)
    eth = _synthetic_prices(200, noise=0.01, seed=2)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    expected = (np.log(btc[-1]/btc[-97]) - np.log(eth[-1]/eth[-97]))
    assert abs(snap.cum_spread - expected) < 1e-9


def test_correlation_strong_and_weak():
    # Identical series → correlation ≈ 1
    same = _synthetic_prices(200, noise=0.02, seed=3)
    snap_same = compute_snapshot(same, same, window=96, zscore_window=96)
    # cum_spread identical paths is zero → z invalid, but correlation still computed
    assert snap_same.correlation > 0.99

    # Anti-correlated series → correlation negative
    a = _synthetic_prices(200, noise=0.02, seed=4)
    b = 1.0 / a
    snap_anti = compute_snapshot(a, b, window=96, zscore_window=96)
    assert snap_anti.correlation < -0.8


def test_is_valid_true_normal_case():
    btc = _synthetic_prices(200, noise=0.01, seed=10)
    eth = _synthetic_prices(200, noise=0.01, seed=11)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert snap.is_valid
    assert not np.isnan(snap.z_score)


def test_snapshot_dataclass_immutable_fields():
    btc = _synthetic_prices(200, noise=0.01, seed=20)
    eth = _synthetic_prices(200, noise=0.01, seed=21)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert isinstance(snap, SpreadSnapshot)
    # Required fields present
    for f in ("cum_spread", "rolling_mean", "rolling_std", "z_score",
              "correlation", "is_valid"):
        assert hasattr(snap, f)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pair_spread_calculator.py -v`
Expected: ModuleNotFoundError / multiple failures.

- [ ] **Step 3: Implement spread_calculator**

Create `pair_trading/spread_calculator.py`:

```python
"""Cumulative return spread + z-score + correlation.

Pure functions. No I/O, no state. Input: two aligned price arrays.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class SpreadSnapshot:
    cum_spread: float
    rolling_mean: float
    rolling_std: float
    z_score: float
    correlation: float
    is_valid: bool


def _is_clean(arr: np.ndarray) -> bool:
    return (
        np.isfinite(arr).all()
        and (arr > 0).all()
    )


def _cum_spread_series(btc: np.ndarray, eth: np.ndarray, window: int) -> np.ndarray:
    """Return array of cum_spread values for each t where it's defined.

    cum_spread(t) = log(btc[t]/btc[t-window]) - log(eth[t]/eth[t-window])
    Result length = len(btc) - window.
    """
    log_btc = np.log(btc)
    log_eth = np.log(eth)
    # For each t in [window, len-1], compute log(btc[t]/btc[t-window]) - same for eth
    return (log_btc[window:] - log_btc[:-window]) - (log_eth[window:] - log_eth[:-window])


def compute_snapshot(
    btc: np.ndarray,
    eth: np.ndarray,
    window: int,
    zscore_window: int,
) -> SpreadSnapshot:
    """Compute current SpreadSnapshot from aligned price arrays.

    Returns SpreadSnapshot with is_valid=False if math is undefined.
    Never raises — caller uses is_valid to decide.
    """
    btc = np.asarray(btc, dtype=np.float64)
    eth = np.asarray(eth, dtype=np.float64)

    required = window + zscore_window
    if len(btc) < required or len(eth) < required:
        return SpreadSnapshot(0.0, 0.0, 0.0, float("nan"), 0.0, False)

    if not (_is_clean(btc) and _is_clean(eth)):
        return SpreadSnapshot(0.0, 0.0, 0.0, float("nan"), 0.0, False)

    spread_series = _cum_spread_series(btc, eth, window)
    if len(spread_series) < zscore_window:
        return SpreadSnapshot(0.0, 0.0, 0.0, float("nan"), 0.0, False)

    recent = spread_series[-zscore_window:]
    mean = float(np.mean(recent))
    std = float(np.std(recent, ddof=0))
    cum_spread = float(spread_series[-1])

    # Correlation of 15m log-returns over the same window
    btc_ret = np.diff(np.log(btc[-(zscore_window + 1):]))
    eth_ret = np.diff(np.log(eth[-(zscore_window + 1):]))
    if np.std(btc_ret) == 0 or np.std(eth_ret) == 0:
        corr = 0.0
    else:
        corr = float(np.corrcoef(btc_ret, eth_ret)[0, 1])

    if std == 0.0 or not np.isfinite(std):
        return SpreadSnapshot(cum_spread, mean, std, float("nan"), corr, False)

    z = (cum_spread - mean) / std
    if not np.isfinite(z):
        return SpreadSnapshot(cum_spread, mean, std, float("nan"), corr, False)

    return SpreadSnapshot(cum_spread, mean, std, z, corr, True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pair_spread_calculator.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/spread_calculator.py tests/test_pair_spread_calculator.py
git commit -m "feat(pair): spread calculator — cum_spread + z-score + correlation with guards"
```

---

## Task 4: PairDecision types + enum

**Files:**
- Modify: `pair_trading/pair_trader.py` (create file, add types)

- [ ] **Step 1: Create types module (no test yet — types only)**

Create `pair_trading/pair_trader.py`:

```python
"""Pair trader — decision logic. Pure function over SpreadSnapshot.

decide() is called every cycle; returns PairDecision that the executor
translates into actions on state.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pair_trading.config import PairConfig
from pair_trading.spread_calculator import SpreadSnapshot


class PairAction(str, Enum):
    NO_ACTION = "no_action"
    OPEN_LONG_BTC_SHORT_ETH = "open_long_btc_short_eth"
    OPEN_SHORT_BTC_LONG_ETH = "open_short_btc_long_eth"
    CLOSE_TP = "close_tp"
    CLOSE_SL = "close_sl"
    CLOSE_TIMEOUT = "close_timeout"
    HOLD = "hold"


@dataclass(frozen=True)
class PairPosition:
    """Represents an open pair position (minimal for decision logic)."""
    direction: PairAction  # one of OPEN_LONG_BTC_SHORT_ETH or OPEN_SHORT_BTC_LONG_ETH
    entry_z: float
    candles_held: int  # count of candles since entry (incremented by executor each cycle)


@dataclass(frozen=True)
class PairDecision:
    action: PairAction
    blocked_by: Optional[str] = None
    trigger_reason: Optional[str] = None


def decide(
    snapshot: SpreadSnapshot,
    position: Optional[PairPosition],
    config: PairConfig,
    circuit_breaker_active: bool = False,
) -> PairDecision:
    raise NotImplementedError("Implemented in Task 5 and Task 6")
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from pair_trading.pair_trader import PairAction, PairDecision, PairPosition, decide; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add pair_trading/pair_trader.py
git commit -m "feat(pair): pair_trader types scaffolding (PairAction, PairDecision, PairPosition)"
```

---

## Task 5: Pair trader — entry logic

**Files:**
- Modify: `pair_trading/pair_trader.py`
- Create: `tests/test_pair_trader.py`

- [ ] **Step 1: Write failing tests for entry logic**

Create `tests/test_pair_trader.py`:

```python
"""Tests for pair_trader.decide — entry branches."""
import pytest
from pair_trading.config import PairConfig
from pair_trading.pair_trader import (
    PairAction, PairDecision, PairPosition, decide,
)
from pair_trading.spread_calculator import SpreadSnapshot


CFG = PairConfig()


def _snap(z: float, is_valid: bool = True) -> SpreadSnapshot:
    return SpreadSnapshot(
        cum_spread=0.1, rolling_mean=0.0, rolling_std=0.05,
        z_score=z, correlation=0.8, is_valid=is_valid,
    )


def test_no_action_when_z_below_threshold():
    d = decide(_snap(1.5), position=None, config=CFG)
    assert d.action == PairAction.NO_ACTION
    assert d.blocked_by == "z_below_threshold"


def test_no_action_when_z_above_entry_guard():
    d = decide(_snap(3.1), position=None, config=CFG)
    assert d.action == PairAction.NO_ACTION
    assert d.blocked_by == "z_above_entry_guard"


def test_no_action_when_invalid_snapshot():
    d = decide(_snap(2.5, is_valid=False), position=None, config=CFG)
    assert d.action == PairAction.NO_ACTION
    assert d.blocked_by == "invalid_zscore"


def test_open_short_btc_long_eth_when_z_positive():
    # z = +2.5 means BTC outperformed → short BTC, long ETH
    d = decide(_snap(2.5), position=None, config=CFG)
    assert d.action == PairAction.OPEN_SHORT_BTC_LONG_ETH
    assert d.blocked_by is None


def test_open_long_btc_short_eth_when_z_negative():
    d = decide(_snap(-2.5), position=None, config=CFG)
    assert d.action == PairAction.OPEN_LONG_BTC_SHORT_ETH
    assert d.blocked_by is None


def test_entry_exactly_at_threshold_opens():
    d = decide(_snap(2.0), position=None, config=CFG)
    assert d.action == PairAction.OPEN_SHORT_BTC_LONG_ETH


def test_entry_at_upper_boundary_opens():
    d = decide(_snap(2.9), position=None, config=CFG)
    assert d.action == PairAction.OPEN_SHORT_BTC_LONG_ETH


def test_circuit_breaker_blocks_entry():
    d = decide(_snap(2.5), position=None, config=CFG, circuit_breaker_active=True)
    assert d.action == PairAction.NO_ACTION
    assert d.blocked_by == "circuit_breaker"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pair_trader.py -v`
Expected: all fail with NotImplementedError.

- [ ] **Step 3: Implement entry logic**

In `pair_trading/pair_trader.py`, replace the `decide()` body:

```python
def decide(
    snapshot: SpreadSnapshot,
    position: Optional[PairPosition],
    config: PairConfig,
    circuit_breaker_active: bool = False,
) -> PairDecision:
    # Invalid snapshot → no action regardless of state
    if not snapshot.is_valid:
        return PairDecision(PairAction.NO_ACTION, blocked_by="invalid_zscore")

    # Position management (exit logic) — implemented in Task 6
    if position is not None:
        return _decide_exit(snapshot, position, config)

    # Entry logic
    if circuit_breaker_active:
        return PairDecision(PairAction.NO_ACTION, blocked_by="circuit_breaker")

    z = snapshot.z_score
    abs_z = abs(z)

    if abs_z < config.entry_z:
        return PairDecision(PairAction.NO_ACTION, blocked_by="z_below_threshold")

    if abs_z > config.entry_max_z:
        return PairDecision(PairAction.NO_ACTION, blocked_by="z_above_entry_guard")

    # Valid entry zone: config.entry_z <= |z| <= config.entry_max_z
    if z > 0:
        return PairDecision(
            PairAction.OPEN_SHORT_BTC_LONG_ETH,
            trigger_reason=f"z={z:.2f}>=+{config.entry_z}",
        )
    else:
        return PairDecision(
            PairAction.OPEN_LONG_BTC_SHORT_ETH,
            trigger_reason=f"z={z:.2f}<=-{config.entry_z}",
        )


def _decide_exit(
    snapshot: SpreadSnapshot,
    position: PairPosition,
    config: PairConfig,
) -> PairDecision:
    # Stub — implemented in Task 6
    raise NotImplementedError("exit logic implemented in Task 6")
```

- [ ] **Step 4: Run entry tests**

Run: `python -m pytest tests/test_pair_trader.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/pair_trader.py tests/test_pair_trader.py
git commit -m "feat(pair): entry decision logic (entry_z, entry_max_z guards)"
```

---

## Task 6: Pair trader — exit logic (priority SL > TIMEOUT > TP)

**Files:**
- Modify: `pair_trading/pair_trader.py`
- Modify: `tests/test_pair_trader.py`

- [ ] **Step 1: Add exit tests**

Append to `tests/test_pair_trader.py`:

```python
# --- exit branch tests ---

def _pos(direction=PairAction.OPEN_SHORT_BTC_LONG_ETH, entry_z=2.5, held=10):
    return PairPosition(direction=direction, entry_z=entry_z, candles_held=held)


def test_hold_when_z_still_wide():
    # Position at z=+2.5 still +2.0 → no exit yet
    d = decide(_snap(2.0), position=_pos(), config=CFG)
    assert d.action == PairAction.HOLD


def test_close_tp_when_z_crosses_tp_threshold():
    d = decide(_snap(0.4), position=_pos(), config=CFG)
    assert d.action == PairAction.CLOSE_TP
    assert "tp" in (d.trigger_reason or "").lower()


def test_close_tp_at_exact_boundary():
    d = decide(_snap(0.5), position=_pos(), config=CFG)
    assert d.action == PairAction.CLOSE_TP


def test_close_sl_when_z_beyond_sl_threshold():
    d = decide(_snap(3.1), position=_pos(), config=CFG)
    assert d.action == PairAction.CLOSE_SL


def test_close_sl_at_exact_boundary():
    d = decide(_snap(3.0), position=_pos(), config=CFG)
    assert d.action == PairAction.CLOSE_SL


def test_close_timeout_when_candles_held_reached():
    pos = _pos(held=96)
    # Pick a z in the HOLD zone so only timeout triggers
    d = decide(_snap(1.5), position=pos, config=CFG)
    assert d.action == PairAction.CLOSE_TIMEOUT


def test_priority_sl_over_timeout():
    pos = _pos(held=96)
    # Both SL and TIMEOUT would fire; SL wins
    d = decide(_snap(3.2), position=pos, config=CFG)
    assert d.action == PairAction.CLOSE_SL


def test_priority_timeout_over_tp():
    pos = _pos(held=96)
    # Both TIMEOUT and TP would fire; TIMEOUT wins
    d = decide(_snap(0.4), position=pos, config=CFG)
    assert d.action == PairAction.CLOSE_TIMEOUT


def test_exit_ignores_circuit_breaker():
    # Once open, circuit breaker does not force-close
    d = decide(_snap(0.4), position=_pos(), config=CFG, circuit_breaker_active=True)
    assert d.action == PairAction.CLOSE_TP  # normal TP still fires


def test_exit_ignores_invalid_snapshot():
    # Position open + invalid snapshot → blocked, no close
    d = decide(_snap(0.4, is_valid=False), position=_pos(), config=CFG)
    assert d.action == PairAction.NO_ACTION
    assert d.blocked_by == "invalid_zscore"
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `python -m pytest tests/test_pair_trader.py -v`
Expected: 8 passing (entry) + 10 failing exit tests.

- [ ] **Step 3: Implement exit logic**

In `pair_trading/pair_trader.py`, replace `_decide_exit`:

```python
def _decide_exit(
    snapshot: SpreadSnapshot,
    position: PairPosition,
    config: PairConfig,
) -> PairDecision:
    """Exit priority: SL > TIMEOUT > TP."""
    abs_z = abs(snapshot.z_score)

    # 1. SL
    if abs_z >= config.exit_sl_z:
        return PairDecision(
            PairAction.CLOSE_SL,
            trigger_reason=f"|z|={abs_z:.2f}>={config.exit_sl_z}",
        )

    # 2. TIMEOUT
    if position.candles_held >= config.time_stop_candles:
        return PairDecision(
            PairAction.CLOSE_TIMEOUT,
            trigger_reason=f"candles_held={position.candles_held}>={config.time_stop_candles}",
        )

    # 3. TP
    if abs_z <= config.exit_tp_z:
        return PairDecision(
            PairAction.CLOSE_TP,
            trigger_reason=f"tp: |z|={abs_z:.2f}<={config.exit_tp_z}",
        )

    return PairDecision(PairAction.HOLD)
```

- [ ] **Step 4: Run all pair_trader tests**

Run: `python -m pytest tests/test_pair_trader.py -v`
Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/pair_trader.py tests/test_pair_trader.py
git commit -m "feat(pair): exit logic with priority SL > TIMEOUT > TP"
```

---

## Task 7: Historical data fetcher

**Files:**
- Create: `pair_trading/historical_data.py`
- Create: `tests/test_pair_historical_data.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pair_historical_data.py`:

```python
"""Tests for historical_data — uses mocked HTTP."""
from unittest.mock import patch, MagicMock

import pytest

from pair_trading.historical_data import (
    fetch_klines,
    fetch_synced_pair,
    klines_to_arrays,
)


_SAMPLE_KLINE = [
    1700000000000,  # open_time ms
    "50000.0",      # open
    "50100.0",      # high
    "49900.0",      # low
    "50050.0",      # close
    "123.45",       # volume
    1700000899999,  # close_time ms
    "6175500.0",    # quote_volume
    100,            # trades
    "60.0",         # taker_buy_base
    "3000000.0",    # taker_buy_quote
    "0",
]


def _mock_response(klines):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = klines
    m.raise_for_status.return_value = None
    return m


def test_fetch_klines_single_page():
    klines = [_SAMPLE_KLINE for _ in range(200)]
    with patch("pair_trading.historical_data.requests.get") as g:
        g.return_value = _mock_response(klines)
        result = fetch_klines("BTCUSDT", "15m", limit=200)
    assert len(result) == 200
    assert result[0][0] == 1700000000000


def test_fetch_klines_pagination_for_large_range():
    # 2500 candles requires 3 pages (1000 + 1000 + 500)
    page1 = [[(1_700_000_000 + i) * 1000, "1", "1", "1", "1", "1",
              (1_700_000_000 + i) * 1000 + 899999, "1", 1, "1", "1", "0"]
             for i in range(1000)]
    page2 = [[(1_700_001_000 + i) * 1000, "1", "1", "1", "1", "1",
              (1_700_001_000 + i) * 1000 + 899999, "1", 1, "1", "1", "0"]
             for i in range(1000)]
    page3 = [[(1_700_002_000 + i) * 1000, "1", "1", "1", "1", "1",
              (1_700_002_000 + i) * 1000 + 899999, "1", 1, "1", "1", "0"]
             for i in range(500)]
    with patch("pair_trading.historical_data.requests.get") as g:
        g.side_effect = [_mock_response(page1), _mock_response(page2), _mock_response(page3)]
        result = fetch_klines("BTCUSDT", "15m", limit=2500)
    assert len(result) == 2500


def test_klines_to_arrays_extracts_close_and_close_time():
    klines = [_SAMPLE_KLINE, _SAMPLE_KLINE]
    close, close_time = klines_to_arrays(klines)
    assert close.tolist() == [50050.0, 50050.0]
    assert close_time.tolist() == [1700000899999, 1700000899999]


def test_fetch_synced_pair_aligns_by_close_time():
    # BTC has 3 candles (t=100, 200, 300)
    btc_k = [
        [100, "1", "1", "1", "1", "1", 199, "1", 1, "1", "1", "0"],
        [200, "1", "1", "1", "2", "1", 299, "1", 1, "1", "1", "0"],
        [300, "1", "1", "1", "3", "1", 399, "1", 1, "1", "1", "0"],
    ]
    # ETH missing t=200 (only t=100, 300)
    eth_k = [
        [100, "1", "1", "1", "10", "1", 199, "1", 1, "1", "1", "0"],
        [300, "1", "1", "1", "30", "1", 399, "1", 1, "1", "1", "0"],
    ]
    with patch("pair_trading.historical_data.fetch_klines") as fk:
        fk.side_effect = [btc_k, eth_k]
        btc_close, eth_close, close_times = fetch_synced_pair(
            "BTCUSDT", "ETHUSDT", "15m", limit=10
        )
    assert btc_close.tolist() == [1.0, 3.0]
    assert eth_close.tolist() == [10.0, 30.0]
    assert close_times.tolist() == [199, 399]
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_pair_historical_data.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement historical_data**

Create `pair_trading/historical_data.py`:

```python
"""Historical candle fetcher for pair trading.

Uses Binance Futures REST endpoint. Handles pagination for ranges > 1000.
"""
from __future__ import annotations

import time
from typing import List, Tuple

import numpy as np
import requests


_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
_MAX_PER_REQUEST = 1000


def fetch_klines(
    symbol: str,
    interval: str,
    limit: int,
    end_time_ms: int | None = None,
) -> List[list]:
    """Fetch `limit` klines ending at end_time_ms (or now).

    Returns raw list-of-lists from Binance. Handles pagination transparently
    by walking backward in time with end_time from previous batch.
    """
    out: List[list] = []
    remaining = limit
    cursor = end_time_ms

    while remaining > 0:
        page_size = min(remaining, _MAX_PER_REQUEST)
        params = {"symbol": symbol, "interval": interval, "limit": page_size}
        if cursor is not None:
            params["endTime"] = cursor
        r = requests.get(_KLINES_URL, params=params, timeout=15)
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        # Binance returns oldest → newest within a page; we walk backward, so
        # prepend pages to keep global chronological order.
        out = page + out
        remaining -= len(page)
        # Next page ends 1ms before the first candle of this page
        cursor = page[0][0] - 1
        if len(page) < page_size:
            break
        time.sleep(0.1)  # polite to the API
    return out


def klines_to_arrays(klines: List[list]) -> Tuple[np.ndarray, np.ndarray]:
    """Extract (close_prices, close_times_ms) as numpy arrays."""
    closes = np.array([float(k[4]) for k in klines], dtype=np.float64)
    close_times = np.array([int(k[6]) for k in klines], dtype=np.int64)
    return closes, close_times


def fetch_synced_pair(
    symbol_a: str,
    symbol_b: str,
    interval: str,
    limit: int,
    end_time_ms: int | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fetch both symbols and align by close_time.

    Returns (close_a, close_b, close_times) with only timestamps present in both.
    """
    a = fetch_klines(symbol_a, interval, limit, end_time_ms=end_time_ms)
    b = fetch_klines(symbol_b, interval, limit, end_time_ms=end_time_ms)

    a_close, a_ct = klines_to_arrays(a)
    b_close, b_ct = klines_to_arrays(b)

    common_ct, a_idx, b_idx = np.intersect1d(a_ct, b_ct, return_indices=True)
    return a_close[a_idx], b_close[b_idx], common_ct
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_historical_data.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/historical_data.py tests/test_pair_historical_data.py
git commit -m "feat(pair): historical candle fetcher with pagination and alignment"
```

---

## Task 8: Research DB schema + CRUD

**Files:**
- Create: `pair_trading/research_db.py`
- Create: `tests/test_pair_research_db.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pair_research_db.py`:

```python
"""Tests for pair research DB CRUD."""
import os
import tempfile
import sqlite3

import pytest

from pair_trading.research_db import (
    init_db,
    insert_decision,
    insert_trade,
    close_trade,
    get_open_trade,
    fetch_all_trades,
    fetch_all_decisions,
)


@pytest.fixture
def db_path():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    yield tmp.name
    os.unlink(tmp.name)


def test_init_db_creates_tables(db_path):
    init_db(db_path)
    con = sqlite3.connect(db_path)
    tables = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "pair_decisions" in tables
    assert "pair_trades" in tables


def test_insert_decision_and_fetch(db_path):
    init_db(db_path)
    insert_decision(db_path, {
        "timestamp": "2026-04-21T00:00:00Z",
        "z_score": 2.3, "cum_spread": 0.05,
        "rolling_mean": 0.0, "rolling_std": 0.022,
        "correlation": 0.85, "btc_regime": "TRENDING",
        "action_taken": "open_short_btc_long_eth",
        "blocked_by": None,
        "position_id": None,
    })
    rows = fetch_all_decisions(db_path)
    assert len(rows) == 1
    assert rows[0]["action_taken"] == "open_short_btc_long_eth"


def test_insert_trade_open_and_close(db_path):
    init_db(db_path)
    tid = insert_trade(db_path, {
        "entry_time": "2026-04-21T00:00:00Z",
        "direction": "open_short_btc_long_eth",
        "entry_btc": 50000.0, "entry_eth": 3000.0,
        "entry_z": 2.3,
        "capital_at_entry": 1000.0,
        "btc_regime_entry": "TRENDING",
        "session_entry": "asia",
    })
    assert tid is not None

    open_t = get_open_trade(db_path)
    assert open_t is not None
    assert open_t["id"] == tid

    close_trade(db_path, tid, {
        "exit_time": "2026-04-21T12:00:00Z",
        "exit_btc": 49500.0, "exit_eth": 3010.0,
        "exit_z": 0.4, "exit_reason": "close_tp",
        "pnl_btc_pct": 1.0, "pnl_eth_pct": 0.33,
        "pnl_total_pct": 0.665, "pnl_usd": 6.65,
        "candles_held": 48,
    })

    open_t2 = get_open_trade(db_path)
    assert open_t2 is None

    trades = fetch_all_trades(db_path)
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "close_tp"
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_pair_research_db.py -v`

- [ ] **Step 3: Implement research_db**

Create `pair_trading/research_db.py`:

```python
"""SQLite persistence for pair trading research/backtest results.

Two tables:
  pair_decisions — one row per evaluated cycle (including skipped)
  pair_trades    — one row per closed trade (dual-leg merged)

Simple sqlite3, no ORM. Functions accept dict payloads to keep call sites flexible.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


_DECISIONS_DDL = """
CREATE TABLE IF NOT EXISTS pair_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    z_score         REAL,
    cum_spread      REAL,
    rolling_mean    REAL,
    rolling_std     REAL,
    correlation     REAL,
    btc_regime      TEXT    NOT NULL DEFAULT '',
    action_taken    TEXT    NOT NULL,
    blocked_by      TEXT,
    position_id     INTEGER,
    param_version   TEXT    NOT NULL DEFAULT 'pair-trading-v1.0'
);
"""

_TRADES_DDL = """
CREATE TABLE IF NOT EXISTS pair_trades (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_time       TEXT    NOT NULL,
    exit_time        TEXT,
    direction        TEXT    NOT NULL,
    entry_btc        REAL    NOT NULL,
    entry_eth        REAL    NOT NULL,
    exit_btc         REAL,
    exit_eth         REAL,
    entry_z          REAL    NOT NULL,
    exit_z           REAL,
    exit_reason      TEXT,
    pnl_btc_pct      REAL,
    pnl_eth_pct      REAL,
    pnl_total_pct    REAL,
    pnl_usd          REAL,
    candles_held     INTEGER,
    capital_at_entry REAL    NOT NULL,
    btc_regime_entry TEXT    NOT NULL DEFAULT '',
    session_entry    TEXT    NOT NULL DEFAULT '',
    param_version    TEXT    NOT NULL DEFAULT 'pair-trading-v1.0'
);
"""


def _connect(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db(db_path: str | Path) -> None:
    con = _connect(db_path)
    try:
        con.execute(_DECISIONS_DDL)
        con.execute(_TRADES_DDL)
        con.commit()
    finally:
        con.close()


def insert_decision(db_path: str | Path, payload: Dict[str, Any]) -> int:
    con = _connect(db_path)
    try:
        cur = con.execute(
            """INSERT INTO pair_decisions
               (timestamp, z_score, cum_spread, rolling_mean, rolling_std,
                correlation, btc_regime, action_taken, blocked_by, position_id)
               VALUES (:timestamp, :z_score, :cum_spread, :rolling_mean, :rolling_std,
                       :correlation, :btc_regime, :action_taken, :blocked_by, :position_id)""",
            payload,
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def insert_trade(db_path: str | Path, payload: Dict[str, Any]) -> int:
    con = _connect(db_path)
    try:
        cur = con.execute(
            """INSERT INTO pair_trades
               (entry_time, direction, entry_btc, entry_eth, entry_z,
                capital_at_entry, btc_regime_entry, session_entry)
               VALUES (:entry_time, :direction, :entry_btc, :entry_eth, :entry_z,
                       :capital_at_entry, :btc_regime_entry, :session_entry)""",
            payload,
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def close_trade(db_path: str | Path, trade_id: int, payload: Dict[str, Any]) -> None:
    con = _connect(db_path)
    try:
        payload = {**payload, "id": trade_id}
        con.execute(
            """UPDATE pair_trades
               SET exit_time=:exit_time, exit_btc=:exit_btc, exit_eth=:exit_eth,
                   exit_z=:exit_z, exit_reason=:exit_reason,
                   pnl_btc_pct=:pnl_btc_pct, pnl_eth_pct=:pnl_eth_pct,
                   pnl_total_pct=:pnl_total_pct, pnl_usd=:pnl_usd,
                   candles_held=:candles_held
               WHERE id=:id""",
            payload,
        )
        con.commit()
    finally:
        con.close()


def get_open_trade(db_path: str | Path) -> Optional[Dict[str, Any]]:
    con = _connect(db_path)
    try:
        row = con.execute(
            "SELECT * FROM pair_trades WHERE exit_time IS NULL LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def fetch_all_trades(db_path: str | Path) -> List[Dict[str, Any]]:
    con = _connect(db_path)
    try:
        rows = con.execute("SELECT * FROM pair_trades ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def fetch_all_decisions(db_path: str | Path) -> List[Dict[str, Any]]:
    con = _connect(db_path)
    try:
        rows = con.execute("SELECT * FROM pair_decisions ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_research_db.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/research_db.py tests/test_pair_research_db.py
git commit -m "feat(pair): research DB schema + CRUD for decisions and trades"
```

---

## Task 9: Research runner — candle-by-candle simulation

**Files:**
- Create: `pair_trading/research_runner.py`
- Create: `tests/test_pair_research_runner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pair_research_runner.py`:

```python
"""Tests for research_runner — candle-by-candle backtest simulation."""
import os
import tempfile

import numpy as np
import pytest

from pair_trading.config import PairConfig
from pair_trading.research_db import (
    init_db, fetch_all_trades, fetch_all_decisions,
)
from pair_trading.research_runner import run_backtest


@pytest.fixture
def db_path():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    init_db(tmp.name)
    yield tmp.name
    os.unlink(tmp.name)


def _diverging_series(n=500):
    """BTC drifts up, ETH flat → generates z excursions that revert periodically."""
    rng = np.random.default_rng(42)
    btc_rets = rng.normal(0.0005, 0.01, n)  # slight positive drift
    eth_rets = rng.normal(0.0, 0.01, n)     # zero drift, same vol
    btc = 50000.0 * np.exp(np.cumsum(btc_rets))
    eth = 3000.0 * np.exp(np.cumsum(eth_rets))
    times = np.arange(n, dtype=np.int64) * 900_000  # 15m in ms
    return btc, eth, times


def test_run_backtest_produces_decisions(db_path):
    btc, eth, times = _diverging_series(500)
    cfg = PairConfig()
    res = run_backtest(
        db_path=db_path, config=cfg,
        btc_close=btc, eth_close=eth, close_times_ms=times,
        regime_fn=lambda idx: "TRENDING",
    )
    decisions = fetch_all_decisions(db_path)
    assert len(decisions) > 0
    # Each cycle after warmup produces exactly one decision
    warmup = cfg.window_candles + cfg.zscore_window_candles
    assert len(decisions) == len(btc) - warmup


def test_run_backtest_produces_trades(db_path):
    btc, eth, times = _diverging_series(500)
    cfg = PairConfig()
    run_backtest(
        db_path=db_path, config=cfg,
        btc_close=btc, eth_close=eth, close_times_ms=times,
        regime_fn=lambda idx: "TRENDING",
    )
    trades = fetch_all_trades(db_path)
    # On diverging data with z excursions, should produce at least 1 trade
    assert len(trades) >= 1
    for t in trades:
        assert t["exit_time"] is not None
        assert t["exit_reason"] in ("close_tp", "close_sl", "close_timeout")


def test_run_backtest_pnl_accounting(db_path):
    btc, eth, times = _diverging_series(500)
    cfg = PairConfig()
    run_backtest(
        db_path=db_path, config=cfg,
        btc_close=btc, eth_close=eth, close_times_ms=times,
        regime_fn=lambda idx: "TRENDING",
    )
    trades = fetch_all_trades(db_path)
    for t in trades:
        # pnl_total_pct should equal (pnl_btc_pct + pnl_eth_pct) / 2 since equal notional
        expected = (t["pnl_btc_pct"] + t["pnl_eth_pct"]) / 2.0
        # Account for fees: 2 legs * 2 sides * 0.04% = 0.16% drag
        assert abs(t["pnl_total_pct"] - (expected - 0.16)) < 0.01


def test_run_backtest_look_ahead_protection(db_path):
    """Decision at t uses prices up to t; entry uses t+1 open.
    Test: with shift=0 (no protection) vs shift=1 (correct), pnl should differ.
    If they're identical, protection is not actually active.
    """
    btc, eth, times = _diverging_series(500)
    cfg = PairConfig()

    tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp2.close()
    init_db(tmp2.name)
    try:
        run_backtest(
            db_path=db_path, config=cfg,
            btc_close=btc, eth_close=eth, close_times_ms=times,
            regime_fn=lambda idx: "TRENDING",
            execution_shift=1,
        )
        run_backtest(
            db_path=tmp2.name, config=cfg,
            btc_close=btc, eth_close=eth, close_times_ms=times,
            regime_fn=lambda idx: "TRENDING",
            execution_shift=0,
        )
        shift1 = fetch_all_trades(db_path)
        shift0 = fetch_all_trades(tmp2.name)
        # Both should produce some trades but PnL totals should differ
        s1_pnl = sum(t["pnl_total_pct"] for t in shift1)
        s0_pnl = sum(t["pnl_total_pct"] for t in shift0)
        # They should not be identical — protection means different execution prices
        if len(shift1) > 0 and len(shift0) > 0:
            assert abs(s1_pnl - s0_pnl) > 1e-9
    finally:
        os.unlink(tmp2.name)
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_pair_research_runner.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement research_runner**

Create `pair_trading/research_runner.py`:

```python
"""Pair trading backtest — candle-by-candle simulation.

Look-ahead protection: decision at candle T uses close prices up to T;
execution happens at T+execution_shift using that candle's close (shift=1 = next
candle close, simulating "enter on next close"). execution_shift=0 is diagnostic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from pair_trading.config import PairConfig
from pair_trading.pair_trader import (
    PairAction, PairPosition, decide,
)
from pair_trading.research_db import (
    close_trade, get_open_trade, insert_decision, insert_trade,
)
from pair_trading.spread_calculator import compute_snapshot


def _ts_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _pnl_pct_per_leg(
    entry_price: float, exit_price: float, is_long: bool
) -> float:
    """Percentage P&L for one leg, without fees."""
    if is_long:
        return (exit_price - entry_price) / entry_price * 100.0
    return (entry_price - exit_price) / entry_price * 100.0


def run_backtest(
    *,
    db_path: str | Path,
    config: PairConfig,
    btc_close: np.ndarray,
    eth_close: np.ndarray,
    close_times_ms: np.ndarray,
    regime_fn: Callable[[int], str] = lambda idx: "UNKNOWN",
    session_fn: Callable[[int], str] = lambda idx: "",
    execution_shift: int = 1,
) -> dict:
    """Run a full backtest over the provided aligned series.

    Args:
        execution_shift: 1 (correct, default) = enter/exit on next candle close.
                         0 (diagnostic) = enter/exit on same candle (look-ahead leak).

    Returns: summary dict with counts.
    """
    warmup = config.window_candles + config.zscore_window_candles
    n = len(btc_close)
    assert len(eth_close) == n and len(close_times_ms) == n

    open_trade_id: Optional[int] = None
    entry_btc = entry_eth = 0.0
    entry_direction: Optional[PairAction] = None
    entry_candles_held = 0
    entry_z = 0.0
    decisions_recorded = 0
    trades_opened = 0
    trades_closed = 0

    for t in range(warmup, n):
        # Use data up to t (inclusive close)
        btc_win = btc_close[: t + 1]
        eth_win = eth_close[: t + 1]
        snap = compute_snapshot(
            btc_win[-warmup:], eth_win[-warmup:],
            window=config.window_candles,
            zscore_window=config.zscore_window_candles,
        )

        # Build PairPosition if trade open
        position = None
        if open_trade_id is not None:
            position = PairPosition(
                direction=entry_direction,
                entry_z=entry_z,
                candles_held=entry_candles_held,
            )

        decision = decide(snap, position, config, circuit_breaker_active=False)

        # Determine execution index
        exec_idx = min(t + execution_shift, n - 1)
        exec_btc = float(btc_close[exec_idx])
        exec_eth = float(eth_close[exec_idx])

        # Record decision
        insert_decision(db_path, {
            "timestamp": _ts_iso(int(close_times_ms[t])),
            "z_score": float(snap.z_score) if snap.is_valid else None,
            "cum_spread": float(snap.cum_spread),
            "rolling_mean": float(snap.rolling_mean),
            "rolling_std": float(snap.rolling_std),
            "correlation": float(snap.correlation),
            "btc_regime": regime_fn(t),
            "action_taken": decision.action.value,
            "blocked_by": decision.blocked_by,
            "position_id": open_trade_id,
        })
        decisions_recorded += 1

        # Execute decision
        if decision.action in (
            PairAction.OPEN_LONG_BTC_SHORT_ETH,
            PairAction.OPEN_SHORT_BTC_LONG_ETH,
        ):
            if open_trade_id is None and exec_idx < n:
                open_trade_id = insert_trade(db_path, {
                    "entry_time": _ts_iso(int(close_times_ms[exec_idx])),
                    "direction": decision.action.value,
                    "entry_btc": exec_btc,
                    "entry_eth": exec_eth,
                    "entry_z": float(snap.z_score),
                    "capital_at_entry": config.total_capital_usd,
                    "btc_regime_entry": regime_fn(t),
                    "session_entry": session_fn(t),
                })
                entry_btc = exec_btc
                entry_eth = exec_eth
                entry_direction = decision.action
                entry_z = float(snap.z_score)
                entry_candles_held = 0
                trades_opened += 1
        elif decision.action in (
            PairAction.CLOSE_TP, PairAction.CLOSE_SL, PairAction.CLOSE_TIMEOUT,
        ):
            if open_trade_id is not None and exec_idx < n:
                # Compute P&L
                is_long_btc = (entry_direction == PairAction.OPEN_LONG_BTC_SHORT_ETH)
                pnl_btc = _pnl_pct_per_leg(entry_btc, exec_btc, is_long_btc)
                pnl_eth = _pnl_pct_per_leg(entry_eth, exec_eth, not is_long_btc)
                # Cost drag: 2 legs * 2 sides * (fees + slippage)
                # Default: fees=0.04% → 0.16% RT. Slippage adds on top.
                cost_per_side = config.fees_taker_pct + config.slippage_pct
                total_cost = cost_per_side * 4
                pnl_total = (pnl_btc + pnl_eth) / 2.0 - total_cost
                pnl_usd = pnl_total / 100.0 * config.total_capital_usd

                close_trade(db_path, open_trade_id, {
                    "exit_time": _ts_iso(int(close_times_ms[exec_idx])),
                    "exit_btc": exec_btc,
                    "exit_eth": exec_eth,
                    "exit_z": float(snap.z_score),
                    "exit_reason": decision.action.value,
                    "pnl_btc_pct": pnl_btc,
                    "pnl_eth_pct": pnl_eth,
                    "pnl_total_pct": pnl_total,
                    "pnl_usd": pnl_usd,
                    "candles_held": entry_candles_held,
                })
                open_trade_id = None
                entry_direction = None
                trades_closed += 1
        elif decision.action == PairAction.HOLD:
            entry_candles_held += 1

    # Force-close any still-open trade at end of series (timeout at last candle).
    # Without this, trades opened near the end have exit_time=None, and the
    # "all trades have exit_time" invariant (used by downstream metrics) breaks.
    if open_trade_id is not None:
        last_idx = n - 1
        exit_btc = float(btc_close[last_idx])
        exit_eth = float(eth_close[last_idx])
        is_long_btc = (entry_direction == PairAction.OPEN_LONG_BTC_SHORT_ETH)
        pnl_btc = _pnl_pct_per_leg(entry_btc, exit_btc, is_long_btc)
        pnl_eth = _pnl_pct_per_leg(entry_eth, exit_eth, not is_long_btc)
        cost_per_side = config.fees_taker_pct + config.slippage_pct
        total_cost = cost_per_side * 4
        pnl_total = (pnl_btc + pnl_eth) / 2.0 - total_cost
        pnl_usd = pnl_total / 100.0 * config.total_capital_usd
        final_snap = compute_snapshot(
            btc_close[-warmup:], eth_close[-warmup:],
            window=config.window_candles,
            zscore_window=config.zscore_window_candles,
        )
        close_trade(db_path, open_trade_id, {
            "exit_time": _ts_iso(int(close_times_ms[last_idx])),
            "exit_btc": exit_btc,
            "exit_eth": exit_eth,
            "exit_z": float(final_snap.z_score) if final_snap.is_valid else 0.0,
            "exit_reason": PairAction.CLOSE_TIMEOUT.value,
            "pnl_btc_pct": pnl_btc,
            "pnl_eth_pct": pnl_eth,
            "pnl_total_pct": pnl_total,
            "pnl_usd": pnl_usd,
            "candles_held": entry_candles_held,
        })
        trades_closed += 1

    return {
        "decisions_recorded": decisions_recorded,
        "trades_opened": trades_opened,
        "trades_closed": trades_closed,
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_research_runner.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/research_runner.py tests/test_pair_research_runner.py
git commit -m "feat(pair): research runner with look-ahead protection and dual-leg PnL"
```

---

## Task 10: Metrics aggregator (PF, WR, DD, etc.)

**Files:**
- Create: `pair_trading/metrics.py`
- Create: `tests/test_pair_metrics.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pair_metrics.py`:

```python
"""Tests for metrics aggregator."""
import pytest
from pair_trading.metrics import compute_metrics


def _trade(pnl):
    return {"pnl_total_pct": pnl}


def test_all_winners():
    trades = [_trade(1.0), _trade(2.0), _trade(0.5)]
    m = compute_metrics(trades)
    assert m["n_trades"] == 3
    assert m["win_rate"] == 100.0
    assert m["profit_factor"] == float("inf")
    assert abs(m["total_pnl_pct"] - 3.5) < 1e-9


def test_mixed_trades():
    trades = [_trade(2.0), _trade(-1.0), _trade(1.0), _trade(-0.5)]
    m = compute_metrics(trades)
    assert m["n_trades"] == 4
    assert m["win_rate"] == 50.0
    assert abs(m["profit_factor"] - 2.0) < 1e-9  # 3.0 gross_win / 1.5 gross_loss
    assert abs(m["total_pnl_pct"] - 1.5) < 1e-9


def test_all_losers():
    trades = [_trade(-1.0), _trade(-2.0)]
    m = compute_metrics(trades)
    assert m["win_rate"] == 0.0
    assert m["profit_factor"] == 0.0
    assert abs(m["total_pnl_pct"] - (-3.0)) < 1e-9


def test_empty_trades():
    m = compute_metrics([])
    assert m["n_trades"] == 0
    assert m["win_rate"] == 0.0
    assert m["profit_factor"] == 0.0
    assert m["total_pnl_pct"] == 0.0


def test_max_drawdown_simple():
    # Equity: 0, +2, -3 (peak 2, trough -1) → DD = 3
    trades = [_trade(2.0), _trade(-3.0)]
    m = compute_metrics(trades)
    assert abs(m["max_drawdown_pct"] - 3.0) < 1e-9
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_pair_metrics.py -v`

- [ ] **Step 3: Implement metrics**

Create `pair_trading/metrics.py`:

```python
"""Aggregate metrics over a list of closed trade dicts."""
from __future__ import annotations

from typing import Dict, List


def compute_metrics(trades: List[Dict]) -> Dict[str, float]:
    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "total_pnl_pct": 0.0, "avg_pnl_pct": 0.0,
            "max_drawdown_pct": 0.0,
        }

    pnls = [t["pnl_total_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss == 0:
        pf = float("inf") if gross_win > 0 else 0.0
    else:
        pf = gross_win / gross_loss

    total = sum(pnls)

    # Max drawdown on cumulative equity
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        "n_trades": n,
        "win_rate": len(wins) / n * 100.0,
        "profit_factor": pf,
        "total_pnl_pct": total,
        "avg_pnl_pct": total / n,
        "max_drawdown_pct": max_dd,
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_metrics.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/metrics.py tests/test_pair_metrics.py
git commit -m "feat(pair): metrics aggregator (PF, WR, DD, total PnL)"
```

---

## Task 11: Baselines — buy-and-hold

**Files:**
- Create: `pair_trading/baselines.py`
- Create: `tests/test_pair_baselines.py`

- [ ] **Step 1: Write failing tests for buy-and-hold**

Create `tests/test_pair_baselines.py`:

```python
"""Tests for baselines (buy-and-hold, random trader)."""
import numpy as np
import pytest

from pair_trading.baselines import buy_and_hold_pf, random_trader_pf_distribution


def test_buy_and_hold_up_market():
    # Price doubles — buy-and-hold is very positive, PF is infinite (no losing trade)
    prices = np.array([100.0, 110.0, 120.0, 150.0, 200.0])
    pf = buy_and_hold_pf(prices)
    assert pf == float("inf")


def test_buy_and_hold_down_market():
    prices = np.array([100.0, 90.0, 80.0])
    pf = buy_and_hold_pf(prices)
    assert pf == 0.0


def test_buy_and_hold_flat_market():
    prices = np.array([100.0, 100.0, 100.0])
    pf = buy_and_hold_pf(prices)
    assert pf == 0.0
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_pair_baselines.py -v`

- [ ] **Step 3: Implement buy_and_hold_pf**

Create `pair_trading/baselines.py`:

```python
"""Baseline strategies for comparison with pair trading edge."""
from __future__ import annotations

import numpy as np


def buy_and_hold_pf(prices: np.ndarray) -> float:
    """Profit factor of a buy-and-hold position over the full price series.

    Interpreted as one single trade: entry at prices[0], exit at prices[-1].
    PF = gross_win / gross_loss (pair of infinite or zero edge cases).
    """
    prices = np.asarray(prices, dtype=np.float64)
    if len(prices) < 2:
        return 0.0
    total_return = (prices[-1] - prices[0]) / prices[0]
    if total_return > 0:
        return float("inf")
    return 0.0
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_baselines.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/baselines.py tests/test_pair_baselines.py
git commit -m "feat(pair): buy-and-hold baseline"
```

---

## Task 12: Baselines — random trader (reproducible with seed)

**Files:**
- Modify: `pair_trading/baselines.py`
- Modify: `tests/test_pair_baselines.py`

- [ ] **Step 1: Add failing tests for random trader**

Append to `tests/test_pair_baselines.py`:

```python
def test_random_trader_reproducible():
    prices = np.array([100.0 + i * 0.1 for i in range(300)])
    dist_a = random_trader_pf_distribution(
        prices, n_trades=10, avg_hold=5, n_runs=20, seed=42,
    )
    dist_b = random_trader_pf_distribution(
        prices, n_trades=10, avg_hold=5, n_runs=20, seed=42,
    )
    assert dist_a == dist_b


def test_random_trader_different_seed_differs():
    prices = np.array([100.0 + i * 0.1 for i in range(300)])
    dist_a = random_trader_pf_distribution(
        prices, n_trades=10, avg_hold=5, n_runs=20, seed=1,
    )
    dist_b = random_trader_pf_distribution(
        prices, n_trades=10, avg_hold=5, n_runs=20, seed=2,
    )
    assert dist_a != dist_b


def test_random_trader_percentiles_available():
    prices = np.array([100.0 + i * 0.1 for i in range(300)])
    dist = random_trader_pf_distribution(
        prices, n_trades=10, avg_hold=5, n_runs=100, seed=42,
    )
    p95 = np.percentile(dist, 95)
    p50 = np.percentile(dist, 50)
    assert p95 >= p50
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_pair_baselines.py -v`

- [ ] **Step 3: Implement random_trader_pf_distribution**

Append to `pair_trading/baselines.py`:

```python
def random_trader_pf_distribution(
    prices: np.ndarray,
    n_trades: int,
    avg_hold: int,
    n_runs: int = 100,
    seed: int = 42,
) -> list:
    """Simulate a random trader N runs and return list of PFs.

    Each run executes n_trades with random entry timestamps, random direction
    (long/short), and fixed holding period of avg_hold candles. Fees not applied
    (gross baseline).
    """
    prices = np.asarray(prices, dtype=np.float64)
    n = len(prices)
    if n < avg_hold + 1 or n_trades <= 0:
        return [0.0] * n_runs

    rng = np.random.default_rng(seed)
    pfs = []
    for _ in range(n_runs):
        pnls = []
        for _ in range(n_trades):
            # Random entry index in [0, n - avg_hold - 1]
            entry_idx = int(rng.integers(0, n - avg_hold))
            exit_idx = entry_idx + avg_hold
            direction = 1 if rng.random() < 0.5 else -1
            ret = (prices[exit_idx] - prices[entry_idx]) / prices[entry_idx] * direction * 100.0
            pnls.append(ret)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gw = sum(wins)
        gl = abs(sum(losses))
        if gl == 0:
            pf = float("inf") if gw > 0 else 0.0
        else:
            pf = gw / gl
        pfs.append(pf)
    return pfs
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_baselines.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/baselines.py tests/test_pair_baselines.py
git commit -m "feat(pair): random trader baseline with seed reproducibility"
```

---

## Task 13: CLI — run_pair_backtest.py

**Files:**
- Create: `scripts/run_pair_backtest.py`

- [ ] **Step 1: Create CLI script**

Create `scripts/run_pair_backtest.py`:

```python
#!/usr/bin/env python
"""CLI: run pair trading backtest over a date range and persist to SQLite.

Usage:
    python scripts/run_pair_backtest.py \
        --start 2026-01-15 --end 2026-04-15 \
        --db research/pair_v1_90d.db

Fetches BTC/ETH 15m candles via Binance REST, runs backtest, writes results.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Ensure repo root on path so `pair_trading` imports work when run from scripts/
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from pair_trading.config import PairConfig
from pair_trading.historical_data import fetch_synced_pair
from pair_trading.metrics import compute_metrics
from pair_trading.research_db import fetch_all_trades, init_db
from pair_trading.research_runner import run_backtest


def _parse_date(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--db", required=True, help="Output SQLite path")
    parser.add_argument("--execution-shift", type=int, default=1,
                        help="1=correct (default). 0=diagnostic (look-ahead leak)")
    parser.add_argument("--slippage", type=float, default=0.0,
                        help="Slippage per leg per side, in percent (e.g. 0.05 = 0.05%%).")
    args = parser.parse_args()

    start_ms = _parse_date(args.start)
    end_ms = _parse_date(args.end)

    # 15m candle = 900000 ms. Add warmup margin (192 candles = 48h).
    total_ms = end_ms - start_ms
    n_15m = total_ms // 900_000
    warmup_margin = 192
    fetch_limit = int(n_15m) + warmup_margin

    print(f"Fetching {fetch_limit} candles for BTCUSDT + ETHUSDT 15m ending {args.end}...")
    btc_close, eth_close, close_times = fetch_synced_pair(
        "BTCUSDT", "ETHUSDT", "15m", fetch_limit, end_time_ms=end_ms,
    )
    print(f"Got {len(btc_close)} aligned candles from "
          f"{datetime.fromtimestamp(close_times[0]/1000, tz=timezone.utc).isoformat()} "
          f"to {datetime.fromtimestamp(close_times[-1]/1000, tz=timezone.utc).isoformat()}")

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    init_db(args.db)
    from dataclasses import replace
    cfg = replace(PairConfig(), slippage_pct=args.slippage)

    summary = run_backtest(
        db_path=args.db,
        config=cfg,
        btc_close=btc_close,
        eth_close=eth_close,
        close_times_ms=close_times,
        execution_shift=args.execution_shift,
    )
    print(f"Backtest done: {summary}")

    trades = fetch_all_trades(args.db)
    metrics = compute_metrics(trades)
    print(f"\n=== Metrics (execution_shift={args.execution_shift}) ===")
    for k, v in metrics.items():
        print(f"  {k:20s} = {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke test (short range, just to confirm it runs)**

Run:
```bash
mkdir -p research
python scripts/run_pair_backtest.py \
    --start 2026-04-10 --end 2026-04-14 \
    --db research/pair_smoke.db
```
Expected: prints candle count, summary dict, metrics dict. No traceback.

- [ ] **Step 3: Commit**

```bash
git add scripts/run_pair_backtest.py
git commit -m "feat(pair): CLI script run_pair_backtest.py"
```

---

## Task 14: Robustness test 1 — monthly consistency

**Files:**
- Create: `pair_trading/robustness_check.py`
- Create: `tests/test_pair_robustness.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pair_robustness.py`:

```python
"""Tests for robustness checks."""
import numpy as np
import pytest

from pair_trading.robustness_check import monthly_consistency


def _mock_trades_with_month(month_pfs):
    """Build 3 synthetic sets of trades whose PF matches the given per-month values."""
    all_trades = []
    base_ts = 1700000000  # seconds
    month_sec = 30 * 24 * 3600
    for month_idx, pf in enumerate(month_pfs):
        # Build 10 trades in this month: 5 wins, 5 losses, adjust magnitudes for target PF
        if pf >= 1.0:
            win_sz = pf
            loss_sz = 1.0
        else:
            win_sz = 1.0
            loss_sz = 1.0 / max(pf, 1e-6) if pf > 0 else 10.0
        ts = base_ts + month_idx * month_sec
        for i in range(5):
            all_trades.append({
                "entry_time": f"2026-0{month_idx+1}-01T00:00:{i:02d}Z",
                "pnl_total_pct": win_sz,
            })
        for i in range(5):
            all_trades.append({
                "entry_time": f"2026-0{month_idx+1}-01T00:01:{i:02d}Z",
                "pnl_total_pct": -loss_sz,
            })
    return all_trades


def test_monthly_consistency_all_positive():
    trades = _mock_trades_with_month([1.5, 1.3, 1.1])
    result = monthly_consistency(trades, n_months=3)
    assert result["n_months"] == 3
    assert result["n_positive_pf"] == 3
    assert result["passes"] is True


def test_monthly_consistency_2_of_3():
    trades = _mock_trades_with_month([1.5, 0.5, 1.2])
    result = monthly_consistency(trades, n_months=3)
    assert result["n_positive_pf"] == 2
    assert result["passes"] is True  # 2 of 3 is the threshold


def test_monthly_consistency_1_of_3_fails():
    trades = _mock_trades_with_month([1.5, 0.3, 0.5])
    result = monthly_consistency(trades, n_months=3)
    assert result["n_positive_pf"] == 1
    assert result["passes"] is False
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_pair_robustness.py -v`

- [ ] **Step 3: Implement monthly_consistency**

Create `pair_trading/robustness_check.py`:

```python
"""Robustness checks for pair trading backtest — 4 tests per spec.

Each check returns a dict with `passes: bool` and detail metrics.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List

import numpy as np


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _pf(pnls: list) -> float:
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gw = sum(wins)
    gl = abs(sum(losses))
    if gl == 0:
        return float("inf") if gw > 0 else 0.0
    return gw / gl


def monthly_consistency(
    trades: List[Dict],
    n_months: int = 3,
    pf_threshold: float = 1.0,
) -> Dict:
    """TEST 1: PF >= pf_threshold in at least (n_months - 1) of n_months.

    Splits trades chronologically into n_months equal buckets.
    """
    if not trades:
        return {
            "n_months": n_months, "month_pfs": [],
            "n_positive_pf": 0, "passes": False,
        }

    sorted_trades = sorted(trades, key=lambda t: _parse_ts(t["entry_time"]))
    bucket_size = len(sorted_trades) // n_months
    if bucket_size == 0:
        return {
            "n_months": n_months, "month_pfs": [],
            "n_positive_pf": 0, "passes": False,
            "note": "too few trades to split into months",
        }

    month_pfs = []
    for i in range(n_months):
        start = i * bucket_size
        end = start + bucket_size if i < n_months - 1 else len(sorted_trades)
        bucket = sorted_trades[start:end]
        pnls = [t["pnl_total_pct"] for t in bucket]
        month_pfs.append(_pf(pnls))

    n_positive = sum(1 for pf in month_pfs if pf >= pf_threshold)
    passes = n_positive >= (n_months - 1)

    return {
        "n_months": n_months,
        "month_pfs": month_pfs,
        "n_positive_pf": n_positive,
        "pf_threshold": pf_threshold,
        "passes": passes,
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_robustness.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/robustness_check.py tests/test_pair_robustness.py
git commit -m "feat(pair): robustness test 1 - monthly consistency"
```

---

## Task 15: Robustness test 2 — holdout OOS

**Files:**
- Modify: `pair_trading/robustness_check.py`
- Modify: `tests/test_pair_robustness.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_pair_robustness.py`:

```python
def test_holdout_oos_pass():
    # Holdout PF = 0.9 passes (>= 0.8)
    holdout_trades = _mock_trades_with_month([0.9])[:10]
    result = holdout_oos(holdout_trades, pf_threshold=0.8)
    assert result["pf"] >= 0.8
    assert result["passes"] is True


def test_holdout_oos_fail():
    holdout_trades = _mock_trades_with_month([0.5])[:10]
    result = holdout_oos(holdout_trades, pf_threshold=0.8)
    assert result["passes"] is False
```

Add import to top: `from pair_trading.robustness_check import holdout_oos`.

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_pair_robustness.py -v`
Expected: new tests fail with ImportError.

- [ ] **Step 3: Implement holdout_oos**

Append to `pair_trading/robustness_check.py`:

```python
def holdout_oos(
    holdout_trades: List[Dict],
    pf_threshold: float = 0.8,
) -> Dict:
    """TEST 2: PF over a pre-window (out-of-sample) period must be >= threshold.

    Typically run on 30 days preceding the main backtest window.
    """
    if not holdout_trades:
        return {
            "pf": 0.0, "n_trades": 0, "pf_threshold": pf_threshold,
            "passes": False, "note": "no trades in holdout",
        }
    pnls = [t["pnl_total_pct"] for t in holdout_trades]
    pf = _pf(pnls)
    return {
        "pf": pf,
        "n_trades": len(holdout_trades),
        "pf_threshold": pf_threshold,
        "passes": pf >= pf_threshold,
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_robustness.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/robustness_check.py tests/test_pair_robustness.py
git commit -m "feat(pair): robustness test 2 - holdout OOS"
```

---

## Task 16: Robustness test 3 — regime breakdown

**Files:**
- Modify: `pair_trading/robustness_check.py`
- Modify: `tests/test_pair_robustness.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_pair_robustness.py`:

```python
def test_regime_breakdown_no_collapse():
    trades = [
        {"btc_regime_entry": "TRENDING", "pnl_total_pct": 2.0} for _ in range(20)
    ] + [
        {"btc_regime_entry": "TRENDING", "pnl_total_pct": -1.0} for _ in range(10)
    ] + [
        {"btc_regime_entry": "WEAK_TREND", "pnl_total_pct": 3.0} for _ in range(15)
    ] + [
        {"btc_regime_entry": "WEAK_TREND", "pnl_total_pct": -1.0} for _ in range(5)
    ]
    result = regime_breakdown(trades, min_trades_per_regime=20, pf_floor=0.5)
    assert result["passes"] is True
    assert "TRENDING" in result["regime_stats"]


def test_regime_breakdown_collapse_fails():
    trades = (
        [{"btc_regime_entry": "TRENDING", "pnl_total_pct": 1.0} for _ in range(5)]
        + [{"btc_regime_entry": "TRENDING", "pnl_total_pct": -5.0} for _ in range(20)]
    )
    result = regime_breakdown(trades, min_trades_per_regime=20, pf_floor=0.5)
    assert result["passes"] is False
    assert result["regime_stats"]["TRENDING"]["pf"] < 0.5
```

Add to top: `from pair_trading.robustness_check import regime_breakdown`.

- [ ] **Step 2: Run to fail**

Run: `python -m pytest tests/test_pair_robustness.py -v`

- [ ] **Step 3: Implement regime_breakdown**

Append to `pair_trading/robustness_check.py`:

```python
def regime_breakdown(
    trades: List[Dict],
    min_trades_per_regime: int = 20,
    pf_floor: float = 0.5,
) -> Dict:
    """TEST 3: No regime with PF < pf_floor in n >= min_trades_per_regime.

    Groups by btc_regime_entry field.
    """
    by_regime: Dict[str, list] = {}
    for t in trades:
        r = t.get("btc_regime_entry", "UNKNOWN") or "UNKNOWN"
        by_regime.setdefault(r, []).append(t["pnl_total_pct"])

    regime_stats = {}
    fails = []
    for regime, pnls in by_regime.items():
        pf = _pf(pnls)
        n = len(pnls)
        regime_stats[regime] = {"n": n, "pf": pf}
        if n >= min_trades_per_regime and pf < pf_floor:
            fails.append(regime)

    return {
        "regime_stats": regime_stats,
        "min_trades_per_regime": min_trades_per_regime,
        "pf_floor": pf_floor,
        "failing_regimes": fails,
        "passes": len(fails) == 0,
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_robustness.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/robustness_check.py tests/test_pair_robustness.py
git commit -m "feat(pair): robustness test 3 - regime breakdown"
```

---

## Task 17: Robustness test 4 — correlation bucket (pair-specific)

**Files:**
- Modify: `pair_trading/robustness_check.py`
- Modify: `tests/test_pair_robustness.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_pair_robustness.py`:

```python
def test_correlation_bucket_edge_in_high_corr():
    """Edge concentrated in high-correlation bucket = expected, OK."""
    trades = (
        [{"correlation": 0.8, "pnl_total_pct": 2.0} for _ in range(20)]
        + [{"correlation": 0.4, "pnl_total_pct": -1.0} for _ in range(20)]
    )
    result = correlation_bucket_analysis(trades)
    # Report only — always passes (diagnostic)
    assert result["passes"] is True
    assert "high" in result["bucket_stats"]
    assert result["bucket_stats"]["high"]["pf"] > result["bucket_stats"]["low"]["pf"]


def test_correlation_bucket_edge_in_low_corr_warns():
    trades = (
        [{"correlation": 0.3, "pnl_total_pct": 2.0} for _ in range(20)]
        + [{"correlation": 0.8, "pnl_total_pct": -1.0} for _ in range(20)]
    )
    result = correlation_bucket_analysis(trades)
    assert result["passes"] is True  # diagnostic only — does not block
    assert result["warning"] is not None
    assert "low" in result["warning"].lower()
```

Add to top: `from pair_trading.robustness_check import correlation_bucket_analysis`.

- [ ] **Step 2: Run to fail**

Run: `python -m pytest tests/test_pair_robustness.py -v`

- [ ] **Step 3: Implement correlation_bucket_analysis**

Append to `pair_trading/robustness_check.py`:

```python
def correlation_bucket_analysis(trades: List[Dict]) -> Dict:
    """TEST 4: Bucket trades by correlation at entry and report PF per bucket.

    Diagnostic: always returns passes=True, but emits a warning if edge
    concentrates in the LOW correlation bucket (suspect).
    """
    buckets = {"low": [], "med": [], "high": []}  # 0.3-0.5, 0.5-0.7, 0.7+
    for t in trades:
        c = float(t.get("correlation") or 0.0)
        pnl = t["pnl_total_pct"]
        if c < 0.5:
            buckets["low"].append(pnl)
        elif c < 0.7:
            buckets["med"].append(pnl)
        else:
            buckets["high"].append(pnl)

    stats = {name: {"n": len(pnls), "pf": _pf(pnls)} for name, pnls in buckets.items()}
    # Warn if edge concentrates in low correlation
    pf_low = stats["low"]["pf"] if stats["low"]["n"] >= 5 else 0.0
    pf_high = stats["high"]["pf"] if stats["high"]["n"] >= 5 else 0.0
    warning = None
    if pf_low > pf_high and pf_low > 1.0:
        warning = (
            "Edge concentra em bucket 'low' de baixa correlação — suspeito "
            "(pair trading assume co-movimento). Investigar."
        )

    return {
        "bucket_stats": stats,
        "warning": warning,
        "passes": True,  # always diagnostic
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_robustness.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add pair_trading/robustness_check.py tests/test_pair_robustness.py
git commit -m "feat(pair): robustness test 4 - correlation bucket analysis (pair-specific)"
```

---

## Task 18: CLI — run_pair_robustness.py

**Files:**
- Create: `scripts/run_pair_robustness.py`

- [ ] **Step 1: Create CLI**

Create `scripts/run_pair_robustness.py`:

```python
#!/usr/bin/env python
"""CLI: read a completed backtest DB and run all 4 robustness tests.

Usage:
    python scripts/run_pair_robustness.py \
        --main-db research/pair_v1_90d.db \
        --holdout-db research/pair_v1_holdout.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from pair_trading.research_db import fetch_all_trades
from pair_trading.robustness_check import (
    correlation_bucket_analysis,
    holdout_oos,
    monthly_consistency,
    regime_breakdown,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--main-db", required=True, help="Main 90d backtest DB")
    p.add_argument("--holdout-db", required=True, help="Holdout 30d DB")
    p.add_argument("--out", default="-", help="Output JSON path or - for stdout")
    args = p.parse_args()

    main_trades = fetch_all_trades(args.main_db)
    holdout_trades = fetch_all_trades(args.holdout_db)

    results = {
        "main_db": args.main_db,
        "holdout_db": args.holdout_db,
        "n_main_trades": len(main_trades),
        "n_holdout_trades": len(holdout_trades),
        "test_1_monthly_consistency": monthly_consistency(main_trades, n_months=3),
        "test_2_holdout_oos": holdout_oos(holdout_trades, pf_threshold=0.8),
        "test_3_regime_breakdown": regime_breakdown(main_trades, min_trades_per_regime=20, pf_floor=0.5),
        "test_4_correlation_bucket": correlation_bucket_analysis(main_trades),
    }
    results["all_pass"] = all(
        results[k]["passes"]
        for k in ("test_1_monthly_consistency", "test_2_holdout_oos",
                  "test_3_regime_breakdown", "test_4_correlation_bucket")
    )

    out = json.dumps(results, indent=2, default=str)
    if args.out == "-":
        print(out)
    else:
        Path(args.out).write_text(out)
        print(f"Results written to {args.out}")
        print(f"All pass: {results['all_pass']}")
    return 0 if results["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke test syntax**

Run: `python scripts/run_pair_robustness.py --help`
Expected: argparse help output.

- [ ] **Step 3: Commit**

```bash
git add scripts/run_pair_robustness.py
git commit -m "feat(pair): CLI script run_pair_robustness.py aggregating all 4 tests"
```

---

## Task 19: GO/NO-GO evaluator (BACKTEST → ROBUSTNESS gate)

**Files:**
- Create: `pair_trading/go_no_go.py`
- Create: `tests/test_pair_go_no_go.py`
- Create: `scripts/evaluate_pair_go_no_go.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pair_go_no_go.py`:

```python
"""Tests for go_no_go evaluator."""
import pytest

from pair_trading.go_no_go import evaluate_backtest_to_robustness


def _metrics(pf, wr, n, dd):
    return {
        "profit_factor": pf, "win_rate": wr,
        "n_trades": n, "max_drawdown_pct": dd,
    }


def test_pass_all_criteria():
    res = evaluate_backtest_to_robustness(
        metrics=_metrics(1.3, 50.0, 80, 10.0),
        buy_hold_btc_pf=1.1,
        buy_hold_eth_pf=1.0,
        random_trader_p95_pf=1.15,
        slippage_sensitivity_pf_at_005=1.22,
        slippage_sensitivity_pf_at_010=1.18,
    )
    assert res["passes"] is True


def test_fail_pf_below_threshold():
    res = evaluate_backtest_to_robustness(
        metrics=_metrics(1.1, 50.0, 80, 10.0),
        buy_hold_btc_pf=1.0, buy_hold_eth_pf=0.9,
        random_trader_p95_pf=1.0,
        slippage_sensitivity_pf_at_005=1.05,
        slippage_sensitivity_pf_at_010=1.0,
    )
    assert res["passes"] is False
    assert "pf_main" in res["failures"]


def test_fail_dd_too_high():
    res = evaluate_backtest_to_robustness(
        metrics=_metrics(1.3, 50.0, 80, 20.0),
        buy_hold_btc_pf=1.0, buy_hold_eth_pf=0.9,
        random_trader_p95_pf=1.1,
        slippage_sensitivity_pf_at_005=1.22,
        slippage_sensitivity_pf_at_010=1.18,
    )
    assert res["passes"] is False
    assert "max_drawdown" in res["failures"]


def test_fail_not_beating_random():
    res = evaluate_backtest_to_robustness(
        metrics=_metrics(1.3, 50.0, 80, 10.0),
        buy_hold_btc_pf=1.0, buy_hold_eth_pf=0.9,
        random_trader_p95_pf=1.4,  # random beats our 1.3
        slippage_sensitivity_pf_at_005=1.22,
        slippage_sensitivity_pf_at_010=1.18,
    )
    assert res["passes"] is False
    assert "random_baseline" in res["failures"]


def test_fail_collapse_at_010_slippage():
    res = evaluate_backtest_to_robustness(
        metrics=_metrics(1.3, 50.0, 80, 10.0),
        buy_hold_btc_pf=1.0, buy_hold_eth_pf=0.9,
        random_trader_p95_pf=1.15,
        slippage_sensitivity_pf_at_005=1.1,
        slippage_sensitivity_pf_at_010=0.95,  # collapses
    )
    assert res["passes"] is False
    assert "slippage_sensitivity" in res["failures"]
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_pair_go_no_go.py -v`

- [ ] **Step 3: Implement go_no_go**

Create `pair_trading/go_no_go.py`:

```python
"""GO/NO-GO gate evaluator for BACKTEST → ROBUSTNESS transition.

Criteria from spec §9:
  - PF >= 1.2
  - WR >= 45%
  - n_trades >= 60 in 90d
  - max DD <= 15%
  - beats buy-and-hold BTC, buy-and-hold ETH, random trader p95 PF
  - does not collapse at +0.10% slippage (PF must remain >= 1.0)
"""
from __future__ import annotations

from typing import Dict


def evaluate_backtest_to_robustness(
    *,
    metrics: Dict[str, float],
    buy_hold_btc_pf: float,
    buy_hold_eth_pf: float,
    random_trader_p95_pf: float,
    slippage_sensitivity_pf_at_005: float,
    slippage_sensitivity_pf_at_010: float,
    pf_threshold: float = 1.2,
    wr_threshold: float = 45.0,
    min_trades: int = 60,
    max_dd_threshold: float = 15.0,
    slippage_min_pf: float = 1.0,
) -> Dict:
    failures = []

    pf = metrics["profit_factor"]
    wr = metrics["win_rate"]
    n = metrics["n_trades"]
    dd = metrics["max_drawdown_pct"]

    if pf < pf_threshold:
        failures.append("pf_main")
    if wr < wr_threshold:
        failures.append("win_rate")
    if n < min_trades:
        failures.append("n_trades")
    if dd > max_dd_threshold:
        failures.append("max_drawdown")

    # Must beat ALL 3 baselines
    if not (pf > buy_hold_btc_pf and pf > buy_hold_eth_pf):
        failures.append("buy_and_hold_baseline")
    if not (pf > random_trader_p95_pf):
        failures.append("random_baseline")

    # Slippage sensitivity: must not collapse at +0.10%
    if slippage_sensitivity_pf_at_010 < slippage_min_pf:
        failures.append("slippage_sensitivity")

    return {
        "passes": len(failures) == 0,
        "failures": failures,
        "criteria_applied": {
            "pf_threshold": pf_threshold,
            "wr_threshold": wr_threshold,
            "min_trades": min_trades,
            "max_dd_threshold": max_dd_threshold,
            "slippage_min_pf": slippage_min_pf,
        },
        "observed": {
            "pf": pf, "wr": wr, "n_trades": n, "dd": dd,
            "buy_hold_btc_pf": buy_hold_btc_pf,
            "buy_hold_eth_pf": buy_hold_eth_pf,
            "random_trader_p95_pf": random_trader_p95_pf,
            "slippage_pf_005": slippage_sensitivity_pf_at_005,
            "slippage_pf_010": slippage_sensitivity_pf_at_010,
        },
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pair_go_no_go.py -v`
Expected: 5 passed.

- [ ] **Step 5: Create CLI**

Create `scripts/evaluate_pair_go_no_go.py`:

```python
#!/usr/bin/env python
"""Evaluate BACKTEST → ROBUSTNESS gate from a backtest DB.

Usage:
    python scripts/evaluate_pair_go_no_go.py \
        --main-db research/pair_v1_90d.db \
        --slippage-005-db research/pair_v1_90d_slip005.db \
        --slippage-010-db research/pair_v1_90d_slip010.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from pair_trading.baselines import buy_and_hold_pf, random_trader_pf_distribution
from pair_trading.go_no_go import evaluate_backtest_to_robustness
from pair_trading.historical_data import fetch_synced_pair
from pair_trading.metrics import compute_metrics
from pair_trading.research_db import fetch_all_trades


def _pf_from_db(db_path: str) -> float:
    trades = fetch_all_trades(db_path)
    return compute_metrics(trades)["profit_factor"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--main-db", required=True)
    p.add_argument("--slippage-005-db", required=True)
    p.add_argument("--slippage-010-db", required=True)
    p.add_argument("--start", required=True, help="YYYY-MM-DD of backtest start")
    p.add_argument("--end", required=True, help="YYYY-MM-DD of backtest end")
    args = p.parse_args()

    main_trades = fetch_all_trades(args.main_db)
    metrics = compute_metrics(main_trades)

    # Fetch prices for baselines
    from datetime import datetime, timezone
    end_ms = int(datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc).timestamp() * 1000)
    total_ms = end_ms - int(datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc).timestamp() * 1000)
    limit = int(total_ms // 900_000) + 10
    btc, eth, _ = fetch_synced_pair("BTCUSDT", "ETHUSDT", "15m", limit, end_time_ms=end_ms)

    btc_pf = buy_and_hold_pf(btc)
    eth_pf = buy_and_hold_pf(eth)

    # Random trader baseline — match N trades and average hold of actual pair
    n_trades = metrics["n_trades"] or 1
    avg_hold_candles = 48  # assumption ≈ 12h avg hold; could be computed from trades
    pf_dist = random_trader_pf_distribution(
        btc, n_trades=n_trades, avg_hold=avg_hold_candles,
        n_runs=100, seed=42,
    )
    p95 = float(np.percentile(pf_dist, 95))

    pf_005 = _pf_from_db(args.slippage_005_db)
    pf_010 = _pf_from_db(args.slippage_010_db)

    result = evaluate_backtest_to_robustness(
        metrics=metrics,
        buy_hold_btc_pf=btc_pf,
        buy_hold_eth_pf=eth_pf,
        random_trader_p95_pf=p95,
        slippage_sensitivity_pf_at_005=pf_005,
        slippage_sensitivity_pf_at_010=pf_010,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["passes"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Commit**

```bash
git add pair_trading/go_no_go.py tests/test_pair_go_no_go.py scripts/evaluate_pair_go_no_go.py
git commit -m "feat(pair): BACKTEST → ROBUSTNESS gate evaluator + CLI"
```

---

## Task 20: End-to-end smoke test + final commit

**Files:**
- Create: `tests/test_pair_smoke_integration.py`

- [ ] **Step 1: Write end-to-end test with offline synthetic data**

Create `tests/test_pair_smoke_integration.py`:

```python
"""End-to-end smoke test: synthetic data → backtest → metrics → robustness.

No network required. Confirms the full pipeline wires up correctly.
"""
import os
import tempfile

import numpy as np
import pytest

from pair_trading.config import PairConfig
from pair_trading.metrics import compute_metrics
from pair_trading.research_db import fetch_all_trades, init_db
from pair_trading.research_runner import run_backtest
from pair_trading.robustness_check import (
    correlation_bucket_analysis,
    monthly_consistency,
    regime_breakdown,
)


def _synthetic_pair(n=2000, seed=42):
    """Generate BTC/ETH with co-movement + noise."""
    rng = np.random.default_rng(seed)
    common = rng.normal(0, 0.008, n)
    btc_spec = rng.normal(0, 0.004, n)
    eth_spec = rng.normal(0, 0.004, n)
    btc = 50000.0 * np.exp(np.cumsum(common + btc_spec))
    eth = 3000.0 * np.exp(np.cumsum(common + eth_spec))
    times = np.arange(n, dtype=np.int64) * 900_000
    return btc, eth, times


def test_full_pipeline_produces_valid_output():
    btc, eth, times = _synthetic_pair(2000)

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        init_db(tmp.name)
        cfg = PairConfig()
        summary = run_backtest(
            db_path=tmp.name, config=cfg,
            btc_close=btc, eth_close=eth, close_times_ms=times,
            regime_fn=lambda idx: "TRENDING" if idx % 3 == 0 else "WEAK_TREND",
        )

        trades = fetch_all_trades(tmp.name)
        metrics = compute_metrics(trades)
        assert metrics["n_trades"] == summary["trades_closed"]

        if metrics["n_trades"] >= 3:
            mc = monthly_consistency(trades, n_months=3)
            assert "n_positive_pf" in mc

        rb = regime_breakdown(trades, min_trades_per_regime=5, pf_floor=0.5)
        assert "regime_stats" in rb

        cb = correlation_bucket_analysis(trades)
        assert "bucket_stats" in cb
    finally:
        os.unlink(tmp.name)
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v -k pair`
Expected: all pair_* tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pair_smoke_integration.py
git commit -m "test(pair): end-to-end smoke integration test for Phase 1 pipeline"
```

---

## Task 21: Update EXPERIMENT_REGISTRY with EXP-004 HYPOTHESIS entry

**Files:**
- Modify: `docs/EXPERIMENT_REGISTRY.md`

- [ ] **Step 1: Add EXP-004 entry to registry**

Read current `docs/EXPERIMENT_REGISTRY.md` and append a new section after EXP-003:

```markdown
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
```

Update the "Indice Rapido" table at the bottom:

```markdown
| EXP-004 | Pair BTC/ETH v1.0 | Cross-asset stat arb | HYPOTHESIS → BACKTEST | — | Aguardando primeiro backtest |
```

- [ ] **Step 2: Commit**

```bash
git add docs/EXPERIMENT_REGISTRY.md
git commit -m "docs(registry): add EXP-004 Pair Trading BTC/ETH entry"
```

---

## Task 22: Run full backtest + robustness + GO/NO-GO decision

**This task is operational, not code. Execute after all prior tasks pass.**

- [ ] **Step 1: Run main 90d backtest**

```bash
mkdir -p research
python scripts/run_pair_backtest.py \
    --start 2026-01-15 --end 2026-04-15 \
    --db research/pair_v1_90d.db
```
Record output: n_trades, PF, WR, PnL, DD.

- [ ] **Step 2: Run holdout 30d backtest (preceding window)**

```bash
python scripts/run_pair_backtest.py \
    --start 2025-12-16 --end 2026-01-15 \
    --db research/pair_v1_holdout.db
```

- [ ] **Step 3: Run slippage sensitivity backtests**

Uses the `--slippage` flag added in Task 13.

```bash
python scripts/run_pair_backtest.py \
    --start 2026-01-15 --end 2026-04-15 \
    --db research/pair_v1_90d_slip005.db \
    --slippage 0.05
python scripts/run_pair_backtest.py \
    --start 2026-01-15 --end 2026-04-15 \
    --db research/pair_v1_90d_slip010.db \
    --slippage 0.10
```

- [ ] **Step 4: Run look-ahead diagnostic**

```bash
python scripts/run_pair_backtest.py \
    --start 2026-01-15 --end 2026-04-15 \
    --db research/pair_v1_90d_shift0.db \
    --execution-shift 0
```
Compare total PnL with shift=1 run. Gap > 20% → investigate spread_calculator for data leak.

- [ ] **Step 5: Run robustness suite**

```bash
python scripts/run_pair_robustness.py \
    --main-db research/pair_v1_90d.db \
    --holdout-db research/pair_v1_holdout.db \
    --out research/pair_v1_robustness.json
cat research/pair_v1_robustness.json
```

- [ ] **Step 6: Evaluate GO/NO-GO**

```bash
python scripts/evaluate_pair_go_no_go.py \
    --main-db research/pair_v1_90d.db \
    --slippage-005-db research/pair_v1_90d_slip005.db \
    --slippage-010-db research/pair_v1_90d_slip010.db \
    --start 2026-01-15 --end 2026-04-15
```

- [ ] **Step 7: Update EXPERIMENT_REGISTRY with result**

If **PASS**: update EXP-004 estagio from "HYPOTHESIS → BACKTEST" to "BACKTEST → ROBUSTNESS PASS". Proceed to write Phase 2 plan for PAPER.

If **FAIL**: update estagio to "DEAD (no BACKTEST)", add postmortem section with failing criteria + observed metrics. Write postmortem note in `~/obsidian-vault/context/decisoes/2026-MM-DD-h1-pair-trading-dead.md`. Move to planning H2 (Liquidation reaction) per spec ordering.

- [ ] **Step 8: Commit all research artifacts (DBs NOT included — they are transient)**

```bash
git add docs/EXPERIMENT_REGISTRY.md research/pair_v1_robustness.json
git commit -m "research(pair): EXP-004 Phase 1 BACKTEST results — [PASS/FAIL]"
```

---

## Self-review notes (for writer)

**Coverage vs spec:**
- ✅ Config (§4) → Task 2
- ✅ Spread calculator (§5) → Task 3
- ✅ Pair trader entry (§6) → Task 5
- ✅ Pair trader exit (§6) → Task 6
- ✅ Historical data (§6) → Task 7
- ✅ Research DB (§6) → Task 8
- ✅ Research runner with look-ahead (§9) → Task 9
- ✅ Metrics → Task 10
- ✅ Baselines (§9) → Tasks 11, 12
- ✅ Backtest CLI → Task 13
- ✅ Robustness 4 tests (§9) → Tasks 14-17
- ✅ Robustness CLI → Task 18
- ✅ GO/NO-GO (§9) → Task 19
- ✅ Smoke test → Task 20
- ✅ Registry update (§9) → Task 21
- ✅ Operational run → Task 22

**Deferred to Phase 2** (not in this plan): paper_executor, state file, main.py integration, Telegram, daily report, circuit breaker in live, proactive alerts extension, dashboard integration. These are explicitly listed as "Non-goals" in the plan header.

**Known limitation — regime labels default to "UNKNOWN":**
`research_runner.run_backtest` has `regime_fn = lambda idx: "UNKNOWN"` as default. In Task 13 the CLI does not wire up a real regime classifier. Consequence: robustness TEST 3 (regime breakdown) will run against a single "UNKNOWN" bucket, making it nearly redundant with the overall PF check. This does NOT block Phase 1 completion — the other 3 robustness tests plus overall metrics carry the GO/NO-GO decision. If the executor wants real regime breakdown:

- Option A (minimal): add a helper `pair_trading/regime_helper.py` that fetches BTC 1h candles once, computes regime label per 1h candle via `htf.classify_htf_trend`, and builds a `regime_fn(idx_15m) -> str` mapping by matching the 15m candle's close time to the enclosing 1h bucket. Wire into Task 13's CLI. ~30 lines.
- Option B (defer): keep as "UNKNOWN" in Phase 1; revisit if Phase 1 passes and regime sensitivity matters for Phase 2.

Recommended: **Option B**. If H1 PF is borderline, regime diagnostics matter; if H1 PF is comfortably PASS or FAIL, the regime bucket won't change the decision.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-04-21-h1-pair-trading-backtest.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — tasks executed in this session with checkpoints.

**Which approach?**
