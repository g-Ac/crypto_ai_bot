"""Tests for research_db schema and CRUD."""
import os
import tempfile

import pytest

from momentum.expansion.research_db import (
    fetch_all_decisions,
    fetch_all_trades,
    init_db,
    insert_decision,
    insert_run,
    insert_trade,
)


@pytest.fixture
def db_path():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    yield f.name
    os.unlink(f.name)


def test_init_creates_tables(db_path):
    init_db(db_path)
    # Verify by inserting a decision
    insert_decision(db_path, {
        "run_id": "r1", "symbol": "BTCUSDT", "ts": "2026-01-01T00:00:00",
        "blocked_by": "no_signal",
    })
    rows = fetch_all_decisions(db_path)
    assert len(rows) == 1


def test_insert_and_fetch_trade(db_path):
    init_db(db_path)
    insert_trade(db_path, {
        "run_id": "r1",
        "symbol": "BTCUSDT", "direction": "long",
        "entry_ts": "2026-01-01T00:00:00", "exit_ts": "2026-01-01T01:00:00",
        "entry_price": 50000.0, "exit_price": 51000.0,
        "exit_reason": "TP1", "pnl_pct": 2.0,
        "regime": "TRENDING", "bucket": "core",
    })
    rows = fetch_all_trades(db_path)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSDT"
    assert rows[0]["pnl_pct"] == 2.0


def test_insert_run_with_config_hash(db_path):
    init_db(db_path)
    insert_run(db_path, {
        "run_id": "r1", "config_hash": "abc123",
        "universe_json": '["BTCUSDT","ETHUSDT"]',
        "started_at": "2026-04-27T15:00:00",
        "completed_at": "2026-04-27T15:30:00",
        "verdict": "PASS",
    })
    # Fetch via raw query for simplicity in test
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT * FROM expansion_runs"))
    conn.close()
    assert len(rows) == 1
    assert rows[0]["config_hash"] == "abc123"
