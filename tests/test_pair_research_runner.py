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
    """BTC drifts up, ETH flat -> generates z excursions that revert periodically."""
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
