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
