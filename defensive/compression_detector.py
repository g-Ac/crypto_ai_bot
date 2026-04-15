"""Layer 1: Compression detection.

Detects real compression — not just "BB is tight", but actively contracting
volatility with declining ATR and stable/low volume.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from defensive.config import DefensiveConfig
from defensive.models import CompressionState
from defensive.value_reference import atr_series, bb_width_series, percentile_rank


def detect_compression(candles: pd.DataFrame, config: DefensiveConfig) -> CompressionState:
    """Evaluate whether the market is in a compression state.

    Args:
        candles: DataFrame with [open, high, low, close, volume], 15m timeframe,
                 at least config.compression_lookback + 20 rows.
        config: DefensiveConfig with compression parameters.

    Returns:
        CompressionState indicating whether compression is active and metrics.
    """
    min_rows = config.compression_lookback + 20  # 20 for BB warmup
    if len(candles) < min_rows:
        return CompressionState()

    # BB Width series
    bw = bb_width_series(candles)

    # Need at least compression_min_decline + 1 valid BB values at end
    valid_bw = bw[~np.isnan(bw)]
    if len(valid_bw) < config.compression_min_decline + 1:
        return CompressionState()

    # Count consecutive declining candles from the end
    consecutive = 0
    for i in range(len(bw) - 1, 0, -1):
        if np.isnan(bw[i]) or np.isnan(bw[i - 1]):
            break
        if bw[i] < bw[i - 1]:
            consecutive += 1
        else:
            break

    # Percentile of current BB Width within lookback window
    lookback = bw[-config.compression_lookback:]
    lookback_valid = lookback[~np.isnan(lookback)]
    current_bw = float(bw[-1]) if not np.isnan(bw[-1]) else 0.0
    pct = percentile_rank(current_bw, lookback_valid)

    # ATR declining
    atr = atr_series(candles)
    atr_check = config.compression_atr_lookback
    atr_declining = False
    if len(atr) >= atr_check + 1:
        recent_atr = atr[-(atr_check + 1):]
        if not any(np.isnan(recent_atr)):
            atr_declining = float(recent_atr[-1]) < float(recent_atr[0])

    # Volume stable/low
    vol = candles["volume"].values
    vol_sma20 = pd.Series(vol).rolling(20).mean().values
    vol_stable = True
    if not np.isnan(vol_sma20[-1]) and vol_sma20[-1] > 0:
        vol_stable = vol[-1] <= vol_sma20[-1] * config.compression_volume_mult

    # Determine if compression is active
    active = (
        consecutive >= config.compression_min_decline
        and pct < config.compression_percentile
        and atr_declining
        and vol_stable
    )

    # Timestamp of when compression started (approximate)
    since = ""
    if active and "timestamp" in candles.columns:
        start_idx = max(0, len(candles) - 1 - consecutive)
        since = str(candles.iloc[start_idx].get("timestamp", ""))

    return CompressionState(
        active=active,
        bb_width_current=current_bw,
        bb_width_percentile=pct,
        consecutive_decline=consecutive,
        atr_declining=atr_declining,
        volume_stable=vol_stable,
        since=since,
    )
