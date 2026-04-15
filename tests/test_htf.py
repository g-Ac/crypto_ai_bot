"""Tests for htf.py — HTF trend classification and regime detection."""

import pandas as pd
import numpy as np
from htf import classify_htf_trend, get_htf_regime
from unittest.mock import patch


def test_classify_alta():
    assert classify_htf_trend(110.0, 100.0) == "alta"


def test_classify_baixa():
    assert classify_htf_trend(90.0, 100.0) == "baixa"


def test_classify_equal_is_lateral():
    assert classify_htf_trend(100.0, 100.0) == "lateral"


def test_classify_nan_is_lateral():
    assert classify_htf_trend(float("nan"), 100.0) == "lateral"
    assert classify_htf_trend(100.0, float("nan")) == "lateral"
    assert classify_htf_trend(None, None) == "lateral"


def _make_htf_df(n=50, adx_high=True, bb_wide=True):
    """Build a mock 1h DataFrame with controlled ADX/BB characteristics."""
    np.random.seed(42)
    if adx_high and bb_wide:
        # Strong trend with wide BBs
        close = 100 + np.arange(n) * 0.5 + np.random.randn(n) * 0.3
    elif adx_high and not bb_wide:
        # Strong trend, tight range
        close = 100 + np.arange(n) * 0.1 + np.random.randn(n) * 0.05
    elif not adx_high and bb_wide:
        # No trend but volatile
        close = 100 + np.random.randn(n) * 3.0
    else:
        # Choppy, no trend, tight
        close = 100 + np.random.randn(n) * 0.1
    high = close + np.abs(np.random.randn(n) * 0.5)
    low = close - np.abs(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=n, freq="1h"),
        "open": close + np.random.randn(n) * 0.1,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(100, 1000, size=n).astype(float),
    })


@patch("htf.get_candles")
def test_get_htf_regime_returns_dict(mock_candles):
    mock_candles.return_value = _make_htf_df()
    result = get_htf_regime("BTCUSDT")
    assert "regime_label" in result
    assert result["regime_label"] in ("TRENDING", "WEAK_TREND", "VOLATILE", "RANGING", "CHOPPY")
    assert "adx_1h" in result
    assert "atr_1h_pct" in result
    assert "bb_width_1h" in result


@patch("htf.get_candles")
def test_get_htf_regime_short_df(mock_candles):
    mock_candles.return_value = _make_htf_df(n=5)
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] == "UNKNOWN"


@patch("htf.get_candles")
def test_get_htf_regime_none_df(mock_candles):
    mock_candles.return_value = None
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] == "UNKNOWN"


@patch("htf.get_candles")
def test_regime_choppy(mock_candles):
    """Very tight, trendless data should be CHOPPY."""
    mock_candles.return_value = _make_htf_df(n=50, adx_high=False, bb_wide=False)
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] in ("CHOPPY", "RANGING")
