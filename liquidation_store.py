"""
Persistencia de liquidacoes reais (evento-cru) na tabela k_liquidations.

Isolado de proposito: recebe a conexao SQLite de fora, nao acopla a v1.1,
ao executor nem ao k_collector. Usado por scripts/liquidation_collector.py.

side: gravado como o lado da ORDEM de liquidacao reportado pela venue
      (BUY/SELL maiusculo). A interpretacao long/short fica na analise,
      pois a convencao varia entre exchanges. source identifica a venue.
"""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS k_liquidations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,   -- venue: 'bybit', 'binance', ...
    symbol       TEXT    NOT NULL,
    event_ts     INTEGER NOT NULL,   -- epoch ms do evento
    side         TEXT    NOT NULL,   -- lado da ordem de liquidacao (BUY/SELL)
    qty          REAL    NOT NULL,
    price        REAL    NOT NULL,
    notional     REAL    NOT NULL,   -- qty * price (USDT)
    collected_at INTEGER NOT NULL    -- epoch s de quando gravamos
);
CREATE INDEX IF NOT EXISTS idx_k_liq_source_symbol_ts ON k_liquidations(source, symbol, event_ts);
CREATE INDEX IF NOT EXISTS idx_k_liq_ts ON k_liquidations(event_ts);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Cria tabela e indices se nao existirem (idempotente)."""
    conn.executescript(SCHEMA)
    conn.commit()


def insert_liquidations(conn: sqlite3.Connection, rows, source: str = "bybit") -> int:
    """Insere um lote de liquidacoes.

    rows: iteravel de (symbol, event_ts, side, qty, price, notional, collected_at)
    source: venue de origem (default 'bybit').
    Retorna o numero de linhas inseridas.
    """
    rows = list(rows)
    if not rows:
        return 0
    conn.executemany(
        "INSERT INTO k_liquidations "
        "(source, symbol, event_ts, side, qty, price, notional, collected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(source, *r) for r in rows],
    )
    conn.commit()
    return len(rows)


def last_event_age_seconds(conn: sqlite3.Connection, now_s: int, source: str | None = None) -> float | None:
    """Idade (s) da liquidacao mais recente. None se vazia. Filtra por source se dado."""
    if source:
        row = conn.execute(
            "SELECT MAX(event_ts) FROM k_liquidations WHERE source=?", (source,)
        ).fetchone()
    else:
        row = conn.execute("SELECT MAX(event_ts) FROM k_liquidations").fetchone()
    if not row or row[0] is None:
        return None
    return now_s - (row[0] / 1000.0)
