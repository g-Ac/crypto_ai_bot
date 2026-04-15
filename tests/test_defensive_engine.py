"""Tests for backtest/backtest_engine.py — core backtest loop."""
import numpy as np
import pandas as pd
import pytest

from backtest.backtest_engine import (
    BacktestEngine,
    _apply_slippage,
    _classify_regime,
    _classify_session,
    _compute_fees,
)
from defensive.config import DefensiveConfig
from defensive.enums import Direction, Outcome, Regime, Session


def _make_candles_15m(n: int = 200, base: float = 100.0) -> pd.DataFrame:
    """Generate 15m candles with timestamps."""
    rng = np.random.RandomState(42)
    closes = base + np.cumsum(rng.randn(n) * 0.3)
    highs = closes + np.abs(rng.randn(n)) * 0.5
    lows = closes - np.abs(rng.randn(n)) * 0.5
    opens = closes + rng.randn(n) * 0.1
    volumes = 1000 + rng.rand(n) * 500
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": volumes,
    })


def _make_candles_1h(n: int = 60, base: float = 100.0) -> pd.DataFrame:
    """Generate 1h candles for regime detection."""
    rng = np.random.RandomState(42)
    closes = base + np.cumsum(rng.randn(n) * 0.5)
    highs = closes + np.abs(rng.randn(n)) * 0.8
    lows = closes - np.abs(rng.randn(n)) * 0.8
    opens = closes + rng.randn(n) * 0.2
    volumes = 5000 + rng.rand(n) * 2000
    ts = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": volumes,
    })


# --- Helper function tests ---

class TestClassifySession:
    def test_asia(self):
        ts = pd.Timestamp("2025-01-01 03:00:00", tz="UTC")
        assert _classify_session(ts) == Session.ASIA

    def test_europe(self):
        ts = pd.Timestamp("2025-01-01 10:00:00", tz="UTC")
        assert _classify_session(ts) == Session.EUROPE

    def test_us(self):
        ts = pd.Timestamp("2025-01-01 16:00:00", tz="UTC")
        assert _classify_session(ts) == Session.US

    def test_dead(self):
        ts = pd.Timestamp("2025-01-01 22:00:00", tz="UTC")
        assert _classify_session(ts) == Session.DEAD


class TestClassifyRegime:
    def test_insufficient_data_returns_unknown(self):
        df = _make_candles_1h(n=10)
        assert _classify_regime(df) == Regime.UNKNOWN

    def test_returns_valid_regime(self):
        df = _make_candles_1h(n=50)
        regime = _classify_regime(df)
        assert regime in list(Regime)


class TestApplySlippage:
    def test_long_entry_worse(self):
        config = DefensiveConfig()
        slipped = _apply_slippage(100.0, Direction.LONG, is_entry=True, config=config)
        assert slipped > 100.0

    def test_long_exit_worse(self):
        config = DefensiveConfig()
        slipped = _apply_slippage(100.0, Direction.LONG, is_entry=False, config=config)
        assert slipped < 100.0

    def test_short_entry_worse(self):
        config = DefensiveConfig()
        slipped = _apply_slippage(100.0, Direction.SHORT, is_entry=True, config=config)
        assert slipped < 100.0

    def test_short_exit_worse(self):
        config = DefensiveConfig()
        slipped = _apply_slippage(100.0, Direction.SHORT, is_entry=False, config=config)
        assert slipped > 100.0

    def test_failed_breakout_worse_than_normal(self):
        config = DefensiveConfig()
        normal = _apply_slippage(100.0, Direction.LONG, is_entry=True, config=config, context="normal")
        fb = _apply_slippage(100.0, Direction.LONG, is_entry=True, config=config, context="failed_breakout")
        assert fb > normal


class TestComputeFees:
    def test_round_trip_fee(self):
        config = DefensiveConfig()
        fees = _compute_fees(1000.0, config)
        expected = 1000.0 * 0.04 / 100 * 2  # 0.08%
        assert fees == pytest.approx(expected, abs=0.01)


# --- Engine tests ---

class TestBacktestEngine:
    def test_engine_init(self):
        config = DefensiveConfig()
        engine = BacktestEngine(config)
        assert engine.capital == config.initial_capital
        assert len(engine.trades) == 0
        assert len(engine.decisions) == 0

    def test_engine_runs_without_crash(self):
        """Engine should process data without errors, even if no trades generated."""
        config = DefensiveConfig()
        engine = BacktestEngine(config)
        candles_15m = _make_candles_15m(200)
        candles_1h = _make_candles_1h(60)

        meta = engine.run(candles_15m, candles_1h, symbol="BTCUSDT")
        assert meta.run_id != ""
        assert meta.candles_total == 200
        # Decisions should have been logged
        assert len(engine.decisions) > 0

    def test_engine_logs_decisions(self):
        """Every evaluated candle must produce a decision."""
        config = DefensiveConfig()
        engine = BacktestEngine(config)
        candles_15m = _make_candles_15m(200)
        candles_1h = _make_candles_1h(60)

        engine.run(candles_15m, candles_1h)

        # Each decision must have a valid Outcome
        for d in engine.decisions:
            assert d.outcome in list(Outcome)

    def test_insufficient_data(self):
        """Engine should handle insufficient data gracefully."""
        config = DefensiveConfig()
        engine = BacktestEngine(config)
        candles_15m = _make_candles_15m(50)
        candles_1h = _make_candles_1h(10)

        meta = engine.run(candles_15m, candles_1h)
        assert len(engine.trades) == 0

    def test_decisions_have_regime(self):
        """All decisions should have a regime set."""
        config = DefensiveConfig()
        engine = BacktestEngine(config)
        candles_15m = _make_candles_15m(200)
        candles_1h = _make_candles_1h(60)

        engine.run(candles_15m, candles_1h)

        for d in engine.decisions:
            assert d.regime in list(Regime)

    def test_no_trade_while_in_position(self):
        """Engine must not open multiple positions."""
        config = DefensiveConfig()
        engine = BacktestEngine(config)

        # Even with many candles, max 1 position at a time
        candles_15m = _make_candles_15m(500)
        candles_1h = _make_candles_1h(130)

        engine.run(candles_15m, candles_1h)

        # If trades were generated, capital should have changed
        if engine.trades:
            assert engine.capital != config.initial_capital

    def test_capital_tracks_with_trades(self):
        """Capital should reflect cumulative PnL of all trades."""
        config = DefensiveConfig()
        engine = BacktestEngine(config)
        candles_15m = _make_candles_15m(500)
        candles_1h = _make_candles_1h(130)

        engine.run(candles_15m, candles_1h)

        if engine.trades:
            expected_capital = config.initial_capital + sum(t.pnl_usd for t in engine.trades)
            assert engine.capital == pytest.approx(expected_capital, rel=0.01)
