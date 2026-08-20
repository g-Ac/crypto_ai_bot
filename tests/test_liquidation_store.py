"""Testes do liquidation_store (persistencia de liquidacoes evento-cru)."""
import sqlite3

import liquidation_store as ls


def _conn():
    c = sqlite3.connect(":memory:")
    ls.ensure_schema(c)
    return c


def test_ensure_schema_creates_table():
    c = _conn()
    got = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='k_liquidations'"
    ).fetchone()
    assert got is not None


def test_ensure_schema_idempotent():
    c = _conn()
    ls.ensure_schema(c)  # segunda chamada nao deve falhar
    ls.insert_liquidations(
        c, [("BTCUSDT", 1700000000000, "SELL", 1.0, 60000.0, 60000.0, 1700000000)]
    )
    assert c.execute("SELECT COUNT(*) FROM k_liquidations").fetchone()[0] == 1


def test_insert_and_count():
    c = _conn()
    rows = [
        ("BTCUSDT", 1700000000000, "SELL", 1.5, 60000.0, 90000.0, 1700000000),
        ("ETHUSDT", 1700000001000, "BUY", 10.0, 3000.0, 30000.0, 1700000001),
    ]
    assert ls.insert_liquidations(c, rows) == 2
    assert c.execute("SELECT COUNT(*) FROM k_liquidations").fetchone()[0] == 2


def test_insert_empty_is_noop():
    c = _conn()
    assert ls.insert_liquidations(c, []) == 0
    assert c.execute("SELECT COUNT(*) FROM k_liquidations").fetchone()[0] == 0


def test_side_semantics_persist():
    c = _conn()
    ls.insert_liquidations(
        c,
        [
            ("BTCUSDT", 1700000000000, "SELL", 1.0, 60000.0, 60000.0, 1700000000),
            ("BTCUSDT", 1700000002000, "BUY", 2.0, 60000.0, 120000.0, 1700000002),
        ],
    )
    long_liq = c.execute(
        "SELECT COUNT(*) FROM k_liquidations WHERE side='SELL'"
    ).fetchone()[0]
    short_liq = c.execute(
        "SELECT COUNT(*) FROM k_liquidations WHERE side='BUY'"
    ).fetchone()[0]
    assert long_liq == 1 and short_liq == 1


def test_last_event_age_none_when_empty():
    c = _conn()
    assert ls.last_event_age_seconds(c, 1700000000) is None


def test_last_event_age_computes():
    c = _conn()
    ls.insert_liquidations(
        c, [("BTCUSDT", 1700000000000, "SELL", 1.0, 60000.0, 60000.0, 1700000000)]
    )
    age = ls.last_event_age_seconds(c, 1700000060)  # 60s depois do evento
    assert abs(age - 60.0) < 1.0
