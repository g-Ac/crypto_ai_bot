"""Tests for 1-minute indicators."""
import numpy as np
import pandas as pd
import pytest
from indicators_1m import add_indicators_1m


def _make_candles(n: int = 50, base_price: float = 100.0) -> pd.DataFrame:
    np.random.seed(42)
    closes = base_price + np.cumsum(np.random.randn(n) * 0.5)
    opens = closes + np.random.randn(n) * 0.2
    # Ensure high >= max(open, close) and low <= min(open, close)
    highs = np.maximum(closes, opens) + np.abs(np.random.randn(n) * 0.3)
    lows = np.minimum(closes, opens) - np.abs(np.random.randn(n) * 0.3)
    volumes = np.random.uniform(100, 1000, n)
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    })


class TestIndicatorColumns:
    def test_all_columns_present(self):
        df = add_indicators_1m(_make_candles(100))
        expected = [
            "ema8", "ema21", "sma20",
            "atr14", "bb_upper", "bb_lower", "bb_middle", "bb_bandwidth",
            "rsi14", "vol_avg20", "vol_ratio", "vwap",
            "body", "range", "body_ratio",
            "upper_shadow", "lower_shadow", "is_green",
        ]
        for col in expected:
            assert col in df.columns, f"Missing column: {col}"

    def test_output_same_length_as_input(self):
        df_in = _make_candles(100)
        df_out = add_indicators_1m(df_in)
        assert len(df_out) == len(df_in)


class TestIndicatorValues:
    def test_ema8_is_close_to_price(self):
        df = add_indicators_1m(_make_candles(100))
        last_ema = df["ema8"].iloc[-1]
        last_close = df["close"].iloc[-1]
        assert abs(last_ema - last_close) / last_close < 0.05

    def test_rsi_bounded_0_100(self):
        df = add_indicators_1m(_make_candles(200))
        valid_rsi = df["rsi14"].dropna()
        assert valid_rsi.min() >= 0
        assert valid_rsi.max() <= 100

    def test_atr_positive(self):
        df = add_indicators_1m(_make_candles(100))
        valid_atr = df["atr14"].dropna()
        assert (valid_atr > 0).all()

    def test_body_ratio_bounded_0_1(self):
        df = add_indicators_1m(_make_candles(100))
        valid = df["body_ratio"].dropna()
        assert valid.min() >= 0
        assert valid.max() <= 1.0 + 1e-9

    def test_vol_ratio_around_one(self):
        df = add_indicators_1m(_make_candles(200))
        valid = df["vol_ratio"].dropna()
        assert 0.5 < valid.mean() < 1.5

    def test_vwap_is_between_low_and_high(self):
        df = add_indicators_1m(_make_candles(250))
        valid_rows = df.dropna(subset=["vwap"]).tail(50)
        for _, row in valid_rows.iterrows():
            assert row["vwap"] > row["low"] * 0.9
            assert row["vwap"] < row["high"] * 1.1

    def test_is_green_boolean(self):
        df = add_indicators_1m(_make_candles(50))
        assert df["is_green"].dtype == bool


class TestMinimumData:
    def test_small_dataframe_doesnt_crash(self):
        df = add_indicators_1m(_make_candles(10))
        assert len(df) == 10
        assert "ema8" in df.columns
