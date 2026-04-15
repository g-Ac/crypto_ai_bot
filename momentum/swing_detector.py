"""Swing high/low detector for Momentum Pullback strategy.

Identifies confirmed swing points in price data without lookahead bias.
A swing high is confirmed only after `lookback` candles have formed lower
highs on both sides. Similarly for swing lows.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List

import pandas as pd


class SwingType(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class SwingPoint:
    """A confirmed swing point in price data."""

    index: int  # Position in the DataFrame
    timestamp: str  # Candle timestamp
    price: float  # High for swing high, low for swing low
    swing_type: SwingType


def detect_swings(
    candles: pd.DataFrame,
    lookback: int = 5,
) -> List[SwingPoint]:
    """Detect confirmed swing highs and lows.

    A swing high at index i is confirmed when:
      - candles[i].high >= all highs in [i-lookback, i+lookback]
      - At least `lookback` candles exist after i (no lookahead)

    A swing low at index i is confirmed when:
      - candles[i].low <= all lows in [i-lookback, i+lookback]
      - At least `lookback` candles exist after i (no lookahead)

    Args:
        candles: DataFrame with columns: high, low, close, timestamp (or open_time).
        lookback: Number of candles on each side to confirm a swing.
                  Default 5 (standard for 15m candles).

    Returns:
        List of SwingPoint sorted by index, oldest first.
    """
    if len(candles) < 2 * lookback + 1:
        return []

    highs = candles["high"].values
    lows = candles["low"].values

    # Resolve timestamp column
    if "timestamp" in candles.columns:
        timestamps = candles["timestamp"].astype(str).values
    elif "open_time" in candles.columns:
        timestamps = candles["open_time"].astype(str).values
    else:
        timestamps = [str(i) for i in range(len(candles))]

    swings: List[SwingPoint] = []
    n = len(candles)

    # Only scan indices where both sides have enough data.
    # Stop at n - lookback - 1 to guarantee no lookahead:
    # the confirmation window [i+1 .. i+lookback] must be fully formed.
    for i in range(lookback, n - lookback):
        h = highs[i]
        lo = lows[i]

        # --- Swing High check ---
        is_swing_high = True
        for j in range(i - lookback, i + lookback + 1):
            if j == i:
                continue
            if highs[j] > h:
                is_swing_high = False
                break

        # --- Swing Low check ---
        is_swing_low = True
        for j in range(i - lookback, i + lookback + 1):
            if j == i:
                continue
            if lows[j] < lo:
                is_swing_low = False
                break

        if is_swing_high:
            swings.append(SwingPoint(
                index=i,
                timestamp=timestamps[i],
                price=h,
                swing_type=SwingType.HIGH,
            ))
        if is_swing_low:
            swings.append(SwingPoint(
                index=i,
                timestamp=timestamps[i],
                price=lo,
                swing_type=SwingType.LOW,
            ))

    return swings


def last_impulse(
    swings: List[SwingPoint],
) -> tuple:
    """Extract the most recent impulse (swing low → swing high or vice versa).

    An impulse is the last pair of consecutive opposite swings.

    Returns:
        (start: SwingPoint, end: SwingPoint) or (None, None) if fewer than
        2 opposite swings exist.
    """
    if len(swings) < 2:
        return (None, None)

    # Walk backwards to find last two opposite-type swings
    end = swings[-1]
    for i in range(len(swings) - 2, -1, -1):
        if swings[i].swing_type != end.swing_type:
            return (swings[i], end)

    return (None, None)


def impulse_retracement_pct(
    start: SwingPoint,
    end: SwingPoint,
    current_price: float,
) -> float:
    """Calculate how much of the impulse has been retraced.

    Returns:
        Retracement as percentage (0-100+).
        0% = price at the end of the impulse (no retracement).
        50% = price halfway back to start.
        100% = price fully back to start.
        >100% = price went beyond start (structure broken).
    """
    impulse_range = abs(end.price - start.price)
    if impulse_range == 0:
        return 0.0

    if end.swing_type == SwingType.HIGH:
        # Upward impulse: retracement = how far price dropped from end
        retracement = end.price - current_price
    else:
        # Downward impulse: retracement = how far price rose from end
        retracement = current_price - end.price

    return (retracement / impulse_range) * 100.0
