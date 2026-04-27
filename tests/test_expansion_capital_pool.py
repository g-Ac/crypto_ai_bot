"""Tests for S-B capital allocation."""
import math

import pytest

from momentum.expansion.capital_pool import (
    PortfolioState,
    allocate_position_size,
    compute_slot_size,
    open_slot,
    close_slot,
)


def test_compute_slot_size_evenly_divides():
    assert math.isclose(compute_slot_size(1000.0, 4), 250.0)
    assert math.isclose(compute_slot_size(1000.0, 1), 1000.0)


def test_compute_slot_size_zero_universe_raises():
    with pytest.raises(ValueError):
        compute_slot_size(1000.0, 0)


def test_allocate_position_size_uses_slot_and_risk_fraction():
    # slot = 250, entry = 100, sl = 95 (risk = 5% of price), risk fraction = 0.01 (1% of slot)
    # risk in usdt = 250 * 0.01 = 2.5
    # position size in usdt = risk / (entry - sl) * entry = 2.5 / 5 * 100 = 50
    size = allocate_position_size(slot_size_usdt=250.0, entry=100.0, sl=95.0, risk_fraction=0.01)
    assert math.isclose(size, 50.0, rel_tol=1e-9)


def test_allocate_position_size_short():
    # short: sl > entry; risk = sl - entry
    size = allocate_position_size(slot_size_usdt=250.0, entry=100.0, sl=105.0, risk_fraction=0.01)
    assert math.isclose(size, 50.0, rel_tol=1e-9)


def test_allocate_position_size_zero_risk_raises():
    with pytest.raises(ValueError):
        allocate_position_size(slot_size_usdt=250.0, entry=100.0, sl=100.0, risk_fraction=0.01)


def test_portfolio_state_tracks_open_slots():
    state = PortfolioState(capital_pool=1000.0, slot_size=250.0)
    assert state.allocated == 0.0
    assert state.peak_concurrent == 0
    assert state.can_open()


def test_open_close_slot_round_trip():
    state = PortfolioState(capital_pool=1000.0, slot_size=250.0)
    open_slot(state, "BTCUSDT")
    assert "BTCUSDT" in state.open_symbols
    assert math.isclose(state.allocated, 250.0)
    assert state.peak_concurrent == 1
    close_slot(state, "BTCUSDT")
    assert "BTCUSDT" not in state.open_symbols
    assert math.isclose(state.allocated, 0.0)


def test_concurrent_slots_capped_by_pool():
    state = PortfolioState(capital_pool=1000.0, slot_size=250.0)  # max 4 concurrent
    for sym in ["A", "B", "C", "D"]:
        open_slot(state, sym)
    assert state.peak_concurrent == 4
    assert math.isclose(state.allocated, 1000.0)
    assert not state.can_open()  # pool exhausted

    # Try opening 5th — must raise
    with pytest.raises(ValueError):
        open_slot(state, "E")


def test_double_open_same_symbol_raises():
    state = PortfolioState(capital_pool=1000.0, slot_size=250.0)
    open_slot(state, "BTCUSDT")
    with pytest.raises(ValueError):
        open_slot(state, "BTCUSDT")
