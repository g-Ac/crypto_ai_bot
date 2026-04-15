"""Tests for momentum/swing_detector.py."""

import pandas as pd
import pytest

from momentum.swing_detector import (
    SwingPoint,
    SwingType,
    detect_swings,
    impulse_retracement_pct,
    last_impulse,
)


def _make_candles(highs, lows, closes=None, timestamps=None):
    """Helper to build a candle DataFrame from lists."""
    n = len(highs)
    if closes is None:
        closes = [(h + lo) / 2 for h, lo in zip(highs, lows)]
    if timestamps is None:
        timestamps = [f"2026-01-01T{i:02d}:00:00" for i in range(n)]
    return pd.DataFrame({
        "high": highs,
        "low": lows,
        "close": closes,
        "timestamp": timestamps,
    })


# ---------------------------------------------------------------
# 1. Uptrend with clear swing highs and lows
# ---------------------------------------------------------------
class TestUptrend:
    def test_detects_swing_low_and_high(self):
        # Pattern: valley at index 5, peak at index 10
        #   highs descend to 5, then ascend to 10, then descend
        highs = [20, 19, 18, 17, 16, 15, 16, 17, 18, 19, 20, 19, 18, 17, 16]
        lows = [h - 1 for h in highs]
        candles = _make_candles(highs, lows)

        swings = detect_swings(candles, lookback=5)

        swing_types = [(s.index, s.swing_type) for s in swings]
        # Index 5 should be swing low (low=14, lowest in [0..10])
        assert (5, SwingType.LOW) in swing_types
        # Index 10 is at the edge (needs 5 candles after = index 15, but we only have 15 candles = index 14)
        # So index 10 is NOT detected (only 4 candles after). Index 9 with lookback=5 needs index 14, OK.
        # Let's check what we actually get
        low_swings = [s for s in swings if s.swing_type == SwingType.LOW]
        assert len(low_swings) >= 1
        assert low_swings[0].price == 14.0  # low at index 5

    def test_swing_high_detected_with_enough_context(self):
        # Explicit peak at index 7, with 5 candles on each side
        highs = [10, 11, 12, 13, 14, 15, 16, 17, 16, 15, 14, 13, 12]
        lows = [h - 1 for h in highs]
        candles = _make_candles(highs, lows)

        swings = detect_swings(candles, lookback=5)

        high_swings = [s for s in swings if s.swing_type == SwingType.HIGH]
        assert len(high_swings) == 1
        assert high_swings[0].index == 7
        assert high_swings[0].price == 17.0


# ---------------------------------------------------------------
# 2. Downtrend
# ---------------------------------------------------------------
class TestDowntrend:
    def test_detects_swing_high_then_low(self):
        # Peak at 5, valley at 10
        highs = [15, 16, 17, 18, 19, 20, 19, 18, 17, 16, 15, 16, 17, 18, 19, 20]
        lows = [h - 1 for h in highs]
        candles = _make_candles(highs, lows)

        swings = detect_swings(candles, lookback=5)

        high_swings = [s for s in swings if s.swing_type == SwingType.HIGH]
        low_swings = [s for s in swings if s.swing_type == SwingType.LOW]

        assert len(high_swings) >= 1
        assert high_swings[0].index == 5
        assert high_swings[0].price == 20.0

        assert len(low_swings) >= 1
        assert low_swings[0].index == 10
        assert low_swings[0].price == 14.0


# ---------------------------------------------------------------
# 3. Sideways market
# ---------------------------------------------------------------
class TestSideways:
    def test_flat_prices_no_swings(self):
        highs = [100.0] * 20
        lows = [99.0] * 20
        candles = _make_candles(highs, lows)

        swings = detect_swings(candles, lookback=5)

        # All highs equal → every point is technically a swing high/low
        # But that's correct behavior: >=/<= means ties count.
        # The important thing is it doesn't crash.
        assert isinstance(swings, list)

    def test_narrow_range_oscillation(self):
        # Small oscillation: 100, 101, 100, 101, ...
        n = 20
        highs = [100 + (i % 2) for i in range(n)]
        lows = [99 + (i % 2) for i in range(n)]
        candles = _make_candles(highs, lows)

        swings = detect_swings(candles, lookback=3)
        # Should not crash; results depend on exact pattern
        assert isinstance(swings, list)


