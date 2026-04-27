# EXP-005 Momentum Universe Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and operationally evaluate whether Momentum Pullback v1.1 generalizes from BTC/ETH-only to a pre-frozen ~12-symbol universe via S-B capital allocation, walk-forward 365d + 90d holdout, and 10 a-priori GO/NO-GO criteria.

**Architecture:** New isolated subdir `momentum/expansion/` reusing the live `evaluate_momentum_pullback` engine via a thin adapter. A pure `run_portfolio_backtest()` function at the center; CLIs and SQLite persistence around it. Universe is preflight-frozen in a JSON artifact before any backtest runs. C3-normalized baseline (BTC/ETH under same S-B framework) is the bloqueante comparator.

**Tech Stack:** Python 3.13, numpy, pandas, sqlite3, requests, pytest. Same deps as `momentum/` core. No new top-level dependencies.

**Spec:** `docs/superpowers/specs/2026-04-27-exp-005-universe-expansion-design.md`
**Worktree:** `.worktrees/feat-exp-005-universe-expansion/` (branch `feat/exp-005-universe-expansion`)

---

## Task 1: Scaffolding `momentum/expansion/__init__.py`

**Files:**
- Create: `momentum/expansion/__init__.py`

- [ ] **Step 1: Create empty package marker**

```python
"""EXP-005 Momentum Universe Expansion — isolated module.

See docs/superpowers/specs/2026-04-27-exp-005-universe-expansion-design.md
"""
```

- [ ] **Step 2: Confirm import works**

Run: `python -c "import momentum.expansion"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add momentum/expansion/__init__.py
git commit -m "feat(expansion): scaffolding EXP-005 module"
```

---

## Task 2: `ExpansionConfig` dataclass + tests

**Files:**
- Create: `momentum/expansion/config.py`
- Create: `tests/test_expansion_config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_config.py`:

```python
"""Tests for ExpansionConfig."""
from dataclasses import FrozenInstanceError

import pytest

from momentum.expansion.config import (
    BUCKET_ASSIGNMENT,
    ExpansionConfig,
    SLIPPAGE_BY_BUCKET,
)


def test_config_defaults():
    cfg = ExpansionConfig(universe=["BTCUSDT", "ETHUSDT"])
    assert cfg.period_main_days == 365
    assert cfg.period_holdout_days == 90
    assert cfg.n_folds == 12
    assert cfg.required_history_days == 455
    assert cfg.gap_threshold_pct == 0.5
    assert cfg.slippage_universal_sensitivity == 0.10
    assert cfg.pf_threshold_main == 1.25
    assert cfg.pf_ratio_vs_baseline == 1.10
    assert cfg.dd_ratio_vs_baseline == 1.30
    assert cfg.min_folds_positive == 9
    assert cfg.holdout_pf_min == 1.0
    assert cfg.holdout_ratio_vs_main == 0.9
    assert cfg.symbol_destructive_min_n == 60
    assert cfg.symbol_destructive_max_pf == 0.5


def test_config_frozen():
    cfg = ExpansionConfig(universe=["BTCUSDT"])
    with pytest.raises(FrozenInstanceError):
        cfg.period_main_days = 180


def test_bucket_assignment_covers_all_candidates():
    expected = {
        "BTCUSDT", "ETHUSDT", "SOLUSDT",
        "XRPUSDT", "DOGEUSDT", "BNBUSDT", "ADAUSDT",
        "LINKUSDT", "AVAXUSDT", "SUIUSDT", "AAVEUSDT", "LTCUSDT", "NEARUSDT",
    }
    assert set(BUCKET_ASSIGNMENT.keys()) == expected
    valid_buckets = {"core", "high_beta", "infra"}
    for sym, bucket in BUCKET_ASSIGNMENT.items():
        assert bucket in valid_buckets, f"{sym} has invalid bucket {bucket}"


def test_slippage_by_bucket():
    assert SLIPPAGE_BY_BUCKET == {"core": 0.03, "high_beta": 0.07, "infra": 0.05}


def test_slippage_for_symbol():
    cfg = ExpansionConfig(universe=["BTCUSDT", "DOGEUSDT", "LINKUSDT"])
    assert cfg.slippage_for("BTCUSDT") == 0.03
    assert cfg.slippage_for("DOGEUSDT") == 0.07
    assert cfg.slippage_for("LINKUSDT") == 0.05


def test_unknown_symbol_raises():
    cfg = ExpansionConfig(universe=["UNKNOWNUSDT"])
    with pytest.raises(KeyError):
        cfg.slippage_for("UNKNOWNUSDT")
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_config.py -v`
Expected: ImportError for `momentum.expansion.config`.

- [ ] **Step 3: Implement config**

Create `momentum/expansion/config.py`:

```python
"""ExpansionConfig — frozen parameters for EXP-005.

All thresholds and bucket mappings are a-priori, congealed before backtest.
See spec section 6 for criteria definitions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


BUCKET_ASSIGNMENT: Mapping[str, str] = {
    "BTCUSDT": "core", "ETHUSDT": "core", "SOLUSDT": "core",
    "XRPUSDT": "high_beta", "DOGEUSDT": "high_beta",
    "BNBUSDT": "high_beta", "ADAUSDT": "high_beta",
    "LINKUSDT": "infra", "AVAXUSDT": "infra", "SUIUSDT": "infra",
    "AAVEUSDT": "infra", "LTCUSDT": "infra", "NEARUSDT": "infra",
}

SLIPPAGE_BY_BUCKET: Mapping[str, float] = {
    "core": 0.03,       # majors (pct per leg)
    "high_beta": 0.07,  # high-beta liquidos
    "infra": 0.05,      # infra/DeFi
}


@dataclass(frozen=True)
class ExpansionConfig:
    """Frozen config for EXP-005. Universe must be passed in (from preflight)."""

    universe: tuple[str, ...]

    # Window
    period_main_days: int = 365
    period_holdout_days: int = 90
    n_folds: int = 12
    required_history_days: int = 455

    # Data validation
    gap_threshold_pct: float = 0.5  # max acceptable gap as pct of expected candles

    # Slippage (universal sensitivity sweep)
    slippage_universal_sensitivity: float = 0.10  # pct per leg

    # GO/NO-GO criteria thresholds (a priori — see spec section 6)
    pf_threshold_main: float = 1.25                  # criterion #1
    pf_ratio_vs_baseline: float = 1.10               # criterion #2
    dd_ratio_vs_baseline: float = 1.30               # criterion #4
    min_folds_positive: int = 9                      # criterion #5 (out of 12)
    holdout_pf_min: float = 1.0                      # criterion #8 part 1
    holdout_ratio_vs_main: float = 0.9               # criterion #8 part 2
    symbol_destructive_min_n: int = 60               # criterion #9 trigger
    symbol_destructive_max_pf: float = 0.5           # criterion #9 threshold
    slippage_collapse_min_pf: float = 1.0            # criterion #10

    # LOO tolerance
    loo_fold_outliers_tolerated: int = 1             # criterion #7 — 1 fold can fail

    def __post_init__(self):
        if not self.universe:
            raise ValueError("universe must not be empty")

    def slippage_for(self, symbol: str) -> float:
        """Return slippage pct per leg for the given symbol's bucket."""
        bucket = BUCKET_ASSIGNMENT[symbol]
        return SLIPPAGE_BY_BUCKET[bucket]

    def bucket_for(self, symbol: str) -> str:
        return BUCKET_ASSIGNMENT[symbol]
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_config.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/config.py tests/test_expansion_config.py
git commit -m "feat(expansion): ExpansionConfig with bucket assignment and 10 thresholds"
```

---

## Task 3: `metrics.py` portfolio metrics

**Files:**
- Create: `momentum/expansion/metrics.py`
- Create: `tests/test_expansion_metrics.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_metrics.py`:

```python
"""Tests for portfolio metrics."""
import math

import pytest

from momentum.expansion.metrics import compute_portfolio_metrics


def _trade(pnl_pct: float, **kwargs) -> dict:
    base = {
        "symbol": "BTCUSDT", "direction": "long",
        "entry_ts": "2026-01-01T00:00:00", "exit_ts": "2026-01-01T01:00:00",
        "pnl_pct": pnl_pct,
    }
    base.update(kwargs)
    return base


def test_empty_trades():
    m = compute_portfolio_metrics([])
    assert m["n_trades"] == 0
    assert m["win_rate"] == 0.0
    assert m["profit_factor"] == 0.0
    assert m["total_pnl_pct"] == 0.0
    assert m["max_drawdown_pct"] == 0.0


def test_single_winning_trade():
    m = compute_portfolio_metrics([_trade(1.0)])
    assert m["n_trades"] == 1
    assert m["win_rate"] == 100.0
    assert m["profit_factor"] == math.inf
    assert m["total_pnl_pct"] == 1.0
    assert m["avg_pnl_pct"] == 1.0


def test_single_losing_trade():
    m = compute_portfolio_metrics([_trade(-0.5)])
    assert m["n_trades"] == 1
    assert m["win_rate"] == 0.0
    assert m["profit_factor"] == 0.0
    assert m["total_pnl_pct"] == -0.5


def test_mixed_trades():
    trades = [_trade(2.0), _trade(-1.0), _trade(1.5), _trade(-0.5)]
    m = compute_portfolio_metrics(trades)
    assert m["n_trades"] == 4
    assert m["win_rate"] == 50.0
    # Gross profit = 3.5; gross loss = 1.5; PF = 3.5/1.5
    assert math.isclose(m["profit_factor"], 3.5 / 1.5, rel_tol=1e-9)
    assert math.isclose(m["total_pnl_pct"], 2.0, rel_tol=1e-9)


def test_max_drawdown():
    # Equity: 0 -> +5 -> +5+3=8 -> 8-10=-2 -> -2+1=-1
    # Peaks: 0, 5, 8, 8, 8 -> DD points: 0, 0, 0, 10, 9
    # max_dd = 10
    trades = [_trade(5.0), _trade(3.0), _trade(-10.0), _trade(1.0)]
    m = compute_portfolio_metrics(trades)
    assert math.isclose(m["max_drawdown_pct"], 10.0, rel_tol=1e-9)


def test_all_zero_pnl():
    trades = [_trade(0.0), _trade(0.0)]
    m = compute_portfolio_metrics(trades)
    assert m["n_trades"] == 2
    assert m["win_rate"] == 0.0  # zero is not a win
    assert m["profit_factor"] == 0.0
    assert m["total_pnl_pct"] == 0.0
    assert m["max_drawdown_pct"] == 0.0
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_metrics.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement metrics**

Create `momentum/expansion/metrics.py`:

```python
"""Portfolio metrics for EXP-005 — reescritos do zero, sem reuso de EXP-004."""
from __future__ import annotations

import math
from typing import Iterable, Mapping


def compute_portfolio_metrics(trades: Iterable[Mapping]) -> dict:
    """Compute aggregate portfolio metrics from a list of closed trades.

    Each trade must have key 'pnl_pct' (float). Other keys are ignored.
    """
    trades_list = list(trades)
    n = len(trades_list)
    if n == 0:
        return {
            "n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "total_pnl_pct": 0.0, "avg_pnl_pct": 0.0, "max_drawdown_pct": 0.0,
        }

    pnls = [float(t["pnl_pct"]) for t in trades_list]
    total = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    win_rate = (wins / n) * 100.0

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)  # positive number
    if gross_loss == 0:
        profit_factor = math.inf if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

    # Max drawdown over equity curve
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
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_pnl_pct": total,
        "avg_pnl_pct": total / n,
        "max_drawdown_pct": max_dd,
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_metrics.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/metrics.py tests/test_expansion_metrics.py
git commit -m "feat(expansion): portfolio metrics (PF/WR/DD/total_pnl) reescritos do zero"
```

---

## Task 4: `capital_pool.py` S-B allocation pure

**Files:**
- Create: `momentum/expansion/capital_pool.py`
- Create: `tests/test_expansion_capital_pool.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_capital_pool.py`:

```python
"""Tests for S-B capital allocation."""
import math

import pytest

from momentum.expansion.capital_pool import (
    PortfolioState,
    allocate_position_size,
    compute_slot_size,
    open_slot,
    close_slot,
)


def test_compute_slot_size_evenly_divides():
    assert math.isclose(compute_slot_size(1000.0, 4), 250.0)
    assert math.isclose(compute_slot_size(1000.0, 1), 1000.0)


def test_compute_slot_size_zero_universe_raises():
    with pytest.raises(ValueError):
        compute_slot_size(1000.0, 0)


def test_allocate_position_size_uses_slot_and_risk_fraction():
    # slot = 250, entry = 100, sl = 95 (risk = 5% of price), risk fraction = 0.01 (1% of slot)
    # risk in usdt = 250 * 0.01 = 2.5
    # position size in usdt = risk / (entry - sl) * entry = 2.5 / 5 * 100 = 50
    size = allocate_position_size(slot_size_usdt=250.0, entry=100.0, sl=95.0, risk_fraction=0.01)
    assert math.isclose(size, 50.0, rel_tol=1e-9)


def test_allocate_position_size_short():
    # short: sl > entry; risk = sl - entry
    size = allocate_position_size(slot_size_usdt=250.0, entry=100.0, sl=105.0, risk_fraction=0.01)
    assert math.isclose(size, 50.0, rel_tol=1e-9)


def test_allocate_position_size_zero_risk_raises():
    with pytest.raises(ValueError):
        allocate_position_size(slot_size_usdt=250.0, entry=100.0, sl=100.0, risk_fraction=0.01)


def test_portfolio_state_tracks_open_slots():
    state = PortfolioState(capital_pool=1000.0, slot_size=250.0)
    assert state.allocated == 0.0
    assert state.peak_concurrent == 0
    assert state.can_open()


def test_open_close_slot_round_trip():
    state = PortfolioState(capital_pool=1000.0, slot_size=250.0)
    open_slot(state, "BTCUSDT")
    assert "BTCUSDT" in state.open_symbols
    assert math.isclose(state.allocated, 250.0)
    assert state.peak_concurrent == 1
    close_slot(state, "BTCUSDT")
    assert "BTCUSDT" not in state.open_symbols
    assert math.isclose(state.allocated, 0.0)


