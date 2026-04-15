"""Persistence layer for Momentum Pullback Research Mode.

Simple SQLite module: two tables (decisions + trades), CRUD functions,
forward-label updates. No ORM, no framework — just sqlite3 + dicts.

Tables are prefixed `momentum_` to avoid conflict with existing bot tables.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DECISIONS_DDL = """
CREATE TABLE IF NOT EXISTS momentum_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    regime          TEXT    NOT NULL,
    session_bucket  TEXT    NOT NULL DEFAULT '',
    asset_bucket    TEXT    NOT NULL DEFAULT '',

    -- Signal evaluation result
    outcome         TEXT    NOT NULL,
    direction       TEXT    NOT NULL,

    -- Diagnostics from MomentumSignal
    ema_fast_value      REAL NOT NULL DEFAULT 0,
    ema_slow_value      REAL NOT NULL DEFAULT 0,
    ema_gap_pct         REAL NOT NULL DEFAULT 0,
    retracement_pct     REAL NOT NULL DEFAULT 0,
    impulse_start_price REAL NOT NULL DEFAULT 0,
    impulse_end_price   REAL NOT NULL DEFAULT 0,
    pullback_rejection  TEXT NOT NULL DEFAULT '',

    -- Versioning
    param_version   TEXT NOT NULL DEFAULT '',

    -- Forward labels (filled asynchronously after N candles)
    forward_mfe_pct REAL,
    forward_mae_pct REAL
);
"""

_TRADES_DDL = """
CREATE TABLE IF NOT EXISTS momentum_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER NOT NULL REFERENCES momentum_decisions(id),
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    direction       TEXT    NOT NULL,
    regime          TEXT    NOT NULL,
    session_bucket  TEXT    NOT NULL DEFAULT '',

    -- Prices
    entry_price     REAL NOT NULL,
    sl_price        REAL NOT NULL,
    tp1_price       REAL NOT NULL,
    tp2_price       REAL NOT NULL,

    -- Exit (NULL while open)
    exit_price      REAL,
    exit_reason     TEXT,
    exit_timestamp  TEXT,

    -- Performance (filled on exit or progressively)
    pnl_pct         REAL,
    duration_candles INTEGER,
    mfe_pct         REAL NOT NULL DEFAULT 0,
    mae_pct         REAL NOT NULL DEFAULT 0,

    -- Research flags
    retested_impulse_end    INTEGER NOT NULL DEFAULT 0,
    lost_pullback_extreme   INTEGER NOT NULL DEFAULT 0,

    -- Versioning
    param_version   TEXT NOT NULL DEFAULT ''
);
"""

_INDEXES_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_mdec_ts ON momentum_decisions(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_mdec_symbol ON momentum_decisions(symbol);",
    "CREATE INDEX IF NOT EXISTS idx_mdec_outcome ON momentum_decisions(outcome);",
    "CREATE INDEX IF NOT EXISTS idx_mtrade_ts ON momentum_trades(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_mtrade_symbol ON momentum_trades(symbol);",
    "CREATE INDEX IF NOT EXISTS idx_mtrade_open ON momentum_trades(exit_price);",
]


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables(db_path: str | Path) -> None:
    """Create tables and indexes if they don't exist. Idempotent."""
    conn = _connect(db_path)
    try:
        conn.execute(_DECISIONS_DDL)
        conn.execute(_TRADES_DDL)
        for idx in _INDEXES_DDL:
            conn.execute(idx)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

_DECISION_COLUMNS = [
    "timestamp", "symbol", "regime", "session_bucket", "asset_bucket",
    "outcome", "direction",
    "ema_fast_value", "ema_slow_value", "ema_gap_pct",
    "retracement_pct", "impulse_start_price", "impulse_end_price",
    "pullback_rejection", "param_version",
    "forward_mfe_pct", "forward_mae_pct",
]


