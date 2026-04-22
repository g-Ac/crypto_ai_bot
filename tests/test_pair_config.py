"""Tests for PairConfig."""
import os
import pytest
from pair_trading.config import PairConfig


def test_defaults():
    cfg = PairConfig()
    assert cfg.symbols == ("BTCUSDT", "ETHUSDT")
    assert cfg.timeframe == "15m"
    assert cfg.window_candles == 96
    assert cfg.zscore_window_candles == 96
    assert cfg.entry_z == 2.0
    assert cfg.entry_max_z == 2.9
    assert cfg.exit_tp_z == 0.5
    assert cfg.exit_sl_z == 3.0
    assert cfg.time_stop_candles == 96
    assert cfg.capital_per_leg_usd == 500.0
    assert cfg.total_capital_usd == 1000.0
    assert cfg.max_concurrent_positions == 1
    assert cfg.circuit_breaker_dd_pct == 5.0
    assert cfg.fees_taker_pct == 0.04
    assert cfg.slippage_pct == 0.0
    assert cfg.param_version == "pair-trading-v1.0"
    assert cfg.enabled is False


def test_invariants_entry_thresholds():
    with pytest.raises(ValueError, match="entry_z"):
        PairConfig(entry_z=0)
    with pytest.raises(ValueError, match="exit_tp_z < entry_z"):
        PairConfig(exit_tp_z=2.5, entry_z=2.0)
    with pytest.raises(ValueError, match="entry_z < exit_sl_z"):
        PairConfig(entry_z=3.5, exit_sl_z=3.0)
    with pytest.raises(ValueError, match="entry_max_z"):
        PairConfig(entry_z=2.0, entry_max_z=1.9)


def test_invariant_capital():
    with pytest.raises(ValueError, match="capital"):
        PairConfig(capital_per_leg_usd=500, total_capital_usd=900)


def test_from_env(monkeypatch):
    monkeypatch.setenv("PAIR_TRADER_ENABLED", "true")
    monkeypatch.setenv("PAIR_CAPITAL_USD", "2000")
    cfg = PairConfig.from_env()
    assert cfg.enabled is True
    assert cfg.total_capital_usd == 2000.0
    assert cfg.capital_per_leg_usd == 1000.0  # recomputed to keep invariant


def test_from_env_boolean_parsing(monkeypatch):
    for v, expected in [("true", True), ("True", True), ("1", True),
                        ("false", False), ("0", False), ("", False)]:
        monkeypatch.setenv("PAIR_TRADER_ENABLED", v)
        assert PairConfig.from_env().enabled == expected