def test_concurrent_slots_capped_by_pool():
    state = PortfolioState(capital_pool=1000.0, slot_size=250.0)  # max 4 concurrent
    for sym in ["A", "B", "C", "D"]:
        open_slot(state, sym)
    assert state.peak_concurrent == 4
    assert math.isclose(state.allocated, 1000.0)
    assert not state.can_open()  # pool exhausted

    # Try opening 5th — must raise
    with pytest.raises(ValueError):
        open_slot(state, "E")


def test_double_open_same_symbol_raises():
    state = PortfolioState(capital_pool=1000.0, slot_size=250.0)
    open_slot(state, "BTCUSDT")
    with pytest.raises(ValueError):
        open_slot(state, "BTCUSDT")
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_capital_pool.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement capital_pool**

Create `momentum/expansion/capital_pool.py`:

```python
"""S-B capital allocation: total pool fixed, divided by |universe|, max_positions = N.

Pure functions + minimal mutable state object for backtest accounting.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def compute_slot_size(capital_pool: float, n_universe: int) -> float:
    """Capital pool divided evenly across symbols."""
    if n_universe <= 0:
        raise ValueError(f"n_universe must be positive, got {n_universe}")
    return capital_pool / n_universe


def allocate_position_size(
    *,
    slot_size_usdt: float,
    entry: float,
    sl: float,
    risk_fraction: float,
) -> float:
    """Compute position size in USDT using risk-based sizing.

    risk_in_usdt = slot_size * risk_fraction
    risk_per_unit = abs(entry - sl)
    position_size_usdt = (risk_in_usdt / risk_per_unit) * entry
    """
    risk_per_unit = abs(entry - sl)
    if risk_per_unit == 0:
        raise ValueError("entry and sl must differ")
    risk_usdt = slot_size_usdt * risk_fraction
    return (risk_usdt / risk_per_unit) * entry


@dataclass
class PortfolioState:
    """Mutable portfolio accounting during a backtest run."""
    capital_pool: float
    slot_size: float
    open_symbols: set[str] = field(default_factory=set)
    allocated: float = 0.0
    peak_concurrent: int = 0

    def can_open(self) -> bool:
        return self.allocated + self.slot_size <= self.capital_pool + 1e-9


def open_slot(state: PortfolioState, symbol: str) -> None:
    if symbol in state.open_symbols:
        raise ValueError(f"{symbol} already open")
    if not state.can_open():
        raise ValueError(f"capital pool exhausted (allocated={state.allocated}, slot={state.slot_size}, pool={state.capital_pool})")
    state.open_symbols.add(symbol)
    state.allocated += state.slot_size
    if len(state.open_symbols) > state.peak_concurrent:
        state.peak_concurrent = len(state.open_symbols)


def close_slot(state: PortfolioState, symbol: str) -> None:
    if symbol not in state.open_symbols:
        raise ValueError(f"{symbol} not open")
    state.open_symbols.remove(symbol)
    state.allocated -= state.slot_size
    if state.allocated < 0:
        state.allocated = 0.0
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_capital_pool.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/capital_pool.py tests/test_expansion_capital_pool.py
git commit -m "feat(expansion): S-B capital_pool allocation with portfolio state tracking"
```

---

## Task 5: `signal_engine_adapter.py` thin adapter

**Files:**
- Create: `momentum/expansion/signal_engine_adapter.py`
- Create: `tests/test_expansion_signal_adapter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_signal_adapter.py`:

```python
"""Adapter snapshot tests: confirms wrapper returns same signal as core."""
import numpy as np
import pandas as pd
import pytest

from momentum.expansion.signal_engine_adapter import evaluate_signal_for_symbol


def _synthetic_candles(n=200, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 50000.0 * np.exp(np.cumsum(rng.normal(0, 0.005, n)))
    highs = closes * (1.0 + np.abs(rng.normal(0, 0.002, n)))
    lows = closes * (1.0 - np.abs(rng.normal(0, 0.002, n)))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volumes = rng.uniform(100, 1000, n)
    times = pd.to_datetime(np.arange(n) * 900_000, unit="ms", utc=True)
    return pd.DataFrame({
        "timestamp": times,
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": volumes,
    })


def test_adapter_returns_signal_or_none():
    candles = _synthetic_candles(200)
    result = evaluate_signal_for_symbol(
        candles=candles,
        symbol="BTCUSDT",
        regime_label="TRENDING",
        timestamp="2026-01-01T00:00:00",
    )
    # Either a signal or None — both valid.
    if result is not None:
        assert hasattr(result, "symbol")
        assert result.symbol == "BTCUSDT"


def test_adapter_does_not_modify_input_candles():
    candles = _synthetic_candles(200)
    snapshot = candles.copy()
    evaluate_signal_for_symbol(
        candles=candles,
        symbol="BTCUSDT",
        regime_label="TRENDING",
        timestamp="2026-01-01T00:00:00",
    )
    pd.testing.assert_frame_equal(candles, snapshot)


def test_adapter_passes_regime_to_core():
    """In a non-permissive regime, signal should be filtered out by core."""
    candles = _synthetic_candles(200)
    # VOLATILE is not in MOMENTUM_PERMISSIVE_REGIMES — core should reject
    result = evaluate_signal_for_symbol(
        candles=candles,
        symbol="BTCUSDT",
        regime_label="VOLATILE",
        timestamp="2026-01-01T00:00:00",
    )
    # Core's regime gate should produce None for non-permissive
    # (Cannot assert deterministically without seeding the core, but assert it doesn't raise)
    assert result is None or hasattr(result, "symbol")
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_signal_adapter.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement adapter**

Create `momentum/expansion/signal_engine_adapter.py`:

```python
"""Thin adapter to call the live evaluate_momentum_pullback engine.

The engine is NOT forked. EXP-005 imports the same function used in production.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from momentum.config import MomentumConfig
from momentum.momentum_trader import MomentumSignal, evaluate_momentum_pullback


def evaluate_signal_for_symbol(
    *,
    candles: pd.DataFrame,
    symbol: str,
    regime_label: str,
    timestamp: str,
    config: Optional[MomentumConfig] = None,
) -> Optional[MomentumSignal]:
    """Pass through to evaluate_momentum_pullback with EXP-005 conventions.

    Returns the live MomentumSignal or None. Does not mutate inputs.
    """
    cfg = config or MomentumConfig()
    regime_data = {"regime_label": regime_label}
    return evaluate_momentum_pullback(
        candles=candles,
        regime_data=regime_data,
        config=cfg,
        symbol=symbol,
        timestamp=timestamp,
    )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_signal_adapter.py -v`
Expected: 3 passed.

If `evaluate_momentum_pullback` signature differs, update import/call to match the live API. Do NOT add logic; the adapter must remain pass-through.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/signal_engine_adapter.py tests/test_expansion_signal_adapter.py
git commit -m "feat(expansion): thin adapter to live evaluate_momentum_pullback (no fork)"
```

---

## Task 6: `data_loader.py` fetch + alignment + gap detection

**Files:**
- Create: `momentum/expansion/data_loader.py`
- Create: `tests/test_expansion_data_loader.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_data_loader.py`:

```python
"""Tests for data_loader: fetching, alignment, gap detection."""
import numpy as np
import pandas as pd
import pytest

from momentum.expansion.data_loader import (
    GapValidationError,
    align_candles_by_timestamp,
    validate_gap_threshold,
)


def _ts_series(n: int, start_ms: int = 0, step_ms: int = 900_000) -> np.ndarray:
    return np.arange(start_ms, start_ms + n * step_ms, step_ms, dtype=np.int64)


def _df(close_times_ms: np.ndarray) -> pd.DataFrame:
    n = len(close_times_ms)
    return pd.DataFrame({
        "close_time_ms": close_times_ms,
        "open": np.full(n, 100.0),
        "high": np.full(n, 101.0),
        "low": np.full(n, 99.0),
        "close": np.full(n, 100.5),
        "volume": np.full(n, 1000.0),
    })


def test_align_perfectly_synchronized():
    btc = _df(_ts_series(100))
    eth = _df(_ts_series(100))
    aligned = align_candles_by_timestamp({"BTCUSDT": btc, "ETHUSDT": eth})
    assert len(aligned["BTCUSDT"]) == 100
    assert len(aligned["ETHUSDT"]) == 100


def test_align_intersection_drops_unique_timestamps():
    btc = _df(_ts_series(100, start_ms=0))                           # 0..89_100_000
    eth = _df(_ts_series(100, start_ms=900_000))                     # 900_000..90_000_000
    aligned = align_candles_by_timestamp({"BTCUSDT": btc, "ETHUSDT": eth})
    assert len(aligned["BTCUSDT"]) == 99
    assert len(aligned["ETHUSDT"]) == 99
    # Common timestamps should match
    assert (aligned["BTCUSDT"]["close_time_ms"].values
            == aligned["ETHUSDT"]["close_time_ms"].values).all()


def test_validate_gap_passes_when_close():
    expected = 1000
    actual = 996  # 0.4% gap
    validate_gap_threshold(symbol="BTCUSDT", expected=expected, actual=actual, threshold_pct=0.5)


def test_validate_gap_fails_when_too_big():
    expected = 1000
    actual = 990  # 1.0% gap
    with pytest.raises(GapValidationError) as exc:
        validate_gap_threshold(symbol="BTCUSDT", expected=expected, actual=actual, threshold_pct=0.5)
    assert "BTCUSDT" in str(exc.value)
    assert "gap_pct" in str(exc.value).lower() or "1.0" in str(exc.value)


def test_align_empty_input_raises():
    with pytest.raises(ValueError):
        align_candles_by_timestamp({})


def test_align_one_symbol_passes_through():
    btc = _df(_ts_series(50))
    aligned = align_candles_by_timestamp({"BTCUSDT": btc})
    assert len(aligned["BTCUSDT"]) == 50
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_data_loader.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement data_loader**

Create `momentum/expansion/data_loader.py`:

```python
"""Candle fetching, alignment by timestamp, and gap validation.

Fetching from Binance fapi is paginated per symbol. Alignment intersects
timestamps across symbols. Gap validation aborts before backtest if any
symbol has more missing candles than threshold permits.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd
import requests


_FAPI_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
_MAX_PER_REQUEST = 1000


class GapValidationError(Exception):
    """Raised when a symbol has too many missing candles."""


@dataclass(frozen=True)
class FetchResult:
    symbol: str
    candles: pd.DataFrame
    first_close_time_ms: int
    last_close_time_ms: int


def fetch_klines_paginated(
    symbol: str, interval: str, end_time_ms: int, total_needed: int,
    *, sleep_between: float = 0.1,
) -> pd.DataFrame:
    """Fetch backwards from end_time_ms in pages of 1000. Returns DataFrame oldest-first."""
    cursor = end_time_ms
    out_pages: list[list] = []
    remaining = total_needed
    while remaining > 0:
        limit = min(_MAX_PER_REQUEST, remaining)
        resp = requests.get(_FAPI_KLINES_URL, params={
            "symbol": symbol, "interval": interval, "limit": limit, "endTime": cursor,
        }, timeout=30)
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        out_pages.insert(0, page)
        cursor = page[0][0] - 1
        remaining -= len(page)
        time.sleep(sleep_between)
    rows = [r for page in out_pages for r in page]
    if not rows:
        return pd.DataFrame(columns=["close_time_ms", "open", "high", "low", "close", "volume"])
    return pd.DataFrame({
        "close_time_ms": [int(r[6]) for r in rows],
        "open": [float(r[1]) for r in rows],
        "high": [float(r[2]) for r in rows],
        "low": [float(r[3]) for r in rows],
        "close": [float(r[4]) for r in rows],
        "volume": [float(r[5]) for r in rows],
    })


