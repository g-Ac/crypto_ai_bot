import numpy as np
import pandas as pd
import pytest

from engines_5m.base import Engine5m
from engines_5m.breakout import BreakoutEngine5m
from indicators_5m import add_indicators_5m
from signal_types import Direction, Signal
from breakout.paper_executor import process_breakout_cycle


class TestEngine5mBase:
    def test_must_define_name(self):
        with pytest.raises(TypeError):
            class BadEngine(Engine5m):
                pass

    def test_subclass_with_name_works(self):
        class GoodEngine(Engine5m):
            name = "test_engine"
            version = "1.0.0"
            def analyze(self, symbol, df_5m, market_data=None):
                return None
            def required_indicators(self):
                return []
        engine = GoodEngine()
        assert engine.name == "test_engine"


class TestIndicators5m:
    def _make_df(self, n=50):
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n) * 0.5)
        return pd.DataFrame({
            "open": close - np.random.rand(n) * 0.3,
            "high": close + np.random.rand(n) * 0.5,
            "low": close - np.random.rand(n) * 0.5,
            "close": close,
            "volume": np.random.rand(n) * 1000 + 100,
        })

    def test_adds_all_required_columns(self):
        df = add_indicators_5m(self._make_df())
        required = [
            "ema8", "ema21", "sma20", "atr14",
            "bb_upper", "bb_lower", "bb_middle", "bb_bandwidth",
            "rsi14", "vol_avg20", "vol_ratio", "vwap",
            "body", "range", "body_ratio",
            "upper_shadow", "lower_shadow", "is_green",
        ]
        for col in required:
            assert col in df.columns, f"Missing column: {col}"

    def test_atr14_not_all_nan(self):
        df = add_indicators_5m(self._make_df(50))
        assert not df["atr14"].isna().all()


class TestBreakoutEngine5m:
    def test_engine_name(self):
        engine = BreakoutEngine5m()
        assert engine.name == "breakout_5m"

    def test_returns_none_insufficient_candles(self):
        engine = BreakoutEngine5m()
        df = pd.DataFrame({
            "open": [1.0] * 5, "high": [2.0] * 5, "low": [0.5] * 5,
            "close": [1.5] * 5, "volume": [100.0] * 5,
        })
        df = add_indicators_5m(df)
        assert engine.analyze("BTCUSDT", df) is None

    def test_required_indicators(self):
        engine = BreakoutEngine5m()
        required = engine.required_indicators()
        assert "atr14" in required
        assert "vol_ratio" in required
        assert "bb_bandwidth" in required
        assert "body_ratio" in required

    def test_returns_none_on_flat_data(self):
        """No breakout on completely flat candles."""
        engine = BreakoutEngine5m()
        n = 50
        df = pd.DataFrame({
            "open": [100.0] * n,
            "high": [100.5] * n,
            "low": [99.5] * n,
            "close": [100.0] * n,
            "volume": [100.0] * n,
        })
        df = add_indicators_5m(df)
        assert engine.analyze("BTCUSDT", df) is None


class TestBreakoutExecutor:
    def test_process_cycle_no_signal(self, tmp_path, monkeypatch):
        """Cycle with no signal returns empty messages."""
        monkeypatch.setattr(
            "breakout.paper_executor.BREAKOUT_STATE_FILE",
            str(tmp_path / "state.json"),
        )

        def flat_candles(symbol, interval, limit):
            n = 50
            return pd.DataFrame({
                "open": [100.0] * n,
                "high": [100.5] * n,
                "low": [99.5] * n,
                "close": [100.0] * n,
                "volume": [100.0] * n,
                "time": pd.date_range("2026-01-01", periods=n, freq="5min"),
            })

        msgs = process_breakout_cycle(
            ["BTCUSDT"],
            open_new=True,
            candle_fn=flat_candles,
        )
        assert isinstance(msgs, list)

    def test_get_breakout_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "breakout.paper_executor.BREAKOUT_STATE_FILE",
            str(tmp_path / "state.json"),
        )
        from breakout.paper_executor import get_breakout_status
        status = get_breakout_status()
        assert "BREAKOUT 5M" in status
