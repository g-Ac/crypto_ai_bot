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
