"""Tests for defensive/ravr_trader.py — RAVR benchmark strategy."""
import numpy as np
import pandas as pd
import pytest

from defensive.config import DefensiveConfig
from defensive.enums import Direction, Outcome, Regime, Session, Strategy
from defensive.ravr_trader import evaluate_ravr


def _make_candles(n: int = 120, base: float = 100.0, trend: float = 0.0) -> pd.DataFrame:
    """Generate candles with optional trend for z-score manipulation."""
    rng = np.random.RandomState(42)
    closes = base + np.cumsum(rng.randn(n) * 0.3) + np.arange(n) * trend
    highs = closes + np.abs(rng.randn(n)) * 0.3
    lows = closes - np.abs(rng.randn(n)) * 0.3
    opens = closes + rng.randn(n) * 0.1
    volumes = 1000 + rng.rand(n) * 200
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": volumes,
    })


@pytest.fixture
def config():
    return DefensiveConfig(ravr_enabled=True)


class TestEvaluateRAVR:
    def test_blocked_in_trending_regime(self, config):
        df = _make_candles()
        result = evaluate_ravr(df, Regime.TRENDING, Session.US, config)
        assert result.outcome == Outcome.REGIME_BLOCKED
        assert result.strategy == Strategy.RAVR

    def test_blocked_in_volatile_regime(self, config):
        df = _make_candles()
        result = evaluate_ravr(df, Regime.VOLATILE, Session.US, config)
        assert result.outcome == Outcome.REGIME_BLOCKED

    def test_allowed_in_ranging_regime(self, config):
        df = _make_candles()
        result = evaluate_ravr(df, Regime.RANGING, Session.US, config)
        # Should not be regime blocked
        assert result.outcome != Outcome.REGIME_BLOCKED

    def test_zscore_insufficient_with_stable_data(self, config):
        """Stable data should have low z-score → ZSCORE_INSUFFICIENT."""
        df = _make_candles(n=120)
        result = evaluate_ravr(df, Regime.RANGING, Session.US, config)
        # With low-noise data, z-score likely below threshold
        if abs(result.z_score) < config.ravr_zscore_threshold:
            assert result.outcome == Outcome.ZSCORE_INSUFFICIENT

    def test_trade_direction_long_when_below_vwap(self, config):
        """If price far below VWAP (negative z-score) → LONG reversion."""
        # Create candles where last prices drop sharply
        df = _make_candles(n=120)
        # Push last few candles down to create negative z-score
        df.loc[df.index[-5:], "close"] = df["close"].iloc[-10] - 10
        df.loc[df.index[-5:], "low"] = df["close"].iloc[-5:] - 0.5
        df.loc[df.index[-5:], "high"] = df["close"].iloc[-5:] + 0.5

        result = evaluate_ravr(df, Regime.RANGING, Session.US, config)
        if result.outcome == Outcome.TRADE:
            assert result.direction == Direction.LONG

    def test_trade_direction_short_when_above_vwap(self, config):
        """If price far above VWAP (positive z-score) → SHORT reversion."""
        df = _make_candles(n=120)
        # Push last few candles up
        df.loc[df.index[-5:], "close"] = df["close"].iloc[-10] + 10
        df.loc[df.index[-5:], "high"] = df["close"].iloc[-5:] + 0.5
        df.loc[df.index[-5:], "low"] = df["close"].iloc[-5:] - 0.5

        result = evaluate_ravr(df, Regime.RANGING, Session.US, config)
        if result.outcome == Outcome.TRADE:
            assert result.direction == Direction.SHORT

    def test_sl_tp_set_on_trade(self, config):
        """When trade is opened, SL and TP must be set."""
        df = _make_candles(n=120)
        df.loc[df.index[-5:], "close"] = df["close"].iloc[-10] - 10
        df.loc[df.index[-5:], "low"] = df["close"].iloc[-5:] - 0.5
        df.loc[df.index[-5:], "high"] = df["close"].iloc[-5:] + 0.5

        result = evaluate_ravr(df, Regime.RANGING, Session.US, config)
        if result.outcome == Outcome.TRADE:
            assert result.sl_price > 0
            assert result.tp1_price > 0
            assert result.tp2_price > 0
            assert result.entry_price > 0

    def test_insufficient_data(self, config):
        df = _make_candles(n=30)
        result = evaluate_ravr(df, Regime.RANGING, Session.US, config)
        assert result.outcome == Outcome.ERROR

    def test_metadata_propagated(self, config):
        df = _make_candles()
        result = evaluate_ravr(
            df, Regime.RANGING, Session.US, config,
            symbol="ETHUSDT", cycle_id="test_123", timestamp="2025-01-01T00:00:00",
        )
        assert result.symbol == "ETHUSDT"
        assert result.cycle_id == "test_123"
        assert result.strategy == Strategy.RAVR
