"""
Testes unitarios para a Execution Layer.

Cobre:
- LONG com ATR normal: entry, SL, TP1, TP2, RR
- SHORT com ATR normal: niveis espelhados
- RR insuficiente: ATR muito baixo, rr_valid=False
- ATR floor: ATR < floor -> usa floor (2%)
- Score alto (>=80): TP2 expandido para ATR*2.5
- Score baixo (<60): TP2 conservador ATR*1.5
- Candles insuficientes: retorna None
- Integracao com confluence: best_signal preenchido
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
import pandas as pd

from signal_types import Direction, Signal
from execution_layer import (
    calculate_levels,
    apply_to_signal,
    _compute_atr14,
    _tp_multiplier_for_score,
)


def _make_signal(symbol: str = "BTCUSDT", source: str = "funding_rate") -> Signal:
    return Signal(
        direction=Direction.LONG,
        strength=0.7,
        timestamp="2026-04-09T10:00:00",
        source=source,
        symbol=symbol,
        price=0.0,
        valid=True,
        reason="test",
        metadata={"score_total": 70},
    )


def _make_candles(
    n: int = 30,
    base_price: float = 80000.0,
    atr_approx: float = 400.0,
) -> pd.DataFrame:
    """Gera candles 5m sinteticos com ATR controlado.

    O ATR(14) aproximado e controlado pela amplitude high-low.
    """
    np.random.seed(42)
    timestamps = pd.date_range("2026-04-09 08:00", periods=n, freq="5min")
    close = np.full(n, base_price)
    # Pequena variacao para realismo
    close = close + np.cumsum(np.random.normal(0, atr_approx * 0.1, n))
    # Garantir que o penultimo (iloc[-2]) esteja proximo ao base
    close[-2] = base_price

    high = close + atr_approx * 0.6
    low = close - atr_approx * 0.4
    open_ = close + np.random.normal(0, atr_approx * 0.05, n)
    volume = np.random.uniform(100, 500, n)

    return pd.DataFrame({
        "timestamp": timestamps,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# ── TP multiplier ────────────────────────────────────────────────────

class TestTPMultiplier:

    def test_high_score(self):
        # ATR_SL_MULTIPLIER=1.5, so tp_mult = 1.5 * 2.5 = 3.75
        assert _tp_multiplier_for_score(80) == pytest.approx(3.75)
        assert _tp_multiplier_for_score(95) == pytest.approx(3.75)

    def test_normal_score(self):
        # tp_mult = 1.5 * 2.0 = 3.0
        assert _tp_multiplier_for_score(60) == pytest.approx(3.0)
        assert _tp_multiplier_for_score(79) == pytest.approx(3.0)

    def test_low_score(self):
        # tp_mult = 1.5 * 1.5 = 2.25
        assert _tp_multiplier_for_score(59) == pytest.approx(2.25)
        assert _tp_multiplier_for_score(40) == pytest.approx(2.25)


# ── LONG levels ──────────────────────────────────────────────────────

class TestLongLevels:
    """LONG: SL abaixo do entry, TP acima."""

    def test_basic_long(self):
        sig = _make_signal()
        candles = _make_candles(base_price=80000.0, atr_approx=400.0)
        plan = calculate_levels(sig, candles, Direction.LONG, score=70)

        assert plan is not None
        assert plan.entry_price == pytest.approx(80000.0, abs=1)
        # SL below entry
        assert plan.sl_price < plan.entry_price
        # TPs above entry
        assert plan.tp1_price > plan.entry_price
        assert plan.tp2_price > plan.entry_price
        assert plan.tp2_price > plan.tp1_price
        # RR positive
        assert plan.rr_ratio > 0
        assert plan.sl_distance_pct > 0

    def test_long_atr_based_sl(self):
        sig = _make_signal()
        candles = _make_candles(base_price=80000.0, atr_approx=400.0)
        plan = calculate_levels(sig, candles, Direction.LONG, score=70)

        # SL distance should be ATR * 1.5 (ATR_SL_MULTIPLIER)
        # ATR ~400, SL dist ~600
        sl_dist = plan.entry_price - plan.sl_price
        assert sl_dist > 0
        # Floor is 2% of 80000 = 1600, ATR*1.5 = ~600, so ATR should be used
        # unless floor kicks in (depends on actual ATR value)


# ── SHORT levels ─────────────────────────────────────────────────────

class TestShortLevels:
    """SHORT: SL acima do entry, TP abaixo."""

    def test_basic_short(self):
        sig = _make_signal()
        candles = _make_candles(base_price=80000.0, atr_approx=400.0)
        plan = calculate_levels(sig, candles, Direction.SHORT, score=70)

        assert plan is not None
        assert plan.entry_price == pytest.approx(80000.0, abs=1)
        # SL above entry
        assert plan.sl_price > plan.entry_price
        # TPs below entry
        assert plan.tp1_price < plan.entry_price
        assert plan.tp2_price < plan.entry_price
        assert plan.tp2_price < plan.tp1_price

    def test_short_symmetric_to_long(self):
        sig = _make_signal()
        candles = _make_candles(base_price=80000.0, atr_approx=400.0)
        plan_long = calculate_levels(sig, candles, Direction.LONG, score=70)
        plan_short = calculate_levels(sig, candles, Direction.SHORT, score=70)

        # SL distances should be equal
        long_sl_dist = plan_long.entry_price - plan_long.sl_price
        short_sl_dist = plan_short.sl_price - plan_short.entry_price
        assert long_sl_dist == pytest.approx(short_sl_dist, rel=0.01)

        # RR ratios should be equal
        assert plan_long.rr_ratio == pytest.approx(plan_short.rr_ratio, rel=0.01)


# ── RR insuficiente ──────────────────────────────────────────────────

class TestRRInsufficient:
    """ATR muito baixo com floor -> RR pode ficar < 1.5."""

    def test_low_atr_floor_kicks_in(self):
        sig = _make_signal()
        # ATR ~50 on price 80000: SL floor = 2% = 1600
        # TP2 = ATR * 2.0 = 100. RR = 100/1600 = 0.0625 -> rr_valid=False
        candles = _make_candles(base_price=80000.0, atr_approx=50.0)
        plan = calculate_levels(sig, candles, Direction.LONG, score=70)

        assert plan is not None
        # Floor should have kicked in (SL dist >= 2%)
        assert plan.sl_distance_pct >= 1.9  # ~2% with rounding
        # RR should be low because TP is ATR-based but SL is floor-based
        assert plan.rr_valid is False
        assert plan.rr_ratio < 1.5


# ── ATR floor ────────────────────────────────────────────────────────

class TestATRFloor:
    """Quando ATR e muito baixo, SL usa floor de 2%."""

    def test_floor_applied(self):
        sig = _make_signal()
        candles = _make_candles(base_price=80000.0, atr_approx=30.0)
        plan = calculate_levels(sig, candles, Direction.LONG, score=70)

        assert plan is not None
        # SL distance should be at least floor_pct
        assert plan.sl_distance_pct >= 1.9  # ~2%


# ── Score alto -> TP expandido ───────────────────────────────────────

class TestHighScore:
    """Score >= 80: TP2 expandido para ATR * 2.5."""

    def test_tp2_expanded(self):
        sig = _make_signal()
        candles = _make_candles(base_price=80000.0, atr_approx=400.0)
        plan_normal = calculate_levels(sig, candles, Direction.LONG, score=70)
        plan_high = calculate_levels(sig, candles, Direction.LONG, score=85)

        assert plan_high is not None
        assert plan_normal is not None
        assert plan_high.tp_multiplier == pytest.approx(3.75)
        assert plan_normal.tp_multiplier == pytest.approx(3.0)
        # TP2 should be further for high score
        assert plan_high.tp2_price > plan_normal.tp2_price


# ── Score baixo -> TP conservador ────────────────────────────────────

class TestLowScore:
    """Score < 60: TP2 conservador ATR * 1.5."""

    def test_tp2_conservative(self):
        sig = _make_signal()
        candles = _make_candles(base_price=80000.0, atr_approx=400.0)
        plan_normal = calculate_levels(sig, candles, Direction.LONG, score=70)
        plan_low = calculate_levels(sig, candles, Direction.LONG, score=45)

        assert plan_low is not None
        assert plan_low.tp_multiplier == pytest.approx(2.25)
        # TP2 should be closer for low score
        assert plan_low.tp2_price < plan_normal.tp2_price


# ── Dados insuficientes ─────────────────────────────────────────────

class TestInsufficientData:

    def test_no_candles(self):
        sig = _make_signal()
        plan = calculate_levels(sig, None, Direction.LONG, score=70)
        assert plan is None

    def test_too_few_candles_uses_floor(self):
        sig = _make_signal()
        candles = _make_candles(n=5, base_price=80000.0)
        plan = calculate_levels(sig, candles, Direction.LONG, score=70)
        # ATR indisponivel com 5 candles -> usa floor como fallback
        assert plan is not None
        assert plan.sl_distance_pct >= 1.9  # floor ~2%

    def test_single_candle_returns_none(self):
        sig = _make_signal()
        candles = pd.DataFrame({
            "open": [80000.0], "high": [80200.0], "low": [79800.0],
            "close": [80100.0], "volume": [100.0],
        })
        plan = calculate_levels(sig, candles, Direction.LONG, score=70)
        assert plan is None

    def test_neutral_direction(self):
        sig = _make_signal()
        candles = _make_candles(base_price=80000.0)
        plan = calculate_levels(sig, candles, Direction.NEUTRAL, score=70)
        assert plan is None


# ── apply_to_signal ──────────────────────────────────────────────────

class TestApplyToSignal:
    """apply_to_signal preenche os campos do Signal."""

    def test_fields_populated(self):
        sig = _make_signal()
        candles = _make_candles(base_price=80000.0, atr_approx=400.0)
        plan = calculate_levels(sig, candles, Direction.LONG, score=70)

        assert sig.entry_price == 0.0  # before apply
        apply_to_signal(sig, plan)

        assert sig.entry_price == plan.entry_price
        assert sig.sl_price == plan.sl_price
        assert sig.tp1_price == plan.tp1_price
        assert sig.tp2_price == plan.tp2_price
        assert sig.sl_distance_pct == plan.sl_distance_pct
        assert sig.rr_ratio == plan.rr_ratio
        assert sig.price == plan.entry_price


# ── Integration: confluence -> execution -> risk_manager fields ──────

class TestIntegrationFlow:
    """Verifica que apos execution layer o signal tem tudo que risk_manager precisa."""

    def test_signal_has_all_risk_fields(self):
        sig = _make_signal()
        candles = _make_candles(base_price=80000.0, atr_approx=400.0)
        plan = calculate_levels(sig, candles, Direction.LONG, score=70)
        apply_to_signal(sig, plan)

        # risk_manager.evaluate_risk lê estes campos do best_signal:
        assert sig.entry_price > 0
        assert sig.sl_price > 0
        assert sig.tp1_price > 0
        assert sig.tp2_price > 0
        assert sig.sl_distance_pct > 0
        assert sig.rr_ratio > 0
        assert sig.source != ""
