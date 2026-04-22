"""Robustness checks for pair trading backtest — 4 tests per spec.

Each check returns a dict with `passes: bool` and detail metrics.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List

import numpy as np


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _pf(pnls: list) -> float:
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gw = sum(wins)
    gl = abs(sum(losses))
    if gl == 0:
        return float("inf") if gw > 0 else 0.0
    return gw / gl


def monthly_consistency(
    trades: List[Dict],
    n_months: int = 3,
    pf_threshold: float = 1.0,
) -> Dict:
    """TEST 1: PF >= pf_threshold in at least (n_months - 1) of n_months.

    Splits trades chronologically into n_months equal buckets.
    """
    if not trades:
        return {
            "n_months": n_months, "month_pfs": [],
            "n_positive_pf": 0, "passes": False,
        }

    sorted_trades = sorted(trades, key=lambda t: _parse_ts(t["entry_time"]))
    bucket_size = len(sorted_trades) // n_months
    if bucket_size == 0:
        return {
            "n_months": n_months, "month_pfs": [],
            "n_positive_pf": 0, "passes": False,
            "note": "too few trades to split into months",
        }

    month_pfs = []
    for i in range(n_months):
        start = i * bucket_size
        end = start + bucket_size if i < n_months - 1 else len(sorted_trades)
        bucket = sorted_trades[start:end]
        pnls = [t["pnl_total_pct"] for t in bucket]
        month_pfs.append(_pf(pnls))

    n_positive = sum(1 for pf in month_pfs if pf >= pf_threshold)
    passes = n_positive >= (n_months - 1)

    return {
        "n_months": n_months,
        "month_pfs": month_pfs,
        "n_positive_pf": n_positive,
        "pf_threshold": pf_threshold,
        "passes": passes,
    }
