"""Tests for momentum/pullback_detector.py."""

import pandas as pd
import pytest

from momentum.pullback_detector import (
    PullbackRejection,
    PullbackResult,
    TrendDirection,
    detect_pullback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uptrend_candles(pullback_close: float, n_pre: int = 8) -> pd.DataFrame:
    """Build candles with an upward impulse followed by a pullback.

    Structure (lookback=5 friendly):
      - Indices 0-5:  rising from 100 to 106 (swing low at 0 area)
      - Index 5:      swing low confirmed (100)
      - Indices 5-12: rising to 120 (swing high around index 12)
      - Indices 12+:  declining (pullback)
      - Last candle:  close = pullback_close

    We need at least 2*5+1 = 11 candles per swing, and the swings need
    to be clearly separated. Build ~25 candles.
    """
    # Phase 1: establish a low around index 5
    highs = [108, 107, 106, 105, 104, 103, 104, 105, 106, 107, 108]
    lows = [h - 2 for h in highs]

    # Phase 2: rise to peak around index 16
    rise = [110, 112, 114, 116, 118, 120]
    highs += rise
    lows += [h - 2 for h in rise]

    # Phase 3: decline (pullback) - 8 candles declining toward pullback_close
    n_decline = 8
    peak = 120.0
    for i in range(1, n_decline + 1):
        frac = i / n_decline
        c = peak - (peak - pullback_close) * frac
        highs.append(c + 1)
        lows.append(c - 1)

    n = len(highs)
    closes = [(h + lo) / 2 for h, lo in zip(highs, lows)]
    # Override last close to exact pullback_close
    closes[-1] = pullback_close
    timestamps = [f"2026-01-01T{i:02d}:00" for i in range(n)]

    return pd.DataFrame({
        "high": highs,
        "low": lows,
        "close": closes,
        "timestamp": timestamps,
    })


def _downtrend_candles(pullback_close: float) -> pd.DataFrame:
    """Build candles with a downward impulse followed by an upward pullback.

    Mirror of _uptrend_candles:
      - Peak around index 5 (swing high ~120)
      - Drop to valley around index 16 (swing low ~100)
      - Rise back toward pullback_close
    """
    # Phase 1: establish a high around index 5
    highs = [112, 113, 114, 115, 116, 117, 116, 115, 114, 113, 112]
    lows = [h - 2 for h in highs]

    # Phase 2: drop to valley around index 16
    drop = [110, 108, 106, 104, 102, 100]
    highs += [d + 2 for d in drop]
    lows += drop

    # Phase 3: rise (pullback) - 8 candles rising toward pullback_close
    n_rise = 8
    valley = 100.0
    for i in range(1, n_rise + 1):
        frac = i / n_rise
        c = valley + (pullback_close - valley) * frac
        highs.append(c + 1)
        lows.append(c - 1)

    n = len(highs)
    closes = [(h + lo) / 2 for h, lo in zip(highs, lows)]
    closes[-1] = pullback_close
    timestamps = [f"2026-01-01T{i:02d}:00" for i in range(n)]

    return pd.DataFrame({
        "high": highs,
        "low": lows,
        "close": closes,
        "timestamp": timestamps,
    })


# ---------------------------------------------------------------------------
# 1. Pullback valido LONG
# ---------------------------------------------------------------------------
class TestValidPullbackLong:
    def test_50pct_retracement_long(self):
        """50% retracement of upward impulse, above EMA 50 → valid."""
        # Impulse: ~103 → ~120, range ~17. 50% retrace → ~111.5
        candles = _uptrend_candles(pullback_close=111.5)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=105.0)

        assert result.valid is True
        assert result.rejection is None
        assert result.impulse_start is not None
        assert result.impulse_end is not None
        assert 30.0 <= result.retracement_pct <= 70.0
        assert result.direction == TrendDirection.LONG


# ---------------------------------------------------------------------------
# 2. Pullback valido SHORT
# ---------------------------------------------------------------------------
class TestValidPullbackShort:
    def test_50pct_retracement_short(self):
        """50% retracement of downward impulse, below EMA 50 → valid."""
        # Impulse: ~117 → ~100, range ~17. 50% retrace → ~108.5
        candles = _downtrend_candles(pullback_close=108.5)
        result = detect_pullback(candles, TrendDirection.SHORT, ema_slow_value=115.0)

        assert result.valid is True
        assert result.rejection is None
        assert 30.0 <= result.retracement_pct <= 70.0
        assert result.direction == TrendDirection.SHORT


