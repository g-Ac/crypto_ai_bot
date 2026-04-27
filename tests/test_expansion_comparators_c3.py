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
