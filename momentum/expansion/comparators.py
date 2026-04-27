"""Comparators: C1 cash, C2 BH equal-weight, C3-normalized, C3-live.

C1 is trivial (PF=1.0, DD=0). C2 is buy-and-hold equal-weight with cost zero
(baseline generoso per spec). C3-normalized and C3-live live in a later task.
"""
from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd


def compute_c1_cash() -> dict:
    """C1: cash position, no PnL, no DD."""
    return {
        "name": "C1_cash",
        "profit_factor": 1.0,
        "max_drawdown_pct": 0.0,
        "total_pnl_pct": 0.0,
    }


def compute_c2_buy_and_hold_equal_weight(
    candles_by_symbol: Mapping[str, pd.DataFrame],
) -> dict:
    """C2: BH equal-weight, no rebalance, zero-cost (no fees, no slippage).

    Returns total_pnl_pct, max_drawdown_pct, profit_factor.
    """
    if not candles_by_symbol:
        raise ValueError("candles_by_symbol must not be empty")

    closes = []
    for sym in sorted(candles_by_symbol.keys()):
        df = candles_by_symbol[sym]
        if len(df) < 2:
            raise ValueError(f"{sym} needs >= 2 candles")
        closes.append(df["close"].values.astype(float))

    n_steps = min(len(c) for c in closes)
    n_symbols = len(closes)
    weights = 1.0 / n_symbols

    # Equity curve: at each step, sum of weighted price ratios from t=0
    equity = np.zeros(n_steps)
    for c in closes:
        c_norm = c[:n_steps] / c[0]
        equity += weights * c_norm

    total_pnl_pct = (equity[-1] - 1.0) * 100.0

    # Max drawdown
    peak = np.maximum.accumulate(equity)
    dd_series = (peak - equity) / peak * 100.0
    max_dd_pct = float(dd_series.max())

    # PF for BH: ratio of upside to downside contributions of step returns
    step_returns = np.diff(equity)
    gains = step_returns[step_returns > 0].sum()
    losses = -step_returns[step_returns < 0].sum()
    if losses == 0:
        pf = float("inf") if gains > 0 else 0.0
    else:
        pf = float(gains / losses)

    return {
        "name": "C2_bh_equal_weight",
        "profit_factor": pf,
        "max_drawdown_pct": max_dd_pct,
        "total_pnl_pct": float(total_pnl_pct),
        "n_symbols": n_symbols,
    }
