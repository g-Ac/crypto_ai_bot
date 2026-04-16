"""Tests for htf.py — HTF trend classification and regime detection."""

import pandas as pd
import numpy as np
from htf import classify_htf_trend, get_htf_regime
from unittest.mock import patch, MagicMock


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


def _setup_regime_mocks(mock_adx_cls, mock_atr_cls, mock_bb_cls, mock_candles,
                         adx_val=30.0, adx_slope=5.0, di_plus=25.0, di_minus=10.0,
                         bb_width_pct=2.0, price=100.0):
    """Configure mocks for regime v2 tests with precise indicator control."""
    n = 50
    mock_candles.return_value = _make_htf_df(n=n)

    # ADX series: iloc[-2]=adx_val, iloc[-5]=adx_val-adx_slope
    adx_s = pd.Series([float("nan")] * n)
    adx_s.iloc[-2] = float(adx_val)
    if adx_slope is not None:
        adx_s.iloc[-5] = float(adx_val) - float(adx_slope)
    mock_adx_cls.return_value.adx.return_value = adx_s

    # DI+ and DI- series
    di_plus_s = pd.Series([float("nan")] * n)
    di_plus_s.iloc[-2] = float("nan") if di_plus is None else float(di_plus)
    mock_adx_cls.return_value.adx_pos.return_value = di_plus_s

    di_minus_s = pd.Series([float("nan")] * n)
    di_minus_s.iloc[-2] = float("nan") if di_minus is None else float(di_minus)
    mock_adx_cls.return_value.adx_neg.return_value = di_minus_s

    # ATR
    mock_atr_cls.return_value.average_true_range.return_value = pd.Series([price * 0.01] * n)

    # BB: (upper - lower) / mid * 100 = bb_width_pct
    bb_half = bb_width_pct * price / 200
    mock_bb_cls.return_value.bollinger_wband.return_value = pd.Series([bb_width_pct / 100] * n)
    mock_bb_cls.return_value.bollinger_mavg.return_value = pd.Series([price] * n)
    mock_bb_cls.return_value.bollinger_hband.return_value = pd.Series([price + bb_half] * n)
    mock_bb_cls.return_value.bollinger_lband.return_value = pd.Series([price - bb_half] * n)


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


# ── Regime Gate v2 tests ──────────────────────────────────────────


@patch("htf.get_candles")
@patch("htf.ta.volatility.BollingerBands")
@patch("htf.ta.volatility.AverageTrueRange")
@patch("htf.ta.trend.ADXIndicator")
def test_v2_trending_base_case(mock_adx, mock_atr, mock_bb, mock_candles):
    """ADX>=25, BB>1.5%, slope>0, DI spread>=10 → TRENDING (no downgrade)."""
    _setup_regime_mocks(mock_adx, mock_atr, mock_bb, mock_candles,
                         adx_val=30.0, adx_slope=5.0, di_plus=25.0, di_minus=10.0,
                         bb_width_pct=2.0)
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] == "TRENDING"


@patch("htf.get_candles")
@patch("htf.ta.volatility.BollingerBands")
@patch("htf.ta.volatility.AverageTrueRange")
@patch("htf.ta.trend.ADXIndicator")
def test_v2_filter_a_adx_slope_downgrade(mock_adx, mock_atr, mock_bb, mock_candles):
    """ADX>=25, BB>1.5%, slope<=0, DI spread>=10 → WEAK_TREND (filter A)."""
    _setup_regime_mocks(mock_adx, mock_atr, mock_bb, mock_candles,
                         adx_val=30.0, adx_slope=-2.0, di_plus=25.0, di_minus=10.0,
                         bb_width_pct=2.0)
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] == "WEAK_TREND"


@patch("htf.get_candles")
@patch("htf.ta.volatility.BollingerBands")
@patch("htf.ta.volatility.AverageTrueRange")
@patch("htf.ta.trend.ADXIndicator")
def test_v2_filter_b_di_spread_downgrade(mock_adx, mock_atr, mock_bb, mock_candles):
    """ADX>=25, BB>1.5%, slope>0, DI spread<10 → WEAK_TREND (filter B)."""
    _setup_regime_mocks(mock_adx, mock_atr, mock_bb, mock_candles,
                         adx_val=30.0, adx_slope=5.0, di_plus=20.0, di_minus=15.0,
                         bb_width_pct=2.0)
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] == "WEAK_TREND"
    assert result["di_spread"] == 5.0


