"""Value reference calculations: VWAP, z-score, percentile rank, BB metrics.

Shared between CFER (BB-based) and RAVR (VWAP/z-score-based).
All functions are pure — no side effects, no API calls.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from defensive.models import ValueMetrics


def compute_value_metrics(candles: pd.DataFrame, vwap_period: int = 96) -> ValueMetrics:
    """Compute all value reference metrics from a candle DataFrame.

    Args:
        candles: DataFrame with columns [open, high, low, close, volume].
                 Must be sorted ascending by time. Index is irrelevant.
        vwap_period: Number of candles for rolling VWAP (default 96 = 24h of 15m).

    Returns:
        ValueMetrics with current values (last row).
    """
    if len(candles) < 20:
        return ValueMetrics()

    close = candles["close"].values
    high = candles["high"].values
    low = candles["low"].values
    volume = candles["volume"].values

    # Bollinger Bands (20, 2σ)
    sma20 = pd.Series(close).rolling(20).mean().values
    std20 = pd.Series(close).rolling(20).std(ddof=0).values
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_mid = sma20

    # BB Width %
    bb_width_pct = np.where(bb_mid > 0, (bb_upper - bb_lower) / bb_mid * 100, 0.0)

    # ATR(14)
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    tr = np.concatenate([[high[0] - low[0]], tr])
    atr = pd.Series(tr).rolling(14).mean().values
    atr_pct = np.where(close > 0, atr / close * 100, 0.0)

    # VWAP rolling
    typical = (high + low + close) / 3.0
    vwap_window = min(vwap_period, len(candles))
    cum_tp_vol = pd.Series(typical * volume).rolling(vwap_window).sum().values
    cum_vol = pd.Series(volume).rolling(vwap_window).sum().values
    vwap = np.where(cum_vol > 0, cum_tp_vol / cum_vol, close)

    # Z-score (price vs VWAP, std over 50 periods)
    price_std = pd.Series(close).rolling(50).std(ddof=0).values
    z_score = np.where(price_std > 0, (close - vwap) / price_std, 0.0)

    last = len(candles) - 1
    return ValueMetrics(
        vwap=float(vwap[last]),
        z_score=float(z_score[last]),
        bb_mid=float(bb_mid[last]),
        bb_upper=float(bb_upper[last]),
        bb_lower=float(bb_lower[last]),
        bb_width_pct=float(bb_width_pct[last]),
        atr=float(atr[last]) if not np.isnan(atr[last]) else 0.0,
        atr_pct=float(atr_pct[last]) if not np.isnan(atr_pct[last]) else 0.0,
    )


def percentile_rank(value: float, series: np.ndarray) -> float:
    """Percentile rank of value within series (0-100)."""
    if len(series) == 0:
        return 50.0
    return float(np.sum(series < value) / len(series) * 100)


def bb_width_series(candles: pd.DataFrame) -> np.ndarray:
    """Return BB Width % as array, aligned with candles index."""
    close = candles["close"].values
    sma20 = pd.Series(close).rolling(20).mean().values
    std20 = pd.Series(close).rolling(20).std(ddof=0).values
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    return np.where(sma20 > 0, (bb_upper - bb_lower) / sma20 * 100, 0.0)


def atr_series(candles: pd.DataFrame, period: int = 14) -> np.ndarray:
    """Return ATR as array."""
    high = candles["high"].values
    low = candles["low"].values
    close = candles["close"].values
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    tr = np.concatenate([[high[0] - low[0]], tr])
    return pd.Series(tr).rolling(period).mean().values
