"""SQLite persistence for pair trading research/backtest results.

Two tables:
  pair_decisions — one row per evaluated cycle (including skipped)
  pair_trades    — one row per closed trade (dual-leg merged)

Simple sqlite3, no ORM. Functions accept dict payloads to keep call sites flexible.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


_DECISIONS_DDL = """
CREATE TABLE IF NOT EXISTS pair_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    z_score         REAL,
    cum_spread      REAL,
    rolling_mean    REAL,
    rolling_std     REAL,
    correlation     REAL,
    btc_regime      TEXT    NOT NULL DEFAULT '',
    action_taken    TEXT    NOT NULL,
    blocked_by      TEXT,
    position_id     INTEGER,
    param_version   TEXT    NOT NULL DEFAULT 'pair-trading-v1.0'
);
"""

_TRADES_DDL = """
CREATE TABLE IF NOT EXISTS pair_trades (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_time       TEXT    NOT NULL,
    exit_time        TEXT,
    direction        TEXT    NOT NULL,
    entry_btc        REAL    NOT NULL,
    entry_eth        REAL    NOT NULL,
    exit_btc         REAL,
    exit_eth         REAL,
    entry_z          REAL    NOT NULL,
    exit_z           REAL,
    exit_reason      TEXT,
    pnl_btc_pct      REAL,
    pnl_eth_pct      REAL,
    pnl_total_pct    REAL,
    pnl_usd          REAL,
    candles_held     INTEGER,
    capital_at_entry REAL    NOT NULL,
    btc_regime_entry TEXT    NOT NULL DEFAULT '',
    session_entry    TEXT    NOT NULL DEFAULT '',
    param_version    TEXT    NOT NULL DEFAULT 'pair-trading-v1.0'
);
"""


def _connect(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db(db_path: str | Path) -> None:
    con = _connect(db_path)
    try:
        con.execute(_DECISIONS_DDL)
        con.execute(_TRADES_DDL)
        con.commit()
    finally:
        con.close()


def insert_decision(db_path: str | Path, payload: Dict[str, Any]) -> int:
    con = _connect(db_path)
    try:
        cur = con.execute(
            """INSERT INTO pair_decisions
               (timestamp, z_score, cum_spread, rolling_mean, rolling_std,
                correlation, btc_regime, action_taken, blocked_by, position_id)
               VALUES (:timestamp, :z_score, :cum_spread, :rolling_mean, :rolling_std,
                       :correlation, :btc_regime, :action_taken, :blocked_by, :position_id)""",
            payload,
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def insert_trade(db_path: str | Path, payload: Dict[str, Any]) -> int:
    con = _connect(db_path)
    try:
        cur = con.execute(
            """INSERT INTO pair_trades
               (entry_time, direction, entry_btc, entry_eth, entry_z,
                capital_at_entry, btc_regime_entry, session_entry)
               VALUES (:entry_time, :direction, :entry_btc, :entry_eth, :entry_z,
                       :capital_at_entry, :btc_regime_entry, :session_entry)""",
            payload,
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def close_trade(db_path: str | Path, trade_id: int, payload: Dict[str, Any]) -> None:
    con = _connect(db_path)
    try:
        payload = {**payload, "id": trade_id}
        con.execute(
            """UPDATE pair_trades
               SET exit_time=:exit_time, exit_btc=:exit_btc, exit_eth=:exit_eth,
                   exit_z=:exit_z, exit_reason=:exit_reason,
                   pnl_btc_pct=:pnl_btc_pct, pnl_eth_pct=:pnl_eth_pct,
                   pnl_total_pct=:pnl_total_pct, pnl_usd=:pnl_usd,
                   candles_held=:candles_held
               WHERE id=:id""",
            payload,
        )
        con.commit()
    finally:
        con.close()


def get_open_trade(db_path: str | Path) -> Optional[Dict[str, Any]]:
    con = _connect(db_path)
    try:
        row = con.execute(
            "SELECT * FROM pair_trades WHERE exit_time IS NULL LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def fetch_all_trades(db_path: str | Path) -> List[Dict[str, Any]]:
    con = _connect(db_path)
    try:
        rows = con.execute("SELECT * FROM pair_trades ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def fetch_all_decisions(db_path: str | Path) -> List[Dict[str, Any]]:
    con = _connect(db_path)
    try:
        rows = con.execute("SELECT * FROM pair_decisions ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
