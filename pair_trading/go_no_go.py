"""GO/NO-GO gate evaluator for BACKTEST → ROBUSTNESS transition.

Criteria from spec §9:
  - PF >= 1.2
  - WR >= 45%
  - n_trades >= 60 in 90d
  - max DD <= 15%
  - beats buy-and-hold BTC, buy-and-hold ETH, random trader p95 PF
  - does not collapse at +0.10% slippage (PF must remain >= 1.0)
"""
from __future__ import annotations

from typing import Dict


def evaluate_backtest_to_robustness(
    *,
    metrics: Dict[str, float],
    buy_hold_btc_pf: float,
    buy_hold_eth_pf: float,
    random_trader_p95_pf: float,
    slippage_sensitivity_pf_at_005: float,
    slippage_sensitivity_pf_at_010: float,
    pf_threshold: float = 1.2,
    wr_threshold: float = 45.0,
    min_trades: int = 60,
    max_dd_threshold: float = 15.0,
    slippage_min_pf: float = 1.0,
) -> Dict:
    failures = []

    pf = metrics["profit_factor"]
    wr = metrics["win_rate"]
    n = metrics["n_trades"]
    dd = metrics["max_drawdown_pct"]

    if pf < pf_threshold:
        failures.append("pf_main")
    if wr < wr_threshold:
        failures.append("win_rate")
    if n < min_trades:
        failures.append("n_trades")
    if dd > max_dd_threshold:
        failures.append("max_drawdown")

    # Must beat ALL 3 baselines
    if not (pf > buy_hold_btc_pf and pf > buy_hold_eth_pf):
        failures.append("buy_and_hold_baseline")
    if not (pf > random_trader_p95_pf):
        failures.append("random_baseline")

    # Slippage sensitivity: must not collapse at +0.10%
    if slippage_sensitivity_pf_at_010 < slippage_min_pf:
        failures.append("slippage_sensitivity")

    return {
        "passes": len(failures) == 0,
        "failures": failures,
        "criteria_applied": {
            "pf_threshold": pf_threshold,
            "wr_threshold": wr_threshold,
            "min_trades": min_trades,
            "max_dd_threshold": max_dd_threshold,
            "slippage_min_pf": slippage_min_pf,
        },
        "observed": {
            "pf": pf, "wr": wr, "n_trades": n, "dd": dd,
            "buy_hold_btc_pf": buy_hold_btc_pf,
            "buy_hold_eth_pf": buy_hold_eth_pf,
            "random_trader_p95_pf": random_trader_p95_pf,
            "slippage_pf_005": slippage_sensitivity_pf_at_005,
            "slippage_pf_010": slippage_sensitivity_pf_at_010,
        },
    }
