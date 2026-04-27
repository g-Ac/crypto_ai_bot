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
