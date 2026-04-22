"""Tests for go_no_go evaluator."""
import pytest

from pair_trading.go_no_go import evaluate_backtest_to_robustness


def _metrics(pf, wr, n, dd):
    return {
        "profit_factor": pf, "win_rate": wr,
        "n_trades": n, "max_drawdown_pct": dd,
    }


def test_pass_all_criteria():
    res = evaluate_backtest_to_robustness(
        metrics=_metrics(1.3, 50.0, 80, 10.0),
        buy_hold_btc_pf=1.1,
        buy_hold_eth_pf=1.0,
        random_trader_p95_pf=1.15,
        slippage_sensitivity_pf_at_005=1.22,
        slippage_sensitivity_pf_at_010=1.18,
    )
    assert res["passes"] is True


def test_fail_pf_below_threshold():
    res = evaluate_backtest_to_robustness(
        metrics=_metrics(1.1, 50.0, 80, 10.0),
        buy_hold_btc_pf=1.0, buy_hold_eth_pf=0.9,
        random_trader_p95_pf=1.0,
        slippage_sensitivity_pf_at_005=1.05,
        slippage_sensitivity_pf_at_010=1.0,
    )
    assert res["passes"] is False
    assert "pf_main" in res["failures"]


def test_fail_dd_too_high():
    res = evaluate_backtest_to_robustness(
        metrics=_metrics(1.3, 50.0, 80, 20.0),
        buy_hold_btc_pf=1.0, buy_hold_eth_pf=0.9,
        random_trader_p95_pf=1.1,
        slippage_sensitivity_pf_at_005=1.22,
        slippage_sensitivity_pf_at_010=1.18,
    )
    assert res["passes"] is False
    assert "max_drawdown" in res["failures"]


def test_fail_not_beating_random():
    res = evaluate_backtest_to_robustness(
        metrics=_metrics(1.3, 50.0, 80, 10.0),
        buy_hold_btc_pf=1.0, buy_hold_eth_pf=0.9,
        random_trader_p95_pf=1.4,  # random beats our 1.3
        slippage_sensitivity_pf_at_005=1.22,
        slippage_sensitivity_pf_at_010=1.18,
    )
    assert res["passes"] is False
    assert "random_baseline" in res["failures"]


def test_fail_collapse_at_010_slippage():
    res = evaluate_backtest_to_robustness(
        metrics=_metrics(1.3, 50.0, 80, 10.0),
        buy_hold_btc_pf=1.0, buy_hold_eth_pf=0.9,
        random_trader_p95_pf=1.15,
        slippage_sensitivity_pf_at_005=1.1,
        slippage_sensitivity_pf_at_010=0.95,  # collapses
    )
    assert res["passes"] is False
    assert "slippage_sensitivity" in res["failures"]
