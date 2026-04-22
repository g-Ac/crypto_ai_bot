"""Aggregate metrics over a list of closed trade dicts."""
from __future__ import annotations

from typing import Dict, List


def compute_metrics(trades: List[Dict]) -> Dict[str, float]:
    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "total_pnl_pct": 0.0, "avg_pnl_pct": 0.0,
            "max_drawdown_pct": 0.0,
        }

    pnls = [t["pnl_total_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss == 0:
        pf = float("inf") if gross_win > 0 else 0.0
    else:
        pf = gross_win / gross_loss

    total = sum(pnls)

    # Max drawdown on cumulative equity
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
        "win_rate": len(wins) / n * 100.0,
        "profit_factor": pf,
        "total_pnl_pct": total,
        "avg_pnl_pct": total / n,
        "max_drawdown_pct": max_dd,
    }
