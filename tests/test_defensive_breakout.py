"""Tests for defensive/breakout_detector.py — breakout and reclaim."""
import numpy as np
import pandas as pd
import pytest

from defensive.breakout_detector import detect_breakout, detect_reclaim
from defensive.config import DefensiveConfig
from defensive.enums import Direction
from defensive.models import BreakoutEvent, CompressionState


def _make_stable_candles(n: int = 50, base: float = 100.0) -> pd.DataFrame:
    """Stable candles — close hugs the mean, volume is steady."""
    rng = np.random.RandomState(42)
    closes = base + rng.randn(n) * 0.5
    highs = closes + 0.3
    lows = closes - 0.3
    opens = closes + rng.randn(n) * 0.1
    volumes = np.full(n, 1000.0)
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": volumes,
    })


def _inject_breakout_up(df: pd.DataFrame, spike_mult: float = 3.0) -> pd.DataFrame:
    """Modify last candle to close above BB upper with volume spike."""
    df = df.copy()
    # Push last close way above the mean
    sma = df["close"].rolling(20).mean().iloc[-1]
    std = df["close"].rolling(20).std().iloc[-1]
    bb_upper = sma + 2 * std
    df.loc[df.index[-1], "close"] = bb_upper + std  # Well above upper
    df.loc[df.index[-1], "high"] = bb_upper + std * 1.5
    # Spike volume
    vol_mean = df["volume"].rolling(20).mean().iloc[-2]
    df.loc[df.index[-1], "volume"] = vol_mean * spike_mult
    return df


def _inject_breakout_down(df: pd.DataFrame, spike_mult: float = 3.0) -> pd.DataFrame:
    """Modify last candle to close below BB lower with volume spike."""
    df = df.copy()
    sma = df["close"].rolling(20).mean().iloc[-1]
    std = df["close"].rolling(20).std().iloc[-1]
    bb_lower = sma - 2 * std
    df.loc[df.index[-1], "close"] = bb_lower - std
    df.loc[df.index[-1], "low"] = bb_lower - std * 1.5
    vol_mean = df["volume"].rolling(20).mean().iloc[-2]
    df.loc[df.index[-1], "volume"] = vol_mean * spike_mult
    return df


@pytest.fixture
def config():
    return DefensiveConfig()


@pytest.fixture
def active_compression():
    return CompressionState(active=True, bb_width_percentile=10.0, consecutive_decline=8)


@pytest.fixture
def inactive_compression():
    return CompressionState(active=False)


class TestDetectBreakout:
    def test_no_breakout_without_compression(self, config, inactive_compression):
        df = _make_stable_candles()
        df = _inject_breakout_up(df)
        result = detect_breakout(df, inactive_compression, config)
        assert result.detected is False

    def test_no_breakout_when_inside_bands(self, config, active_compression):
        df = _make_stable_candles()
        result = detect_breakout(df, active_compression, config)
        assert result.detected is False

    def test_breakout_up_detected(self, config, active_compression):
        df = _make_stable_candles()
        df = _inject_breakout_up(df)
        result = detect_breakout(df, active_compression, config)
        assert result.detected is True
        assert result.direction == Direction.LONG
        assert result.price > 0
        assert result.volume_ratio >= config.breakout_volume_mult

    def test_breakout_down_detected(self, config, active_compression):
        df = _make_stable_candles()
        df = _inject_breakout_down(df)
        result = detect_breakout(df, active_compression, config)
        assert result.detected is True
        assert result.direction == Direction.SHORT

    def test_no_breakout_without_volume_spike(self, config, active_compression):
        df = _make_stable_candles()
        # Close above BB but normal volume
        df = _inject_breakout_up(df, spike_mult=1.0)
        result = detect_breakout(df, active_compression, config)
        assert result.detected is False

    def test_insufficient_data(self, config, active_compression):
        df = _make_stable_candles(n=10)
        result = detect_breakout(df, active_compression, config)
        assert result.detected is False

    def test_breakout_event_fields_populated(self, config, active_compression):
        df = _make_stable_candles()
        df = _inject_breakout_up(df)
        result = detect_breakout(df, active_compression, config)
        assert result.bb_level > 0
        assert result.candle_index == len(df) - 1
        assert result.timestamp != ""


class TestDetectReclaim:
    def test_reclaim_after_long_breakout(self, config):
        """Close back below BB upper = reclaim for long breakout."""
        df = _make_stable_candles(n=50)
        breakout = BreakoutEvent(
            detected=True,
            direction=Direction.LONG,
            candle_index=len(df) - 3,  # 2 candles ago
            bb_level=101.0,
        )
        # Last candle close is near mean (within bands) — should reclaim
        result = detect_reclaim(df, breakout, config)
        assert result is True

    def test_no_reclaim_if_still_outside(self, config):
        df = _make_stable_candles(n=50)
        df = _inject_breakout_up(df)
        breakout = BreakoutEvent(
            detected=True,
            direction=Direction.LONG,
            candle_index=len(df) - 2,
            bb_level=101.0,
        )
        result = detect_reclaim(df, breakout, config)
        assert result is False

    def test_no_reclaim_without_breakout(self, config):
        df = _make_stable_candles()
        breakout = BreakoutEvent(detected=False)
        result = detect_reclaim(df, breakout, config)
        assert result is False

    def test_no_reclaim_outside_window(self, config):
        """If too many candles passed, reclaim window expired."""
        df = _make_stable_candles(n=50)
        breakout = BreakoutEvent(
            detected=True,
            direction=Direction.LONG,
            candle_index=10,  # Way too many candles ago
            bb_level=101.0,
        )
        result = detect_reclaim(df, breakout, config)
        assert result is False

    def test_reclaim_after_short_breakout(self, config):
        """Close back above BB lower = reclaim for short breakout."""
        df = _make_stable_candles(n=50)
        breakout = BreakoutEvent(
            detected=True,
            direction=Direction.SHORT,
            candle_index=len(df) - 3,
            bb_level=99.0,
        )
        result = detect_reclaim(df, breakout, config)
        assert result is True
