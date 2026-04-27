"""Thin adapter to call the live evaluate_momentum_pullback engine.

The engine is NOT forked. EXP-005 imports the same function used in production.

The live evaluate_momentum_pullback ALWAYS returns a MomentumSignal (never None);
non-trade outcomes (REGIME_BLOCKED, NO_TREND, NO_VALID_PULLBACK, etc.) are encoded
as MomentumOutcome values. This adapter filters: returns None unless outcome == TRADE,
preserving the 'None = no trade' contract used by run_portfolio_backtest.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from momentum.config import MomentumConfig, MomentumOutcome
from momentum.momentum_trader import MomentumSignal, evaluate_momentum_pullback


def evaluate_signal_for_symbol(
    *,
    candles: pd.DataFrame,
    symbol: str,
    regime_label: str,
    timestamp: str,
    config: Optional[MomentumConfig] = None,
) -> Optional[MomentumSignal]:
    """Pass through to evaluate_momentum_pullback; filter to TRADE outcomes only.

    Returns the live MomentumSignal when outcome == TRADE, else None.
    Does not mutate inputs.
    """
    cfg = config or MomentumConfig()
    sig = evaluate_momentum_pullback(
        candles=candles,
        regime=regime_label,
        config=cfg,
        symbol=symbol,
        timestamp=timestamp,
    )
    if sig.outcome != MomentumOutcome.TRADE:
        return None
    return sig
