"""Tests for RAVR v2 exit variants — TP modes, z-score decay, smart timeout."""
import numpy as np
import pandas as pd
import pytest

from defensive.config import DefensiveConfig
from defensive.enums import Direction, ExitReason, Outcome, Regime, Session, Strategy
from defensive.ravr_trader import evaluate_ravr
from backtest.backtest_engine import BacktestEngine, _OpenPosition
from defensive.models import TradeDecision


def _make_candles(n: int = 120, base: float = 100.0, trend: float = 0.0) -> pd.DataFrame:
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


def _force_trade_decision(direction=Direction.LONG, entry=100.0, sl=98.0,
                          tp1=102.0, tp2=104.0) -> TradeDecision:
    """Create a minimal TradeDecision that looks like RAVR trade."""
    d = TradeDecision(
        strategy=Strategy.RAVR,
        outcome=Outcome.TRADE,
        direction=direction,
        entry_price=entry,
        sl_price=sl,
        tp1_price=tp1,
        tp2_price=tp2,
        position_size_usd=500.0,
        z_score=-2.5,
        vwap_distance_pct=1.2,
    )
    return d


# ── TP calculation modes ──────────────────────────────────────────────────


class TestRAVRv2TPModes:
    def test_vwap_frac_40pct(self):
        """TP1 at 40% of VWAP distance should be closer than full VWAP."""
        config = DefensiveConfig(
            ravr_enabled=True,
            ravr_tp1_mode="vwap",
            ravr_tp1_vwap_frac=0.4,
            ravr_tp2_vwap_frac=1.0,
        )
        df = _make_candles(n=120)
        # Push price below VWAP
        df.loc[df.index[-5:], "close"] = df["close"].iloc[-10] - 10
        df.loc[df.index[-5:], "low"] = df["close"].iloc[-5:] - 0.5
        df.loc[df.index[-5:], "high"] = df["close"].iloc[-5:] + 0.5

        result = evaluate_ravr(df, Regime.RANGING, Session.US, config)
        if result.outcome == Outcome.TRADE:
            # TP1 should be closer to entry than TP2
            assert abs(result.tp1_price - result.entry_price) < abs(
                result.tp2_price - result.entry_price
            )

    def test_rr_mode_tp1_equals_sl_distance(self):
        """TP1 in rr mode at 1.0 should equal SL distance from entry."""
        config = DefensiveConfig(
            ravr_enabled=True,
            ravr_tp1_mode="rr",
            ravr_tp1_rr_mult=1.0,
        )
        df = _make_candles(n=120)
        df.loc[df.index[-5:], "close"] = df["close"].iloc[-10] - 10
        df.loc[df.index[-5:], "low"] = df["close"].iloc[-5:] - 0.5
        df.loc[df.index[-5:], "high"] = df["close"].iloc[-5:] + 0.5

        result = evaluate_ravr(df, Regime.RANGING, Session.US, config)
        if result.outcome == Outcome.TRADE:
            sl_dist = abs(result.entry_price - result.sl_price)
            tp1_dist = abs(result.tp1_price - result.entry_price)
            assert tp1_dist == pytest.approx(sl_dist, rel=0.01)

    def test_tp2_always_beyond_tp1(self):
        """TP2 must always be further from entry than TP1."""
        for frac in [0.3, 0.5, 0.8, 1.0]:
            config = DefensiveConfig(
                ravr_enabled=True,
                ravr_tp1_mode="vwap",
                ravr_tp1_vwap_frac=frac,
                ravr_tp2_vwap_frac=max(frac * 1.1, frac + 0.1),
            )
            df = _make_candles(n=120)
            df.loc[df.index[-5:], "close"] = df["close"].iloc[-10] - 10
            df.loc[df.index[-5:], "low"] = df["close"].iloc[-5:] - 0.5
            df.loc[df.index[-5:], "high"] = df["close"].iloc[-5:] + 0.5

            result = evaluate_ravr(df, Regime.RANGING, Session.US, config)
            if result.outcome == Outcome.TRADE:
                tp1_dist = abs(result.tp1_price - result.entry_price)
                tp2_dist = abs(result.tp2_price - result.entry_price)
                assert tp2_dist > tp1_dist, f"TP2 not beyond TP1 for frac={frac}"

    def test_v1_defaults_unchanged(self):
        """Default config should produce same behavior as v1."""
        config = DefensiveConfig(ravr_enabled=True)
        # ravr_tp1_mode defaults to "vwap", ravr_tp1_vwap_frac defaults to 1.0
        assert config.ravr_tp1_mode == "vwap"
        assert config.ravr_tp1_vwap_frac == 1.0
        assert config.ravr_tp2_vwap_frac == 1.5


# ── Z-score decay exit ────────────────────────────────────────────────────


