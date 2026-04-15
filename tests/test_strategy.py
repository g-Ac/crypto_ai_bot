"""Tests for strategy.py — signal scoring logic."""

import pandas as pd
import numpy as np
from strategy import _score_row, generate_signal
from indicators import add_indicators
from config import SMA_SHORT, SMA_LONG, BREAKOUT_WINDOW, SIGNAL_SCORE_MIN


def _make_row(**overrides):
    """Build a row dict with all required indicator columns."""
    base = {
        f"sma_{SMA_SHORT}": 100.0,
        f"sma_{SMA_LONG}": 99.0,
        f"sma_{SMA_SHORT}_prev": 99.5,
        f"sma_{SMA_LONG}_prev": 99.0,
        "close": 101.0,
        "rsi": 55.0,
        f"recent_high_{BREAKOUT_WINDOW}": 100.5,
        f"recent_low_{BREAKOUT_WINDOW}": 98.0,
        "volume": 500.0,
        "volume_avg": 400.0,
        "body_ratio": 0.7,
    }
    base.update(overrides)
    return base


def test_score_row_returns_dict():
    result = _score_row(_make_row())
    assert result is not None
    assert "decision" in result
    assert "buy_score" in result
    assert "sell_score" in result


def test_score_row_nan_returns_none():
    row = _make_row(rsi=float("nan"))
    assert _score_row(row) is None


def test_strong_buy_signal():
    """All buy criteria met should produce BUY."""
    row = _make_row(
        close=101.5,
        **{f"sma_{SMA_SHORT}": 101.0, f"sma_{SMA_LONG}": 100.0},
        **{f"sma_{SMA_SHORT}_prev": 100.5, f"sma_{SMA_LONG}_prev": 99.5},
        rsi=40.0,
        **{f"recent_high_{BREAKOUT_WINDOW}": 101.0},
        volume=600.0,
        volume_avg=400.0,
        body_ratio=0.8,
    )
    result = _score_row(row, htf_trend="alta")
    assert result["decision"] == "BUY"
    assert result["buy_score"] >= SIGNAL_SCORE_MIN


def test_strong_sell_signal():
    """All sell criteria met should produce SELL."""
    row = _make_row(
        close=97.0,
        **{f"sma_{SMA_SHORT}": 98.0, f"sma_{SMA_LONG}": 99.0},
        **{f"sma_{SMA_SHORT}_prev": 98.5, f"sma_{SMA_LONG}_prev": 99.5},
        rsi=65.0,
        **{f"recent_low_{BREAKOUT_WINDOW}": 97.5},
        volume=600.0,
        volume_avg=400.0,
        body_ratio=-0.8,
    )
    result = _score_row(row, htf_trend="baixa")
    assert result["decision"] == "SELL"
    assert result["sell_score"] >= SIGNAL_SCORE_MIN


def test_htf_blocks_counter_trend():
    """BUY in htf baixa should be blocked to HOLD."""
    row = _make_row(
        close=101.5,
        **{f"sma_{SMA_SHORT}": 101.0, f"sma_{SMA_LONG}": 100.0},
        **{f"sma_{SMA_SHORT}_prev": 100.5, f"sma_{SMA_LONG}_prev": 99.5},
        rsi=40.0,
        **{f"recent_high_{BREAKOUT_WINDOW}": 101.0},
        volume=600.0,
        body_ratio=0.8,
    )
    result = _score_row(row, htf_trend="baixa")
    assert result["decision"] == "HOLD"


def test_overbought_blocks_buy():
    """RSI overbought should block BUY even with high buy_score."""
    row = _make_row(
        close=101.5,
        **{f"sma_{SMA_SHORT}": 101.0, f"sma_{SMA_LONG}": 100.0},
        **{f"sma_{SMA_SHORT}_prev": 100.5, f"sma_{SMA_LONG}_prev": 99.5},
        rsi=85.0,
        **{f"recent_high_{BREAKOUT_WINDOW}": 101.0},
        volume=600.0,
        body_ratio=0.8,
    )
    result = _score_row(row, htf_trend="alta")
    assert result["decision"] == "HOLD"


def test_weak_signal_is_hold():
    """Low scores should result in HOLD."""
    row = _make_row(
        close=100.0,
        **{f"sma_{SMA_SHORT}": 100.0, f"sma_{SMA_LONG}": 100.0},
        **{f"sma_{SMA_SHORT}_prev": 100.0, f"sma_{SMA_LONG}_prev": 100.0},
        rsi=50.0,
        **{f"recent_high_{BREAKOUT_WINDOW}": 101.0, f"recent_low_{BREAKOUT_WINDOW}": 99.0},
        volume=300.0,
        volume_avg=400.0,
        body_ratio=0.3,
    )
    result = _score_row(row)
    assert result["decision"] == "HOLD"


def test_generate_signal_with_df():
    """generate_signal should work with a full DataFrame."""
    np.random.seed(42)
    n = 50
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=n, freq="5min"),
        "open": close + np.random.randn(n) * 0.1,
        "high": close + 0.3,
        "low": close - 0.3,
        "close": close,
        "volume": np.random.randint(100, 1000, size=n).astype(float),
    })
    df = add_indicators(df)
    result = generate_signal(df)
    if result is not None:
        assert "decision" in result
        assert result["decision"] in ("BUY", "SELL", "HOLD")
        assert 0 <= result["confidence_score"] <= 100


def test_trend_group_scoring():
    """Trend group: 3/3 hits = 1.5pts, not 3pts."""
    row = _make_row(
        close=102.0,
        **{f"sma_{SMA_SHORT}": 101.0, f"sma_{SMA_LONG}": 100.0},
        **{f"sma_{SMA_SHORT}_prev": 100.5, f"sma_{SMA_LONG}_prev": 99.5},
        rsi=50.0,
        **{f"recent_high_{BREAKOUT_WINDOW}": 103.0, f"recent_low_{BREAKOUT_WINDOW}": 98.0},
        volume=300.0,
        volume_avg=400.0,
        body_ratio=0.3,
    )
    result = _score_row(row)
    # 3 trend hits = 1.5pts buy, no other buy criteria
    assert result["buy_score"] == 1.5
