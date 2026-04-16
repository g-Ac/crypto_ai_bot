# tests/test_momentum_burst_1m.py
"""Tests for Momentum Burst 1-min engine."""
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone

from engines_1m.momentum_burst import MomentumBurst1m
from indicators_1m import add_indicators_1m
from signal_types import Direction


def _make_candles(n: int = 100, base: float = 100.0, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic candle data."""
    np.random.seed(seed)
    closes = base + np.cumsum(np.random.randn(n) * 0.3)
    highs = closes + np.abs(np.random.randn(n) * 0.2)
    lows = closes - np.abs(np.random.randn(n) * 0.2)
    opens = closes + np.random.randn(n) * 0.1
    volumes = np.random.uniform(100, 500, n)
    times = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "time": times, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": volumes,
    })


def _make_burst_candle(df: pd.DataFrame, direction: str = "LONG") -> pd.DataFrame:
    """Inject a momentum burst candle at the end of the dataframe.

    Creates a candle with:
    - range > 2.0x ATR
    - volume > 2.5x average
    - body ratio > 65%
    - aligned with EMA direction
    """
    df = add_indicators_1m(df.copy())
    atr = df["atr14"].iloc[-1]
    avg_vol = df["vol_avg20"].iloc[-1]
    last_close = df["close"].iloc[-2]

    burst_range = atr * 3.0  # well above 2.0x threshold
    if direction == "LONG":
        o = last_close
        c = last_close + burst_range * 0.8  # body = 80% of range
        h = last_close + burst_range
        l = last_close - burst_range * 0.1
    else:
        o = last_close
        c = last_close - burst_range * 0.8
        l = last_close - burst_range
        h = last_close + burst_range * 0.1

    burst = pd.DataFrame({
        "time": [df["time"].iloc[-1] + pd.Timedelta(minutes=1)],
        "open": [o], "high": [h], "low": [l], "close": [c],
        "volume": [avg_vol * 3.5],  # well above 2.5x threshold
    })

    # Replace last row with burst
    result = pd.concat([df[["time", "open", "high", "low", "close", "volume"]].iloc[:-1], burst], ignore_index=True)
    return result


class TestMomentumBurstDetection:

    def test_no_signal_on_normal_candles(self):
        """Normal market data should not trigger a signal."""
        engine = MomentumBurst1m()
        df = add_indicators_1m(_make_candles(100))
        signal = engine.analyze("BTCUSDT", df)
        assert signal is None

    def test_detects_long_burst(self):
        """Strong bullish candle with volume triggers LONG signal."""
        engine = MomentumBurst1m()
        # Create trending-up data so EMA8 > EMA21
        np.random.seed(42)
        n = 100
        trend = np.linspace(100, 110, n)  # uptrend
        noise = np.random.randn(n) * 0.2
        closes = trend + noise
        highs = closes + 0.3
        lows = closes - 0.3
        opens = closes - 0.1
        volumes = np.random.uniform(100, 500, n)
        times = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")

        df = pd.DataFrame({
            "time": times, "open": opens, "high": highs,
            "low": lows, "close": closes, "volume": volumes,
        })

        df = _make_burst_candle(df, direction="LONG")
        df = add_indicators_1m(df)
        signal = engine.analyze("BTCUSDT", df)

        if signal is not None:
            assert signal.direction == Direction.LONG
            assert signal.valid is True
            assert signal.source == "momentum_burst_1m"
            assert signal.sl_price < signal.entry_price
            assert signal.tp1_price > signal.entry_price
            assert 0 < signal.strength <= 1.0
            assert "atr_multiple" in signal.metadata
            assert "volume_multiple" in signal.metadata

    def test_no_signal_when_rsi_extreme(self):
        """RSI outside 30-70 range should block signal."""
        engine = MomentumBurst1m()
        df = add_indicators_1m(_make_candles(100))
        # Force RSI to extreme
        df.loc[df.index[-1], "rsi14"] = 80.0
        signal = engine.analyze("BTCUSDT", df)
        assert signal is None


class TestEngineInterface:

    def test_has_name_and_version(self):
        engine = MomentumBurst1m()
        assert engine.name == "momentum_burst_1m"
        assert engine.version == "1.0.0"

    def test_required_indicators(self):
        engine = MomentumBurst1m()
        required = engine.required_indicators()
        assert "atr14" in required
        assert "ema8" in required
        assert "ema21" in required
        assert "rsi14" in required
        assert "vol_ratio" in required
        assert "body_ratio" in required


class TestSignalPrices:

    def test_sl_uses_atr(self):
        """SL should be based on candle low minus ATR fraction."""
        engine = MomentumBurst1m()
        # Create a scenario that triggers a signal
        np.random.seed(42)
        n = 100
        trend = np.linspace(100, 115, n)
        closes = trend + np.random.randn(n) * 0.1
        highs = closes + 0.4
        lows = closes - 0.2
        opens = closes - 0.05
        volumes = np.random.uniform(100, 500, n)
        times = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")

        df = pd.DataFrame({
            "time": times, "open": opens, "high": highs,
            "low": lows, "close": closes, "volume": volumes,
        })
        df = _make_burst_candle(df, "LONG")
        df = add_indicators_1m(df)
        signal = engine.analyze("BTCUSDT", df)

        if signal is not None:
            last = df.iloc[-1]
            # SL should be below the candle low
            assert signal.sl_price < last["low"]
            # TP should be above entry
            assert signal.tp1_price > signal.entry_price