@patch("htf.get_candles")
@patch("htf.ta.volatility.BollingerBands")
@patch("htf.ta.volatility.AverageTrueRange")
@patch("htf.ta.trend.ADXIndicator")
def test_v2_both_filters_downgrade(mock_adx, mock_atr, mock_bb, mock_candles):
    """ADX>=25, BB>1.5%, slope<=0, DI spread<10 → WEAK_TREND (both filters)."""
    _setup_regime_mocks(mock_adx, mock_atr, mock_bb, mock_candles,
                         adx_val=28.0, adx_slope=-1.0, di_plus=18.0, di_minus=14.0,
                         bb_width_pct=2.0)
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] == "WEAK_TREND"


@patch("htf.get_candles")
@patch("htf.ta.volatility.BollingerBands")
@patch("htf.ta.volatility.AverageTrueRange")
@patch("htf.ta.trend.ADXIndicator")
def test_v2_bb_narrow_still_weak_trend(mock_adx, mock_atr, mock_bb, mock_candles):
    """ADX>=25, BB<=1.5% → WEAK_TREND regardless of slope/DI (unchanged)."""
    _setup_regime_mocks(mock_adx, mock_atr, mock_bb, mock_candles,
                         adx_val=30.0, adx_slope=5.0, di_plus=25.0, di_minus=10.0,
                         bb_width_pct=1.0)
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] == "WEAK_TREND"


@patch("htf.get_candles")
@patch("htf.ta.volatility.BollingerBands")
@patch("htf.ta.volatility.AverageTrueRange")
@patch("htf.ta.trend.ADXIndicator")
def test_v2_low_adx_not_affected(mock_adx, mock_atr, mock_bb, mock_candles):
    """ADX<25 → regime based on BB width only, filters don't apply."""
    _setup_regime_mocks(mock_adx, mock_atr, mock_bb, mock_candles,
                         adx_val=20.0, adx_slope=-5.0, di_plus=12.0, di_minus=11.0,
                         bb_width_pct=2.5)
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] == "VOLATILE"


@patch("htf.get_candles")
@patch("htf.ta.volatility.BollingerBands")
@patch("htf.ta.volatility.AverageTrueRange")
@patch("htf.ta.trend.ADXIndicator")
def test_v2_nan_di_triggers_downgrade(mock_adx, mock_atr, mock_bb, mock_candles):
    """NaN DI+ or DI- → di_spread=0 → downgrade applied."""
    _setup_regime_mocks(mock_adx, mock_atr, mock_bb, mock_candles,
                         adx_val=30.0, adx_slope=5.0, di_plus=None, di_minus=None,
                         bb_width_pct=2.0)
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] == "WEAK_TREND"
    assert result["di_spread"] == 0.0


@patch("htf.get_candles")
def test_v2_unknown_includes_new_fields(mock_candles):
    """UNKNOWN return (short data) includes adx_slope_3 and di_spread."""
    mock_candles.return_value = _make_htf_df(n=5)
    result = get_htf_regime("BTCUSDT")
    assert result["regime_label"] == "UNKNOWN"
    assert "adx_slope_3" in result
    assert "di_spread" in result
    assert result["adx_slope_3"] == 0.0
    assert result["di_spread"] == 0.0


@patch("htf.get_candles")
@patch("htf.ta.volatility.BollingerBands")
@patch("htf.ta.volatility.AverageTrueRange")
@patch("htf.ta.trend.ADXIndicator")
def test_v2_new_fields_in_return(mock_adx, mock_atr, mock_bb, mock_candles):
    """Normal return includes adx_slope_3 and di_spread with correct values."""
    _setup_regime_mocks(mock_adx, mock_atr, mock_bb, mock_candles,
                         adx_val=30.0, adx_slope=3.5, di_plus=25.0, di_minus=10.0,
                         bb_width_pct=2.0)
    result = get_htf_regime("BTCUSDT")
    assert result["adx_slope_3"] == 3.5
    assert result["di_spread"] == 15.0
    assert result["regime_label"] == "TRENDING"


# ── Integration: momentum accepts downgraded regime ──


def test_v2_momentum_accepts_weak_trend():
    """WEAK_TREND is in MOMENTUM_PERMISSIVE_REGIMES — downgrade doesn't block."""
    from momentum.config import MOMENTUM_PERMISSIVE_REGIMES
    assert "WEAK_TREND" in MOMENTUM_PERMISSIVE_REGIMES
    assert "TRENDING" in MOMENTUM_PERMISSIVE_REGIMES
