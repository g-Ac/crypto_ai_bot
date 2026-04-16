"""Technical indicators for the 5-minute trading system.

Calculated once per cycle, reused by all engines.
Uses the `ta` library (same as indicators_1m.py).
"""
import numpy as np
import pandas as pd
import ta


def add_indicators_5m(df: pd.DataFrame) -> pd.DataFrame:
    """Add all indicators needed for 5-minute engines.

    Args:
        df: DataFrame with columns: open, high, low, close, volume

    Returns:
        Same DataFrame with indicator columns added.
    """
    # Moving averages
    df["ema8"] = ta.trend.ema_indicator(df["close"], window=8)
    df["ema21"] = ta.trend.ema_indicator(df["close"], window=21)
    df["sma20"] = ta.trend.sma_indicator(df["close"], window=20)

    # Volatility
    if len(df) >= 14:
        atr_raw = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=14
        )
        # ta fills pre-window rows with 0 instead of NaN — normalise to NaN
        df["atr14"] = atr_raw.replace(0, np.nan)
    else:
        df["atr14"] = np.nan
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_bandwidth"] = bb.bollinger_wband()

    # Momentum
    df["rsi14"] = ta.momentum.rsi(df["close"], window=14)

    # Volume
    df["vol_avg20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg20"]

    # Rolling VWAP (crypto 24/7 — no daily reset, use 200-candle window)
    typical = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical * df["volume"]
    df["vwap"] = tp_vol.rolling(200).sum() / df["volume"].rolling(200).sum()

    # Candle properties
    df["body"] = (df["close"] - df["open"]).abs()
    candle_range = df["high"] - df["low"]
    df["range"] = candle_range
    df["body_ratio"] = df["body"] / candle_range.replace(0, np.nan)
    df["upper_shadow"] = df["high"] - df[["close", "open"]].max(axis=1)
    df["lower_shadow"] = df[["close", "open"]].min(axis=1) - df["low"]
    df["is_green"] = df["close"] > df["open"]

    return df
