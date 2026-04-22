"""Tests for robustness checks."""
import numpy as np
import pytest

from pair_trading.robustness_check import (
    correlation_bucket_analysis,
    holdout_oos,
    monthly_consistency,
    regime_breakdown,
)


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


def test_holdout_oos_pass():
    # Holdout PF = 0.9 passes (>= 0.8)
    holdout_trades = _mock_trades_with_month([0.9])[:10]
    result = holdout_oos(holdout_trades, pf_threshold=0.8)
    assert result["pf"] >= 0.8
    assert result["passes"] is True


def test_holdout_oos_fail():
    holdout_trades = _mock_trades_with_month([0.5])[:10]
    result = holdout_oos(holdout_trades, pf_threshold=0.8)
    assert result["passes"] is False


def test_regime_breakdown_no_collapse():
    trades = [
        {"btc_regime_entry": "TRENDING", "pnl_total_pct": 2.0} for _ in range(20)
    ] + [
        {"btc_regime_entry": "TRENDING", "pnl_total_pct": -1.0} for _ in range(10)
    ] + [
        {"btc_regime_entry": "WEAK_TREND", "pnl_total_pct": 3.0} for _ in range(15)
    ] + [
        {"btc_regime_entry": "WEAK_TREND", "pnl_total_pct": -1.0} for _ in range(5)
    ]
    result = regime_breakdown(trades, min_trades_per_regime=20, pf_floor=0.5)
    assert result["passes"] is True
    assert "TRENDING" in result["regime_stats"]


def test_regime_breakdown_collapse_fails():
    trades = (
        [{"btc_regime_entry": "TRENDING", "pnl_total_pct": 1.0} for _ in range(5)]
        + [{"btc_regime_entry": "TRENDING", "pnl_total_pct": -5.0} for _ in range(20)]
    )
    result = regime_breakdown(trades, min_trades_per_regime=20, pf_floor=0.5)
    assert result["passes"] is False
    assert result["regime_stats"]["TRENDING"]["pf"] < 0.5


def test_correlation_bucket_edge_in_high_corr():
    """Edge concentrated in high-correlation bucket = expected, OK."""
    trades = (
        [{"correlation": 0.8, "pnl_total_pct": 2.0} for _ in range(20)]
        + [{"correlation": 0.4, "pnl_total_pct": -1.0} for _ in range(20)]
    )
    result = correlation_bucket_analysis(trades)
    # Report only — always passes (diagnostic)
    assert result["passes"] is True
    assert "high" in result["bucket_stats"]
    assert result["bucket_stats"]["high"]["pf"] > result["bucket_stats"]["low"]["pf"]


def test_correlation_bucket_edge_in_low_corr_warns():
    trades = (
        [{"correlation": 0.3, "pnl_total_pct": 2.0} for _ in range(20)]
        + [{"correlation": 0.8, "pnl_total_pct": -1.0} for _ in range(20)]
    )
    result = correlation_bucket_analysis(trades)
    assert result["passes"] is True  # diagnostic only — does not block
    assert result["warning"] is not None
    assert "low" in result["warning"].lower()