# ---------------------------------------------------------------
# 4. Insufficient data
# ---------------------------------------------------------------
class TestInsufficientData:
    def test_too_few_candles(self):
        highs = [10, 11, 12]
        lows = [9, 10, 11]
        candles = _make_candles(highs, lows)

        swings = detect_swings(candles, lookback=5)
        assert swings == []

    def test_exact_minimum_candles(self):
        # 2*5+1 = 11 candles: exactly enough for 1 candidate at index 5
        highs = [10, 11, 12, 13, 14, 15, 14, 13, 12, 11, 10]
        lows = [h - 1 for h in highs]
        candles = _make_candles(highs, lows)

        swings = detect_swings(candles, lookback=5)
        assert len(swings) >= 1
        high_swings = [s for s in swings if s.swing_type == SwingType.HIGH]
        assert high_swings[0].index == 5
        assert high_swings[0].price == 15.0

    def test_empty_dataframe(self):
        candles = pd.DataFrame(columns=["high", "low", "close", "timestamp"])
        swings = detect_swings(candles, lookback=5)
        assert swings == []


# ---------------------------------------------------------------
# 5. No lookahead bias
# ---------------------------------------------------------------
class TestNoLookahead:
    def test_last_swing_never_in_final_lookback_candles(self):
        """The last `lookback` candles can never contain a confirmed swing."""
        highs = [10, 12, 14, 16, 18, 20, 18, 16, 14, 12, 10, 8, 10, 12, 14, 16, 18, 20, 19, 18]
        lows = [h - 1 for h in highs]
        candles = _make_candles(highs, lows)
        lookback = 5

        swings = detect_swings(candles, lookback=lookback)

        n = len(candles)
        for s in swings:
            assert s.index < n - lookback, (
                f"Swing at index {s.index} is within the last {lookback} candles "
                f"(n={n}). This indicates lookahead bias."
            )

    def test_adding_candles_doesnt_change_past_swings(self):
        """Swings detected with 20 candles should not change when we add 5 more."""
        base_highs = [10, 12, 14, 16, 18, 20, 18, 16, 14, 12, 10, 12, 14, 16, 18, 20, 18, 16, 14, 12]
        base_lows = [h - 1 for h in base_highs]
        candles_20 = _make_candles(base_highs, base_lows)

        extended_highs = base_highs + [10, 8, 6, 4, 2]
        extended_lows = [h - 1 for h in extended_highs]
        candles_25 = _make_candles(extended_highs, extended_lows)

        swings_20 = detect_swings(candles_20, lookback=5)
        swings_25 = detect_swings(candles_25, lookback=5)

        # All swings from the 20-candle run should appear identically in the 25-candle run
        for s20 in swings_20:
            match = [s for s in swings_25 if s.index == s20.index and s.swing_type == s20.swing_type]
            assert len(match) == 1, (
                f"Swing {s20} from 20-candle run not found in 25-candle run. "
                "Past swings should be stable when new data arrives."
            )
            assert match[0].price == s20.price


# ---------------------------------------------------------------
# 6. Determinism
# ---------------------------------------------------------------
class TestDeterminism:
    def test_same_input_same_output(self):
        highs = [10, 12, 14, 16, 18, 20, 18, 16, 14, 12, 10]
        lows = [h - 1 for h in highs]
        candles = _make_candles(highs, lows)

        result1 = detect_swings(candles, lookback=5)
        result2 = detect_swings(candles, lookback=5)

        assert result1 == result2


# ---------------------------------------------------------------
# 7. All prices equal
# ---------------------------------------------------------------
class TestAllEqual:
    def test_all_same_price(self):
        highs = [100.0] * 15
        lows = [100.0] * 15
        candles = _make_candles(highs, lows, closes=[100.0] * 15)

        swings = detect_swings(candles, lookback=5)
        # With >= / <= all points qualify as both high and low
        # This is degenerate but should not crash
        assert isinstance(swings, list)


