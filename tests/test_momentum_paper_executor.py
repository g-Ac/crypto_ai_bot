"""Tests for momentum paper executor."""
import json
import os
import tempfile

import pytest


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
