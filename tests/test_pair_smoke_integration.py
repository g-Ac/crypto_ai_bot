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
