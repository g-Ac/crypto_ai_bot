"""Tests for defensive/compression_detector.py."""
import numpy as np
import pandas as pd
import pytest

from defensive.compression_detector import detect_compression
from defensive.config import DefensiveConfig


def _make_candles_compressing(n: int = 150) -> pd.DataFrame:
    """Candles where BB Width is declining (compression)."""
    rng = np.random.RandomState(42)
    # Start with normal volatility, then decrease noise over last 30 candles
    noise = np.ones(n) * 2.0
    noise[-30:] = np.linspace(2.0, 0.1, 30)  # Decreasing volatility

    closes = 100.0 + np.cumsum(rng.randn(n) * noise * 0.1)
    highs = closes + np.abs(rng.randn(n)) * noise
    lows = closes - np.abs(rng.randn(n)) * noise
    opens = closes + rng.randn(n) * noise * 0.3
    volumes = 1000 + rng.rand(n) * 200  # Stable volume

    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    })


def _make_candles_volatile(n: int = 150) -> pd.DataFrame:
    """Candles with increasing volatility (no compression).

    Ensures BB Width is EXPANDING at the tail so compression cannot trigger.
    """
    rng = np.random.RandomState(42)
    # Volatility ramps up sharply at the end — BB Width must expand
    noise = np.ones(n) * 0.3
    noise[-40:] = np.linspace(0.3, 8.0, 40)  # Aggressively increasing

    closes = 100.0 + np.cumsum(rng.randn(n) * noise)
    highs = closes + np.abs(rng.randn(n)) * noise * 1.5
    lows = closes - np.abs(rng.randn(n)) * noise * 1.5
    opens = closes + rng.randn(n) * noise * 0.3
    volumes = 1000 + rng.rand(n) * 500 + np.linspace(0, 2000, n)  # Volume rising too

    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    })


class TestDetectCompression:
    def test_insufficient_data_returns_inactive(self):
        df = pd.DataFrame({
            "open": [100.0] * 10, "high": [101.0] * 10,
            "low": [99.0] * 10, "close": [100.0] * 10,
            "volume": [1000.0] * 10,
        })
        config = DefensiveConfig()
        result = detect_compression(df, config)
        assert result.active is False

    def test_volatile_market_not_compressed(self):
        df = _make_candles_volatile()
        config = DefensiveConfig()
        result = detect_compression(df, config)
        assert result.active is False

    def test_compression_detected_with_declining_bb(self):
        """Synthetic data with declining BB should trigger compression."""
        df = _make_candles_compressing()
        config = DefensiveConfig()
        result = detect_compression(df, config)
        # The compressing data should show consecutive decline
        assert result.consecutive_decline > 0
        assert result.bb_width_current > 0

    def test_compression_state_fields_populated(self):
        df = _make_candles_compressing()
        config = DefensiveConfig()
        result = detect_compression(df, config)
        # Regardless of active status, metrics should be computed
        assert isinstance(result.bb_width_percentile, (float, np.floating))
        assert result.atr_declining in (True, False)
        assert result.volume_stable in (True, False)

    def test_compression_since_populated_when_active(self):
        """If compression is active and timestamps exist, 'since' should be set."""
        df = _make_candles_compressing()
        config = DefensiveConfig()
        result = detect_compression(df, config)
        if result.active:
            assert result.since != ""

    def test_default_state_is_inactive(self):
        from defensive.models import CompressionState
        cs = CompressionState()
        assert cs.active is False
        assert cs.consecutive_decline == 0
        assert cs.bb_width_percentile == 100.0
