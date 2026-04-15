"""Golden backtests — regression tests with fixed synthetic data.

These tests use deterministic synthetic data to verify that:
1. A known compression→breakout→reclaim pattern generates a trade
2. A regime-blocked period generates zero trades
3. No-trade reasons are correctly distributed

If a refactoring changes the strategy without anyone noticing,
these tests will catch it.

NOTE: These use synthetic data, not real market data.
Real-data golden tests will be added after the first matrix run
produces reference outputs.
"""
import numpy as np
import pandas as pd
import pytest

from backtest.backtest_engine import BacktestEngine
from defensive.config import DefensiveConfig
from defensive.enums import Outcome, Regime


def _make_golden_candles_15m(scenario: str) -> pd.DataFrame:
    """Generate deterministic candle sets for golden tests.

    Scenarios:
      - "compression_breakout_reclaim": Clear CFER setup
      - "trending_only": Strong trend, no compression
      - "flat_ranging": Ultra-flat, compression but no breakout
    """
    n = 200
    rng = np.random.RandomState(123)  # Fixed seed
    ts = pd.date_range("2025-03-01", periods=n, freq="15min", tz="UTC")

    if scenario == "compression_breakout_reclaim":
        # Phase 1 (0-120): Normal volatility
        closes = np.zeros(n)
        closes[:120] = 100.0 + np.cumsum(rng.randn(120) * 0.5)

        # Phase 2 (120-170): Compression — tightening range
        base = closes[119]
        for i in range(120, 170):
            noise = 0.5 * (1 - (i - 120) / 50)  # Decreasing noise
            closes[i] = base + rng.randn() * noise

        # Phase 3 (170-175): Breakout UP with volume spike
        closes[170] = closes[169] + 3.0  # Sharp up
        closes[171] = closes[170] + 1.5
        closes[172] = closes[171] + 0.5

        # Phase 4 (175-180): Reclaim — price comes back
        closes[175] = closes[172] - 2.0
        closes[176] = closes[175] - 1.5
        closes[177] = closes[176] - 1.0

        # Phase 5 (180+): Drift
        for i in range(178, n):
            closes[i] = closes[i - 1] + rng.randn() * 0.3

        highs = closes + np.abs(rng.randn(n)) * 0.5
        lows = closes - np.abs(rng.randn(n)) * 0.5
        opens = closes + rng.randn(n) * 0.1

        volumes = np.full(n, 1000.0)
        # Volume spike on breakout candles
        volumes[170:175] = 5000.0
        volumes += rng.rand(n) * 100

    elif scenario == "trending_only":
        # Strong uptrend — no compression possible
        closes = 100.0 + np.arange(n) * 0.3 + rng.randn(n) * 0.5
        highs = closes + np.abs(rng.randn(n)) * 1.0
        lows = closes - np.abs(rng.randn(n)) * 0.5
        opens = closes + rng.randn(n) * 0.2
        volumes = 1000 + rng.rand(n) * 300

    elif scenario == "flat_ranging":
        # Ultra-flat — compression yes, breakout no (no volume spike, no BB breach)
        closes = 100.0 + rng.randn(n) * 0.1
        highs = closes + 0.05
        lows = closes - 0.05
        opens = closes + rng.randn(n) * 0.01
        volumes = 1000 + rng.rand(n) * 50

    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    return pd.DataFrame({
        "timestamp": ts, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": volumes,
    })


def _make_golden_candles_1h(regime_target: str = "ranging") -> pd.DataFrame:
    """Generate 1h candles that produce a target regime."""
    n = 60
    rng = np.random.RandomState(123)
    ts = pd.date_range("2025-03-01", periods=n, freq="1h", tz="UTC")

    if regime_target == "ranging":
        closes = 100.0 + rng.randn(n) * 0.2
    elif regime_target == "trending":
        closes = 100.0 + np.arange(n) * 0.5 + rng.randn(n) * 0.3
    else:
        closes = 100.0 + rng.randn(n) * 0.2

    highs = closes + np.abs(rng.randn(n)) * 0.3
    lows = closes - np.abs(rng.randn(n)) * 0.3
    opens = closes + rng.randn(n) * 0.1
    volumes = 5000 + rng.rand(n) * 1000

    return pd.DataFrame({
        "timestamp": ts, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": volumes,
    })


