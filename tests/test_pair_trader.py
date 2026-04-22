"""Tests for pair_trader.decide — entry branches."""
import pytest
from pair_trading.config import PairConfig
from pair_trading.pair_trader import (
    PairAction, PairDecision, PairPosition, decide,
)
from pair_trading.spread_calculator import SpreadSnapshot


CFG = PairConfig()


def _snap(z: float, is_valid: bool = True) -> SpreadSnapshot:
    return SpreadSnapshot(
        cum_spread=0.1, rolling_mean=0.0, rolling_std=0.05,
        z_score=z, correlation=0.8, is_valid=is_valid,
    )


def test_no_action_when_z_below_threshold():
    d = decide(_snap(1.5), position=None, config=CFG)
    assert d.action == PairAction.NO_ACTION
    assert d.blocked_by == "z_below_threshold"


def test_no_action_when_z_above_entry_guard():
    d = decide(_snap(3.1), position=None, config=CFG)
    assert d.action == PairAction.NO_ACTION
    assert d.blocked_by == "z_above_entry_guard"


def test_no_action_when_invalid_snapshot():
    d = decide(_snap(2.5, is_valid=False), position=None, config=CFG)
    assert d.action == PairAction.NO_ACTION
    assert d.blocked_by == "invalid_zscore"


def test_open_short_btc_long_eth_when_z_positive():
    # z = +2.5 means BTC outperformed → short BTC, long ETH
    d = decide(_snap(2.5), position=None, config=CFG)
    assert d.action == PairAction.OPEN_SHORT_BTC_LONG_ETH
    assert d.blocked_by is None


def test_open_long_btc_short_eth_when_z_negative():
    d = decide(_snap(-2.5), position=None, config=CFG)
    assert d.action == PairAction.OPEN_LONG_BTC_SHORT_ETH
    assert d.blocked_by is None


def test_entry_exactly_at_threshold_opens():
    d = decide(_snap(2.0), position=None, config=CFG)
    assert d.action == PairAction.OPEN_SHORT_BTC_LONG_ETH


def test_entry_at_upper_boundary_opens():
    d = decide(_snap(2.9), position=None, config=CFG)
    assert d.action == PairAction.OPEN_SHORT_BTC_LONG_ETH


def test_circuit_breaker_blocks_entry():
    d = decide(_snap(2.5), position=None, config=CFG, circuit_breaker_active=True)
    assert d.action == PairAction.NO_ACTION
    assert d.blocked_by == "circuit_breaker"


# --- exit branch tests ---

def _pos(direction=PairAction.OPEN_SHORT_BTC_LONG_ETH, entry_z=2.5, held=10):
    return PairPosition(direction=direction, entry_z=entry_z, candles_held=held)


def test_hold_when_z_still_wide():
    # Position at z=+2.5 still +2.0 → no exit yet
    d = decide(_snap(2.0), position=_pos(), config=CFG)
    assert d.action == PairAction.HOLD


def test_close_tp_when_z_crosses_tp_threshold():
    d = decide(_snap(0.4), position=_pos(), config=CFG)
    assert d.action == PairAction.CLOSE_TP
    assert "tp" in (d.trigger_reason or "").lower()


def test_close_tp_at_exact_boundary():
    d = decide(_snap(0.5), position=_pos(), config=CFG)
    assert d.action == PairAction.CLOSE_TP


def test_close_sl_when_z_beyond_sl_threshold():
    d = decide(_snap(3.1), position=_pos(), config=CFG)
    assert d.action == PairAction.CLOSE_SL


def test_close_sl_at_exact_boundary():
    d = decide(_snap(3.0), position=_pos(), config=CFG)
    assert d.action == PairAction.CLOSE_SL


def test_close_timeout_when_candles_held_reached():
    pos = _pos(held=96)
    # Pick a z in the HOLD zone so only timeout triggers
    d = decide(_snap(1.5), position=pos, config=CFG)
    assert d.action == PairAction.CLOSE_TIMEOUT


def test_priority_sl_over_timeout():
    pos = _pos(held=96)
    # Both SL and TIMEOUT would fire; SL wins
    d = decide(_snap(3.2), position=pos, config=CFG)
    assert d.action == PairAction.CLOSE_SL


def test_priority_timeout_over_tp():
    pos = _pos(held=96)
    # Both TIMEOUT and TP would fire; TIMEOUT wins
    d = decide(_snap(0.4), position=pos, config=CFG)
    assert d.action == PairAction.CLOSE_TIMEOUT


def test_exit_ignores_circuit_breaker():
    # Once open, circuit breaker does not force-close
    d = decide(_snap(0.4), position=_pos(), config=CFG, circuit_breaker_active=True)
    assert d.action == PairAction.CLOSE_TP  # normal TP still fires


def test_exit_ignores_invalid_snapshot():
    # Position open + invalid snapshot → blocked, no close
    d = decide(_snap(0.4, is_valid=False), position=_pos(), config=CFG)
    assert d.action == PairAction.NO_ACTION
    assert d.blocked_by == "invalid_zscore"
