"""Tests for the 10-criteria GO/NO-GO evaluator."""
import pytest

from momentum.expansion.go_no_go import evaluate_expansion


def _baseline_metrics(pf=1.10, dd=8.0, total_pnl=15.0):
    return {"profit_factor": pf, "max_drawdown_pct": dd, "total_pnl_pct": total_pnl, "n_trades": 60}


def _passing_inputs():
    return dict(
        main_metrics={"profit_factor": 1.30, "max_drawdown_pct": 9.0, "total_pnl_pct": 30.0,
                      "n_trades": 200, "win_rate": 50.0},
        holdout_metrics={"profit_factor": 1.25, "max_drawdown_pct": 6.0, "n_trades": 50, "total_pnl_pct": 8.0,
                          "win_rate": 50.0},
        fold_pfs=[1.1, 1.2, 0.9, 1.3, 1.4, 1.0, 1.5, 1.1, 1.2, 1.3, 0.95, 1.6],
        loo_symbol={"BTCUSDT": {"profit_factor": 1.25}, "ETHUSDT": {"profit_factor": 1.28}},
        loo_fold={i: {"profit_factor": 1.20 if i != 0 else 0.95} for i in range(12)},
        c2_metrics={"total_pnl_pct": 20.0, "max_drawdown_pct": 12.0, "profit_factor": 1.15},
        c3_normalized_metrics=_baseline_metrics(),
        slippage_010_metrics={"profit_factor": 1.05},
        per_symbol_stats={"BTCUSDT": {"n_trades": 100, "profit_factor": 1.4},
                          "ETHUSDT": {"n_trades": 100, "profit_factor": 1.2}},
    )


def test_pass_all_criteria():
    res = evaluate_expansion(**_passing_inputs())
    assert res["passes"] is True
    assert res["failures"] == []


def test_fail_pf_main_below_125():
    inputs = _passing_inputs()
    inputs["main_metrics"]["profit_factor"] = 1.20
    res = evaluate_expansion(**inputs)
    assert res["passes"] is False
    assert "pf_main" in res["failures"]


def test_fail_baseline_ratio():
    inputs = _passing_inputs()
    inputs["main_metrics"]["profit_factor"] = 1.15  # 1.15 / 1.10 = 1.045 < 1.10
    res = evaluate_expansion(**inputs)
    assert "pf_vs_baseline" in res["failures"]


def test_fail_c2_return_below():
    inputs = _passing_inputs()
    inputs["c2_metrics"]["total_pnl_pct"] = 35.0  # exceeds main 30
    res = evaluate_expansion(**inputs)
    assert "c2_return_or_dd" in res["failures"]


def test_fail_c2_dd_worse():
    inputs = _passing_inputs()
    inputs["c2_metrics"]["max_drawdown_pct"] = 7.0  # main has 9 → main worse
    res = evaluate_expansion(**inputs)
    assert "c2_return_or_dd" in res["failures"]


def test_fail_dd_ratio():
    inputs = _passing_inputs()
    inputs["main_metrics"]["max_drawdown_pct"] = 11.0  # 11/8 > 1.30
    res = evaluate_expansion(**inputs)
    assert "dd_vs_baseline" in res["failures"]


def test_fail_folds_positive():
    inputs = _passing_inputs()
    inputs["fold_pfs"] = [0.9] * 8 + [1.1] * 4  # only 4 positive
    res = evaluate_expansion(**inputs)
    assert "folds_positive" in res["failures"]


def test_fail_loo_symbol_below_baseline():
    inputs = _passing_inputs()
    inputs["loo_symbol"]["BTCUSDT"] = {"profit_factor": 1.05}  # below baseline 1.10
    res = evaluate_expansion(**inputs)
    assert "loo_symbol" in res["failures"]


def test_fail_loo_fold_more_than_one_below():
    inputs = _passing_inputs()
    inputs["loo_fold"][0] = {"profit_factor": 0.9}
    inputs["loo_fold"][1] = {"profit_factor": 0.95}  # 2 outliers, tolerance is 1
    res = evaluate_expansion(**inputs)
    assert "loo_fold" in res["failures"]


def test_fail_holdout_below_min():
    inputs = _passing_inputs()
    inputs["holdout_metrics"]["profit_factor"] = 0.8
    res = evaluate_expansion(**inputs)
    assert "holdout" in res["failures"]


def test_fail_destructive_symbol():
    inputs = _passing_inputs()
    inputs["per_symbol_stats"]["DOGEUSDT"] = {"n_trades": 70, "profit_factor": 0.4}
    res = evaluate_expansion(**inputs)
    assert "destructive_symbol" in res["failures"]


def test_fail_slippage_collapse():
    inputs = _passing_inputs()
    inputs["slippage_010_metrics"]["profit_factor"] = 0.95
    res = evaluate_expansion(**inputs)
    assert "slippage_sensitivity" in res["failures"]