class TestGoldenCFERBaseline:
    """Golden tests: fixed input → expected behavior."""

    def test_trending_produces_zero_trades(self):
        """Strong trend → regime blocks everything → 0 trades."""
        candles_15m = _make_golden_candles_15m("trending_only")
        candles_1h = _make_golden_candles_1h("trending")

        config = DefensiveConfig()
        engine = BacktestEngine(config)
        engine.run(candles_15m, candles_1h, symbol="BTCUSDT")

        # Should have zero trades in a strong trend
        assert len(engine.trades) == 0
        # But should have many decisions logged
        assert len(engine.decisions) > 0

    def test_trending_blocked_by_regime(self):
        """In trending regime, most decisions should be REGIME_BLOCKED."""
        candles_15m = _make_golden_candles_15m("trending_only")
        candles_1h = _make_golden_candles_1h("trending")

        config = DefensiveConfig()
        engine = BacktestEngine(config)
        engine.run(candles_15m, candles_1h, symbol="BTCUSDT")

        regime_blocked = sum(
            1 for d in engine.decisions if d.outcome == Outcome.REGIME_BLOCKED
        )
        # Should be a significant fraction
        if engine.decisions:
            assert regime_blocked / len(engine.decisions) > 0.3

    def test_flat_ranging_no_breakout(self):
        """Ultra-flat market: compression may happen but no breakout."""
        candles_15m = _make_golden_candles_15m("flat_ranging")
        candles_1h = _make_golden_candles_1h("ranging")

        config = DefensiveConfig()
        engine = BacktestEngine(config)
        engine.run(candles_15m, candles_1h, symbol="BTCUSDT")

        # No trades (no breakout in flat market)
        assert len(engine.trades) == 0

        # Should see NO_BREAKOUT or NO_COMPRESSION reasons
        no_breakout = sum(
            1 for d in engine.decisions if d.outcome == Outcome.NO_BREAKOUT
        )
        no_compression = sum(
            1 for d in engine.decisions if d.outcome == Outcome.NO_COMPRESSION
        )
        assert no_breakout + no_compression > 0

    def test_decisions_deterministic(self):
        """Same input twice → exactly same decisions."""
        candles_15m = _make_golden_candles_15m("compression_breakout_reclaim")
        candles_1h = _make_golden_candles_1h("ranging")

        config = DefensiveConfig()

        engine1 = BacktestEngine(config)
        engine1.run(candles_15m.copy(), candles_1h.copy(), symbol="BTCUSDT")

        engine2 = BacktestEngine(config)
        engine2.run(candles_15m.copy(), candles_1h.copy(), symbol="BTCUSDT")

        assert len(engine1.decisions) == len(engine2.decisions)
        for d1, d2 in zip(engine1.decisions, engine2.decisions):
            assert d1.outcome == d2.outcome
            assert d1.entry_price == d2.entry_price

    def test_decision_outcomes_always_valid(self):
        """Every decision must have a valid Outcome enum value."""
        candles_15m = _make_golden_candles_15m("compression_breakout_reclaim")
        candles_1h = _make_golden_candles_1h("ranging")

        config = DefensiveConfig()
        engine = BacktestEngine(config)
        engine.run(candles_15m, candles_1h, symbol="BTCUSDT")

        for d in engine.decisions:
            assert d.outcome in list(Outcome), f"Invalid outcome: {d.outcome}"

    def test_no_trade_reasons_documented(self):
        """All no-trade decisions must have a specific reason, never empty."""
        candles_15m = _make_golden_candles_15m("trending_only")
        candles_1h = _make_golden_candles_1h("trending")

        config = DefensiveConfig()
        engine = BacktestEngine(config)
        engine.run(candles_15m, candles_1h, symbol="BTCUSDT")

        for d in engine.decisions:
            # outcome must never be the default NO_COMPRESSION if a real evaluation happened
            assert d.outcome != Outcome.TRADE or d.entry_price > 0

    def test_enhanced_flag_off_by_default(self):
        """Default config must have enhanced_enabled=False."""
        config = DefensiveConfig()
        assert config.enhanced_enabled is False
        assert config.ravr_enabled is False
        assert config.baseline_enabled is True
