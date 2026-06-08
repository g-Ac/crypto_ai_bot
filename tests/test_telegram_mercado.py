import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from liquidation_store import SCHEMA as LIQ_SCHEMA
from k_collector import SCHEMA as K_SCHEMA

NOW_S = 1_780_000_000
NOW_MS = NOW_S * 1000
HOUR = 3600


@pytest.fixture
def market_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(K_SCHEMA)
    conn.executescript(LIQ_SCHEMA)
    # BTC sobe 5% em 24h + 1 liquidacao de short
    conn.execute("INSERT INTO k_prices (symbol,bucket_ts,open_price,close_price,high_price,"
                 "low_price,volume,taker_buy_base,taker_buy_quote,collected_at) "
                 "VALUES ('BTCUSDT',?,100,100,100,100,1000,600,60000,?)",
                 (NOW_S - 24 * HOUR, NOW_S))
    conn.execute("INSERT INTO k_prices (symbol,bucket_ts,open_price,close_price,high_price,"
                 "low_price,volume,taker_buy_base,taker_buy_quote,collected_at) "
                 "VALUES ('BTCUSDT',?,100,105,106,99,1000,600,63000,?)", (NOW_S, NOW_S))
    conn.execute("INSERT INTO k_liquidations (source,symbol,event_ts,side,qty,price,notional,"
                 "collected_at) VALUES ('bybit','BTCUSDT',?,'SELL',5,100,500,?)", (NOW_MS, NOW_S))
    conn.commit()
    conn.close()
    monkeypatch.setattr("database.DB_FILE", path)
    yield path
    os.unlink(path)


def test_cmd_mercado_macro(market_db):
    from telegram_commands import _cmd_mercado
    msg = _cmd_mercado("")
    assert "Leitura de Mercado" in msg
    assert "BTC" in msg
    assert "+5.00%" in msg


def test_cmd_mercado_symbol_zoom(market_db):
    from telegram_commands import _cmd_mercado
    msg = _cmd_mercado("btcusdt")          # case-insensitive
    assert "BTC" in msg
    assert "Pressao" in msg


def test_cmd_mercado_unknown_symbol(market_db):
    from telegram_commands import _cmd_mercado
    msg = _cmd_mercado("FOOBAR")
    assert "FOOBAR" in msg
    assert "Disponiveis" in msg           # mensagem amigavel
    assert "BTC" in msg                   # lista os coletados


def test_handle_command_routes_mercado_with_arg(market_db):
    import telegram_commands as tc
    out = tc._handle_command("/mercado BTCUSDT")
    assert out is not None and "BTC" in out


def test_handle_command_legacy_handlers_still_work(monkeypatch):
    import telegram_commands as tc
    monkeypatch.setitem(tc._HANDLERS, "/ping_test", lambda: "pong")
    assert tc._handle_command("/ping_test") == "pong"