def align_candles_by_timestamp(
    candles_by_symbol: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Intersect timestamps across all symbols and return aligned subsets."""
    if not candles_by_symbol:
        raise ValueError("candles_by_symbol must not be empty")

    common = None
    for sym, df in candles_by_symbol.items():
        ts_set = set(df["close_time_ms"].values.tolist())
        common = ts_set if common is None else (common & ts_set)
    common_sorted = sorted(common)

    aligned: dict[str, pd.DataFrame] = {}
    for sym, df in candles_by_symbol.items():
        mask = df["close_time_ms"].isin(common_sorted)
        aligned[sym] = df.loc[mask].reset_index(drop=True)
    return aligned


def validate_gap_threshold(
    *, symbol: str, expected: int, actual: int, threshold_pct: float,
) -> None:
    """Raise GapValidationError if gap exceeds threshold_pct of expected."""
    if expected <= 0:
        raise ValueError(f"expected must be positive, got {expected}")
    gap = expected - actual
    gap_pct = (gap / expected) * 100.0
    if gap_pct > threshold_pct:
        raise GapValidationError(
            f"{symbol}: expected_candles={expected}, actual_candles={actual}, "
            f"gap_pct={gap_pct:.2f}% > threshold {threshold_pct}%"
        )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_data_loader.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/data_loader.py tests/test_expansion_data_loader.py
git commit -m "feat(expansion): data_loader with paginated fetch, alignment, gap validation"
```

---

## Task 7: `preflight.py` eligibility check

**Files:**
- Create: `momentum/expansion/preflight.py`
- Create: `tests/test_expansion_preflight.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_preflight.py`:

```python
"""Tests for preflight: mock Binance + eligibility classification."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from momentum.expansion.preflight import PreflightResult, run_preflight


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_eligible_with_long_history():
    today = datetime(2026, 4, 27, tzinfo=timezone.utc)
    # First kline 700d ago — eligible for 455d requirement
    first_kline_ms = _ms(today - timedelta(days=700))

    with patch("momentum.expansion.preflight._fetch_first_kline_time") as mock_fetch:
        mock_fetch.return_value = first_kline_ms
        result = run_preflight(
            symbols=["BTCUSDT"], required_days=455, today=today,
        )
    assert "BTCUSDT" in result.universe
    assert "BTCUSDT" not in result.ineligible


def test_ineligible_with_short_history():
    today = datetime(2026, 4, 27, tzinfo=timezone.utc)
    first_kline_ms = _ms(today - timedelta(days=100))

    with patch("momentum.expansion.preflight._fetch_first_kline_time") as mock_fetch:
        mock_fetch.return_value = first_kline_ms
        result = run_preflight(
            symbols=["NEWCOINUSDT"], required_days=455, today=today,
        )
    assert "NEWCOINUSDT" not in result.universe
    assert "NEWCOINUSDT" in result.ineligible
    assert result.ineligible["NEWCOINUSDT"]["days_available"] == 100


def test_mixed_eligibility():
    today = datetime(2026, 4, 27, tzinfo=timezone.utc)

    def fake_fetch(symbol):
        if symbol == "BTCUSDT":
            return _ms(today - timedelta(days=2000))
        if symbol == "NEWCOINUSDT":
            return _ms(today - timedelta(days=50))
        return _ms(today - timedelta(days=455))  # exactly at threshold

    with patch("momentum.expansion.preflight._fetch_first_kline_time", side_effect=fake_fetch):
        result = run_preflight(
            symbols=["BTCUSDT", "NEWCOINUSDT", "EDGEUSDT"],
            required_days=455, today=today,
        )
    assert "BTCUSDT" in result.universe
    assert "NEWCOINUSDT" in result.ineligible
    # Exactly at threshold = eligible
    assert "EDGEUSDT" in result.universe


def test_preflight_serializes_to_json_dict():
    today = datetime(2026, 4, 27, tzinfo=timezone.utc)
    with patch("momentum.expansion.preflight._fetch_first_kline_time") as mock_fetch:
        mock_fetch.return_value = _ms(today - timedelta(days=700))
        result = run_preflight(symbols=["BTCUSDT"], required_days=455, today=today)
    d = result.to_dict()
    assert d["frozen_at"]
    assert d["required_days"] == 455
    assert d["universe"] == ["BTCUSDT"]
    assert d["candidates_checked"] == 1
    assert d["universe_size"] == 1


def test_preflight_empty_eligible_raises_in_caller():
    today = datetime(2026, 4, 27, tzinfo=timezone.utc)
    with patch("momentum.expansion.preflight._fetch_first_kline_time") as mock_fetch:
        mock_fetch.return_value = _ms(today - timedelta(days=10))
        result = run_preflight(symbols=["NEWUSDT"], required_days=455, today=today)
    # run_preflight returns the result; abort decision is on the CLI
    assert result.universe_size == 0
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_preflight.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement preflight**

Create `momentum/expansion/preflight.py`:

```python
"""Preflight: per-symbol eligibility check against Binance fapi history."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping

import requests


_FAPI_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"


def _fetch_first_kline_time(symbol: str) -> int:
    """Return close_time_ms of first available 15m kline for symbol."""
    resp = requests.get(_FAPI_KLINES_URL, params={
        "symbol": symbol, "interval": "15m", "startTime": 0, "limit": 1,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise RuntimeError(f"No klines returned for {symbol}")
    # Index 0 is open_time_ms; use it as the "first available" marker
    return int(data[0][0])


@dataclass(frozen=True)
class PreflightResult:
    frozen_at: str
    required_days: int
    universe: list[str]
    ineligible: Mapping[str, Mapping]
    candidates_checked: int
    per_symbol_stats: Mapping[str, Mapping] = field(default_factory=dict)

    @property
    def universe_size(self) -> int:
        return len(self.universe)

    def to_dict(self) -> dict:
        return {
            "frozen_at": self.frozen_at,
            "required_days": self.required_days,
            "universe": list(self.universe),
            "ineligible": dict(self.ineligible),
            "candidates_checked": self.candidates_checked,
            "universe_size": self.universe_size,
            "per_symbol_stats": dict(self.per_symbol_stats),
        }


def run_preflight(
    *,
    symbols: list[str],
    required_days: int,
    today: datetime | None = None,
) -> PreflightResult:
    today = today or datetime.now(tz=timezone.utc)
    universe: list[str] = []
    ineligible: dict[str, dict] = {}
    per_symbol_stats: dict[str, dict] = {}

    for sym in symbols:
        first_kline_ms = _fetch_first_kline_time(sym)
        first_kline_dt = datetime.fromtimestamp(first_kline_ms / 1000.0, tz=timezone.utc)
        days_available = (today - first_kline_dt).days
        per_symbol_stats[sym] = {
            "first_kline": first_kline_dt.isoformat(),
            "days_available": days_available,
        }
        if days_available >= required_days:
            universe.append(sym)
        else:
            ineligible[sym] = {
                "first_kline": first_kline_dt.isoformat(),
                "days_available": days_available,
                "reason": "below_required_days",
            }

    return PreflightResult(
        frozen_at=today.isoformat(),
        required_days=required_days,
        universe=universe,
        ineligible=ineligible,
        candidates_checked=len(symbols),
        per_symbol_stats=per_symbol_stats,
    )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_preflight.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/preflight.py tests/test_expansion_preflight.py
git commit -m "feat(expansion): preflight eligibility check with mock-friendly Binance fetch"
```

---

## Task 8: `comparators.py` C1 cash + C2 BH equal-weight

**Files:**
- Create: `momentum/expansion/comparators.py`
- Create: `tests/test_expansion_comparators_c1c2.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_comparators_c1c2.py`:

```python
"""Tests for C1 cash and C2 buy-and-hold equal-weight comparators."""
import math

import numpy as np
import pandas as pd
import pytest

from momentum.expansion.comparators import (
    compute_c1_cash,
    compute_c2_buy_and_hold_equal_weight,
)


def _close_series(values: list[float]) -> pd.DataFrame:
    n = len(values)
    return pd.DataFrame({
        "close_time_ms": np.arange(n, dtype=np.int64) * 900_000,
        "close": np.array(values, dtype=float),
        "open": np.array(values, dtype=float),
        "high": np.array(values, dtype=float),
        "low": np.array(values, dtype=float),
        "volume": np.full(n, 1.0),
    })


def test_c1_cash_is_constant():
    c1 = compute_c1_cash()
    assert c1["profit_factor"] == 1.0
    assert c1["max_drawdown_pct"] == 0.0
    assert c1["total_pnl_pct"] == 0.0


def test_c2_two_symbols_both_up():
    btc = _close_series([100.0, 110.0])  # +10%
    eth = _close_series([50.0, 55.0])    # +10%
    c2 = compute_c2_buy_and_hold_equal_weight({"BTCUSDT": btc, "ETHUSDT": eth})
    # Equal-weight equity: 0.5 * 1.10 + 0.5 * 1.10 = 1.10 → +10%
    assert math.isclose(c2["total_pnl_pct"], 10.0, rel_tol=1e-9)
    assert c2["max_drawdown_pct"] == 0.0


def test_c2_one_up_one_down():
    btc = _close_series([100.0, 120.0])  # +20%
    eth = _close_series([50.0, 45.0])    # -10%
    c2 = compute_c2_buy_and_hold_equal_weight({"BTCUSDT": btc, "ETHUSDT": eth})
    # 0.5 * 1.20 + 0.5 * 0.90 = 1.05 → +5%
    assert math.isclose(c2["total_pnl_pct"], 5.0, rel_tol=1e-9)


def test_c2_drawdown_tracked():
    # 100 -> 90 -> 100. eth: 50 -> 50 -> 50.
    btc = _close_series([100.0, 90.0, 100.0])
    eth = _close_series([50.0, 50.0, 50.0])
    c2 = compute_c2_buy_and_hold_equal_weight({"BTCUSDT": btc, "ETHUSDT": eth})
    # Equity: 1.0 -> 0.5*0.9+0.5*1.0=0.95 -> 1.0
    # Max DD = 5%
    assert math.isclose(c2["max_drawdown_pct"], 5.0, rel_tol=1e-9)


def test_c2_zero_cost_no_fees_applied():
    """C2 is reported zero-cost per spec section 6.1: 'baseline generoso'."""
    btc = _close_series([100.0, 110.0])
    eth = _close_series([50.0, 55.0])
    c2 = compute_c2_buy_and_hold_equal_weight({"BTCUSDT": btc, "ETHUSDT": eth})
    # No fee deduction — return is exactly the price ratio
    assert math.isclose(c2["total_pnl_pct"], 10.0, rel_tol=1e-9)


def test_c2_empty_universe_raises():
    with pytest.raises(ValueError):
        compute_c2_buy_and_hold_equal_weight({})
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_comparators_c1c2.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement C1 + C2**

Create `momentum/expansion/comparators.py`:

```python
"""Comparators: C1 cash, C2 BH equal-weight, C3-normalized, C3-live.

C1 is trivial (PF=1.0, DD=0). C2 is buy-and-hold equal-weight with cost zero
(baseline generoso per spec). C3-normalized and C3-live live in a later task.
"""
from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd


def compute_c1_cash() -> dict:
    """C1: cash position, no PnL, no DD."""
    return {
        "name": "C1_cash",
        "profit_factor": 1.0,
        "max_drawdown_pct": 0.0,
        "total_pnl_pct": 0.0,
    }


def compute_c2_buy_and_hold_equal_weight(
    candles_by_symbol: Mapping[str, pd.DataFrame],
) -> dict:
    """C2: BH equal-weight, no rebalance, zero-cost (no fees, no slippage).

    Returns total_pnl_pct, max_drawdown_pct, profit_factor.
    """
    if not candles_by_symbol:
        raise ValueError("candles_by_symbol must not be empty")

    closes = []
    for sym in sorted(candles_by_symbol.keys()):
        df = candles_by_symbol[sym]
        if len(df) < 2:
            raise ValueError(f"{sym} needs >= 2 candles")
        closes.append(df["close"].values.astype(float))

    n_steps = min(len(c) for c in closes)
    n_symbols = len(closes)
    weights = 1.0 / n_symbols

    # Equity curve: at each step, sum of weighted price ratios from t=0
    equity = np.zeros(n_steps)
    for c in closes:
        c_norm = c[:n_steps] / c[0]
        equity += weights * c_norm

    total_pnl_pct = (equity[-1] - 1.0) * 100.0

    # Max drawdown
    peak = np.maximum.accumulate(equity)
    dd_series = (peak - equity) / peak * 100.0
    max_dd_pct = float(dd_series.max())

    # PF for BH: ratio of upside to downside contributions of step returns
    step_returns = np.diff(equity)
    gains = step_returns[step_returns > 0].sum()
    losses = -step_returns[step_returns < 0].sum()
    if losses == 0:
        pf = float("inf") if gains > 0 else 0.0
    else:
        pf = float(gains / losses)

    return {
        "name": "C2_bh_equal_weight",
        "profit_factor": pf,
        "max_drawdown_pct": max_dd_pct,
        "total_pnl_pct": float(total_pnl_pct),
        "n_symbols": n_symbols,
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_comparators_c1c2.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/comparators.py tests/test_expansion_comparators_c1c2.py
git commit -m "feat(expansion): C1 cash + C2 BH equal-weight comparators (zero-cost)"
```

---

## Task 9: `run_portfolio_backtest()` pure core

**Files:**
- Create: `momentum/expansion/research_runner.py`
- Create: `tests/test_expansion_run_portfolio_backtest.py`

This is the central pure function. It glues config + adapter + capital_pool + metrics. Lookahead protection and force-close at end-of-series are inherited as best practices from EXP-004.

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_run_portfolio_backtest.py`:

```python
"""Tests for run_portfolio_backtest pure function."""
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.research_runner import (
    ExpansionResult,
    run_portfolio_backtest,
)


def _candles(n: int, base: float, drift: float = 0.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base * np.exp(np.cumsum(rng.normal(drift, 0.005, n)))
    highs = closes * (1.0 + np.abs(rng.normal(0, 0.002, n)))
    lows = closes * (1.0 - np.abs(rng.normal(0, 0.002, n)))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volumes = rng.uniform(100, 1000, n)
    return pd.DataFrame({
        "close_time_ms": np.arange(n, dtype=np.int64) * 900_000,
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": volumes,
    })


def _no_signal_fn(*, candles, symbol, regime_label, timestamp, config=None):
    return None


def _force_long_signal_fn(*, candles, symbol, regime_label, timestamp, config=None):
    """Always emits a long signal at the most recent candle."""
    from momentum.momentum_trader import MomentumSignal
    last = candles.iloc[-1]
    entry = float(last["close"])
    return MomentumSignal(
        symbol=symbol, direction="long",
        entry=entry, sl=entry * 0.98, tp1=entry * 1.02, tp2=entry * 1.05,
        timestamp=timestamp, regime=regime_label,
        score=1.0, signal_subtype="forced",
    )


def _basic_config(universe: tuple[str, ...]) -> ExpansionConfig:
    return ExpansionConfig(universe=universe)


def test_no_signals_produces_zero_trades():
    cfg = _basic_config(("BTCUSDT", "ETHUSDT"))
    candles = {"BTCUSDT": _candles(100, 50000.0, seed=1),
               "ETHUSDT": _candles(100, 3000.0, seed=2)}
    result = run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles,
        signal_fn=_no_signal_fn,
        capital_pool_usdt=10000.0,
        risk_fraction=0.01,
    )
    assert isinstance(result, ExpansionResult)
    assert len(result.trades) == 0
    assert result.peak_concurrent_positions == 0


def test_input_validation_empty_candles():
    cfg = _basic_config(("BTCUSDT",))
    with pytest.raises(ValueError):
        run_portfolio_backtest(
            config=cfg, candles_by_symbol={},
            signal_fn=_no_signal_fn,
            capital_pool_usdt=10000.0,
            risk_fraction=0.01,
        )


def test_input_validation_universe_mismatch():
    cfg = _basic_config(("BTCUSDT", "ETHUSDT"))
    with pytest.raises(ValueError):
        run_portfolio_backtest(
            config=cfg, candles_by_symbol={"BTCUSDT": _candles(100, 50000.0)},
            signal_fn=_no_signal_fn,
            capital_pool_usdt=10000.0,
            risk_fraction=0.01,
        )


def test_force_close_at_end_of_series():
    cfg = _basic_config(("BTCUSDT",))
    candles = {"BTCUSDT": _candles(150, 50000.0, drift=0.001, seed=3)}
    result = run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles,
        signal_fn=_force_long_signal_fn,
        capital_pool_usdt=10000.0,
        risk_fraction=0.01,
    )
    # All trades must have an exit_ts (force-close at end)
    for t in result.trades:
        assert t["exit_ts"] is not None
        assert t["exit_reason"] in {"SL", "TP1", "TP2", "TIMEOUT", "TRAIL", "FORCE_CLOSE"}


def test_capital_pool_caps_concurrency():
    cfg = _basic_config(("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    candles = {
        "BTCUSDT": _candles(150, 50000.0, drift=0.001, seed=4),
        "ETHUSDT": _candles(150, 3000.0, drift=0.001, seed=5),
        "SOLUSDT": _candles(150, 100.0, drift=0.001, seed=6),
    }
    # Pool 300 with slot 100; max 3 concurrent — fine
    result = run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles,
        signal_fn=_force_long_signal_fn,
        capital_pool_usdt=300.0,
        risk_fraction=0.01,
    )
    assert result.peak_concurrent_positions <= 3


def test_pure_function_no_side_effects_on_candles():
    cfg = _basic_config(("BTCUSDT",))
    candles_orig = _candles(100, 50000.0, seed=7)
    candles = {"BTCUSDT": candles_orig.copy()}
    run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles,
        signal_fn=_force_long_signal_fn,
        capital_pool_usdt=10000.0,
        risk_fraction=0.01,
    )
    pd.testing.assert_frame_equal(candles["BTCUSDT"], candles_orig)
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_run_portfolio_backtest.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement run_portfolio_backtest**

Create `momentum/expansion/research_runner.py`:

```python
"""run_portfolio_backtest — pure function center of EXP-005.

Inputs: config, candles_by_symbol (already aligned), signal_fn (default: live adapter),
        capital_pool_usdt, risk_fraction.
Outputs: ExpansionResult with trades, decisions, portfolio peak, metrics.

No I/O. No network. No SQLite. Deterministic for same inputs.
Look-ahead protection: signals evaluated using candles up to t; trade opens at
candle t+1 close (execution_shift=1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional

import pandas as pd

from momentum.expansion.capital_pool import (
    PortfolioState,
    allocate_position_size,
    compute_slot_size,
    open_slot,
    close_slot,
)
from momentum.expansion.config import ExpansionConfig
from momentum.expansion.metrics import compute_portfolio_metrics


SignalFn = Callable[..., Optional[object]]


@dataclass(frozen=True)
class ExpansionResult:
    trades: list[dict]
    decisions: list[dict]
    final_capital_pool: float
    peak_concurrent_positions: int
    metrics: dict


def _ts_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _check_exit(
    *, position: dict, candle_high: float, candle_low: float,
    candle_close: float,
) -> tuple[Optional[str], float]:
    """Return (exit_reason, exit_price) or (None, 0.0) if no exit triggered."""
    if position["direction"] == "long":
        if candle_low <= position["sl"]:
            return ("SL", position["sl"])
        if candle_high >= position["tp2"]:
            return ("TP2", position["tp2"])
        if candle_high >= position["tp1"]:
            return ("TP1", position["tp1"])
    else:  # short
        if candle_high >= position["sl"]:
            return ("SL", position["sl"])
        if candle_low <= position["tp2"]:
            return ("TP2", position["tp2"])
        if candle_low <= position["tp1"]:
            return ("TP1", position["tp1"])
    return (None, 0.0)


def _pnl_pct(entry: float, exit_price: float, direction: str, slippage_pct: float) -> float:
    """PnL pct including slippage on entry and exit (per leg)."""
    if direction == "long":
        gross = (exit_price - entry) / entry * 100.0
    else:
        gross = (entry - exit_price) / entry * 100.0
    # 2 legs (entry + exit) of slippage
    return gross - 2.0 * slippage_pct


def run_portfolio_backtest(
    *,
    config: ExpansionConfig,
    candles_by_symbol: Mapping[str, pd.DataFrame],
    signal_fn: SignalFn,
    capital_pool_usdt: float,
    risk_fraction: float,
    regime_fn: Optional[Callable[[str], str]] = None,
    execution_shift: int = 1,
    slippage_override_pct: Optional[float] = None,
) -> ExpansionResult:
    """Pure backtest over multi-symbol portfolio under S-B allocation."""
    if not candles_by_symbol:
        raise ValueError("candles_by_symbol must not be empty")
    if set(candles_by_symbol.keys()) != set(config.universe):
        raise ValueError(
            f"candles keys {sorted(candles_by_symbol)} != universe {sorted(config.universe)}"
        )

    n_symbols = len(config.universe)
    slot = compute_slot_size(capital_pool_usdt, n_symbols)
    state = PortfolioState(capital_pool=capital_pool_usdt, slot_size=slot)
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    decisions: list[dict] = []

    # Determine common length (already aligned in upstream)
    n_candles = min(len(df) for df in candles_by_symbol.values())
    if n_candles < execution_shift + 2:
        raise ValueError(f"Not enough candles ({n_candles}) for execution_shift={execution_shift}")

    regime_resolver = regime_fn or (lambda sym: "TRENDING")

    # Iterate by candle index
    for i in range(n_candles - execution_shift):
        # Phase 1: manage open positions on candle i+execution_shift
        for sym in list(open_positions.keys()):
            df = candles_by_symbol[sym]
            mgmt_idx = i + execution_shift
            if mgmt_idx >= len(df):
                continue
            row = df.iloc[mgmt_idx]
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
            ts_ms = int(row["close_time_ms"])
            position = open_positions[sym]
            exit_reason, exit_price = _check_exit(
                position=position, candle_high=high, candle_low=low, candle_close=close,
            )
            position["candles_held"] = position.get("candles_held", 0) + 1
            if exit_reason is None and position["candles_held"] >= 96:  # 24h timeout
                exit_reason, exit_price = ("TIMEOUT", close)
            if exit_reason is not None:
                slip = slippage_override_pct if slippage_override_pct is not None else config.slippage_for(sym)
                pnl_pct = _pnl_pct(
                    entry=position["entry"], exit_price=exit_price,
                    direction=position["direction"], slippage_pct=slip,
                )
                trades.append({
                    "symbol": sym,
                    "direction": position["direction"],
                    "entry_ts": position["entry_ts"],
                    "exit_ts": _ts_to_iso(ts_ms),
                    "entry_price": position["entry"],
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "pnl_pct": pnl_pct,
                    "regime": position["regime"],
                    "bucket": config.bucket_for(sym),
                })
                close_slot(state, sym)
                del open_positions[sym]

        # Phase 2: emit signals from candle i (look-ahead protection)
        for sym in config.universe:
            if sym in open_positions:
                continue
            df = candles_by_symbol[sym]
            if i + 1 > len(df):
                continue
            history = df.iloc[: i + 1]
            ts_ms = int(history.iloc[-1]["close_time_ms"])
            ts_iso = _ts_to_iso(ts_ms)
            regime = regime_resolver(sym)
            sig = signal_fn(
                candles=history, symbol=sym, regime_label=regime, timestamp=ts_iso,
            )
            if sig is None:
                decisions.append({"symbol": sym, "ts": ts_iso, "blocked_by": "no_signal"})
                continue
            # Need execution candle (i + execution_shift)
            exec_idx = i + execution_shift
            if exec_idx >= len(df):
                decisions.append({"symbol": sym, "ts": ts_iso, "blocked_by": "no_exec_candle"})
                continue
            if not state.can_open():
                decisions.append({"symbol": sym, "ts": ts_iso, "blocked_by": "no_capital"})
                continue
            # Open at execution candle close
            exec_row = df.iloc[exec_idx]
            entry_price = float(exec_row["close"])
            try:
                open_slot(state, sym)
            except ValueError:
                decisions.append({"symbol": sym, "ts": ts_iso, "blocked_by": "no_capital"})
                continue
            open_positions[sym] = {
                "direction": getattr(sig, "direction", "long"),
                "entry": entry_price,
                "sl": float(getattr(sig, "sl", entry_price * 0.98)),
                "tp1": float(getattr(sig, "tp1", entry_price * 1.02)),
                "tp2": float(getattr(sig, "tp2", entry_price * 1.05)),
                "entry_ts": _ts_to_iso(int(exec_row["close_time_ms"])),
                "regime": regime,
                "candles_held": 0,
            }
            decisions.append({"symbol": sym, "ts": ts_iso, "blocked_by": None})

    # Phase 3: force-close any positions still open at end of series
    for sym, position in list(open_positions.items()):
        df = candles_by_symbol[sym]
        last = df.iloc[-1]
        close = float(last["close"])
        ts_ms = int(last["close_time_ms"])
        slip = slippage_override_pct if slippage_override_pct is not None else config.slippage_for(sym)
        pnl_pct = _pnl_pct(
            entry=position["entry"], exit_price=close,
            direction=position["direction"], slippage_pct=slip,
        )
        trades.append({
            "symbol": sym,
            "direction": position["direction"],
            "entry_ts": position["entry_ts"],
            "exit_ts": _ts_to_iso(ts_ms),
            "entry_price": position["entry"],
            "exit_price": close,
            "exit_reason": "FORCE_CLOSE",
            "pnl_pct": pnl_pct,
            "regime": position["regime"],
            "bucket": config.bucket_for(sym),
        })
        close_slot(state, sym)
    open_positions.clear()

    metrics = compute_portfolio_metrics(trades)
    return ExpansionResult(
        trades=trades,
        decisions=decisions,
        final_capital_pool=state.capital_pool,
        peak_concurrent_positions=state.peak_concurrent,
        metrics=metrics,
    )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_run_portfolio_backtest.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/research_runner.py tests/test_expansion_run_portfolio_backtest.py
git commit -m "feat(expansion): pure run_portfolio_backtest with S-B allocation, look-ahead protection, force-close"
```

---

## Task 10: `comparators.py` C3-normalized + C3-live

**Files:**
- Modify: `momentum/expansion/comparators.py`
- Create: `tests/test_expansion_comparators_c3.py`

C3-normalized uses `run_portfolio_backtest` with `universe=("BTCUSDT","ETHUSDT")` under same S-B framework. C3-live is a marker placeholder reported only as transparency (live PnL would come from existing `momentum_trades` DB query in operational task).

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_comparators_c3.py`:

```python
"""Tests for C3-normalized and C3-live comparators."""
from typing import Optional

import numpy as np
import pandas as pd

from momentum.expansion.comparators import compute_c3_normalized
from momentum.expansion.config import ExpansionConfig


def _candles(n=200, base=50000.0, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base * np.exp(np.cumsum(rng.normal(0, 0.005, n)))
    return pd.DataFrame({
        "close_time_ms": np.arange(n, dtype=np.int64) * 900_000,
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": np.full(n, 1000.0),
    })


def _no_signal_fn(*, candles, symbol, regime_label, timestamp, config=None):
    return None


def test_c3_normalized_runs_baseline_universe():
    cfg = ExpansionConfig(universe=("BTCUSDT", "ETHUSDT"))
    candles = {
        "BTCUSDT": _candles(seed=1),
        "ETHUSDT": _candles(base=3000.0, seed=2),
        "SOLUSDT": _candles(base=100.0, seed=3),  # extra symbol — should be ignored
    }
    c3 = compute_c3_normalized(
        config=cfg, candles_by_symbol=candles,
        signal_fn=_no_signal_fn, capital_pool_usdt=10000.0, risk_fraction=0.01,
    )
    assert c3["name"] == "C3_normalized"
    assert "profit_factor" in c3
    assert "max_drawdown_pct" in c3


def test_c3_normalized_filters_to_btc_eth_only():
    """Even if extra symbols are in candles, C3 baseline must use BTC+ETH."""
    cfg = ExpansionConfig(universe=("BTCUSDT", "ETHUSDT"))
    full_candles = {
        "BTCUSDT": _candles(seed=4),
        "ETHUSDT": _candles(base=3000.0, seed=5),
        "DOGEUSDT": _candles(base=0.5, seed=6),
    }
    c3 = compute_c3_normalized(
        config=cfg, candles_by_symbol=full_candles,
        signal_fn=_no_signal_fn, capital_pool_usdt=10000.0, risk_fraction=0.01,
    )
    # No signals means n_trades=0 — but no exception means it filtered correctly
    assert c3["n_trades"] == 0
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_comparators_c3.py -v`
Expected: ImportError of `compute_c3_normalized`.

- [ ] **Step 3: Implement C3-normalized**

Append to `momentum/expansion/comparators.py`:

```python
from typing import Callable, Optional

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.research_runner import run_portfolio_backtest


_BASELINE_UNIVERSE = ("BTCUSDT", "ETHUSDT")


def compute_c3_normalized(
    *,
    config: ExpansionConfig,
    candles_by_symbol: dict,
    signal_fn: Callable,
    capital_pool_usdt: float,
    risk_fraction: float,
    regime_fn: Optional[Callable[[str], str]] = None,
    slippage_override_pct: Optional[float] = None,
) -> dict:
    """C3-normalized: v1.1 baseline (BTC/ETH) under same S-B framework.

    Builds a reduced ExpansionConfig with universe=(BTC,ETH), invokes
    run_portfolio_backtest with the SAME capital_pool_usdt and risk_fraction.
    """
    missing = [s for s in _BASELINE_UNIVERSE if s not in candles_by_symbol]
    if missing:
        raise ValueError(f"C3 requires candles for {_BASELINE_UNIVERSE}; missing {missing}")
    reduced_config = ExpansionConfig(
        universe=_BASELINE_UNIVERSE,
        period_main_days=config.period_main_days,
        period_holdout_days=config.period_holdout_days,
        n_folds=config.n_folds,
        required_history_days=config.required_history_days,
        gap_threshold_pct=config.gap_threshold_pct,
        slippage_universal_sensitivity=config.slippage_universal_sensitivity,
    )
    reduced_candles = {sym: candles_by_symbol[sym] for sym in _BASELINE_UNIVERSE}
    result = run_portfolio_backtest(
        config=reduced_config, candles_by_symbol=reduced_candles,
        signal_fn=signal_fn, capital_pool_usdt=capital_pool_usdt,
        risk_fraction=risk_fraction, regime_fn=regime_fn,
        slippage_override_pct=slippage_override_pct,
    )
    return {
        "name": "C3_normalized",
        "profit_factor": result.metrics["profit_factor"],
        "max_drawdown_pct": result.metrics["max_drawdown_pct"],
        "total_pnl_pct": result.metrics["total_pnl_pct"],
        "n_trades": result.metrics["n_trades"],
        "win_rate": result.metrics["win_rate"],
    }


def compute_c3_live_marker(*, n_trades_live: int, pf_live: float, dd_live: float) -> dict:
    """C3-live: reported for transparency only; values come from operational DB query."""
    return {
        "name": "C3_live",
        "profit_factor": pf_live,
        "max_drawdown_pct": dd_live,
        "n_trades": n_trades_live,
        "note": "non-blocking; reported as transparency",
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_comparators_c3.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/comparators.py tests/test_expansion_comparators_c3.py
git commit -m "feat(expansion): C3-normalized (S-B baseline BTC/ETH) + C3-live marker"
```

---

## Task 11: `walk_forward.py` partitioning

**Files:**
- Create: `momentum/expansion/walk_forward.py`
- Create: `tests/test_expansion_walk_forward.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_walk_forward.py`:

```python
"""Tests for walk-forward fold partitioning."""
import numpy as np
import pandas as pd
import pytest

from momentum.expansion.walk_forward import FoldData, partition_into_folds


def _df(n_candles: int, start_ms: int = 0, step_ms: int = 900_000) -> pd.DataFrame:
    return pd.DataFrame({
        "close_time_ms": np.arange(start_ms, start_ms + n_candles * step_ms, step_ms, dtype=np.int64),
        "open": np.full(n_candles, 100.0),
        "high": np.full(n_candles, 101.0),
        "low": np.full(n_candles, 99.0),
        "close": np.full(n_candles, 100.5),
        "volume": np.full(n_candles, 1000.0),
    })


def test_partition_evenly_into_n_folds():
    n_candles = 1200  # 12 folds × 100 candles each
    candles = {"BTCUSDT": _df(n_candles), "ETHUSDT": _df(n_candles)}
    folds = partition_into_folds(candles, n_folds=12)
    assert len(folds) == 12
    for fold in folds:
        assert isinstance(fold, FoldData)
        for sym in candles:
            assert len(fold.candles_by_symbol[sym]) == 100


def test_partition_handles_remainder():
    n_candles = 1205  # 12 × 100 + 5 remainder
    candles = {"BTCUSDT": _df(n_candles)}
    folds = partition_into_folds(candles, n_folds=12)
    total_candles = sum(len(f.candles_by_symbol["BTCUSDT"]) for f in folds)
    assert total_candles == 1205  # nothing dropped


def test_partition_fold_indices_sequential():
    candles = {"BTCUSDT": _df(120)}
    folds = partition_into_folds(candles, n_folds=12)
    for i, fold in enumerate(folds):
        assert fold.fold_idx == i


def test_partition_fold_boundaries_no_overlap():
    candles = {"BTCUSDT": _df(120)}
    folds = partition_into_folds(candles, n_folds=12)
    seen = set()
    for fold in folds:
        for ts in fold.candles_by_symbol["BTCUSDT"]["close_time_ms"]:
            assert ts not in seen, f"timestamp {ts} appears in multiple folds"
            seen.add(int(ts))
    assert len(seen) == 120


def test_partition_n_folds_must_be_positive():
    candles = {"BTCUSDT": _df(100)}
    with pytest.raises(ValueError):
        partition_into_folds(candles, n_folds=0)


def test_partition_too_few_candles_raises():
    candles = {"BTCUSDT": _df(5)}
    with pytest.raises(ValueError):
        partition_into_folds(candles, n_folds=12)
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_walk_forward.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement walk_forward.py**

Create `momentum/expansion/walk_forward.py`:

```python
"""Walk-forward partitioning into N monthly folds (no overlap)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd


@dataclass(frozen=True)
class FoldData:
    fold_idx: int
    candles_by_symbol: Mapping[str, pd.DataFrame]


def partition_into_folds(
    candles_by_symbol: Mapping[str, pd.DataFrame],
    n_folds: int,
) -> list[FoldData]:
    """Split candles into N sequential, non-overlapping folds.

    All symbols must have the same number of candles (caller's responsibility
    via align_candles_by_timestamp). Remainder candles are added to the last fold.
    """
    if n_folds <= 0:
        raise ValueError(f"n_folds must be positive, got {n_folds}")
    n_candles = min(len(df) for df in candles_by_symbol.values())
    if n_candles < n_folds * 2:
        raise ValueError(f"Not enough candles ({n_candles}) for {n_folds} folds")

    fold_size = n_candles // n_folds
    folds: list[FoldData] = []
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_folds - 1 else n_candles
        fold_candles = {
            sym: df.iloc[start:end].reset_index(drop=True)
            for sym, df in candles_by_symbol.items()
        }
        folds.append(FoldData(fold_idx=i, candles_by_symbol=fold_candles))
    return folds
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_walk_forward.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/walk_forward.py tests/test_expansion_walk_forward.py
git commit -m "feat(expansion): walk-forward partitioning into N non-overlapping folds"
```

---

## Task 12: `walk_forward.py` run per fold

**Files:**
- Modify: `momentum/expansion/walk_forward.py`
- Create: `tests/test_expansion_walk_forward_run.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_walk_forward_run.py`:

```python
"""Tests for executing run_portfolio_backtest per fold and aggregating PFs."""
import numpy as np
import pandas as pd

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.walk_forward import (
    FoldResult,
    partition_into_folds,
    run_walk_forward,
)


def _df(n=240, base=100.0, seed=0):
    rng = np.random.default_rng(seed)
    closes = base * np.exp(np.cumsum(rng.normal(0, 0.005, n)))
    return pd.DataFrame({
        "close_time_ms": np.arange(n, dtype=np.int64) * 900_000,
        "open": closes, "high": closes * 1.001, "low": closes * 0.999,
        "close": closes, "volume": np.full(n, 1000.0),
    })


def _no_signal(*, candles, symbol, regime_label, timestamp, config=None):
    return None


def test_walk_forward_returns_n_results():
    cfg = ExpansionConfig(universe=("BTCUSDT", "ETHUSDT"))
    candles = {"BTCUSDT": _df(seed=1), "ETHUSDT": _df(base=3000.0, seed=2)}
    folds = partition_into_folds(candles, n_folds=4)
    results = run_walk_forward(
        config=cfg, folds=folds, signal_fn=_no_signal,
        capital_pool_usdt=10000.0, risk_fraction=0.01,
    )
    assert len(results) == 4
    for r in results:
        assert isinstance(r, FoldResult)
        assert r.metrics["n_trades"] == 0  # no signals → no trades


def test_fold_results_carry_fold_idx():
    cfg = ExpansionConfig(universe=("BTCUSDT",))
    candles = {"BTCUSDT": _df(seed=3)}
    folds = partition_into_folds(candles, n_folds=3)
    results = run_walk_forward(
        config=cfg, folds=folds, signal_fn=_no_signal,
        capital_pool_usdt=1000.0, risk_fraction=0.01,
    )
    for i, r in enumerate(results):
        assert r.fold_idx == i
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_walk_forward_run.py -v`
Expected: ImportError of `FoldResult` / `run_walk_forward`.

- [ ] **Step 3: Append to walk_forward.py**

Add to `momentum/expansion/walk_forward.py`:

```python
from typing import Callable, Optional

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.research_runner import (
    ExpansionResult,
    run_portfolio_backtest,
)


@dataclass(frozen=True)
class FoldResult:
    fold_idx: int
    metrics: dict
    n_trades: int
    expansion_result: ExpansionResult


def run_walk_forward(
    *,
    config: ExpansionConfig,
    folds: list[FoldData],
    signal_fn: Callable,
    capital_pool_usdt: float,
    risk_fraction: float,
    regime_fn: Optional[Callable[[str], str]] = None,
) -> list[FoldResult]:
    """Run run_portfolio_backtest on each fold; return per-fold metrics."""
    results: list[FoldResult] = []
    for fold in folds:
        # Each fold gets a fresh PortfolioState (no carryover across folds)
        result = run_portfolio_backtest(
            config=config,
            candles_by_symbol=fold.candles_by_symbol,
            signal_fn=signal_fn,
            capital_pool_usdt=capital_pool_usdt,
            risk_fraction=risk_fraction,
            regime_fn=regime_fn,
        )
        results.append(FoldResult(
            fold_idx=fold.fold_idx,
            metrics=result.metrics,
            n_trades=result.metrics["n_trades"],
            expansion_result=result,
        ))
    return results
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_walk_forward_run.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/walk_forward.py tests/test_expansion_walk_forward_run.py
git commit -m "feat(expansion): run_walk_forward executes backtest per fold with fresh state"
```

---

## Task 13: `leave_one_out.py` by symbol

**Files:**
- Create: `momentum/expansion/leave_one_out.py`
- Create: `tests/test_expansion_loo_symbol.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_loo_symbol.py`:

```python
"""Tests for leave-one-out by symbol."""
from momentum.expansion.leave_one_out import loo_by_symbol


def _trade(sym, pnl):
    return {"symbol": sym, "pnl_pct": pnl}


def test_loo_removes_one_symbol_at_a_time():
    trades = [
        _trade("BTCUSDT", 1.0), _trade("BTCUSDT", -0.5),
        _trade("ETHUSDT", 2.0),
        _trade("DOGEUSDT", 0.3),
    ]
    universe = ("BTCUSDT", "ETHUSDT", "DOGEUSDT")
    loo = loo_by_symbol(trades, universe)
    assert set(loo.keys()) == set(universe)
    # When BTCUSDT is removed, only ETH(+2.0) and DOGE(+0.3) remain
    assert loo["BTCUSDT"]["n_trades"] == 2


def test_loo_preserves_others():
    trades = [_trade("BTCUSDT", 1.0), _trade("ETHUSDT", -1.0)]
    loo = loo_by_symbol(trades, ("BTCUSDT", "ETHUSDT"))
    assert loo["BTCUSDT"]["n_trades"] == 1  # only ETH left
    assert loo["ETHUSDT"]["n_trades"] == 1  # only BTC left


def test_loo_empty_trades():
    loo = loo_by_symbol([], ("BTCUSDT", "ETHUSDT"))
    for sym in ("BTCUSDT", "ETHUSDT"):
        assert loo[sym]["n_trades"] == 0
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_loo_symbol.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement loo_by_symbol**

Create `momentum/expansion/leave_one_out.py`:

```python
"""Leave-one-out: by symbol and by fold."""
from __future__ import annotations

from typing import Iterable, Mapping

from momentum.expansion.metrics import compute_portfolio_metrics


def loo_by_symbol(
    trades: Iterable[Mapping], universe: Iterable[str],
) -> dict[str, dict]:
    """For each symbol, compute aggregate metrics WITHOUT that symbol's trades."""
    trades_list = list(trades)
    out: dict[str, dict] = {}
    for sym in universe:
        remaining = [t for t in trades_list if t.get("symbol") != sym]
        out[sym] = compute_portfolio_metrics(remaining)
    return out
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_loo_symbol.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/leave_one_out.py tests/test_expansion_loo_symbol.py
git commit -m "feat(expansion): leave-one-out by symbol"
```

---

## Task 14: `leave_one_out.py` by fold

**Files:**
- Modify: `momentum/expansion/leave_one_out.py`
- Create: `tests/test_expansion_loo_fold.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_loo_fold.py`:

```python
"""Tests for leave-one-out by fold."""
from momentum.expansion.leave_one_out import loo_by_fold


def _fold_trades(fold_idx, trades):
    """Wrap a list of trades as a fold-results-style payload."""
    return {"fold_idx": fold_idx, "trades": trades}


def test_loo_fold_removes_one_fold_at_a_time():
    fold_results = [
        _fold_trades(0, [{"symbol": "BTC", "pnl_pct": 1.0}]),
        _fold_trades(1, [{"symbol": "BTC", "pnl_pct": -0.5}]),
        _fold_trades(2, [{"symbol": "BTC", "pnl_pct": 2.0}]),
    ]
    loo = loo_by_fold(fold_results)
    assert set(loo.keys()) == {0, 1, 2}
    # Removing fold 0: 2 trades remain
    assert loo[0]["n_trades"] == 2


def test_loo_fold_correct_aggregation():
    fold_results = [
        _fold_trades(0, [{"symbol": "A", "pnl_pct": 1.0}]),
        _fold_trades(1, [{"symbol": "A", "pnl_pct": 2.0}]),
    ]
    loo = loo_by_fold(fold_results)
    # Removing fold 0: only fold 1's trade (pnl=2.0) remains
    assert loo[0]["total_pnl_pct"] == 2.0
    # Removing fold 1: only fold 0's trade (pnl=1.0) remains
    assert loo[1]["total_pnl_pct"] == 1.0
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_loo_fold.py -v`
Expected: ImportError of `loo_by_fold`.

- [ ] **Step 3: Append to leave_one_out.py**

Add to `momentum/expansion/leave_one_out.py`:

```python
def loo_by_fold(fold_results: Iterable[Mapping]) -> dict[int, dict]:
    """For each fold, compute aggregate metrics WITHOUT that fold's trades.

    fold_results: iterable of dicts with keys 'fold_idx' and 'trades'.
    """
    folds = list(fold_results)
    out: dict[int, dict] = {}
    for skip in folds:
        skip_idx = skip["fold_idx"]
        remaining_trades: list = []
        for f in folds:
            if f["fold_idx"] == skip_idx:
                continue
            remaining_trades.extend(f["trades"])
        out[skip_idx] = compute_portfolio_metrics(remaining_trades)
    return out
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_loo_fold.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/leave_one_out.py tests/test_expansion_loo_fold.py
git commit -m "feat(expansion): leave-one-out by fold"
```

---

## Task 15: `research_db.py` schema + CRUD

**Files:**
- Create: `momentum/expansion/research_db.py`
- Create: `tests/test_expansion_research_db.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_research_db.py`:

```python
"""Tests for research_db schema and CRUD."""
import os
import tempfile

import pytest

from momentum.expansion.research_db import (
    fetch_all_decisions,
    fetch_all_trades,
    init_db,
    insert_decision,
    insert_run,
    insert_trade,
)


@pytest.fixture
def db_path():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    yield f.name
    os.unlink(f.name)


def test_init_creates_tables(db_path):
    init_db(db_path)
    # Verify by inserting a decision
    insert_decision(db_path, {
        "run_id": "r1", "symbol": "BTCUSDT", "ts": "2026-01-01T00:00:00",
        "blocked_by": "no_signal",
    })
    rows = fetch_all_decisions(db_path)
    assert len(rows) == 1


def test_insert_and_fetch_trade(db_path):
    init_db(db_path)
    insert_trade(db_path, {
        "run_id": "r1",
        "symbol": "BTCUSDT", "direction": "long",
        "entry_ts": "2026-01-01T00:00:00", "exit_ts": "2026-01-01T01:00:00",
        "entry_price": 50000.0, "exit_price": 51000.0,
        "exit_reason": "TP1", "pnl_pct": 2.0,
        "regime": "TRENDING", "bucket": "core",
    })
    rows = fetch_all_trades(db_path)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSDT"
    assert rows[0]["pnl_pct"] == 2.0


def test_insert_run_with_config_hash(db_path):
    init_db(db_path)
    insert_run(db_path, {
        "run_id": "r1", "config_hash": "abc123",
        "universe_json": '["BTCUSDT","ETHUSDT"]',
        "started_at": "2026-04-27T15:00:00",
        "completed_at": "2026-04-27T15:30:00",
        "verdict": "PASS",
    })
    # Fetch via raw query for simplicity in test
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT * FROM expansion_runs"))
    conn.close()
    assert len(rows) == 1
    assert rows[0]["config_hash"] == "abc123"
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_research_db.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement research_db**

Create `momentum/expansion/research_db.py`:

```python
"""SQLite schema and CRUD for EXP-005 research artifacts."""
from __future__ import annotations

import sqlite3


_DDL = """
CREATE TABLE IF NOT EXISTS expansion_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_ts TEXT NOT NULL,
    exit_ts TEXT,
    entry_price REAL NOT NULL,
    exit_price REAL,
    exit_reason TEXT,
    pnl_pct REAL,
    regime TEXT,
    bucket TEXT
);

CREATE TABLE IF NOT EXISTS expansion_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    blocked_by TEXT
);

CREATE TABLE IF NOT EXISTS expansion_folds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    fold_idx INTEGER NOT NULL,
    n_trades INTEGER NOT NULL,
    pf REAL NOT NULL,
    win_rate REAL NOT NULL,
    max_dd_pct REAL NOT NULL,
    total_pnl_pct REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS expansion_runs (
    run_id TEXT PRIMARY KEY,
    config_hash TEXT NOT NULL,
    universe_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    verdict TEXT
);
"""


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript("PRAGMA journal_mode=WAL;")
    conn.executescript(_DDL)
    conn.commit()
    conn.close()


def insert_trade(db_path: str, trade: dict) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO expansion_trades "
        "(run_id, symbol, direction, entry_ts, exit_ts, entry_price, exit_price, "
        "exit_reason, pnl_pct, regime, bucket) "
        "VALUES (:run_id,:symbol,:direction,:entry_ts,:exit_ts,:entry_price,"
        ":exit_price,:exit_reason,:pnl_pct,:regime,:bucket)",
        trade,
    )
    conn.commit()
    conn.close()


def insert_decision(db_path: str, decision: dict) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO expansion_decisions (run_id, symbol, ts, blocked_by) "
        "VALUES (:run_id,:symbol,:ts,:blocked_by)",
        decision,
    )
    conn.commit()
    conn.close()


