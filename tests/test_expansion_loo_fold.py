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
