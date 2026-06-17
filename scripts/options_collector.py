"""Coletor de opções Deribit (EXP-019 Fase 0). Hourly, idempotente, ts da Deribit.

Padrão consolidado de scripts/k_collector.py. Só coleta — nenhuma análise.
Spec: research/exp019_options_structure/PREREGISTRO.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import options_features as of  # noqa: E402

DB_PATH = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")
SYMBOLS = ["BTC", "ETH"]
INDEX_NAME = {"BTC": "btc_usd", "ETH": "eth_usd"}
BASE_URL = "https://www.deribit.com/api/v2"
USER_AGENT = "crypto_ai_bot/options_collector"
HTTP_TIMEOUT = 15.0
MAX_RETRIES = 4
BACKOFF_SECONDS = (5, 30, 120, 300)
MIN_YEAR_SANITY = 2025

SCHEMA = """
CREATE TABLE IF NOT EXISTS k_options_features (
    symbol      TEXT    NOT NULL,
    bucket_ts   INTEGER NOT NULL,
    spot        REAL,
    gex         REAL, gex_abs REAL, gamma_flip REAL,
    dvol        REAL, dvol_chg REAL,
    skew_25d    REAL, iv_atm REAL, rv_48h REAL, vrp REAL, term_slope REAL,
    n_strikes   INTEGER, oi_total REAL,
    collected_at INTEGER NOT NULL,
    PRIMARY KEY (symbol, bucket_ts)
);
CREATE INDEX IF NOT EXISTS idx_k_options_features_bucket ON k_options_features(bucket_ts);

CREATE TABLE IF NOT EXISTS k_options_snapshot_agg (
    symbol        TEXT    NOT NULL,
    bucket_ts     INTEGER NOT NULL,
    expiry_bucket TEXT    NOT NULL,
    strike_bucket TEXT    NOT NULL,
    oi            REAL, iv_mean REAL, n INTEGER,
    collected_at  INTEGER NOT NULL,
    PRIMARY KEY (symbol, bucket_ts, expiry_bucket, strike_bucket)
);

CREATE TABLE IF NOT EXISTS k_options_collector_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL, finished_at INTEGER, status TEXT,
    symbols_ok INTEGER DEFAULT 0, symbols_fail INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0, notes TEXT
);
"""

_FEATURE_COLS = ["symbol","bucket_ts","spot","gex","gex_abs","gamma_flip","dvol",
                 "dvol_chg","skew_25d","iv_atm","rv_48h","vrp","term_slope",
                 "n_strikes","oi_total"]


def now_ts() -> int:
    return int(time.time())


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_features(conn, row: dict, collected_at: int) -> int:
    vals = [row.get(c) for c in _FEATURE_COLS] + [collected_at]
    placeholders = ", ".join(["?"] * len(vals))
    cur = conn.execute(
        f"INSERT OR IGNORE INTO k_options_features "
        f"({', '.join(_FEATURE_COLS)}, collected_at) VALUES ({placeholders})",
        vals,
    )
    return cur.rowcount


def upsert_agg(conn, rows: list[dict], collected_at: int) -> int:
    inserted = 0
    for r in rows:
        cur = conn.execute(
            "INSERT OR IGNORE INTO k_options_snapshot_agg "
            "(symbol, bucket_ts, expiry_bucket, strike_bucket, oi, iv_mean, n, collected_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (r["symbol"], r["bucket_ts"], r["expiry_bucket"], r["strike_bucket"],
             r.get("oi"), r.get("iv_mean"), r.get("n"), collected_at),
        )
        inserted += cur.rowcount
    return inserted


def check_clock_sanity() -> tuple[bool, str]:
    now = dt.datetime.now(dt.timezone.utc)
    if now.year < MIN_YEAR_SANITY:
        return False, f"relogio do Pi parece errado: ano={now.year} < {MIN_YEAR_SANITY}. Aborta."
    return True, f"clock ok: {now.isoformat()}"