# ---------------------------------------------------------------------------
# 3-4. Pullback raso demais (LONG e SHORT)
# ---------------------------------------------------------------------------
class TestTooShallow:
    def test_shallow_long(self):
        """15% retracement → too shallow."""
        # Impulse ~17 range. 15% retrace = ~2.5 from top → close ~117.5
        candles = _uptrend_candles(pullback_close=117.5)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=105.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.RETRACEMENT_TOO_SHALLOW

    def test_shallow_short(self):
        """15% retracement of downward impulse → too shallow."""
        # Impulse ~17 range. 15% retrace from bottom → close ~102.5
        candles = _downtrend_candles(pullback_close=102.5)
        result = detect_pullback(candles, TrendDirection.SHORT, ema_slow_value=115.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.RETRACEMENT_TOO_SHALLOW


# ---------------------------------------------------------------------------
# 5-6. Pullback profundo demais (LONG e SHORT)
# ---------------------------------------------------------------------------
class TestTooDeep:
    def test_deep_long(self):
        """80% retracement → too deep, likely reversal."""
        # Impulse ~17 range. 80% retrace = ~13.6 from top → close ~106.4
        candles = _uptrend_candles(pullback_close=106.4)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=104.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.RETRACEMENT_TOO_DEEP

    def test_deep_short(self):
        """80% retracement of downward impulse → too deep."""
        # 80% retrace from bottom → close ~113.6
        candles = _downtrend_candles(pullback_close=113.6)
        result = detect_pullback(candles, TrendDirection.SHORT, ema_slow_value=115.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.RETRACEMENT_TOO_DEEP


# ---------------------------------------------------------------------------
# 7-8. Estrutura quebrada (LONG e SHORT)
# ---------------------------------------------------------------------------
class TestStructureBroken:
    def test_structure_broken_long(self):
        """Price below EMA 50 in LONG trend → structure broken."""
        # Valid retracement range but price below EMA 50
        candles = _uptrend_candles(pullback_close=111.5)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=115.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.STRUCTURE_BROKEN

    def test_structure_broken_short(self):
        """Price above EMA 50 in SHORT trend → structure broken."""
        candles = _downtrend_candles(pullback_close=108.5)
        result = detect_pullback(candles, TrendDirection.SHORT, ema_slow_value=105.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.STRUCTURE_BROKEN


# ---------------------------------------------------------------------------
# 9. Sem impulso valido
# ---------------------------------------------------------------------------
class TestNoImpulse:
    def test_insufficient_data(self):
        """Too few candles → no swings → no impulse."""
        candles = pd.DataFrame({
            "high": [100, 101, 102],
            "low": [99, 100, 101],
            "close": [99.5, 100.5, 101.5],
            "timestamp": ["t1", "t2", "t3"],
        })
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=100.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.NO_IMPULSE

    def test_wrong_impulse_direction(self):
        """Downward impulse but LONG direction → no matching impulse."""
        candles = _downtrend_candles(pullback_close=108.5)
        # Ask for LONG but impulse ends at swing LOW → mismatch
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=100.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.NO_IMPULSE

    def test_monotonic_trend_no_swing(self):
        """Perfectly monotonic trend has no detectable swing low/high pair.

        With sufficient data but zero price oscillation, detect_swings
        finds at most one swing (at the peak). last_impulse needs two
        opposite swings → returns (None, None) → NO_IMPULSE.

        This is the documented contract: the detector requires structure
        (at least one completed impulse leg) — a trendline alone is not
        enough.
        """
        n = 70
        # Pure monotonic uptrend + pullback, no oscillation
        closes = [100.0 + 0.5 * i for i in range(55)]
        peak = closes[-1]
        for i in range(15):
            closes.append(peak - 0.8 * (i + 1))

        candles = pd.DataFrame({
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "timestamp": [f"t{i}" for i in range(n)],
        })
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=110.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.NO_IMPULSE


# ---------------------------------------------------------------------------
# 10-13. Bordas exatas do retracement
# ---------------------------------------------------------------------------
class TestBoundaries:
    def _get_impulse_range(self, candles, direction):
        """Helper: detect impulse and return (start_price, end_price, range)."""
        from momentum.swing_detector import detect_swings, last_impulse
        swings = detect_swings(candles, lookback=5)
        start, end = last_impulse(swings)
        if start is None:
            return None, None, None
        return start.price, end.price, abs(end.price - start.price)

    def test_exactly_30pct(self):
        """Retracement at 30% → should be valid (inclusive).

        Uses the impulse from the actual result to compute exact target,
        since candle generation can shift swing prices slightly.
        """
        # First run: discover actual impulse in these candles
        candles = _uptrend_candles(pullback_close=111.5)
        probe = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=100.0)
        if probe.impulse_end is None:
            pytest.skip("No impulse found in test candles")

        # Compute exact 30% target from the discovered impulse
        ep = probe.impulse_end.price
        sp = probe.impulse_start.price
        rng = abs(ep - sp)
        target_price = float(ep - 0.30 * rng)

        candles2 = _uptrend_candles(pullback_close=target_price)
        result = detect_pullback(candles2, TrendDirection.LONG, ema_slow_value=100.0)

        assert result.valid is True, f"30% retracement should be valid, got {result.rejection} ({result.retracement_pct:.1f}%)"

    def test_exactly_70pct(self):
        """Retracement exactly at 70% → should be valid (inclusive)."""
        candles_probe = _uptrend_candles(pullback_close=115.0)
        sp, ep, rng = self._get_impulse_range(candles_probe, TrendDirection.LONG)
        if rng is None:
            pytest.skip("No impulse found in test candles")

        target_price = ep - 0.70 * rng
        candles = _uptrend_candles(pullback_close=target_price)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=100.0)

        assert result.valid is True, f"70% retracement should be valid, got {result.rejection} ({result.retracement_pct:.1f}%)"

    def test_just_below_30pct(self):
        """Retracement at 29% → too shallow."""
        candles_probe = _uptrend_candles(pullback_close=115.0)
        sp, ep, rng = self._get_impulse_range(candles_probe, TrendDirection.LONG)
        if rng is None:
            pytest.skip("No impulse found in test candles")

        target_price = ep - 0.29 * rng
        candles = _uptrend_candles(pullback_close=target_price)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=100.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.RETRACEMENT_TOO_SHALLOW

    def test_just_above_70pct(self):
        """Retracement at 71% → too deep."""
        candles_probe = _uptrend_candles(pullback_close=115.0)
        sp, ep, rng = self._get_impulse_range(candles_probe, TrendDirection.LONG)
        if rng is None:
            pytest.skip("No impulse found in test candles")

        target_price = ep - 0.71 * rng
        candles = _uptrend_candles(pullback_close=target_price)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=100.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.RETRACEMENT_TOO_DEEP


# ---------------------------------------------------------------------------
# 14. Dados retornados corretos
# ---------------------------------------------------------------------------
class TestReturnedData:
    def test_impulse_data_populated(self):
        """Valid pullback should have all fields populated correctly."""
        candles = _uptrend_candles(pullback_close=111.5)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=105.0)

        assert result.valid is True
        assert result.impulse_start is not None
        assert result.impulse_end is not None
        assert result.impulse_start.swing_type != result.impulse_end.swing_type
        assert result.retracement_pct > 0
        assert result.current_price == 111.5
        assert result.direction == TrendDirection.LONG

    def test_rejected_still_has_impulse_data(self):
        """Even rejected pullbacks should have impulse data when impulse exists."""
        # Too shallow but impulse exists
        candles = _uptrend_candles(pullback_close=117.5)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=105.0)

        assert result.valid is False
        assert result.impulse_start is not None
        assert result.impulse_end is not None
        assert result.retracement_pct > 0


