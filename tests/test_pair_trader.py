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
