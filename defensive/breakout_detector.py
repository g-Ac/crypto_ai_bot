"""Layer 2: Breakout detection and Layer 4: Reclaim detection.

Detects breakout attempts from a compression range and subsequent
range reclaim (failed breakout).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from defensive.config import DefensiveConfig
from defensive.enums import Direction
from defensive.models import BreakoutEvent, CompressionState
from defensive.value_reference import compute_value_metrics


def detect_breakout(
    candles: pd.DataFrame,
    compression: CompressionState,
    config: DefensiveConfig,
) -> BreakoutEvent:
    """Detect a breakout attempt from compression range.

    Only looks for breakouts when compression is active.
    Requires close outside BB AND volume spike.

    Args:
        candles: 15m candles with [open, high, low, close, volume].
        compression: Current CompressionState (must be active).
        config: DefensiveConfig.

    Returns:
        BreakoutEvent (detected=True if breakout found on last candle).
    """
    if not compression.active or len(candles) < 21:
        return BreakoutEvent()

    vm = compute_value_metrics(candles)
    if vm.bb_upper == 0 or vm.bb_lower == 0:
        return BreakoutEvent()

    last = candles.iloc[-1]
    close = float(last["close"])
    volume = float(last["volume"])

    # Volume spike check
    vol_sma20 = float(candles["volume"].rolling(20).mean().iloc[-1])
    if vol_sma20 <= 0:
        return BreakoutEvent()
    volume_ratio = volume / vol_sma20

    has_volume_spike = volume_ratio >= config.breakout_volume_mult

    # Direction check — v0.2 allows breakout without volume spike
    if config.breakout_require_volume:
        breakout_up = close > vm.bb_upper and has_volume_spike
        breakout_down = close < vm.bb_lower and has_volume_spike
    else:
        breakout_up = close > vm.bb_upper
        breakout_down = close < vm.bb_lower

    if not breakout_up and not breakout_down:
        return BreakoutEvent()

    direction = Direction.LONG if breakout_up else Direction.SHORT
    bb_level = vm.bb_upper if breakout_up else vm.bb_lower
    ts = str(last.get("timestamp", "")) if "timestamp" in candles.columns else ""

    return BreakoutEvent(
        detected=True,
        direction=direction,
        price=close,
        volume_ratio=volume_ratio,
        bb_level=bb_level,
        timestamp=ts,
        candle_index=len(candles) - 1,
    )


def detect_reclaim(
    candles: pd.DataFrame,
    breakout: BreakoutEvent,
    config: DefensiveConfig,
) -> bool:
    """Check if the price has reclaimed the range after a breakout.

    Must be called on candles AFTER the breakout candle.
    Looks at the last candle in the DataFrame.

    Args:
        candles: 15m candles (must include candles after breakout).
        breakout: The BreakoutEvent that was detected.
        config: DefensiveConfig.

    Returns:
        True if reclaim detected on the last candle.
    """
    if not breakout.detected or len(candles) < 21:
        return False

    # How many candles since breakout
    candles_since = len(candles) - 1 - breakout.candle_index
    if candles_since < 1 or candles_since > config.breakout_reclaim_window:
        return False

    vm = compute_value_metrics(candles)
    close = float(candles.iloc[-1]["close"])

    if breakout.direction == Direction.LONG:
        # Breakout was UP — reclaim means close back below BB upper
        return close < vm.bb_upper
    else:
        # Breakout was DOWN — reclaim means close back above BB lower
        return close > vm.bb_lower