def insert_decision(db_path: str | Path, decision: Dict[str, Any]) -> int:
    """Insert a decision row. Returns the new row id."""
    cols = [c for c in _DECISION_COLUMNS if c in decision]
    placeholders = ", ".join(["?"] * len(cols))
    col_names = ", ".join(cols)
    values = [decision[c] for c in cols]

    conn = _connect(db_path)
    try:
        cur = conn.execute(
            f"INSERT INTO momentum_decisions ({col_names}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_decision_forward(
    db_path: str | Path,
    decision_id: int,
    forward_mfe_pct: float,
    forward_mae_pct: float,
) -> None:
    """Fill forward-label fields on an existing decision."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE momentum_decisions "
            "SET forward_mfe_pct = ?, forward_mae_pct = ? "
            "WHERE id = ?",
            (forward_mfe_pct, forward_mae_pct, decision_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_decisions(
    db_path: str | Path,
    *,
    days: Optional[int] = None,
    symbol: Optional[str] = None,
    outcome: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query decisions with optional filters.

    Args:
        days: Only return decisions from the last N days.
        symbol: Filter by symbol.
        outcome: Filter by outcome string.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if days is not None:
        clauses.append("timestamp >= datetime('now', ?)")
        params.append(f"-{days} days")
    if symbol is not None:
        clauses.append("symbol = ?")
        params.append(symbol)
    if outcome is not None:
        clauses.append("outcome = ?")
        params.append(outcome)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM momentum_decisions{where} ORDER BY id", params
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

_TRADE_COLUMNS = [
    "decision_id", "timestamp", "symbol", "direction", "regime",
    "session_bucket",
    "entry_price", "sl_price", "tp1_price", "tp2_price",
    "exit_price", "exit_reason", "exit_timestamp",
    "pnl_pct", "duration_candles", "mfe_pct", "mae_pct",
    "retested_impulse_end", "lost_pullback_extreme",
    "param_version",
]


def insert_trade(db_path: str | Path, trade: Dict[str, Any]) -> int:
    """Insert a trade row. Returns the new row id."""
    cols = [c for c in _TRADE_COLUMNS if c in trade]
    placeholders = ", ".join(["?"] * len(cols))
    col_names = ", ".join(cols)
    values = [trade[c] for c in cols]

    conn = _connect(db_path)
    try:
        cur = conn.execute(
            f"INSERT INTO momentum_trades ({col_names}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def close_trade(
    db_path: str | Path,
    trade_id: int,
    exit_price: float,
    exit_reason: str,
    exit_timestamp: str,
    pnl_pct: float,
    duration_candles: int,
    mfe_pct: float,
    mae_pct: float,
    retested_impulse_end: bool = False,
    lost_pullback_extreme: bool = False,
) -> None:
    """Close an open trade with exit data and research flags."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE momentum_trades SET "
            "exit_price = ?, exit_reason = ?, exit_timestamp = ?, "
            "pnl_pct = ?, duration_candles = ?, "
            "mfe_pct = ?, mae_pct = ?, "
            "retested_impulse_end = ?, lost_pullback_extreme = ? "
            "WHERE id = ?",
            (
                exit_price, exit_reason, exit_timestamp,
                pnl_pct, duration_candles,
                mfe_pct, mae_pct,
                int(retested_impulse_end), int(lost_pullback_extreme),
                trade_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_trade_mfe_mae(
    db_path: str | Path,
    trade_id: int,
    mfe_pct: float,
    mae_pct: float,
) -> None:
    """Update running MFE/MAE on an open trade."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE momentum_trades SET mfe_pct = ?, mae_pct = ? WHERE id = ?",
            (mfe_pct, mae_pct, trade_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_open_trades(db_path: str | Path) -> List[Dict[str, Any]]:
    """Return trades that haven't been closed yet (exit_price IS NULL)."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM momentum_trades WHERE exit_price IS NULL ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_trades(
    db_path: str | Path,
    *,
    days: Optional[int] = None,
    symbol: Optional[str] = None,
    closed_only: bool = False,
) -> List[Dict[str, Any]]:
    """Query trades with optional filters.

    Args:
        days: Only return trades from the last N days.
        symbol: Filter by symbol.
        closed_only: If True, exclude open trades.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if days is not None:
        clauses.append("timestamp >= datetime('now', ?)")
        params.append(f"-{days} days")
    if symbol is not None:
        clauses.append("symbol = ?")
        params.append(symbol)
    if closed_only:
        clauses.append("exit_price IS NOT NULL")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM momentum_trades{where} ORDER BY id", params
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
