"""Tests for indicators.py — technical indicator computation."""

import pandas as pd
import numpy as np
from indicators import add_indicators


def _make_df(n=50):
    """Create a realistic OHLCV DataFrame for testing."""
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n) * 0.3)
    low = close - np.abs(np.random.randn(n) * 0.3)
    open_ = close + np.random.randn(n) * 0.2
    volume = np.random.randint(100, 1000, size=n).astype(float)
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def test_add_indicators_columns_exist():
    df = add_indicators(_make_df())
    from config import BREAKOUT_WINDOW
    expected = ["sma_9", "sma_21", "sma_9_prev", "sma_21_prev",
                "rsi", f"recent_high_{BREAKOUT_WINDOW}", f"recent_low_{BREAKOUT_WINDOW}",
                "volume_avg", "body_ratio"]
    for col in expected:
        assert col in df.columns, f"Missing column: {col}"


def test_sma_values_reasonable():
    df = add_indicators(_make_df())
    valid = df.dropna(subset=["sma_9", "sma_21"])
    assert len(valid) > 0
    assert (valid["sma_9"] > 0).all()
    assert (valid["sma_21"] > 0).all()


def test_rsi_in_range():
    df = add_indicators(_make_df())
    valid_rsi = df["rsi"].dropna()
    assert len(valid_rsi) > 0
    assert (valid_rsi >= 0).all()
    assert (valid_rsi <= 100).all()


def test_body_ratio_nonzero():
    """body_ratio should have non-zero values for normal candles."""
    df = add_indicators(_make_df())
    assert df["body_ratio"].abs().sum() > 0


def test_body_ratio_zero_range_candle():
    """Candle with high == low should have body_ratio = 0."""
    df = _make_df(5)
    df["high"] = df["close"]
    df["low"] = df["close"]
    df = add_indicators(df)
    assert (df["body_ratio"] == 0).all()


def test_volume_avg_is_rolling():
    df = add_indicators(_make_df(50))
    valid = df["volume_avg"].dropna()
    assert len(valid) > 0
    assert valid.iloc[-1] > 0
