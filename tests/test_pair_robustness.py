"""Tests for robustness checks."""
import numpy as np
import pytest

from pair_trading.robustness_check import monthly_consistency


def _mock_trades_with_month(month_pfs):
    """Build 3 synthetic sets of trades whose PF matches the given per-month values."""
    all_trades = []
    base_ts = 1700000000  # seconds
    month_sec = 30 * 24 * 3600
    for month_idx, pf in enumerate(month_pfs):
        # Build 10 trades in this month: 5 wins, 5 losses, adjust magnitudes for target PF
        if pf >= 1.0:
            win_sz = pf
            loss_sz = 1.0
        else:
            win_sz = 1.0
            loss_sz = 1.0 / max(pf, 1e-6) if pf > 0 else 10.0
        ts = base_ts + month_idx * month_sec
        for i in range(5):
            all_trades.append({
                "entry_time": f"2026-0{month_idx+1}-01T00:00:{i:02d}Z",
                "pnl_total_pct": win_sz,
            })
        for i in range(5):
            all_trades.append({
                "entry_time": f"2026-0{month_idx+1}-01T00:01:{i:02d}Z",
                "pnl_total_pct": -loss_sz,
            })
    return all_trades


def test_monthly_consistency_all_positive():
    trades = _mock_trades_with_month([1.5, 1.3, 1.1])
    result = monthly_consistency(trades, n_months=3)
    assert result["n_months"] == 3
    assert result["n_positive_pf"] == 3
    assert result["passes"] is True


def test_monthly_consistency_2_of_3():
    trades = _mock_trades_with_month([1.5, 0.5, 1.2])
    result = monthly_consistency(trades, n_months=3)
    assert result["n_positive_pf"] == 2
    assert result["passes"] is True  # 2 of 3 is the threshold


def test_monthly_consistency_1_of_3_fails():
    trades = _mock_trades_with_month([1.5, 0.3, 0.5])
    result = monthly_consistency(trades, n_months=3)
    assert result["n_positive_pf"] == 1
    assert result["passes"] is False
