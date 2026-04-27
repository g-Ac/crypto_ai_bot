"""GO/NO-GO evaluator: 10 criteria from spec section 6."""
from __future__ import annotations

from typing import Mapping

from momentum.expansion.config import ExpansionConfig


def evaluate_expansion(
    *,
    main_metrics: Mapping,
    holdout_metrics: Mapping,
    fold_pfs: list[float],
    loo_symbol: Mapping[str, Mapping],
    loo_fold: Mapping[int, Mapping],
    c2_metrics: Mapping,
    c3_normalized_metrics: Mapping,
    slippage_010_metrics: Mapping,
    per_symbol_stats: Mapping[str, Mapping],
    config: ExpansionConfig | None = None,
) -> dict:
    cfg = config or ExpansionConfig(universe=("BTCUSDT",))  # only thresholds matter
    failures: list[str] = []

    pf_main = main_metrics["profit_factor"]
    dd_main = main_metrics["max_drawdown_pct"]
    pnl_main = main_metrics["total_pnl_pct"]
    pf_baseline = c3_normalized_metrics["profit_factor"]
    dd_baseline = c3_normalized_metrics["max_drawdown_pct"]

    # 1. pf_main >= 1.25
    if pf_main < cfg.pf_threshold_main:
        failures.append("pf_main")

    # 2. pf_main > 1.10 * pf_baseline
    if pf_main <= cfg.pf_ratio_vs_baseline * pf_baseline:
        failures.append("pf_vs_baseline")

    # 3. C2 BH equal-weight: total_return > C2 AND dd <= C2_dd
    if not (pnl_main > c2_metrics["total_pnl_pct"] and dd_main <= c2_metrics["max_drawdown_pct"]):
        failures.append("c2_return_or_dd")

    # 4. dd_main <= 1.30 * dd_baseline
    if dd_main > cfg.dd_ratio_vs_baseline * dd_baseline:
        failures.append("dd_vs_baseline")

    # 5. >= 9/12 folds with PF > 1.0
    n_positive = sum(1 for pf in fold_pfs if pf > 1.0)
    if n_positive < cfg.min_folds_positive:
        failures.append("folds_positive")

    # 6. LOO by symbol: every removal leaves agg_pf > baseline_pf
    for sym, m in loo_symbol.items():
        if m["profit_factor"] <= pf_baseline:
            failures.append("loo_symbol")
            break

    # 7. LOO by fold: tolerance of 1 outlier
    n_below = sum(1 for m in loo_fold.values() if m["profit_factor"] <= pf_baseline)
    if n_below > cfg.loo_fold_outliers_tolerated:
        failures.append("loo_fold")

    # 8. Holdout: pf > 1.0 AND pf > 0.9 * pf_main
    pf_holdout = holdout_metrics["profit_factor"]
    if pf_holdout <= cfg.holdout_pf_min or pf_holdout <= cfg.holdout_ratio_vs_main * pf_main:
        failures.append("holdout")

    # 9. Destructive symbol: any with n>=60 AND pf<0.5
    for sym, stats in per_symbol_stats.items():
        if stats["n_trades"] >= cfg.symbol_destructive_min_n and stats["profit_factor"] < cfg.symbol_destructive_max_pf:
            failures.append("destructive_symbol")
            break

    # 10. Slippage 0.10% universal: pf >= 1.0
    if slippage_010_metrics["profit_factor"] < cfg.slippage_collapse_min_pf:
        failures.append("slippage_sensitivity")

    return {
        "passes": len(failures) == 0,
        "failures": failures,
        "criteria_applied": {
            "pf_threshold_main": cfg.pf_threshold_main,
            "pf_ratio_vs_baseline": cfg.pf_ratio_vs_baseline,
            "dd_ratio_vs_baseline": cfg.dd_ratio_vs_baseline,
            "min_folds_positive": cfg.min_folds_positive,
            "holdout_pf_min": cfg.holdout_pf_min,
            "holdout_ratio_vs_main": cfg.holdout_ratio_vs_main,
            "symbol_destructive_min_n": cfg.symbol_destructive_min_n,
            "symbol_destructive_max_pf": cfg.symbol_destructive_max_pf,
            "loo_fold_outliers_tolerated": cfg.loo_fold_outliers_tolerated,
        },
        "observed": {
            "pf_main": pf_main, "pf_baseline": pf_baseline,
            "pnl_main": pnl_main, "pnl_c2": c2_metrics["total_pnl_pct"],
            "dd_main": dd_main, "dd_baseline": dd_baseline, "dd_c2": c2_metrics["max_drawdown_pct"],
            "n_folds_positive": n_positive, "n_folds": len(fold_pfs),
            "pf_holdout": pf_holdout,
            "pf_slippage_010": slippage_010_metrics["profit_factor"],
        },
    }
