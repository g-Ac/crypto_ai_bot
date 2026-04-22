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