class TestZScoreDecayExit:
    def test_zscore_decay_triggers_exit(self):
        """Position should close when z-score drops below threshold."""
        config = DefensiveConfig(
            ravr_enabled=True,
            ravr_zscore_exit_threshold=0.8,
        )
        decision = _force_trade_decision()
        pos = _OpenPosition(decision, config)
        pos.entry_candle_idx = 0

        candle = pd.Series({
            "high": 101.0, "low": 99.5, "close": 100.5,
        })

        result = pos.check_exit(
            candle, candles_since_entry=5, current_regime=Regime.RANGING,
            config=config, current_zscore=0.5,
        )
        assert result is not None
        assert result[0] == ExitReason.ZSCORE_DECAY

    def test_zscore_decay_no_exit_above_threshold(self):
        """No exit when z-score still above threshold."""
        config = DefensiveConfig(
            ravr_enabled=True,
            ravr_zscore_exit_threshold=0.8,
        )
        decision = _force_trade_decision()
        pos = _OpenPosition(decision, config)

        candle = pd.Series({
            "high": 101.0, "low": 99.5, "close": 100.5,
        })

        result = pos.check_exit(
            candle, candles_since_entry=5, current_regime=Regime.RANGING,
            config=config, current_zscore=-1.5,
        )
        # Should not trigger z-score decay (|1.5| > 0.8)
        assert result is None or result[0] != ExitReason.ZSCORE_DECAY

    def test_zscore_decay_disabled_when_zero(self):
        """Z-score exit should not trigger when threshold is 0 (disabled)."""
        config = DefensiveConfig(
            ravr_enabled=True,
            ravr_zscore_exit_threshold=0.0,
        )
        decision = _force_trade_decision()
        pos = _OpenPosition(decision, config)

        candle = pd.Series({
            "high": 101.0, "low": 99.5, "close": 100.5,
        })

        result = pos.check_exit(
            candle, candles_since_entry=5, current_regime=Regime.RANGING,
            config=config, current_zscore=0.3,
        )
        assert result is None or result[0] != ExitReason.ZSCORE_DECAY


# ── Smart timeout exit ────────────────────────────────────────────────────


class TestSmartTimeoutExit:
    def test_smart_timeout_triggers_when_positive(self):
        """Smart timeout should trigger when PnL is positive at check candle."""
        config = DefensiveConfig(
            ravr_enabled=True,
            ravr_smart_timeout_candles=8,
            ravr_smart_timeout_min_pnl_pct=0.0,
            timeout_candles=12,
        )
        decision = _force_trade_decision(entry=100.0, sl=98.0)
        pos = _OpenPosition(decision, config)

        # Price moved favorably (LONG, close > entry)
        candle = pd.Series({
            "high": 101.5, "low": 100.0, "close": 101.0,
        })

        result = pos.check_exit(
            candle, candles_since_entry=8, current_regime=Regime.RANGING,
            config=config,
        )
        assert result is not None
        assert result[0] == ExitReason.SMART_TIMEOUT

    def test_smart_timeout_no_trigger_when_negative(self):
        """Smart timeout should NOT trigger when PnL is negative."""
        config = DefensiveConfig(
            ravr_enabled=True,
            ravr_smart_timeout_candles=8,
            ravr_smart_timeout_min_pnl_pct=0.0,
            timeout_candles=12,
        )
        decision = _force_trade_decision(entry=100.0, sl=98.0)
        pos = _OpenPosition(decision, config)

        # Price moved against (LONG, close < entry)
        candle = pd.Series({
            "high": 100.5, "low": 99.0, "close": 99.5,
        })

        result = pos.check_exit(
            candle, candles_since_entry=8, current_regime=Regime.RANGING,
            config=config,
        )
        # Should NOT be smart_timeout (PnL negative)
        assert result is None or result[0] != ExitReason.SMART_TIMEOUT

    def test_smart_timeout_before_normal_timeout(self):
        """Smart timeout at candle 8 should fire before normal timeout at 12."""
        config = DefensiveConfig(
            ravr_enabled=True,
            ravr_smart_timeout_candles=8,
            timeout_candles=12,
        )
        decision = _force_trade_decision(entry=100.0)
        pos = _OpenPosition(decision, config)

        candle = pd.Series({"high": 101.5, "low": 100.0, "close": 101.0})

        # At candle 8: smart timeout should fire (not normal timeout)
        result = pos.check_exit(
            candle, candles_since_entry=8, current_regime=Regime.RANGING,
            config=config,
        )
        if result:
            assert result[0] == ExitReason.SMART_TIMEOUT

    def test_smart_timeout_disabled_when_zero(self):
        """Smart timeout should not trigger when ravr_smart_timeout_candles=0."""
        config = DefensiveConfig(
            ravr_enabled=True,
            ravr_smart_timeout_candles=0,
            timeout_candles=12,
        )
        decision = _force_trade_decision(entry=100.0)
        pos = _OpenPosition(decision, config)

        candle = pd.Series({"high": 101.5, "low": 100.0, "close": 101.0})

        result = pos.check_exit(
            candle, candles_since_entry=8, current_regime=Regime.RANGING,
            config=config,
        )
        assert result is None or result[0] != ExitReason.SMART_TIMEOUT


# ── TP1 partial weight uses config ────────────────────────────────────────


class TestTP1PartialWeight:
    def test_tp1_partial_uses_config_pct(self):
        """After TP1 hit, remaining_pct should match config.tp1_partial_pct."""
        config = DefensiveConfig(
            ravr_enabled=True,
            tp1_partial_pct=60.0,
        )
        decision = _force_trade_decision(entry=100.0, tp1=102.0, tp2=104.0)
        pos = _OpenPosition(decision, config)

        # Candle that hits TP1
        candle = pd.Series({"high": 103.0, "low": 100.0, "close": 102.5})

        pos.check_exit(
            candle, candles_since_entry=3, current_regime=Regime.RANGING,
            config=config,
        )
        assert pos.tp1_hit is True
        assert pos.remaining_pct == 60.0  # From config


# ── SL still takes priority ──────────────────────────────────────────────


class TestSLPriority:
    def test_sl_fires_before_zscore_decay(self):
        """SL check happens before z-score decay."""
        config = DefensiveConfig(
            ravr_enabled=True,
            ravr_zscore_exit_threshold=0.8,
        )
        decision = _force_trade_decision(entry=100.0, sl=98.0)
        pos = _OpenPosition(decision, config)

        # Price hits SL
        candle = pd.Series({"high": 99.0, "low": 97.5, "close": 98.0})

        result = pos.check_exit(
            candle, candles_since_entry=5, current_regime=Regime.RANGING,
            config=config, current_zscore=0.3,
        )
        assert result is not None
        assert result[0] == ExitReason.STOP_LOSS
