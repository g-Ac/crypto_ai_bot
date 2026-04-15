"""Tests for momentum paper executor."""
import json
import os
import sqlite3
import tempfile
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from momentum.config import MomentumConfig, MomentumOutcome, MomentumDirection
from momentum.momentum_trader import MomentumSignal


@pytest.fixture
def state_file(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    # Remove so load_state creates fresh
    os.unlink(path)
    monkeypatch.setattr("momentum.paper_executor.MOMENTUM_STATE_FILE", path)
    monkeypatch.setattr("momentum.paper_executor.MOMENTUM_INITIAL_CAPITAL", 1000.0)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("database.DB_FILE", path)
    import database as db
    db.init_db()
    yield path
    os.unlink(path)


def _make_trade_signal(symbol="BTCUSDT", direction="LONG",
                       entry=85000.0, sl=84500.0,
                       tp1=85800.0, tp2=86500.0):
    return MomentumSignal(
        outcome=MomentumOutcome.TRADE,
        direction=MomentumDirection(direction),
        entry_price=entry,
        sl_price=sl,
        tp1_price=tp1,
        tp2_price=tp2,
        ema_fast_value=85100.0,
        ema_slow_value=84800.0,
        ema_gap_pct=0.35,
        retracement_pct=42.5,
        impulse_start_price=84000.0,
        impulse_end_price=86000.0,
        symbol=symbol,
        regime="TRENDING",
        timestamp="2026-04-15T12:00:00",
        param_version="momentum-pullback-v1.1",
    )


def _make_reject_signal(symbol="BTCUSDT", outcome=MomentumOutcome.NO_TREND):
    return MomentumSignal(
        outcome=outcome,
        direction=MomentumDirection.NEUTRAL,
        symbol=symbol,
        regime="TRENDING",
        timestamp="2026-04-15T12:00:00",
        param_version="momentum-pullback-v1.1",
    )


class TestOpenPosition:
    def test_opens_position_on_trade_signal(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position

        state = load_state()
        signal = _make_trade_signal()
        msgs = open_position(state, signal, "20260415_120000")
        save_state(state)

        assert "BTCUSDT" in state["positions"]
        pos = state["positions"]["BTCUSDT"]
        assert pos["direction"] == "LONG"
        assert pos["entry_price"] == 85000.0
        assert pos["sl_price"] == 84500.0
        assert pos["position_size_usd"] > 0
        assert len(msgs) > 0

    def test_respects_max_positions(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position

        state = load_state()
        signal1 = _make_trade_signal(symbol="BTCUSDT")
        open_position(state, signal1, "cycle1")

        signal2 = _make_trade_signal(symbol="ETHUSDT", entry=3200.0,
                                     sl=3150.0, tp1=3280.0, tp2=3350.0)
        msgs = open_position(state, signal2, "cycle1")
        save_state(state)

        assert "ETHUSDT" not in state["positions"]
        assert len(state["positions"]) == 1

    def test_skips_duplicate_symbol(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")
        msgs = open_position(state, signal, "cycle2")
        save_state(state)

        assert len(state["positions"]) == 1

    def test_position_size_within_capital(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, open_position

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")

        pos = state["positions"]["BTCUSDT"]
        assert pos["position_size_usd"] <= state["capital"]


class TestStateManagement:
    def test_load_fresh_state(self, state_file):
        from momentum.paper_executor import load_state

        state = load_state()
        assert state["capital"] == 1000.0
        assert state["positions"] == {}
        assert state["cooldowns"] == {}
        assert state["total_trades"] == 0
        assert state["wins"] == 0
        assert state["losses"] == 0
        assert state["total_pnl_usd"] == 0.0
        assert state["hwm"] == 1000.0

    def test_save_and_reload(self, state_file):
        from momentum.paper_executor import load_state, save_state

        state = load_state()
        state["capital"] = 1050.0
        state["hwm"] = 1050.0
        state["total_trades"] = 3
        save_state(state)

        reloaded = load_state()
        assert reloaded["capital"] == 1050.0
        assert reloaded["hwm"] == 1050.0
        assert reloaded["total_trades"] == 3

    def test_save_is_atomic(self, state_file):
        from momentum.paper_executor import load_state, save_state

        state = load_state()
        save_state(state)

        # File exists and is valid JSON
        with open(state_file) as f:
            data = json.load(f)
        assert data["capital"] == 1000.0

    def test_get_status_no_positions(self, state_file):
        from momentum.paper_executor import load_state, get_momentum_status

        load_state()  # ensure state file exists
        status = get_momentum_status()
        assert "MOMENTUM" in status
        assert "$1000.00" in status
        assert "0W" in status
