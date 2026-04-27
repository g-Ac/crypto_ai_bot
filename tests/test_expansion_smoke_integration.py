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
