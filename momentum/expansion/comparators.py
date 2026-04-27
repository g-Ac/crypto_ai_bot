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


from typing import Callable, Optional

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.research_runner import run_portfolio_backtest


_BASELINE_UNIVERSE = ("BTCUSDT", "ETHUSDT")


def compute_c3_normalized(
    *,
    config: ExpansionConfig,
    candles_by_symbol: dict,
    signal_fn: Callable,
    capital_pool_usdt: float,
    risk_fraction: float,
    regime_fn: Optional[Callable[[str], str]] = None,
    slippage_override_pct: Optional[float] = None,
) -> dict:
    """C3-normalized: v1.1 baseline (BTC/ETH) under same S-B framework.

    Builds a reduced ExpansionConfig with universe=(BTC,ETH), invokes
    run_portfolio_backtest with the SAME capital_pool_usdt and risk_fraction.
    """
    missing = [s for s in _BASELINE_UNIVERSE if s not in candles_by_symbol]
    if missing:
        raise ValueError(f"C3 requires candles for {_BASELINE_UNIVERSE}; missing {missing}")
    reduced_config = ExpansionConfig(
        universe=_BASELINE_UNIVERSE,
        period_main_days=config.period_main_days,
        period_holdout_days=config.period_holdout_days,
        n_folds=config.n_folds,
        required_history_days=config.required_history_days,
        gap_threshold_pct=config.gap_threshold_pct,
        slippage_universal_sensitivity=config.slippage_universal_sensitivity,
    )
    reduced_candles = {sym: candles_by_symbol[sym] for sym in _BASELINE_UNIVERSE}
    result = run_portfolio_backtest(
        config=reduced_config, candles_by_symbol=reduced_candles,
        signal_fn=signal_fn, capital_pool_usdt=capital_pool_usdt,
        risk_fraction=risk_fraction, regime_fn=regime_fn,
        slippage_override_pct=slippage_override_pct,
    )
    return {
        "name": "C3_normalized",
        "profit_factor": result.metrics["profit_factor"],
        "max_drawdown_pct": result.metrics["max_drawdown_pct"],
        "total_pnl_pct": result.metrics["total_pnl_pct"],
        "n_trades": result.metrics["n_trades"],
        "win_rate": result.metrics["win_rate"],
    }


def compute_c3_live_marker(*, n_trades_live: int, pf_live: float, dd_live: float) -> dict:
    """C3-live: reported for transparency only; values come from operational DB query."""
    return {
        "name": "C3_live",
        "profit_factor": pf_live,
        "max_drawdown_pct": dd_live,
        "n_trades": n_trades_live,
        "note": "non-blocking; reported as transparency",
    }