# ---------------------------------------------------------------------------
# 15. Determinismo
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_same_input_same_output(self):
        candles = _uptrend_candles(pullback_close=111.5)

        r1 = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=105.0)
        r2 = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=105.0)

        assert r1.valid == r2.valid
        assert r1.rejection == r2.rejection
        assert r1.retracement_pct == r2.retracement_pct
        assert r1.current_price == r2.current_price


# ---------------------------------------------------------------------------
# 16. Rejection priority: structure check comes after retracement
# ---------------------------------------------------------------------------
class TestRejectionPriority:
    def test_deep_and_broken_reports_deep(self):
        """When both too deep AND structure broken, retracement is checked first."""
        # 80% retracement AND below EMA 50
        candles = _uptrend_candles(pullback_close=106.4)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=115.0)

        # Retracement check runs before structure check
        assert result.valid is False
        assert result.rejection == PullbackRejection.RETRACEMENT_TOO_DEEP

    def test_valid_range_but_broken_structure(self):
        """In-range retracement but broken structure → STRUCTURE_BROKEN."""
        candles = _uptrend_candles(pullback_close=111.5)
        result = detect_pullback(candles, TrendDirection.LONG, ema_slow_value=115.0)

        assert result.valid is False
        assert result.rejection == PullbackRejection.STRUCTURE_BROKEN
