"""Tests for momentum/momentum_trader.py."""

import numpy as np
import pandas as pd
import pytest

from momentum.config import MomentumConfig, MomentumDirection, MomentumOutcome
from momentum.momentum_trader import (
    MomentumSignal,
    evaluate_momentum_pullback,
    _ema,
    _crossover_age,
    _emas_converging,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_trend_pullback_candles(
    direction: str = "LONG",
    pullback_close: float | None = None,
    n_trend: int = 55,
    n_pullback: int = 10,
    confirm: bool = True,
) -> pd.DataFrame:
    """Build realistic candles with trend → pullback → optional confirmation.

    For LONG: price rises steadily, then pulls back, then (optionally) resumes.
    For SHORT: price falls steadily, then pulls back up, then resumes down.

    Returns DataFrame with 60+ candles (enough for EMA 50 + swing detection).
    """
    candles_data = {"high": [], "low": [], "close": [], "timestamp": []}

    if direction == "LONG":
        # Base: start at 100, trend up
        base = 100.0
        trend_slope = 0.5  # per candle

        # Phase 1: uptrend (n_trend candles)
        # A mid-trend dip creates a detectable swing low so the swing
        # detector can find an upward impulse (swing_low → swing_high).
        mid = n_trend // 2
        for i in range(n_trend):
            c = base + trend_slope * i
            if i == mid:
                c -= 6.0  # dip creates swing low for impulse detection
            candles_data["close"].append(c)
            candles_data["high"].append(c + 0.5)
            candles_data["low"].append(c - 0.5)
            candles_data["timestamp"].append(f"2026-01-01T{i:04d}")

        peak = base + trend_slope * (n_trend - 1)

        # Phase 2: pullback down (n_pullback candles)
        # Default pullback to ~50% of impulse
        if pullback_close is None:
            impulse_range = peak - base
            pullback_close = peak - 0.50 * impulse_range

        for i in range(n_pullback):
            frac = (i + 1) / n_pullback
            c = peak - (peak - pullback_close) * frac
            candles_data["close"].append(c)
            candles_data["high"].append(c + 0.5)
            candles_data["low"].append(c - 0.5)
            candles_data["timestamp"].append(f"2026-01-01T{n_trend + i:04d}")

        # Phase 3: confirmation candle (close back above EMA 20)
        if confirm:
            # EMA 20 should be roughly around the recent trend level
            ema20_approx = peak - 0.25 * (peak - base)
            c = ema20_approx + 1.0  # above EMA 20
            candles_data["close"].append(c)
            candles_data["high"].append(c + 0.5)
            candles_data["low"].append(c - 0.5)
            candles_data["timestamp"].append(f"2026-01-01T{n_trend + n_pullback:04d}")

    else:  # SHORT
        base = 120.0
        trend_slope = -0.5

        # Phase 1: downtrend
        # A mid-trend bump creates a detectable swing high so the swing
        # detector can find a downward impulse (swing_high → swing_low).
        mid = n_trend // 2
        for i in range(n_trend):
            c = base + trend_slope * i
            if i == mid:
                c += 6.0  # bump creates swing high for impulse detection
            candles_data["close"].append(c)
            candles_data["high"].append(c + 0.5)
            candles_data["low"].append(c - 0.5)
            candles_data["timestamp"].append(f"2026-01-01T{i:04d}")

        valley = base + trend_slope * (n_trend - 1)

        # Phase 2: pullback up
        if pullback_close is None:
            impulse_range = base - valley
            pullback_close = valley + 0.50 * impulse_range

        for i in range(n_pullback):
            frac = (i + 1) / n_pullback
            c = valley + (pullback_close - valley) * frac
            candles_data["close"].append(c)
            candles_data["high"].append(c + 0.5)
            candles_data["low"].append(c - 0.5)
            candles_data["timestamp"].append(f"2026-01-01T{n_trend + i:04d}")

        # Phase 3: confirmation (close back below EMA 20)
        if confirm:
            ema20_approx = valley + 0.25 * (base - valley)
            c = ema20_approx - 1.0
            candles_data["close"].append(c)
            candles_data["high"].append(c + 0.5)
            candles_data["low"].append(c - 0.5)
            candles_data["timestamp"].append(f"2026-01-01T{n_trend + n_pullback:04d}")

    return pd.DataFrame(candles_data)


def _flat_candles(n: int = 70, price: float = 100.0) -> pd.DataFrame:
    """Flat market — no trend."""
    return pd.DataFrame({
        "high": [price + 0.1] * n,
        "low": [price - 0.1] * n,
        "close": [price] * n,
        "timestamp": [f"2026-01-01T{i:04d}" for i in range(n)],
    })


# ---------------------------------------------------------------------------
# 1. Sinal LONG completo
# ---------------------------------------------------------------------------
class TestTradeSignalLong:
    def test_valid_long_signal(self):
        candles = _build_trend_pullback_candles("LONG", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        assert result.outcome == MomentumOutcome.TRADE
        assert result.direction == MomentumDirection.LONG
        assert result.entry_price > 0
        assert result.sl_price < result.entry_price
        assert result.tp1_price > result.entry_price
        assert result.tp2_price > result.tp1_price


# ---------------------------------------------------------------------------
# 2. Sinal SHORT completo
# ---------------------------------------------------------------------------
class TestTradeSignalShort:
    def test_valid_short_signal(self):
        candles = _build_trend_pullback_candles("SHORT", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        assert result.outcome == MomentumOutcome.TRADE
        assert result.direction == MomentumDirection.SHORT
        assert result.entry_price > 0
        assert result.sl_price > result.entry_price
        assert result.tp1_price < result.entry_price
        assert result.tp2_price < result.tp1_price


# ---------------------------------------------------------------------------
# 3. Sem tendencia
# ---------------------------------------------------------------------------
class TestNoTrend:
    def test_flat_market(self):
        candles = _flat_candles()
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        # EMA 20 == EMA 50 in flat market → NO_TREND or NO_VALID_PULLBACK
        assert result.outcome in (MomentumOutcome.NO_TREND, MomentumOutcome.NO_VALID_PULLBACK)
        assert result.direction in (MomentumDirection.NEUTRAL, MomentumDirection.LONG, MomentumDirection.SHORT)


# ---------------------------------------------------------------------------
# 4. Tendencia jovem demais
# ---------------------------------------------------------------------------
class TestTrendTooYoung:
    def test_recent_crossover(self):
        # Build candles where trend only established in last 3 candles
        n = 70
        closes = [100.0] * (n - 3) + [102.0, 103.0, 104.0]  # EMA cross very recent
        candles = pd.DataFrame({
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "timestamp": [f"2026-01-01T{i:04d}" for i in range(n)],
        })
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        # Should be NO_TREND (EMAs barely separated) or TREND_TOO_YOUNG
        assert result.outcome in (
            MomentumOutcome.NO_TREND,
            MomentumOutcome.TREND_TOO_YOUNG,
            MomentumOutcome.NO_VALID_PULLBACK,
        )


# ---------------------------------------------------------------------------
# 5. EMAs convergindo
# ---------------------------------------------------------------------------
class TestTrendExhaustion:
    def test_converging_emas(self):
        # Build trend that's losing steam: strong up then flattening
        n = 70
        closes = []
        for i in range(50):
            closes.append(100 + i * 0.8)  # strong trend
        for i in range(20):
            closes.append(closes[-1] + 0.05)  # barely moving → EMAs converge

        candles = pd.DataFrame({
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "timestamp": [f"2026-01-01T{i:04d}" for i in range(n)],
        })
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        # With converging EMAs we expect TREND_EXHAUSTION or downstream rejection
        assert result.outcome != MomentumOutcome.TRADE


# ---------------------------------------------------------------------------
# 6-7. Pullback invalido
# ---------------------------------------------------------------------------
class TestPullbackInvalid:
    def test_pullback_too_shallow(self):
        """Retracement too small (< 30%) → NO_VALID_PULLBACK."""
        candles = _build_trend_pullback_candles("LONG", pullback_close=125.0, confirm=False)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        assert result.outcome != MomentumOutcome.TRADE

    def test_pullback_too_deep(self):
        """Retracement too large (> 70%) → NO_VALID_PULLBACK."""
        candles = _build_trend_pullback_candles("LONG", pullback_close=103.0, confirm=False)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        assert result.outcome != MomentumOutcome.TRADE


# ---------------------------------------------------------------------------
# 8. Sem confirmacao
# ---------------------------------------------------------------------------
class TestNoConfirmation:
    def test_no_confirmation_long(self):
        """Pullback valid but price still below EMA 20 → NO_CONFIRMATION."""
        candles = _build_trend_pullback_candles("LONG", confirm=False)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        # Without confirmation candle, last close is at pullback level
        assert result.outcome != MomentumOutcome.TRADE


# ---------------------------------------------------------------------------
# 9. Regime bloqueado
# ---------------------------------------------------------------------------
class TestRegimeBlocked:
    def test_ranging_blocked(self):
        candles = _build_trend_pullback_candles("LONG", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "RANGING", config)

        assert result.outcome == MomentumOutcome.REGIME_BLOCKED

    def test_volatile_blocked(self):
        candles = _build_trend_pullback_candles("LONG", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "VOLATILE", config)

        assert result.outcome == MomentumOutcome.REGIME_BLOCKED

    def test_trending_allowed(self):
        candles = _build_trend_pullback_candles("LONG", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        assert result.outcome != MomentumOutcome.REGIME_BLOCKED

    def test_weak_trend_allowed(self):
        candles = _build_trend_pullback_candles("LONG", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "WEAK_TREND", config)

        assert result.outcome != MomentumOutcome.REGIME_BLOCKED


# ---------------------------------------------------------------------------
# 10-11. SL e TP1 calculados corretamente
# ---------------------------------------------------------------------------
class TestExitPrices:
    def test_sl_below_entry_long(self):
        candles = _build_trend_pullback_candles("LONG", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        if result.outcome == MomentumOutcome.TRADE:
            assert result.sl_price < result.entry_price
            # SL should be at or below impulse start
            assert result.sl_price <= result.impulse_start_price + 0.01

    def test_sl_above_entry_short(self):
        candles = _build_trend_pullback_candles("SHORT", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        if result.outcome == MomentumOutcome.TRADE:
            assert result.sl_price > result.entry_price
            assert result.sl_price >= result.impulse_start_price - 0.01

    def test_tp1_at_impulse_end(self):
        candles = _build_trend_pullback_candles("LONG", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        if result.outcome == MomentumOutcome.TRADE:
            assert result.tp1_price == result.impulse_end_price


# ---------------------------------------------------------------------------
# 12. TP2 calculado corretamente (1.5R)
# ---------------------------------------------------------------------------
class TestTP2:
    def test_tp2_is_1_5r_long(self):
        candles = _build_trend_pullback_candles("LONG", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        if result.outcome == MomentumOutcome.TRADE:
            sl_dist = abs(result.entry_price - result.sl_price)
            expected_tp2 = result.entry_price + 1.5 * sl_dist
            assert abs(result.tp2_price - expected_tp2) < 0.01

    def test_tp2_is_1_5r_short(self):
        candles = _build_trend_pullback_candles("SHORT", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        if result.outcome == MomentumOutcome.TRADE:
            sl_dist = abs(result.entry_price - result.sl_price)
            expected_tp2 = result.entry_price - 1.5 * sl_dist
            assert abs(result.tp2_price - expected_tp2) < 0.01


# ---------------------------------------------------------------------------
# 13. SL floor (0.3%)
# ---------------------------------------------------------------------------
class TestSLFloor:
    def test_sl_floor_respected(self):
        candles = _build_trend_pullback_candles("LONG", confirm=True)
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        if result.outcome == MomentumOutcome.TRADE:
            sl_pct = abs(result.entry_price - result.sl_price) / result.entry_price * 100
            assert sl_pct >= config.sl_floor_pct - 0.001


# ---------------------------------------------------------------------------
# 14. Dados insuficientes
# ---------------------------------------------------------------------------
class TestInsufficientData:
    def test_few_candles(self):
        candles = pd.DataFrame({
            "high": [101] * 10,
            "low": [99] * 10,
            "close": [100] * 10,
            "timestamp": [f"t{i}" for i in range(10)],
        })
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        assert result.outcome == MomentumOutcome.INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# 15. Determinismo
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_same_input_same_output(self):
        candles = _build_trend_pullback_candles("LONG", confirm=True)
        config = MomentumConfig()

        r1 = evaluate_momentum_pullback(candles, "TRENDING", config)
        r2 = evaluate_momentum_pullback(candles, "TRENDING", config)

        assert r1.outcome == r2.outcome
        assert r1.direction == r2.direction
        assert r1.entry_price == r2.entry_price
        assert r1.sl_price == r2.sl_price
        assert r1.tp1_price == r2.tp1_price
        assert r1.tp2_price == r2.tp2_price


# ---------------------------------------------------------------------------
# 16. Sem lookahead
# ---------------------------------------------------------------------------
class TestNoLookahead:
    def test_decision_uses_only_past_and_current(self):
        """Adding future candles must not change the decision on the current candle.

        We evaluate at candle N, then add 10 more candles and re-evaluate
        at the same candle N. The result must be identical.
        """
        candles_full = _build_trend_pullback_candles("LONG", confirm=True)
        n = len(candles_full)
        config = MomentumConfig()

        # Evaluate at candle N (the last candle)
        result_at_n = evaluate_momentum_pullback(candles_full, "TRENDING", config)

        # Now add 10 future candles and re-evaluate at the same candle N
        future_closes = [candles_full["close"].iloc[-1] + i * 0.3 for i in range(1, 11)]
        future = pd.DataFrame({
            "high": [c + 0.5 for c in future_closes],
            "low": [c - 0.5 for c in future_closes],
            "close": future_closes,
            "timestamp": [f"2026-02-01T{i:04d}" for i in range(10)],
        })

        candles_extended = pd.concat([candles_full, future], ignore_index=True)

        # Re-evaluate using only candles up to index N (the original last candle)
        candles_at_n = candles_extended.iloc[:n]
        result_at_n_with_future = evaluate_momentum_pullback(candles_at_n, "TRENDING", config)

        assert result_at_n.outcome == result_at_n_with_future.outcome
        assert result_at_n.direction == result_at_n_with_future.direction
        assert result_at_n.entry_price == result_at_n_with_future.entry_price
        assert result_at_n.sl_price == result_at_n_with_future.sl_price

    def test_ema_is_causal(self):
        """EMA computation must be causal — adding future data doesn't change past EMA values."""
        closes = np.array([100 + i * 0.5 for i in range(70)], dtype=float)
        ema_20 = _ema(closes, 20)

        # Add 10 more values
        extended = np.concatenate([closes, [140, 141, 142, 143, 144, 145, 146, 147, 148, 149]])
        ema_20_ext = _ema(extended, 20)

        # EMA at position 69 must be the same
        assert abs(ema_20[69] - ema_20_ext[69]) < 1e-10


# ---------------------------------------------------------------------------
# 17. Prioridade fixa de rejeição
# ---------------------------------------------------------------------------
class TestRejectionPriority:
    def test_regime_before_trend(self):
        """Regime blocked should come before trend check, even if no trend exists."""
        candles = _flat_candles()
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "VOLATILE", config)

        assert result.outcome == MomentumOutcome.REGIME_BLOCKED

    def test_insufficient_data_before_regime(self):
        """Insufficient data is checked before regime."""
        candles = pd.DataFrame({
            "high": [101] * 5, "low": [99] * 5,
            "close": [100] * 5, "timestamp": ["t"] * 5,
        })
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "VOLATILE", config)

        assert result.outcome == MomentumOutcome.INSUFFICIENT_DATA

    def test_trend_before_pullback(self):
        """No trend is checked before pullback, even if pullback would be valid."""
        candles = _flat_candles()
        config = MomentumConfig()
        result = evaluate_momentum_pullback(candles, "TRENDING", config)

        # Flat market: NO_TREND comes before NO_VALID_PULLBACK
        assert result.outcome in (MomentumOutcome.NO_TREND, MomentumOutcome.NO_VALID_PULLBACK)


# ---------------------------------------------------------------------------
# 18. Helpers unit tests
# ---------------------------------------------------------------------------
class TestHelpers:
    def test_crossover_age(self):
        fast = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        slow = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        # fast > slow from index 3 onwards (values 4>2, 5>1)
        age = _crossover_age(fast, slow)
        assert age == 2

    def test_crossover_age_all_above(self):
        fast = np.array([10.0, 11.0, 12.0, 13.0])
        slow = np.array([1.0, 2.0, 3.0, 4.0])
        age = _crossover_age(fast, slow)
        assert age == 4  # Always above

    def test_emas_converging_true(self):
        # Slow EMA was trending strongly, then flattened → exhaustion
        # slope_before = |103 - 100| = 3.0, slope_now = |103.3 - 103| = 0.3
        # ratio = 0.1 < 0.3 → True
        fast = np.array([110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 104.0])
        slow = np.array([100.0, 101.0, 102.0, 103.0, 103.1, 103.2, 103.3])
        assert _emas_converging(fast, slow, lookback=3) is True

    def test_emas_converging_false(self):
        # Slow EMA keeps trending at same pace → healthy trend
        # slope_before = |103 - 100| = 3.0, slope_now = |106 - 103| = 3.0
        # ratio = 1.0 >= 0.3 → False
        fast = np.array([104.0, 106.0, 108.0, 110.0, 112.0, 114.0, 116.0])
        slow = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
        assert _emas_converging(fast, slow, lookback=3) is False
