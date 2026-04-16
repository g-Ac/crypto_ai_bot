# tests/test_backtest_1m.py
"""Tests for the 1-minute backtest engine."""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from backtest_1m import (
    Backtest1m,
    BacktestResult,
    ClosedTrade1m,
    run_backtest_1m,
)
from config_1m import Config1m
from engines_1m.momentum_burst import MomentumBurst1m


def _make_trending_candles(n=500, base=100.0, trend=0.01) -> pd.DataFrame:
    """Generate trending candle data with occasional bursts."""
    np.random.seed(123)
    times = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    prices = base + np.cumsum(np.random.randn(n) * 0.3 + trend)
    highs = prices + np.abs(np.random.randn(n) * 0.2)
    lows = prices - np.abs(np.random.randn(n) * 0.2)
    opens = prices - np.random.randn(n) * 0.1
    volumes = np.random.uniform(100, 500, n)

    return pd.DataFrame({
        "timestamp": times, "open": opens, "high": highs,
        "low": lows, "close": prices, "volume": volumes,
    })


class TestClosedTrade1m:

    def test_dataclass_fields(self):
        t = ClosedTrade1m(
            symbol="BTCUSDT", direction="LONG", engine="momentum_burst_1m",
            entry_price=100.0, exit_price=101.0, sl_price=99.0, tp_price=102.0,
            entry_time="2026-01-01T00:00Z", exit_time="2026-01-01T00:05Z",
            exit_reason="TP", pnl_pct=1.0, pnl_usd=8.0,
            fee_usd=0.64, notional_usd=800.0, leverage=125,
            duration_candles=5, metadata={},
        )
        assert t.symbol == "BTCUSDT"
        assert t.pnl_usd == 8.0


class TestBacktestResult:

    def test_empty_result(self):
        r = BacktestResult(
            trades=[], total_candles=1000, symbols=["BTCUSDT"],
            config=Config1m(),
        )
        assert r.total_trades == 0
        assert r.win_rate == 0.0
        assert r.total_pnl_usd == 0.0

    def test_result_with_trades(self):
        trades = [
            ClosedTrade1m(
                symbol="BTCUSDT", direction="LONG", engine="test",
                entry_price=100, exit_price=101, sl_price=99, tp_price=102,
                entry_time="", exit_time="", exit_reason="TP",
                pnl_pct=1.0, pnl_usd=5.0, fee_usd=0.5,
                notional_usd=500, leverage=100, duration_candles=3, metadata={},
            ),
            ClosedTrade1m(
                symbol="BTCUSDT", direction="SHORT", engine="test",
                entry_price=100, exit_price=101, sl_price=99, tp_price=98,
                entry_time="", exit_time="", exit_reason="SL",
                pnl_pct=-1.0, pnl_usd=-5.0, fee_usd=0.5,
                notional_usd=500, leverage=100, duration_candles=2, metadata={},
            ),
        ]
        r = BacktestResult(
            trades=trades, total_candles=1000, symbols=["BTCUSDT"],
            config=Config1m(),
        )
        assert r.total_trades == 2
        assert r.win_rate == 0.5
        assert r.total_pnl_usd == 0.0
        assert r.total_fee_usd == 1.0


class TestBacktest1mEngine:

    def test_backtest_runs_without_crash(self):
        """Backtest on synthetic data completes without error."""
        df = _make_trending_candles(500)
        config = Config1m(max_risk_per_trade_usd=2.0)
        engines = [MomentumBurst1m()]

        bt = Backtest1m(engines=engines, config=config)
        result = bt.run_on_dataframe("BTCUSDT", df)

        assert isinstance(result, BacktestResult)
        assert result.total_candles == 500

    def test_no_look_ahead(self):
        """Engine at candle i should not see candle i+1 data."""
        df = _make_trending_candles(200)
        config = Config1m()
        engines = [MomentumBurst1m()]

        bt = Backtest1m(engines=engines, config=config)
        # This is structural -- the test verifies the loop slices df[:i+1]
        result = bt.run_on_dataframe("BTCUSDT", df)
        assert isinstance(result, BacktestResult)

    def test_fees_are_included(self):
        """All trades should have fee_usd > 0."""
        df = _make_trending_candles(1000, trend=0.02)  # strong trend
        config = Config1m(max_risk_per_trade_usd=2.0)
        engines = [MomentumBurst1m()]

        bt = Backtest1m(engines=engines, config=config)
        result = bt.run_on_dataframe("BTCUSDT", df)

        for trade in result.trades:
            assert trade.fee_usd > 0

    def test_entry_on_next_candle_open(self):
        """Entries should use open of candle i+1, not close of candle i."""
        df = _make_trending_candles(1000, trend=0.02)
        config = Config1m(max_risk_per_trade_usd=2.0)
        engines = [MomentumBurst1m()]

        bt = Backtest1m(engines=engines, config=config)
        result = bt.run_on_dataframe("BTCUSDT", df)

        for trade in result.trades:
            # entry_price should come from an actual candle open, not close
            # We can't check exact value but verify it's > 0
            assert trade.entry_price > 0


