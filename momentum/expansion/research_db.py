"""SQLite schema and CRUD for EXP-005 research artifacts."""
from __future__ import annotations

import sqlite3


_DDL = """
CREATE TABLE IF NOT EXISTS expansion_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_ts TEXT NOT NULL,
    exit_ts TEXT,
    entry_price REAL NOT NULL,
    exit_price REAL,
    exit_reason TEXT,
    pnl_pct REAL,
    regime TEXT,
    bucket TEXT
);

CREATE TABLE IF NOT EXISTS expansion_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    blocked_by TEXT
);

CREATE TABLE IF NOT EXISTS expansion_folds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    fold_idx INTEGER NOT NULL,
    n_trades INTEGER NOT NULL,
    pf REAL NOT NULL,
    win_rate REAL NOT NULL,
    max_dd_pct REAL NOT NULL,
    total_pnl_pct REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS expansion_runs (
    run_id TEXT PRIMARY KEY,
    config_hash TEXT NOT NULL,
    universe_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    verdict TEXT
);
"""


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript("PRAGMA journal_mode=WAL;")
    conn.executescript(_DDL)
    conn.commit()
    conn.close()


def insert_trade(db_path: str, trade: dict) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO expansion_trades "
        "(run_id, symbol, direction, entry_ts, exit_ts, entry_price, exit_price, "
        "exit_reason, pnl_pct, regime, bucket) "
        "VALUES (:run_id,:symbol,:direction,:entry_ts,:exit_ts,:entry_price,"
        ":exit_price,:exit_reason,:pnl_pct,:regime,:bucket)",
        trade,
    )
    conn.commit()
    conn.close()


def insert_decision(db_path: str, decision: dict) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO expansion_decisions (run_id, symbol, ts, blocked_by) "
        "VALUES (:run_id,:symbol,:ts,:blocked_by)",
        decision,
    )
    conn.commit()
    conn.close()


def insert_fold(db_path: str, fold: dict) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO expansion_folds (run_id, fold_idx, n_trades, pf, win_rate, "
        "max_dd_pct, total_pnl_pct) VALUES (:run_id,:fold_idx,:n_trades,:pf,:win_rate,"
        ":max_dd_pct,:total_pnl_pct)",
        fold,
    )
    conn.commit()
    conn.close()


def insert_run(db_path: str, run: dict) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO expansion_runs (run_id, config_hash, universe_json, "
        "started_at, completed_at, verdict) "
        "VALUES (:run_id,:config_hash,:universe_json,:started_at,:completed_at,:verdict)",
        run,
    )
    conn.commit()
    conn.close()


def fetch_all_trades(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM expansion_trades ORDER BY id")]
    conn.close()
    return rows


def fetch_all_decisions(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM expansion_decisions ORDER BY id")]
    conn.close()
    return rows