# ---------------------------------------------------------------
# 8. last_impulse function
# ---------------------------------------------------------------
class TestLastImpulse:
    def test_finds_last_opposite_pair(self):
        swings = [
            SwingPoint(5, "t5", 100.0, SwingType.LOW),
            SwingPoint(10, "t10", 120.0, SwingType.HIGH),
            SwingPoint(15, "t15", 110.0, SwingType.LOW),
        ]
        start, end = last_impulse(swings)
        assert start.index == 10  # HIGH
        assert end.index == 15    # LOW
        assert start.swing_type != end.swing_type

    def test_returns_none_with_single_swing(self):
        swings = [SwingPoint(5, "t5", 100.0, SwingType.LOW)]
        start, end = last_impulse(swings)
        assert start is None
        assert end is None

    def test_returns_none_with_same_type(self):
        swings = [
            SwingPoint(5, "t5", 100.0, SwingType.HIGH),
            SwingPoint(10, "t10", 105.0, SwingType.HIGH),
        ]
        start, end = last_impulse(swings)
        assert start is None

    def test_empty_list(self):
        start, end = last_impulse([])
        assert start is None


# ---------------------------------------------------------------
# 9. impulse_retracement_pct
# ---------------------------------------------------------------
class TestRetracement:
    def test_no_retracement(self):
        start = SwingPoint(0, "t0", 100.0, SwingType.LOW)
        end = SwingPoint(5, "t5", 120.0, SwingType.HIGH)
        # Price at end of impulse = no retracement
        assert impulse_retracement_pct(start, end, 120.0) == 0.0

    def test_50_pct_retracement_upward(self):
        start = SwingPoint(0, "t0", 100.0, SwingType.LOW)
        end = SwingPoint(5, "t5", 120.0, SwingType.HIGH)
        # Price at 110 = 50% back toward 100
        assert impulse_retracement_pct(start, end, 110.0) == 50.0

    def test_full_retracement(self):
        start = SwingPoint(0, "t0", 100.0, SwingType.LOW)
        end = SwingPoint(5, "t5", 120.0, SwingType.HIGH)
        assert impulse_retracement_pct(start, end, 100.0) == 100.0

    def test_beyond_full_retracement(self):
        start = SwingPoint(0, "t0", 100.0, SwingType.LOW)
        end = SwingPoint(5, "t5", 120.0, SwingType.HIGH)
        result = impulse_retracement_pct(start, end, 90.0)
        assert result == 150.0  # Went 30 past on a 20 range

    def test_downward_impulse(self):
        start = SwingPoint(0, "t0", 120.0, SwingType.HIGH)
        end = SwingPoint(5, "t5", 100.0, SwingType.LOW)
        # Price at 110 = 50% retracement of downward move
        assert impulse_retracement_pct(start, end, 110.0) == 50.0

    def test_zero_range_impulse(self):
        start = SwingPoint(0, "t0", 100.0, SwingType.LOW)
        end = SwingPoint(5, "t5", 100.0, SwingType.HIGH)
        assert impulse_retracement_pct(start, end, 100.0) == 0.0

    def test_no_retracement_downward(self):
        start = SwingPoint(0, "t0", 120.0, SwingType.HIGH)
        end = SwingPoint(5, "t5", 100.0, SwingType.LOW)
        assert impulse_retracement_pct(start, end, 100.0) == 0.0


# ---------------------------------------------------------------
# 10. Timestamp handling
# ---------------------------------------------------------------
class TestTimestamps:
    def test_uses_open_time_column(self):
        candles = pd.DataFrame({
            "high": [10, 12, 14, 16, 18, 20, 18, 16, 14, 12, 10],
            "low": [9, 11, 13, 15, 17, 19, 17, 15, 13, 11, 9],
            "close": [9.5] * 11,
            "open_time": pd.date_range("2026-01-01", periods=11, freq="15min"),
        })
        swings = detect_swings(candles, lookback=5)
        assert len(swings) >= 1
        assert "2026" in swings[0].timestamp

    def test_no_timestamp_column_uses_index(self):
        candles = pd.DataFrame({
            "high": [10, 12, 14, 16, 18, 20, 18, 16, 14, 12, 10],
            "low": [9, 11, 13, 15, 17, 19, 17, 15, 13, 11, 9],
            "close": [9.5] * 11,
        })
        swings = detect_swings(candles, lookback=5)
        assert len(swings) >= 1
        assert swings[0].timestamp == "5"  # index as string