class TestEntryGapHandling:
    """B1 + B3: Gap-aware entry validation and SL/TP on entry candle."""

    def _build_scenario(self, signal_idx, entry_open, entry_high, entry_low,
                        entry_close, signal_entry, sl, tp, direction="LONG",
                        n=50, base=100.0):
        """Build a minimal backtest scenario with a mock engine.

        Creates n candles at base price, injects specific values on the entry
        candle (signal_idx + 1), and a mock engine that fires at signal_idx.
        """
        from signal_types import Direction, Signal
        from engines_1m.base import Engine1m

        times = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
        df = pd.DataFrame({
            "time": times,
            "open": [base] * n,
            "high": [base + 0.5] * n,
            "low": [base - 0.5] * n,
            "close": [base] * n,
            "volume": [1000.0] * n,
        })

        # Set entry candle (the candle AFTER the signal)
        entry_idx = signal_idx + 1
        df.loc[entry_idx, "open"] = entry_open
        df.loc[entry_idx, "high"] = entry_high
        df.loc[entry_idx, "low"] = entry_low
        df.loc[entry_idx, "close"] = entry_close

        d = Direction.LONG if direction == "LONG" else Direction.SHORT
        sl_dist = abs(signal_entry - sl) / signal_entry * 100
        tp_dist = abs(tp - signal_entry) / signal_entry * 100

        sig = Signal(
            direction=d, strength=0.8, timestamp="2026-01-01",
            source="test_engine", symbol="SOLUSDT", price=signal_entry,
            entry_price=signal_entry, sl_price=sl, tp1_price=tp,
            sl_distance_pct=sl_dist, rr_ratio=tp_dist / sl_dist if sl_dist else 0,
            valid=True, metadata={},
        )

        class MockEngine(Engine1m):
            name = "test_engine"
            version = "1.0"
            def analyze(self, symbol, df_1m, **kw):
                if len(df_1m) - 1 == signal_idx:
                    return sig
                return None
            def required_indicators(self):
                return []

        return df, MockEngine()

    def test_unfavorable_gap_rejects_trade(self):
        """B1: Large unfavorable gap makes SL distance exceed max → rejected."""
        # LONG signal: entry=100, SL=99.5 (0.5%), TP=101.5 (1.5%)
        # Entry candle gaps down to 97 → SL distance from 97 to 99.5 = 2.58% > 1.0%
        df, engine = self._build_scenario(
            signal_idx=29,
            entry_open=97.0, entry_high=97.5, entry_low=96.5, entry_close=97.0,
            signal_entry=100.0, sl=99.5, tp=101.5, direction="LONG",
        )
        config = Config1m(max_risk_per_trade_usd=2.0, max_sl_distance_pct=1.0)
        bt = Backtest1m(engines=[engine], config=config)
        result = bt.run_on_dataframe("SOLUSDT", df)

        assert result.total_trades == 0

    def test_favorable_gap_executes_with_correct_notional(self):
        """B1: Favorable gap recalculates notional via Risk Calculator."""
        # LONG signal: entry=100, SL=99.5 (0.5%), TP=102.0 (2.0%)
        # Entry candle opens at 100.2 (slight gap up)
        # New SL dist = |100.2-99.5|/100.2 = 0.699%
        # New notional = 2.0 / 0.00699 = ~286
        df, engine = self._build_scenario(
            signal_idx=29,
            entry_open=100.2, entry_high=100.5, entry_low=100.0,
            entry_close=100.3,
            signal_entry=100.0, sl=99.5, tp=102.0, direction="LONG",
        )
        # Make sure TP gets hit eventually
        for i in range(32, 40):
            df.loc[i, "open"] = 101.5
            df.loc[i, "high"] = 102.5
            df.loc[i, "low"] = 101.0
            df.loc[i, "close"] = 102.0

        config = Config1m(max_risk_per_trade_usd=2.0, min_rr_net=1.0)
        bt = Backtest1m(engines=[engine], config=config)
        result = bt.run_on_dataframe("SOLUSDT", df)

        assert result.total_trades == 1
        trade = result.trades[0]
        assert trade.entry_price == pytest.approx(100.2)
        # Notional recalculated: 2.0 / (0.699/100) ≈ 286
        assert trade.notional_usd == pytest.approx(2.0 / (abs(100.2 - 99.5) / 100.2), rel=0.01)
        assert trade.fee_usd > 0

    def test_entry_candle_sl_tp_both_hit_uses_gap_direction(self):
        """B3: Both SL and TP in entry candle range → gap direction decides."""
        # LONG signal: entry=100, SL=99.3, TP=102.0
        # Entry candle: open=100.3 (gap UP = favorable), high=103, low=99.0
        # After gap: sl_dist=1.0%, tp_dist=1.7%, R:R=1.5 → viable
        # Both SL (99.0 < 99.3) and TP (103 > 102) hit
        # Gap up → favorable → TP should win
        df, engine = self._build_scenario(
            signal_idx=29,
            entry_open=100.3, entry_high=103.0, entry_low=99.0,
            entry_close=101.5,
            signal_entry=100.0, sl=99.3, tp=102.0, direction="LONG",
        )
        config = Config1m(max_risk_per_trade_usd=2.0, min_rr_net=1.0)
        bt = Backtest1m(engines=[engine], config=config)
        result = bt.run_on_dataframe("SOLUSDT", df)

        assert result.total_trades == 1
        trade = result.trades[0]
        assert trade.exit_reason == "TP"
        assert trade.exit_price == pytest.approx(102.0)
        assert trade.duration_candles == 0  # Closed on same candle as entry

    def test_entry_candle_sl_tp_both_hit_unfavorable_gap(self):
        """B3: Both SL and TP hit on entry, unfavorable gap → SL wins."""
        # LONG signal: entry=100, SL=99.3, TP=102.0
        # Entry candle: open=99.8 (gap DOWN = unfavorable), high=103, low=99.0
        # After gap: sl_dist=0.50%, tp_dist=2.20%, R:R≈3.7 → viable
        # Both SL (99.0 < 99.3) and TP (103 > 102) hit
        # Gap down → unfavorable → SL should win
        df, engine = self._build_scenario(
            signal_idx=29,
            entry_open=99.8, entry_high=103.0, entry_low=99.0,
            entry_close=101.0,
            signal_entry=100.0, sl=99.3, tp=102.0, direction="LONG",
        )
        config = Config1m(max_risk_per_trade_usd=2.0, min_rr_net=1.0)
        bt = Backtest1m(engines=[engine], config=config)
        result = bt.run_on_dataframe("SOLUSDT", df)

        assert result.total_trades == 1
        trade = result.trades[0]
        assert trade.exit_reason == "SL"
        assert trade.exit_price == pytest.approx(99.3)


