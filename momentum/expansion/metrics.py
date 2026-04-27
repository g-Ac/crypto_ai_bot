"""Portfolio metrics for EXP-005 — reescritos do zero, sem reuso de EXP-004."""
from __future__ import annotations

import math
from typing import Iterable, Mapping


def compute_portfolio_metrics(trades: Iterable[Mapping]) -> dict:
    """Compute aggregate portfolio metrics from a list of closed trades.

    Each trade must have key 'pnl_pct' (float). Other keys are ignored.
    """
    trades_list = list(trades)
    n = len(trades_list)
    if n == 0:
        return {
            "n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "total_pnl_pct": 0.0, "avg_pnl_pct": 0.0, "max_drawdown_pct": 0.0,
        }

    pnls = [float(t["pnl_pct"]) for t in trades_list]
    total = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    win_rate = (wins / n) * 100.0

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)  # positive number
    if gross_loss == 0:
        profit_factor = math.inf if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

    # Max drawdown over equity curve
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        "n_trades": n,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_pnl_pct": total,
        "avg_pnl_pct": total / n,
        "max_drawdown_pct": max_dd,
    }
