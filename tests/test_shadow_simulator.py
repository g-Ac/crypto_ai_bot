"""Testes pro shadow_simulator (lógica pura, sem rede/DB)."""
from __future__ import annotations

import pandas as pd
import pytest

from momentum.config import MomentumConfig
from shadow_simulator import compute_levels, parse_ts_to_ms, simulate_decision


# ---------------------------------------------------------------------------
# parse_ts_to_ms
# ---------------------------------------------------------------------------

EXPECTED_MS = 1777333500000  # 2026-04-27 23:45:00 UTC


def test_parse_ts_simple_format():
    assert parse_ts_to_ms("2026-04-27 23:45:00") == EXPECTED_MS


def test_parse_ts_iso_with_tz():
    assert parse_ts_to_ms("2026-04-27T23:45:00+00:00") == EXPECTED_MS


def test_parse_ts_iso_with_microseconds():
    ms = parse_ts_to_ms("2026-04-27T23:45:00.123456+00:00")
    assert EXPECTED_MS <= ms < EXPECTED_MS + 200


def test_parse_ts_invalid_returns_zero():
    assert parse_ts_to_ms("") == 0
    assert parse_ts_to_ms("not a date") == 0


# ---------------------------------------------------------------------------
# compute_levels
# ---------------------------------------------------------------------------

def test_compute_levels_long_uses_impulse_start_as_sl():
    cfg = MomentumConfig()
    sl, tp1, tp2 = compute_levels(
        direction="LONG",
        impulse_start_price=100.0,
        impulse_end_price=110.0,
        entry_price=105.0,
        cfg=cfg,
    )
    # LONG: SL = min(impulse_start=100, entry-floor=105*(1-0.5%)=104.475)
    assert sl == pytest.approx(100.0, rel=1e-6)
    # TP1 = impulse_end (factor=1.0)
    assert tp1 == pytest.approx(110.0, rel=1e-6)
    # TP2 = entry + 1.5 * (entry-sl) = 105 + 1.5*5 = 112.5
    assert tp2 == pytest.approx(112.5, rel=1e-6)


def test_compute_levels_short_uses_impulse_start_as_sl():
    cfg = MomentumConfig()
    sl, tp1, tp2 = compute_levels(
        direction="SHORT",
        impulse_start_price=110.0,
        impulse_end_price=100.0,
        entry_price=105.0,
        cfg=cfg,
    )
    # SHORT: SL = max(impulse_start=110, entry+floor=105*(1.005)=105.525)
    assert sl == pytest.approx(110.0, rel=1e-6)
    assert tp1 == pytest.approx(100.0, rel=1e-6)
    # TP2 = entry - 1.5 * (sl-entry) = 105 - 1.5*5 = 97.5
    assert tp2 == pytest.approx(97.5, rel=1e-6)


def test_compute_levels_long_floor_kicks_in_when_impulse_too_close():
    cfg = MomentumConfig()  # sl_floor_pct = 0.5
    # Entry 100, impulse_start very close at 99.9 (only 0.1% away)
    # Floor enforces minimum 0.5% → SL should be at 99.5 (entry - 0.5%)
    sl, _, _ = compute_levels(
        direction="LONG",
        impulse_start_price=99.9,
        impulse_end_price=105.0,
        entry_price=100.0,
        cfg=cfg,
    )
    assert sl == pytest.approx(99.5, rel=1e-6)


def test_compute_levels_short_floor_kicks_in():
    cfg = MomentumConfig()
    sl, _, _ = compute_levels(
        direction="SHORT",
        impulse_start_price=100.1,
        impulse_end_price=95.0,
        entry_price=100.0,
        cfg=cfg,
    )
    # Floor: 100 * 1.005 = 100.5; max(100.1, 100.5) = 100.5
    assert sl == pytest.approx(100.5, rel=1e-6)


# ---------------------------------------------------------------------------
# simulate_decision (integration: synthetic candles)
# ---------------------------------------------------------------------------

def _make_candles(closes: list[float], highs: list[float] | None = None,
                  lows: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "open": closes,
        "high": highs or [c * 1.001 for c in closes],
        "low": lows or [c * 0.999 for c in closes],
        "close": closes,
    })


def test_simulate_decision_tp1_hit_long():
    cfg = MomentumConfig()
    # Entry 100, SL=95 (impulse_start), TP1=105 (impulse_end), TP2=107.5
    # Candle 1: high=106 → bate TP1 (>=105) mas NAO TP2 (<107.5)
    candles = _make_candles(
        closes=[100.0, 105.5],
        highs=[100.5, 106.0],
        lows=[99.8, 105.0],
    )
    result = simulate_decision(
        direction="LONG",
        impulse_start_price=95.0,
        impulse_end_price=105.0,
        candles_forward=candles,
        cfg=cfg,
    )
    assert result["complete"] == 1
    assert result["exit_reason"] == "tp1_hit"
    assert result["pnl_pct"] > 0


def test_simulate_decision_sl_hit_long():
    cfg = MomentumConfig()
    candles = _make_candles(
        closes=[100.0, 99.0, 95.0],
        highs=[100.5, 99.5, 95.5],
        lows=[99.5, 98.0, 94.0],  # 94 << 99.5 SL
    )
    result = simulate_decision(
        direction="LONG",
        impulse_start_price=99.5,
        impulse_end_price=110.0,
        candles_forward=candles,
        cfg=cfg,
    )
    assert result["complete"] == 1
    assert result["exit_reason"] == "sl_hit"
    assert result["pnl_pct"] < 0


def test_simulate_decision_empty_candles():
    cfg = MomentumConfig()
    result = simulate_decision(
        direction="LONG",
        impulse_start_price=99.5,
        impulse_end_price=110.0,
        candles_forward=pd.DataFrame(),
        cfg=cfg,
    )
    assert result["complete"] == 0
    assert result["exit_reason"] == "no_candles"


def test_simulate_decision_incomplete_runs_out_of_candles():
    cfg = MomentumConfig()
    # entry=100, SL=95 (impulse_start), TP1=110, TP2=107.5
    # Candles fracos: highs 100.3-101.3 < TP2; lows 99.7-100.7 > SL; sem timeout
    candles = _make_candles(
        closes=[100.0, 100.5, 101.0],
        highs=[100.3, 100.8, 101.3],
        lows=[99.7, 100.2, 100.7],
    )
    result = simulate_decision(
        direction="LONG",
        impulse_start_price=95.0,
        impulse_end_price=110.0,
        candles_forward=candles,
        cfg=cfg,
    )
    assert result["complete"] == 0
    assert result["exit_reason"] == "incomplete"
