"""Pullback detector for Momentum Pullback strategy.

Uses swing_detector to identify the last impulse, then evaluates whether
the current price represents a valid pullback (retracement within the
accepted range, structure intact).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from momentum.swing_detector import (
    SwingPoint,
    SwingType,
    detect_swings,
    impulse_retracement_pct,
    last_impulse,
)


class PullbackRejection(str, Enum):
    """Reason a pullback was rejected."""

    NO_IMPULSE = "no_impulse"
    RETRACEMENT_TOO_SHALLOW = "retracement_too_shallow"
    RETRACEMENT_TOO_DEEP = "retracement_too_deep"
    STRUCTURE_BROKEN = "structure_broken"


class TrendDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class PullbackResult:
    """Result of pullback detection."""

    valid: bool
    rejection: Optional[PullbackRejection]

    # Impulse data (populated when impulse exists)
    impulse_start: Optional[SwingPoint]
    impulse_end: Optional[SwingPoint]
    retracement_pct: float

    # Context
    current_price: float
    direction: TrendDirection


def detect_pullback(
    candles: pd.DataFrame,
    direction: TrendDirection,
    ema_slow_value: float,
    *,
    swing_lookback: int = 5,
    min_retracement_pct: float = 30.0,
    max_retracement_pct: float = 70.0,
) -> PullbackResult:
    """Detect whether current price is in a valid pullback.

    A valid pullback satisfies all three conditions:
      1. An impulse exists (two opposite swings found)
      2. Retracement is between min_retracement_pct and max_retracement_pct
      3. Structure is intact (price hasn't broken past EMA slow)

    Args:
        candles: DataFrame with high, low, close columns.
        direction: LONG or SHORT — the trend context from the caller.
        ema_slow_value: Current value of EMA 50 (caller computes this).
        swing_lookback: Lookback for swing detection (default 5).
        min_retracement_pct: Minimum retracement to qualify (default 30%).
        max_retracement_pct: Maximum retracement allowed (default 70%).

    Returns:
        PullbackResult with valid=True/False and rejection reason if invalid.
    """
    current_price = float(candles["close"].iloc[-1])

    # --- Step 1: Find impulse ---
    swings = detect_swings(candles, lookback=swing_lookback)
    start, end = last_impulse(swings)

    if start is None or end is None:
        return PullbackResult(
            valid=False,
            rejection=PullbackRejection.NO_IMPULSE,
            impulse_start=None,
            impulse_end=None,
            retracement_pct=0.0,
            current_price=current_price,
            direction=direction,
        )

    # Validate impulse direction matches trend context:
    # LONG trend → we want an upward impulse (end is swing HIGH)
    # SHORT trend → we want a downward impulse (end is swing LOW)
    impulse_matches = (
        (direction == TrendDirection.LONG and end.swing_type == SwingType.HIGH)
        or (direction == TrendDirection.SHORT and end.swing_type == SwingType.LOW)
    )

    if not impulse_matches:
        return PullbackResult(
            valid=False,
            rejection=PullbackRejection.NO_IMPULSE,
            impulse_start=start,
            impulse_end=end,
            retracement_pct=0.0,
            current_price=current_price,
            direction=direction,
        )

    # --- Step 2: Calculate retracement ---
    retracement = impulse_retracement_pct(start, end, current_price)

    if retracement < min_retracement_pct:
        return PullbackResult(
            valid=False,
            rejection=PullbackRejection.RETRACEMENT_TOO_SHALLOW,
            impulse_start=start,
            impulse_end=end,
            retracement_pct=retracement,
            current_price=current_price,
            direction=direction,
        )

    if retracement > max_retracement_pct:
        return PullbackResult(
            valid=False,
            rejection=PullbackRejection.RETRACEMENT_TOO_DEEP,
            impulse_start=start,
            impulse_end=end,
            retracement_pct=retracement,
            current_price=current_price,
            direction=direction,
        )

    # --- Step 3: Structure check ---
    structure_intact = _check_structure(direction, current_price, ema_slow_value)

    if not structure_intact:
        return PullbackResult(
            valid=False,
            rejection=PullbackRejection.STRUCTURE_BROKEN,
            impulse_start=start,
            impulse_end=end,
            retracement_pct=retracement,
            current_price=current_price,
            direction=direction,
        )

    # --- All checks passed ---
    return PullbackResult(
        valid=True,
        rejection=None,
        impulse_start=start,
        impulse_end=end,
        retracement_pct=retracement,
        current_price=current_price,
        direction=direction,
    )


def _check_structure(
    direction: TrendDirection,
    current_price: float,
    ema_slow_value: float,
) -> bool:
    """Check if trend structure is intact.

    LONG: price must be above EMA slow (not broken below support).
    SHORT: price must be below EMA slow (not broken above resistance).
    """
    if direction == TrendDirection.LONG:
        return current_price >= ema_slow_value
    else:
        return current_price <= ema_slow_value
