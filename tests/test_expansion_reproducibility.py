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
