"""Tests for pair research DB CRUD."""
import os
import tempfile
import sqlite3

import pytest

from pair_trading.research_db import (
    init_db,
    insert_decision,
    insert_trade,
    close_trade,
    get_open_trade,
    fetch_all_trades,
    fetch_all_decisions,
)


@pytest.fixture
def db_path():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    yield tmp.name
    os.unlink(tmp.name)


def test_init_db_creates_tables(db_path):
    init_db(db_path)
    con = sqlite3.connect(db_path)
    tables = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "pair_decisions" in tables
    assert "pair_trades" in tables


def test_insert_decision_and_fetch(db_path):
    init_db(db_path)
    insert_decision(db_path, {
        "timestamp": "2026-04-21T00:00:00Z",
        "z_score": 2.3, "cum_spread": 0.05,
        "rolling_mean": 0.0, "rolling_std": 0.022,
        "correlation": 0.85, "btc_regime": "TRENDING",
        "action_taken": "open_short_btc_long_eth",
        "blocked_by": None,
        "position_id": None,
    })
    rows = fetch_all_decisions(db_path)
    assert len(rows) == 1
    assert rows[0]["action_taken"] == "open_short_btc_long_eth"


def test_insert_trade_open_and_close(db_path):
    init_db(db_path)
    tid = insert_trade(db_path, {
        "entry_time": "2026-04-21T00:00:00Z",
        "direction": "open_short_btc_long_eth",
        "entry_btc": 50000.0, "entry_eth": 3000.0,
        "entry_z": 2.3,
        "capital_at_entry": 1000.0,
        "btc_regime_entry": "TRENDING",
        "session_entry": "asia",
    })
    assert tid is not None

    open_t = get_open_trade(db_path)
    assert open_t is not None
    assert open_t["id"] == tid

    close_trade(db_path, tid, {
        "exit_time": "2026-04-21T12:00:00Z",
        "exit_btc": 49500.0, "exit_eth": 3010.0,
        "exit_z": 0.4, "exit_reason": "close_tp",
        "pnl_btc_pct": 1.0, "pnl_eth_pct": 0.33,
        "pnl_total_pct": 0.665, "pnl_usd": 6.65,
        "candles_held": 48,
    })

    open_t2 = get_open_trade(db_path)
    assert open_t2 is None

    trades = fetch_all_trades(db_path)
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "close_tp"
