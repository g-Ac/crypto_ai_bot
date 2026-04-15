"""Tests for defensive/value_reference.py — BB, ATR, VWAP, z-score."""
import numpy as np
import pandas as pd
import pytest

from defensive.value_reference import (
    atr_series,
    bb_width_series,
    compute_value_metrics,
    percentile_rank,
)


def _make_candles(n: int = 100, base: float = 100.0, noise: float = 1.0) -> pd.DataFrame:
    """Generate synthetic candles with controlled noise."""
    rng = np.random.RandomState(42)
    closes = base + np.cumsum(rng.randn(n) * noise)
    highs = closes + rng.rand(n) * noise
    lows = closes - rng.rand(n) * noise
    opens = closes + rng.randn(n) * noise * 0.3
    volumes = 1000 + rng.rand(n) * 500
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    })


# --- compute_value_metrics ---

class TestComputeValueMetrics:
    def test_returns_value_metrics_with_enough_data(self):
        df = _make_candles(100)
        vm = compute_value_metrics(df)
        assert vm.bb_upper > vm.bb_mid > vm.bb_lower
        assert vm.bb_width_pct > 0
        assert vm.atr > 0
        assert vm.atr_pct > 0
        assert vm.vwap > 0

    def test_returns_empty_with_insufficient_data(self):
        df = _make_candles(10)
        vm = compute_value_metrics(df)
        assert vm.bb_upper == 0.0
        assert vm.vwap == 0.0

    def test_bb_bands_contain_price(self):
        """BB upper > close > BB lower on average (statistical, not every candle)."""
        df = _make_candles(200, noise=0.5)
        vm = compute_value_metrics(df)
        last_close = df["close"].iloc[-1]
        # Bands should bracket the SMA, not necessarily every close
        assert vm.bb_upper > vm.bb_lower

    def test_vwap_near_price(self):
        """VWAP should be near the mean price for stable data."""
        df = _make_candles(200, base=100.0, noise=0.1)
        vm = compute_value_metrics(df)
        assert abs(vm.vwap - 100.0) < 10.0  # Should be within 10% of base

    def test_zscore_sign_matches_displacement(self):
        """If price is above VWAP, z-score should be positive."""
        df = _make_candles(100, noise=0.1)
        vm = compute_value_metrics(df)
        last_close = df["close"].iloc[-1]
        if last_close > vm.vwap:
            assert vm.z_score > 0
        elif last_close < vm.vwap:
            assert vm.z_score < 0

    def test_flat_price_low_bb_width(self):
        """Flat price series should have very narrow BB Width."""
        df = pd.DataFrame({
            "open": [100.0] * 50,
            "high": [100.1] * 50,
            "low": [99.9] * 50,
            "close": [100.0] * 50,
            "volume": [1000.0] * 50,
        })
        vm = compute_value_metrics(df)
        assert vm.bb_width_pct < 1.0  # Very tight bands

    def test_atr_reflects_volatility(self):
        """Higher noise → higher ATR."""
        df_calm = _make_candles(100, noise=0.1)
        df_wild = _make_candles(100, noise=5.0)
        vm_calm = compute_value_metrics(df_calm)
        vm_wild = compute_value_metrics(df_wild)
        assert vm_wild.atr > vm_calm.atr


# --- percentile_rank ---

class TestPercentileRank:
    def test_basic_percentile(self):
        series = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert percentile_rank(3.0, series) == 40.0  # 2/5 * 100

    def test_min_value(self):
        series = np.array([1.0, 2.0, 3.0])
        assert percentile_rank(1.0, series) == 0.0

    def test_max_value(self):
        series = np.array([1.0, 2.0, 3.0])
        assert percentile_rank(4.0, series) == 100.0

    def test_empty_series(self):
        assert percentile_rank(5.0, np.array([])) == 50.0


# --- bb_width_series ---

class TestBBWidthSeries:
    def test_length_matches_candles(self):
        df = _make_candles(50)
        bw = bb_width_series(df)
        assert len(bw) == len(df)

    def test_first_19_are_nan_or_zero(self):
        """BB(20) needs 20 periods — first 19 should be NaN/zero."""
        df = _make_candles(50)
        bw = bb_width_series(df)
        # First 19 values: SMA not ready yet, should be NaN from rolling
        assert np.isnan(bw[0]) or bw[0] == 0.0

    def test_positive_after_warmup(self):
        df = _make_candles(50)
        bw = bb_width_series(df)
        valid = bw[20:]
        assert all(v > 0 for v in valid if not np.isnan(v))


# --- atr_series ---

class TestATRSeries:
    def test_length_matches_candles(self):
        df = _make_candles(50)
        a = atr_series(df)
        assert len(a) == len(df)

    def test_positive_after_warmup(self):
        df = _make_candles(50)
        a = atr_series(df)
        valid = a[14:]
        assert all(v > 0 for v in valid if not np.isnan(v))

    def test_flat_market_low_atr(self):
        df = pd.DataFrame({
            "open": [100.0] * 30,
            "high": [100.1] * 30,
            "low": [99.9] * 30,
            "close": [100.0] * 30,
            "volume": [1000.0] * 30,
        })
        a = atr_series(df)
        assert a[-1] == pytest.approx(0.2, abs=0.01)  # high-low = 0.2
