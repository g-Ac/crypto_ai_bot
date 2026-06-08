"""Testes do coletor de liquidacoes (buffer + integracao feed->buffer->store)."""
import json
import os
import sqlite3
import sys

import bybit_liquidation_feed as feed
import liquidation_store as ls

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
import liquidation_collector as lc  # noqa: E402


def test_buffer_add_and_drain():
    b = lc.LiquidationBuffer()
    b.add(1700000000000, "BTCUSDT", "SELL", 1.0, 60000.0, 60000.0, 1700000000)
    assert len(b) == 1
    rows = b.drain()
    assert len(b) == 0  # drenou
    # formato esperado pelo store: (symbol, event_ts, side, qty, price, notional, collected_at)
    assert rows[0][0] == "BTCUSDT"
    assert rows[0][1] == 1700000000000
    assert rows[0][2] == "SELL"


def test_buffer_drain_empty():
    assert lc.LiquidationBuffer().drain() == []


def test_default_symbols_has_14():
    assert len(lc._DEFAULT_SYMBOLS) == 14
    assert "BTCUSDT" in lc._DEFAULT_SYMBOLS and "ETHUSDT" in lc._DEFAULT_SYMBOLS


def test_symbols_env_override(monkeypatch):
    monkeypatch.setenv("LIQUIDATION_SYMBOLS", "btcusdt, solusdt")
    assert lc._symbols() == ["BTCUSDT", "SOLUSDT"]


def test_source_is_bybit():
    assert lc.SOURCE == "bybit"


def test_feed_to_buffer_to_store_integration():
    """Caminho real sem WebSocket: bybit feed -> sink -> buffer -> store, com source."""
    b = lc.LiquidationBuffer()
    feed.set_event_sink(lambda ems, s, sd, q, p, n: b.add(ems, s, sd, q, p, n, 1700000000))
    try:
        msg = json.dumps({"topic": "allLiquidation.BTCUSDT", "type": "snapshot",
                          "ts": 1700000000000,
                          "data": [{"T": 1700000000000, "s": "BTCUSDT",
                                    "S": "Sell", "v": "1.0", "p": "60000"}]}).encode()
        feed._process_message(msg)
    finally:
        feed.set_event_sink(None)

    conn = sqlite3.connect(":memory:")
    ls.ensure_schema(conn)
    n = ls.insert_liquidations(conn, b.drain(), source=lc.SOURCE)
    assert n == 1
    row = conn.execute("SELECT source, symbol, side, notional FROM k_liquidations").fetchone()
    assert row == ("bybit", "BTCUSDT", "SELL", 60000.0)