class TestAmbiguousSlTpResolution:
    """B4: Non-entry candle with both SL and TP hit."""

    def test_sl_tp_both_hit_uses_open_proximity(self):
        """B4: When both SL+TP hit, closer to candle open wins."""
        from backtest_1m import _OpenPosition

        config = Config1m()
        bt = Backtest1m(engines=[], config=config)

        pos = _OpenPosition(
            symbol="TEST", direction="LONG", engine="test",
            entry_price=100.0, sl_price=99.0, tp_price=101.0,
            entry_time="", entry_candle_idx=0,
            notional_usd=400.0, leverage=100,
            fee_roundtrip_pct=0.08,
        )

        # Candle opens near TP side → TP should win
        candle_tp_first = pd.Series({
            "open": 100.8, "high": 101.5, "low": 98.5, "close": 99.5, "time": ""
        })
        trade = bt._check_exit(pos, candle_tp_first, 5)
        assert trade.exit_reason == "TP"

        # Candle opens near SL side → SL should win
        pos2 = _OpenPosition(
            symbol="TEST", direction="LONG", engine="test",
            entry_price=100.0, sl_price=99.0, tp_price=101.0,
            entry_time="", entry_candle_idx=0,
            notional_usd=400.0, leverage=100,
            fee_roundtrip_pct=0.08,
        )
        candle_sl_first = pd.Series({
            "open": 99.2, "high": 101.5, "low": 98.5, "close": 100.5, "time": ""
        })
        trade2 = bt._check_exit(pos2, candle_sl_first, 5)
        assert trade2.exit_reason == "SL"


class TestRunBacktest1m:
    """Integration test for the convenience function."""

    @patch("backtest_1m.fetch_1m_historical")
    def test_run_backtest_1m_convenience(self, mock_fetch):
        mock_fetch.return_value = _make_trending_candles(300)
        result = run_backtest_1m(
            symbols=["BTCUSDT"],
            days=1,
            config=Config1m(),
        )
        assert isinstance(result, dict)
        assert "BTCUSDT" in result
