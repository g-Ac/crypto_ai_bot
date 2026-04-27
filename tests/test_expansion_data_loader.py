"""Tests for data_loader: fetching, alignment, gap detection."""
import numpy as np
import pandas as pd
import pytest

from momentum.expansion.data_loader import (
    GapValidationError,
    align_candles_by_timestamp,
    validate_gap_threshold,
)


def _ts_series(n: int, start_ms: int = 0, step_ms: int = 900_000) -> np.ndarray:
    return np.arange(start_ms, start_ms + n * step_ms, step_ms, dtype=np.int64)


def _df(close_times_ms: np.ndarray) -> pd.DataFrame:
    n = len(close_times_ms)
    return pd.DataFrame({
        "close_time_ms": close_times_ms,
        "open": np.full(n, 100.0),
        "high": np.full(n, 101.0),
        "low": np.full(n, 99.0),
        "close": np.full(n, 100.5),
        "volume": np.full(n, 1000.0),
    })


def test_align_perfectly_synchronized():
    btc = _df(_ts_series(100))
    eth = _df(_ts_series(100))
    aligned = align_candles_by_timestamp({"BTCUSDT": btc, "ETHUSDT": eth})
    assert len(aligned["BTCUSDT"]) == 100
    assert len(aligned["ETHUSDT"]) == 100


def test_align_intersection_drops_unique_timestamps():
    btc = _df(_ts_series(100, start_ms=0))                           # 0..89_100_000
    eth = _df(_ts_series(100, start_ms=900_000))                     # 900_000..90_000_000
    aligned = align_candles_by_timestamp({"BTCUSDT": btc, "ETHUSDT": eth})
    assert len(aligned["BTCUSDT"]) == 99
    assert len(aligned["ETHUSDT"]) == 99
    # Common timestamps should match
    assert (aligned["BTCUSDT"]["close_time_ms"].values
            == aligned["ETHUSDT"]["close_time_ms"].values).all()


def test_validate_gap_passes_when_close():
    expected = 1000
    actual = 996  # 0.4% gap
    validate_gap_threshold(symbol="BTCUSDT", expected=expected, actual=actual, threshold_pct=0.5)


def test_validate_gap_fails_when_too_big():
    expected = 1000
    actual = 990  # 1.0% gap
    with pytest.raises(GapValidationError) as exc:
        validate_gap_threshold(symbol="BTCUSDT", expected=expected, actual=actual, threshold_pct=0.5)
    assert "BTCUSDT" in str(exc.value)
    assert "gap_pct" in str(exc.value).lower() or "1.0" in str(exc.value)


def test_align_empty_input_raises():
    with pytest.raises(ValueError):
        align_candles_by_timestamp({})


def test_align_one_symbol_passes_through():
    btc = _df(_ts_series(50))
    aligned = align_candles_by_timestamp({"BTCUSDT": btc})
    assert len(aligned["BTCUSDT"]) == 50