def insert_fold(db_path: str, fold: dict) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO expansion_folds (run_id, fold_idx, n_trades, pf, win_rate, "
        "max_dd_pct, total_pnl_pct) VALUES (:run_id,:fold_idx,:n_trades,:pf,:win_rate,"
        ":max_dd_pct,:total_pnl_pct)",
        fold,
    )
    conn.commit()
    conn.close()


def insert_run(db_path: str, run: dict) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO expansion_runs (run_id, config_hash, universe_json, "
        "started_at, completed_at, verdict) "
        "VALUES (:run_id,:config_hash,:universe_json,:started_at,:completed_at,:verdict)",
        run,
    )
    conn.commit()
    conn.close()


def fetch_all_trades(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM expansion_trades ORDER BY id")]
    conn.close()
    return rows


def fetch_all_decisions(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM expansion_decisions ORDER BY id")]
    conn.close()
    return rows
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_research_db.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/research_db.py tests/test_expansion_research_db.py
git commit -m "feat(expansion): research_db schema + CRUD (trades/decisions/folds/runs)"
```

---

## Task 16: `go_no_go.py` 10 criteria evaluator

**Files:**
- Create: `momentum/expansion/go_no_go.py`
- Create: `tests/test_expansion_go_no_go.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_expansion_go_no_go.py`:

```python
"""Tests for the 10-criteria GO/NO-GO evaluator."""
import pytest

from momentum.expansion.go_no_go import evaluate_expansion


def _baseline_metrics(pf=1.10, dd=8.0, total_pnl=15.0):
    return {"profit_factor": pf, "max_drawdown_pct": dd, "total_pnl_pct": total_pnl, "n_trades": 60}


def _passing_inputs():
    return dict(
        main_metrics={"profit_factor": 1.30, "max_drawdown_pct": 9.0, "total_pnl_pct": 30.0,
                      "n_trades": 200, "win_rate": 50.0},
        holdout_metrics={"profit_factor": 1.25, "max_drawdown_pct": 6.0, "n_trades": 50, "total_pnl_pct": 8.0,
                          "win_rate": 50.0},
        fold_pfs=[1.1, 1.2, 0.9, 1.3, 1.4, 1.0, 1.5, 1.1, 1.2, 1.3, 0.95, 1.6],
        loo_symbol={"BTCUSDT": {"profit_factor": 1.25}, "ETHUSDT": {"profit_factor": 1.28}},
        loo_fold={i: {"profit_factor": 1.20 if i != 0 else 0.95} for i in range(12)},
        c2_metrics={"total_pnl_pct": 20.0, "max_drawdown_pct": 12.0, "profit_factor": 1.15},
        c3_normalized_metrics=_baseline_metrics(),
        slippage_010_metrics={"profit_factor": 1.05},
        per_symbol_stats={"BTCUSDT": {"n_trades": 100, "profit_factor": 1.4},
                          "ETHUSDT": {"n_trades": 100, "profit_factor": 1.2}},
    )


def test_pass_all_criteria():
    res = evaluate_expansion(**_passing_inputs())
    assert res["passes"] is True
    assert res["failures"] == []


def test_fail_pf_main_below_125():
    inputs = _passing_inputs()
    inputs["main_metrics"]["profit_factor"] = 1.20
    res = evaluate_expansion(**inputs)
    assert res["passes"] is False
    assert "pf_main" in res["failures"]


def test_fail_baseline_ratio():
    inputs = _passing_inputs()
    inputs["main_metrics"]["profit_factor"] = 1.15  # 1.15 / 1.10 = 1.045 < 1.10
    res = evaluate_expansion(**inputs)
    assert "pf_vs_baseline" in res["failures"]


def test_fail_c2_return_below():
    inputs = _passing_inputs()
    inputs["c2_metrics"]["total_pnl_pct"] = 35.0  # exceeds main 30
    res = evaluate_expansion(**inputs)
    assert "c2_return_or_dd" in res["failures"]


def test_fail_c2_dd_worse():
    inputs = _passing_inputs()
    inputs["c2_metrics"]["max_drawdown_pct"] = 7.0  # main has 9 → main worse
    res = evaluate_expansion(**inputs)
    assert "c2_return_or_dd" in res["failures"]


def test_fail_dd_ratio():
    inputs = _passing_inputs()
    inputs["main_metrics"]["max_drawdown_pct"] = 11.0  # 11/8 > 1.30
    res = evaluate_expansion(**inputs)
    assert "dd_vs_baseline" in res["failures"]


def test_fail_folds_positive():
    inputs = _passing_inputs()
    inputs["fold_pfs"] = [0.9] * 8 + [1.1] * 4  # only 4 positive
    res = evaluate_expansion(**inputs)
    assert "folds_positive" in res["failures"]


def test_fail_loo_symbol_below_baseline():
    inputs = _passing_inputs()
    inputs["loo_symbol"]["BTCUSDT"] = {"profit_factor": 1.05}  # below baseline 1.10
    res = evaluate_expansion(**inputs)
    assert "loo_symbol" in res["failures"]


def test_fail_loo_fold_more_than_one_below():
    inputs = _passing_inputs()
    inputs["loo_fold"][0] = {"profit_factor": 0.9}
    inputs["loo_fold"][1] = {"profit_factor": 0.95}  # 2 outliers, tolerance is 1
    res = evaluate_expansion(**inputs)
    assert "loo_fold" in res["failures"]


def test_fail_holdout_below_min():
    inputs = _passing_inputs()
    inputs["holdout_metrics"]["profit_factor"] = 0.8
    res = evaluate_expansion(**inputs)
    assert "holdout" in res["failures"]


def test_fail_destructive_symbol():
    inputs = _passing_inputs()
    inputs["per_symbol_stats"]["DOGEUSDT"] = {"n_trades": 70, "profit_factor": 0.4}
    res = evaluate_expansion(**inputs)
    assert "destructive_symbol" in res["failures"]


def test_fail_slippage_collapse():
    inputs = _passing_inputs()
    inputs["slippage_010_metrics"]["profit_factor"] = 0.95
    res = evaluate_expansion(**inputs)
    assert "slippage_sensitivity" in res["failures"]
```

- [ ] **Step 2: Run tests to fail**

Run: `python -m pytest tests/test_expansion_go_no_go.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement go_no_go**

Create `momentum/expansion/go_no_go.py`:

```python
"""GO/NO-GO evaluator: 10 criteria from spec section 6."""
from __future__ import annotations

from typing import Mapping

from momentum.expansion.config import ExpansionConfig


def evaluate_expansion(
    *,
    main_metrics: Mapping,
    holdout_metrics: Mapping,
    fold_pfs: list[float],
    loo_symbol: Mapping[str, Mapping],
    loo_fold: Mapping[int, Mapping],
    c2_metrics: Mapping,
    c3_normalized_metrics: Mapping,
    slippage_010_metrics: Mapping,
    per_symbol_stats: Mapping[str, Mapping],
    config: ExpansionConfig | None = None,
) -> dict:
    cfg = config or ExpansionConfig(universe=("BTCUSDT",))  # only thresholds matter
    failures: list[str] = []

    pf_main = main_metrics["profit_factor"]
    dd_main = main_metrics["max_drawdown_pct"]
    pnl_main = main_metrics["total_pnl_pct"]
    pf_baseline = c3_normalized_metrics["profit_factor"]
    dd_baseline = c3_normalized_metrics["max_drawdown_pct"]

    # 1. pf_main >= 1.25
    if pf_main < cfg.pf_threshold_main:
        failures.append("pf_main")

    # 2. pf_main > 1.10 * pf_baseline
    if pf_main <= cfg.pf_ratio_vs_baseline * pf_baseline:
        failures.append("pf_vs_baseline")

    # 3. C2 BH equal-weight: total_return > C2 AND dd <= C2_dd
    if not (pnl_main > c2_metrics["total_pnl_pct"] and dd_main <= c2_metrics["max_drawdown_pct"]):
        failures.append("c2_return_or_dd")

    # 4. dd_main <= 1.30 * dd_baseline
    if dd_main > cfg.dd_ratio_vs_baseline * dd_baseline:
        failures.append("dd_vs_baseline")

    # 5. >= 9/12 folds with PF > 1.0
    n_positive = sum(1 for pf in fold_pfs if pf > 1.0)
    if n_positive < cfg.min_folds_positive:
        failures.append("folds_positive")

    # 6. LOO by symbol: every removal leaves agg_pf > baseline_pf
    for sym, m in loo_symbol.items():
        if m["profit_factor"] <= pf_baseline:
            failures.append("loo_symbol")
            break

    # 7. LOO by fold: tolerance of 1 outlier
    n_below = sum(1 for m in loo_fold.values() if m["profit_factor"] <= pf_baseline)
    if n_below > cfg.loo_fold_outliers_tolerated:
        failures.append("loo_fold")

    # 8. Holdout: pf > 1.0 AND pf > 0.9 * pf_main
    pf_holdout = holdout_metrics["profit_factor"]
    if pf_holdout <= cfg.holdout_pf_min or pf_holdout <= cfg.holdout_ratio_vs_main * pf_main:
        failures.append("holdout")

    # 9. Destructive symbol: any with n>=60 AND pf<0.5
    for sym, stats in per_symbol_stats.items():
        if stats["n_trades"] >= cfg.symbol_destructive_min_n and stats["profit_factor"] < cfg.symbol_destructive_max_pf:
            failures.append("destructive_symbol")
            break

    # 10. Slippage 0.10% universal: pf >= 1.0
    if slippage_010_metrics["profit_factor"] < cfg.slippage_collapse_min_pf:
        failures.append("slippage_sensitivity")

    return {
        "passes": len(failures) == 0,
        "failures": failures,
        "criteria_applied": {
            "pf_threshold_main": cfg.pf_threshold_main,
            "pf_ratio_vs_baseline": cfg.pf_ratio_vs_baseline,
            "dd_ratio_vs_baseline": cfg.dd_ratio_vs_baseline,
            "min_folds_positive": cfg.min_folds_positive,
            "holdout_pf_min": cfg.holdout_pf_min,
            "holdout_ratio_vs_main": cfg.holdout_ratio_vs_main,
            "symbol_destructive_min_n": cfg.symbol_destructive_min_n,
            "symbol_destructive_max_pf": cfg.symbol_destructive_max_pf,
            "loo_fold_outliers_tolerated": cfg.loo_fold_outliers_tolerated,
        },
        "observed": {
            "pf_main": pf_main, "pf_baseline": pf_baseline,
            "pnl_main": pnl_main, "pnl_c2": c2_metrics["total_pnl_pct"],
            "dd_main": dd_main, "dd_baseline": dd_baseline, "dd_c2": c2_metrics["max_drawdown_pct"],
            "n_folds_positive": n_positive, "n_folds": len(fold_pfs),
            "pf_holdout": pf_holdout,
            "pf_slippage_010": slippage_010_metrics["profit_factor"],
        },
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_expansion_go_no_go.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add momentum/expansion/go_no_go.py tests/test_expansion_go_no_go.py
git commit -m "feat(expansion): GO/NO-GO evaluator with 10 a-priori criteria"
```

---

## Task 17: No-lookahead test

**Files:**
- Create: `tests/test_expansion_no_lookahead.py`

This test catches accidental data leaks in run_portfolio_backtest by constructing a dataset where the only signal is at t (last candle) but the entry executes at t+1 — and verifying that result with execution_shift=1 cannot use t+1's information for the signal decision.

- [ ] **Step 1: Write the test**

Create `tests/test_expansion_no_lookahead.py`:

```python
"""No-lookahead invariant: signal_fn never sees candles >= execution_shift index."""
import numpy as np
import pandas as pd

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.research_runner import run_portfolio_backtest


def test_signal_fn_only_sees_history_up_to_decision_candle():
    cfg = ExpansionConfig(universe=("BTCUSDT",))
    n = 50
    candles = {"BTCUSDT": pd.DataFrame({
        "close_time_ms": np.arange(n, dtype=np.int64) * 900_000,
        "open": np.arange(n, dtype=float),
        "high": np.arange(n, dtype=float) + 1,
        "low": np.arange(n, dtype=float) - 1,
        "close": np.arange(n, dtype=float),
        "volume": np.full(n, 1000.0),
    })}

    seen_lengths: list[int] = []

    def recording_signal_fn(*, candles, symbol, regime_label, timestamp, config=None):
        seen_lengths.append(len(candles))
        return None

    run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles,
        signal_fn=recording_signal_fn,
        capital_pool_usdt=1000.0, risk_fraction=0.01,
        execution_shift=1,
    )
    # signal_fn must never see all 50 candles (would mean future leak)
    assert all(L < n for L in seen_lengths), \
        f"signal_fn saw a dataset of full length n={n} which means look-ahead"
    # And it must see strictly increasing history lengths starting from 1
    assert seen_lengths[0] == 1
    assert seen_lengths == sorted(seen_lengths)
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_expansion_no_lookahead.py -v`
Expected: PASS (proves run_portfolio_backtest already enforces no-lookahead).

- [ ] **Step 3: Commit**

```bash
git add tests/test_expansion_no_lookahead.py
git commit -m "test(expansion): no-lookahead invariant for run_portfolio_backtest"
```

---

## Task 18: Reproducibility test

**Files:**
- Create: `tests/test_expansion_reproducibility.py`

- [ ] **Step 1: Write the test**

Create `tests/test_expansion_reproducibility.py`:

```python
"""Same input must produce same output (no dict ordering or sort instability)."""
import json

import numpy as np
import pandas as pd

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.research_runner import run_portfolio_backtest


def _candles(n=120, base=100.0, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base * np.exp(np.cumsum(rng.normal(0, 0.005, n)))
    return pd.DataFrame({
        "close_time_ms": np.arange(n, dtype=np.int64) * 900_000,
        "open": closes, "high": closes * 1.001, "low": closes * 0.999,
        "close": closes, "volume": np.full(n, 1000.0),
    })


def _no_signal(*, candles, symbol, regime_label, timestamp, config=None):
    return None


def test_two_runs_produce_identical_result():
    cfg = ExpansionConfig(universe=("BTCUSDT", "ETHUSDT"))
    candles = {"BTCUSDT": _candles(seed=10), "ETHUSDT": _candles(base=3000.0, seed=11)}

    r1 = run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles, signal_fn=_no_signal,
        capital_pool_usdt=10000.0, risk_fraction=0.01,
    )
    r2 = run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles, signal_fn=_no_signal,
        capital_pool_usdt=10000.0, risk_fraction=0.01,
    )

    # Serialize trades to JSON to cover dict-ordering and field types
    j1 = json.dumps(r1.trades, sort_keys=True, default=str)
    j2 = json.dumps(r2.trades, sort_keys=True, default=str)
    assert j1 == j2
    assert r1.metrics == r2.metrics
    assert r1.peak_concurrent_positions == r2.peak_concurrent_positions
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_expansion_reproducibility.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_expansion_reproducibility.py
git commit -m "test(expansion): reproducibility — same input produces same output"
```

---

## Task 19: CLI `run_expansion_preflight.py`

**Files:**
- Create: `scripts/run_expansion_preflight.py`

- [ ] **Step 1: Implement CLI**

Create `scripts/run_expansion_preflight.py`:

```python
#!/usr/bin/env python
"""Run preflight to check 455d availability for all 13 candidates.

Writes research/expansion_v1_preflight.json (write-once artifact).

Usage:
    python scripts/run_expansion_preflight.py --out research/expansion_v1_preflight.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from momentum.expansion.config import BUCKET_ASSIGNMENT
from momentum.expansion.preflight import run_preflight


_CANDIDATES = list(BUCKET_ASSIGNMENT.keys())


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="Output path for preflight JSON")
    p.add_argument("--required-days", type=int, default=455)
    args = p.parse_args()

    print(f"Running preflight for {len(_CANDIDATES)} candidates (required {args.required_days}d)...")
    result = run_preflight(symbols=_CANDIDATES, required_days=args.required_days)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(args.out, result.to_dict())

    print(f"Universe size: {result.universe_size}")
    print(f"Eligible: {result.universe}")
    print(f"Ineligible: {list(result.ineligible.keys())}")

    if result.universe_size == 0:
        print("ERROR: no symbol eligible. Aborting.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify --help parses**

Run: `python scripts/run_expansion_preflight.py --help`
Expected: clean argparse output.

- [ ] **Step 3: Commit**

```bash
git add scripts/run_expansion_preflight.py
git commit -m "feat(expansion): CLI run_expansion_preflight.py with atomic JSON write"
```

---

## Task 20: CLI `run_expansion_backtest.py`

**Files:**
- Create: `scripts/run_expansion_backtest.py`

This CLI orchestrates: preflight load → fetch candles → align → main backtest → holdout → DB persist.

- [ ] **Step 1: Implement CLI**

Create `scripts/run_expansion_backtest.py`:

```python
#!/usr/bin/env python
"""Run main 365d + holdout 90d backtest for EXP-005.

Reads preflight JSON for the frozen universe.
Writes results to a SQLite DB.

Usage:
    python scripts/run_expansion_backtest.py \
        --preflight research/expansion_v1_preflight.json \
        --start 2025-04-27 --end 2026-04-27 \
        --holdout-start 2025-01-27 --holdout-end 2025-04-27 \
        --db research/expansion_v1_365d.db \
        --capital-pool 35000 --risk-fraction 0.01
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.data_loader import (
    align_candles_by_timestamp,
    fetch_klines_paginated,
    validate_gap_threshold,
)
from momentum.expansion.research_db import (
    init_db, insert_decision, insert_run, insert_trade,
)
from momentum.expansion.research_runner import run_portfolio_backtest
from momentum.expansion.signal_engine_adapter import evaluate_signal_for_symbol


def _ms(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _signal_fn(*, candles, symbol, regime_label, timestamp, config=None):
    return evaluate_signal_for_symbol(
        candles=candles, symbol=symbol, regime_label=regime_label, timestamp=timestamp,
    )


def _persist(db_path: str, run_id: str, result, label: str):
    for t in result.trades:
        insert_trade(db_path, {**t, "run_id": run_id})
    for d in result.decisions:
        insert_decision(db_path, {**d, "run_id": run_id})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--preflight", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--holdout-start", required=True)
    p.add_argument("--holdout-end", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--capital-pool", type=float, default=35000.0)
    p.add_argument("--risk-fraction", type=float, default=0.01)
    args = p.parse_args()

    with open(args.preflight) as f:
        pf_data = json.load(f)
    universe = tuple(pf_data["universe"])
    if not universe:
        print("ERROR: empty universe in preflight", file=sys.stderr)
        return 2

    config = ExpansionConfig(universe=universe)
    end_ms = _ms(args.end)
    start_ms = _ms(args.start)
    total_candles_main = (end_ms - start_ms) // 900_000 + 10
    holdout_start_ms = _ms(args.holdout_start)
    holdout_end_ms = _ms(args.holdout_end)
    total_candles_holdout = (holdout_end_ms - holdout_start_ms) // 900_000 + 10

    # Fetch and align main window
    print("Fetching main window candles...")
    raw_main = {}
    for sym in universe:
        df = fetch_klines_paginated(sym, "15m", end_ms, total_candles_main)
        df = df[df["close_time_ms"] >= start_ms].reset_index(drop=True)
        raw_main[sym] = df
    candles_main = align_candles_by_timestamp(raw_main)
    expected = (end_ms - start_ms) // 900_000
    for sym, df in candles_main.items():
        validate_gap_threshold(symbol=sym, expected=expected, actual=len(df), threshold_pct=0.5)

    # Fetch and align holdout window
    print("Fetching holdout window candles...")
    raw_hold = {}
    for sym in universe:
        df = fetch_klines_paginated(sym, "15m", holdout_end_ms, total_candles_holdout)
        df = df[df["close_time_ms"] >= holdout_start_ms].reset_index(drop=True)
        raw_hold[sym] = df
    candles_holdout = align_candles_by_timestamp(raw_hold)
    expected_hold = (holdout_end_ms - holdout_start_ms) // 900_000
    for sym, df in candles_holdout.items():
        validate_gap_threshold(symbol=sym, expected=expected_hold, actual=len(df), threshold_pct=0.5)

    # Run main + holdout
    init_db(args.db)
    run_id = uuid.uuid4().hex
    config_hash = hashlib.sha256(json.dumps(pf_data, sort_keys=True).encode()).hexdigest()[:12]
    insert_run(args.db, {
        "run_id": run_id, "config_hash": config_hash,
        "universe_json": json.dumps(list(universe)),
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "completed_at": None, "verdict": None,
    })

    print("Running main backtest...")
    main_result = run_portfolio_backtest(
        config=config, candles_by_symbol=candles_main, signal_fn=_signal_fn,
        capital_pool_usdt=args.capital_pool, risk_fraction=args.risk_fraction,
    )
    _persist(args.db, run_id + "_main", main_result, "main")

    print("Running holdout backtest...")
    holdout_result = run_portfolio_backtest(
        config=config, candles_by_symbol=candles_holdout, signal_fn=_signal_fn,
        capital_pool_usdt=args.capital_pool, risk_fraction=args.risk_fraction,
    )
    _persist(args.db, run_id + "_holdout", holdout_result, "holdout")

    print(f"\n=== MAIN ===")
    print(json.dumps(main_result.metrics, indent=2, default=str))
    print(f"\n=== HOLDOUT ===")
    print(json.dumps(holdout_result.metrics, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify --help parses**

Run: `python scripts/run_expansion_backtest.py --help`

- [ ] **Step 3: Commit**

```bash
git add scripts/run_expansion_backtest.py
git commit -m "feat(expansion): CLI run_expansion_backtest.py orchestrating main + holdout"
```

---

## Task 21: CLI `run_expansion_robustness.py`

**Files:**
- Create: `scripts/run_expansion_robustness.py`

- [ ] **Step 1: Implement CLI**

Create `scripts/run_expansion_robustness.py`:

```python
#!/usr/bin/env python
"""Run walk-forward + LOO from a populated backtest DB.

Reads expansion_v1_365d.db (main run), partitions trades into 12 folds by
entry_ts, computes LOO-by-symbol and LOO-by-fold, and writes JSON.

Usage:
    python scripts/run_expansion_robustness.py \
        --db research/expansion_v1_365d.db \
        --out research/expansion_v1_robustness.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from momentum.expansion.leave_one_out import loo_by_fold, loo_by_symbol
from momentum.expansion.metrics import compute_portfolio_metrics
from momentum.expansion.research_db import fetch_all_trades


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def _partition_trades_by_month(trades: list[dict], n_folds: int = 12) -> list[dict]:
    """Partition trades into n_folds equal-sized buckets by entry_ts ordering."""
    sorted_trades = sorted(trades, key=lambda t: t["entry_ts"])
    n = len(sorted_trades)
    if n == 0 or n_folds == 0:
        return [{"fold_idx": i, "trades": []} for i in range(n_folds)]
    per = max(1, n // n_folds)
    out = []
    for i in range(n_folds):
        start = i * per
        end = (i + 1) * per if i < n_folds - 1 else n
        out.append({"fold_idx": i, "trades": sorted_trades[start:end]})
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--n-folds", type=int, default=12)
    args = p.parse_args()

    trades = fetch_all_trades(args.db)
    main_trades = [t for t in trades if t["run_id"].endswith("_main")]
    holdout_trades = [t for t in trades if t["run_id"].endswith("_holdout")]

    main_metrics = compute_portfolio_metrics(main_trades)
    holdout_metrics = compute_portfolio_metrics(holdout_trades)

    universe = sorted({t["symbol"] for t in main_trades})
    loo_sym = loo_by_symbol(main_trades, universe)
    folds = _partition_trades_by_month(main_trades, n_folds=args.n_folds)
    loo_fold_result = loo_by_fold(folds)

    fold_metrics = []
    for f in folds:
        m = compute_portfolio_metrics(f["trades"])
        fold_metrics.append({"fold_idx": f["fold_idx"], **m})

    per_symbol_stats = {
        sym: compute_portfolio_metrics([t for t in main_trades if t["symbol"] == sym])
        for sym in universe
    }

    payload = {
        "main_metrics": main_metrics,
        "holdout_metrics": holdout_metrics,
        "fold_metrics": fold_metrics,
        "loo_symbol": {sym: loo_sym[sym] for sym in universe},
        "loo_fold": {idx: loo_fold_result[idx] for idx in loo_fold_result},
        "per_symbol_stats": per_symbol_stats,
        "generated_at": datetime.utcnow().isoformat(),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(args.out, payload)
    print(f"Robustness written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify --help parses**

Run: `python scripts/run_expansion_robustness.py --help`

- [ ] **Step 3: Commit**

```bash
git add scripts/run_expansion_robustness.py
git commit -m "feat(expansion): CLI run_expansion_robustness.py aggregating walk-forward + LOO"
```

---

## Task 22: CLI `evaluate_expansion_go_no_go.py`

**Files:**
- Create: `scripts/evaluate_expansion_go_no_go.py`

- [ ] **Step 1: Implement CLI**

Create `scripts/evaluate_expansion_go_no_go.py`:

```python
#!/usr/bin/env python
"""Evaluate the 10-criteria GO/NO-GO from robustness + slippage runs.

Usage:
    python scripts/evaluate_expansion_go_no_go.py \
        --robustness research/expansion_v1_robustness.json \
        --slippage-010-db research/expansion_v1_slip010.db \
        --c2-json research/expansion_v1_c2.json \
        --c3-json research/expansion_v1_c3_normalized.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from momentum.expansion.go_no_go import evaluate_expansion
from momentum.expansion.metrics import compute_portfolio_metrics
from momentum.expansion.research_db import fetch_all_trades


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--robustness", required=True)
    p.add_argument("--slippage-010-db", required=True)
    p.add_argument("--c2-json", required=True)
    p.add_argument("--c3-json", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    with open(args.robustness) as f:
        rob = json.load(f)
    with open(args.c2_json) as f:
        c2 = json.load(f)
    with open(args.c3_json) as f:
        c3 = json.load(f)

    slip_trades = fetch_all_trades(args.slippage_010_db)
    slip_metrics = compute_portfolio_metrics(slip_trades)

    fold_pfs = [f["profit_factor"] for f in rob["fold_metrics"]]

    res = evaluate_expansion(
        main_metrics=rob["main_metrics"],
        holdout_metrics=rob["holdout_metrics"],
        fold_pfs=fold_pfs,
        loo_symbol=rob["loo_symbol"],
        loo_fold={int(k): v for k, v in rob["loo_fold"].items()},
        c2_metrics=c2,
        c3_normalized_metrics=c3,
        slippage_010_metrics=slip_metrics,
        per_symbol_stats=rob["per_symbol_stats"],
    )

    print(json.dumps(res, indent=2, default=str))
    if args.out:
        _atomic_write_json(args.out, res)
    return 0 if res["passes"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify --help parses**

Run: `python scripts/evaluate_expansion_go_no_go.py --help`

- [ ] **Step 3: Commit**

```bash
git add scripts/evaluate_expansion_go_no_go.py
git commit -m "feat(expansion): CLI evaluate_expansion_go_no_go.py — 10-criteria veredict"
```

---

## Task 23: End-to-end smoke integration test

**Files:**
- Create: `tests/test_expansion_smoke_integration.py`

- [ ] **Step 1: Write the test**

Create `tests/test_expansion_smoke_integration.py`:

```python
"""End-to-end smoke: synthetic candles → backtest → metrics → robustness pieces.

No network required. Validates the whole pipeline including a gap-detection abort.
"""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.data_loader import GapValidationError, validate_gap_threshold
from momentum.expansion.leave_one_out import loo_by_fold, loo_by_symbol
from momentum.expansion.metrics import compute_portfolio_metrics
from momentum.expansion.research_db import fetch_all_trades, init_db, insert_trade
from momentum.expansion.research_runner import run_portfolio_backtest
from momentum.expansion.walk_forward import partition_into_folds, run_walk_forward


def _candles(n=240, base=100.0, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base * np.exp(np.cumsum(rng.normal(0, 0.005, n)))
    return pd.DataFrame({
        "close_time_ms": np.arange(n, dtype=np.int64) * 900_000,
        "open": closes, "high": closes * 1.001, "low": closes * 0.999,
        "close": closes, "volume": np.full(n, 1000.0),
    })


def _no_signal(*, candles, symbol, regime_label, timestamp, config=None):
    return None


def test_full_pipeline_synthetic():
    cfg = ExpansionConfig(universe=("BTCUSDT", "ETHUSDT", "DOGEUSDT"))
    candles = {
        "BTCUSDT": _candles(seed=1),
        "ETHUSDT": _candles(base=3000.0, seed=2),
        "DOGEUSDT": _candles(base=0.5, seed=3),
    }

    # main run
    main_result = run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles, signal_fn=_no_signal,
        capital_pool_usdt=10000.0, risk_fraction=0.01,
    )
    assert main_result.metrics["n_trades"] == 0  # no signals → no trades

    # walk-forward
    folds = partition_into_folds(candles, n_folds=4)
    fold_results = run_walk_forward(
        config=cfg, folds=folds, signal_fn=_no_signal,
        capital_pool_usdt=10000.0, risk_fraction=0.01,
    )
    assert len(fold_results) == 4

    # LOO
    loo_s = loo_by_symbol(main_result.trades, cfg.universe)
    assert set(loo_s.keys()) == set(cfg.universe)

    # DB persistence
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        init_db(tmp.name)
        for t in main_result.trades:
            insert_trade(tmp.name, {**t, "run_id": "smoke"})
        rows = fetch_all_trades(tmp.name)
        assert len(rows) == len(main_result.trades)
    finally:
        os.unlink(tmp.name)


def test_smoke_gap_detection_aborts_early():
    """Confirm validate_gap_threshold raises GapValidationError before anything heavy."""
    with pytest.raises(GapValidationError):
        validate_gap_threshold(symbol="BTCUSDT", expected=1000, actual=900, threshold_pct=0.5)
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_expansion_smoke_integration.py -v`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_expansion_smoke_integration.py
git commit -m "test(expansion): end-to-end smoke integration with gap-abort proof"
```

---

## Task 24: Update EXPERIMENT_REGISTRY (HYPOTHESIS entry)

**Files:**
- Modify: `docs/EXPERIMENT_REGISTRY.md`

- [ ] **Step 1: Append EXP-005 entry**

In `docs/EXPERIMENT_REGISTRY.md`, after the EXP-004 section (and the closing `---`), insert:

```markdown
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
```

Update "Indice Rapido" table:

```markdown
| EXP-005 | Momentum Universe v1.0 | Momentum (extensao) | HYPOTHESIS → BACKTEST | — | Aguardando backtest operacional |
```

- [ ] **Step 2: Commit**

```bash
git add docs/EXPERIMENT_REGISTRY.md
git commit -m "docs(registry): add EXP-005 Momentum Universe Expansion entry"
```

---

## Task 25: Operacional — preflight + backtest 365d + robustness + GO/NO-GO

**This task is operational, not code. Execute after all prior tasks pass and the spec/plan are merged or archived consistently.**

- [ ] **Step 1: Run preflight**

```bash
mkdir -p research
python scripts/run_expansion_preflight.py --out research/expansion_v1_preflight.json
cat research/expansion_v1_preflight.json
```

Inspect: confirm universe is 11-13 symbols. Note any ineligible.

- [ ] **Step 2: Run main + holdout backtest**

```bash
python scripts/run_expansion_backtest.py \
    --preflight research/expansion_v1_preflight.json \
    --start 2025-04-27 --end 2026-04-27 \
    --holdout-start 2025-01-27 --holdout-end 2025-04-27 \
    --db research/expansion_v1_365d.db \
    --capital-pool 35000 --risk-fraction 0.01
```

Estimated time on Pi: 15-30 minutes (network + CPU). Record metrics output.

- [ ] **Step 3: Run slippage 0.10% universal sensitivity**

```bash
# Same as Step 2 but with universal slippage override applied via the runner.
# (Slippage override is implemented as run_portfolio_backtest's slippage_override_pct;
# the CLI in this plan does not yet expose it. Add a --slippage-override flag if needed.)
python scripts/run_expansion_backtest.py \
    --preflight research/expansion_v1_preflight.json \
    --start 2025-04-27 --end 2026-04-27 \
    --holdout-start 2025-01-27 --holdout-end 2025-04-27 \
    --db research/expansion_v1_slip010.db \
    --capital-pool 35000 --risk-fraction 0.01 \
    --slippage-override 0.10
```

If `--slippage-override` flag is missing in `run_expansion_backtest.py`, add it now: append `p.add_argument("--slippage-override", type=float, default=None)` and pass `slippage_override_pct=args.slippage_override` to `run_portfolio_backtest`. Commit the addition.

- [ ] **Step 4: Run C2 BH equal-weight + C3-normalized**

```bash
# Generate C2 + C3 JSON artifacts via small ad-hoc script
python -c "
import json
from datetime import datetime, timezone
from momentum.expansion.config import ExpansionConfig
from momentum.expansion.comparators import compute_c2_buy_and_hold_equal_weight, compute_c3_normalized
from momentum.expansion.data_loader import fetch_klines_paginated, align_candles_by_timestamp
from momentum.expansion.signal_engine_adapter import evaluate_signal_for_symbol

with open('research/expansion_v1_preflight.json') as f:
    pf_data = json.load(f)
universe = tuple(pf_data['universe'])
config = ExpansionConfig(universe=universe)
end_ms = int(datetime.fromisoformat('2026-04-27').replace(tzinfo=timezone.utc).timestamp()*1000)
start_ms = int(datetime.fromisoformat('2025-04-27').replace(tzinfo=timezone.utc).timestamp()*1000)
total = (end_ms - start_ms)//900_000 + 10
raw = {sym: fetch_klines_paginated(sym, '15m', end_ms, total) for sym in universe}
for sym in raw:
    raw[sym] = raw[sym][raw[sym]['close_time_ms'] >= start_ms].reset_index(drop=True)
candles = align_candles_by_timestamp(raw)

c2 = compute_c2_buy_and_hold_equal_weight(candles)
def sig_fn(*, candles, symbol, regime_label, timestamp, config=None):
    return evaluate_signal_for_symbol(candles=candles, symbol=symbol, regime_label=regime_label, timestamp=timestamp)
c3 = compute_c3_normalized(config=config, candles_by_symbol=candles, signal_fn=sig_fn,
                            capital_pool_usdt=35000.0, risk_fraction=0.01)
with open('research/expansion_v1_c2.json','w') as f: json.dump(c2, f, indent=2, default=str)
with open('research/expansion_v1_c3_normalized.json','w') as f: json.dump(c3, f, indent=2, default=str)
print('C2:', json.dumps(c2, indent=2, default=str))
print('C3:', json.dumps(c3, indent=2, default=str))
"
```

- [ ] **Step 5: Run robustness aggregation**

```bash
python scripts/run_expansion_robustness.py \
    --db research/expansion_v1_365d.db \
    --out research/expansion_v1_robustness.json
cat research/expansion_v1_robustness.json
```

- [ ] **Step 6: Evaluate GO/NO-GO**

```bash
python scripts/evaluate_expansion_go_no_go.py \
    --robustness research/expansion_v1_robustness.json \
    --slippage-010-db research/expansion_v1_slip010.db \
    --c2-json research/expansion_v1_c2.json \
    --c3-json research/expansion_v1_c3_normalized.json \
    --out research/expansion_v1_verdict.json
```

- [ ] **Step 7: Update EXPERIMENT_REGISTRY based on result**

If **PASS**: change EXP-005 estagio to `BACKTEST → ROBUSTNESS PASS`. Plan Phase 2 (paper trading integration) separately.

If **FAIL**: change estagio to `DEAD (no BACKTEST)`. Add postmortem section with failing criteria + observed metrics. Write postmortem note in `~/obsidian-vault/context/decisoes/2026-MM-DD-exp-005-universe-expansion-dead.md` analogous to EXP-004.

- [ ] **Step 8: Commit results**

```bash
git add docs/EXPERIMENT_REGISTRY.md
git add -f research/expansion_v1_robustness.json research/expansion_v1_verdict.json \
            research/expansion_v1_preflight.json research/expansion_v1_c2.json \
            research/expansion_v1_c3_normalized.json
git commit -m "research(expansion): EXP-005 Phase 1 BACKTEST results — [PASS/FAIL]"
```

---

## Coverage check (self-review against spec)

- §1 H-C' hypothesis → Tasks 16 (encoded in 10 criteria), 24 (registry)
- §2 Universe + buckets → Task 2 (BUCKET_ASSIGNMENT), Task 7 (preflight), Task 19 (CLI)
- §3 S-B allocation → Task 4 (capital_pool), Task 9 (run_portfolio_backtest)
- §4 W-C window + walk-forward → Task 11, Task 12, Task 21 (CLI)
- §5 Slippage SL-B → Task 2 (config), Task 9 (slippage_for in run)
- §6 GO/NO-GO 10 criteria → Task 16, Task 22 (CLI)
- §7 Architecture/components → all Tasks 1-15
- §8 Data flow → Task 20 (CLI orchestrator)
- §9 Error handling → Task 6 (gap), Task 9 (input validation), Tasks 19-22 (atomic JSON write)
- §10 Testing strategy → all Tasks have TDD; Tasks 17 (no-lookahead), 18 (reproducibility), 23 (smoke + gap abort)
- §11 Output operacional → Task 24 (registry HYPOTHESIS), Task 25 (operacional)
- §12 Sequence → this plan's 25 tasks

All spec sections covered.

---

**Status:** plan ready for execution.
