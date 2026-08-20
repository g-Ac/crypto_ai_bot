"""Testes do mercado_data (views da aba Mercado). Molde do test_market_read."""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import market_read as mr
import mercado_data as md                            # FALHA aqui ate o modulo existir (RED)
from k_collector import SCHEMA as K_SCHEMA, SYMBOLS as K_SYMBOLS
from liquidation_store import SCHEMA as LIQ_SCHEMA
from tests.test_market_read import (
    FORBIDDEN_SIGNAL_WORDS, HOUR, NOW_MS, NOW_S,
    add_basis, add_funding, add_liq, add_oi, add_price, add_ratio,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(K_SCHEMA)
    c.executescript(LIQ_SCHEMA)
    yield c
    c.close()


# ---- Task 1: lista canonica + normalize_symbol ----

def test_supported_symbols_match_k_collector():
    """Paridade canonica: a tupla local DEVE espelhar scripts/k_collector.SYMBOLS."""
    assert md.SUPPORTED_MARKET_SYMBOLS == tuple(K_SYMBOLS)


@pytest.mark.parametrize("raw,expected", [
    ("BTC", "BTCUSDT"),
    ("btcusdt", "BTCUSDT"),
    ("DOGE", "DOGEUSDT"),           # DOGEUSDT esta nos 14 -> valido
    ("1000PEPE", "1000PEPEUSDT"),
    ("  eth  ", "ETHUSDT"),
    ("FOO", None),
    ("PEPE", None),                 # PEPEUSDT nao esta na lista (so 1000PEPEUSDT)
    ("", None),
    (None, None),
])
def test_normalize_symbol(raw, expected):
    assert md.normalize_symbol(raw) == expected


# ---- Task 2: macro_view ----

def _seed_macro(conn):
    """Banco com dados em todas as fontes (majors + liq) na ancora NOW_S."""
    for sym in mr.MAJORS:
        add_price(conn, sym, bucket_ts=NOW_S - 24 * HOUR, close=100.0)
        add_price(conn, sym, bucket_ts=NOW_S, close=104.0, volume=1000, taker_buy_base=600)
        add_funding(conn, sym, NOW_S, rate=0.0001)
    add_ratio(conn, "BTCUSDT", NOW_S, source="global_account", lsr=1.7)
    add_ratio(conn, "BTCUSDT", NOW_S, source="top_position", lsr=1.2)
    add_basis(conn, "BTCUSDT", NOW_S, basis_rate=0.0005)
    add_oi(conn, "BTCUSDT", bucket_ts=NOW_S - 24 * HOUR, oi=1000.0)
    add_oi(conn, "BTCUSDT", bucket_ts=NOW_S, oi=1050.0)
    add_liq(conn, "BTCUSDT", NOW_MS, side="SELL", qty=8.0, price=100.0)   # 800 short liq
    add_liq(conn, "BTCUSDT", NOW_MS, side="BUY", qty=2.0, price=100.0)    # 200 long liq


def test_macro_view_structure(conn):
    _seed_macro(conn)
    v = md.macro_view(conn, NOW_S)

    assert [m["name"] for m in v["majors"]] == ["BTC", "ETH", "SOL"]
    assert v["majors"][0]["symbol"] == "BTCUSDT"
    assert v["majors"][0]["ret_24h"] == {"value": pytest.approx(4.0), "text": "+4.00%"}
    assert v["breadth"] == "3/3"                       # X/Y com Y = total real do banco
    # vela NOW_S: open=100, high=104 (max(open,close)), low=100 -> range 4%;
    # a vela em NOW_S-24h fica FORA (read_volatility filtra bucket_ts > cutoff)
    assert v["vol_btc"] == "4.00%"
    assert v["taker_btc"] == "60.00%"
    assert v["lsr"] == {"global": "1.70", "top": "1.20"}
    assert [f["name"] for f in v["funding"]] == ["BTC", "ETH", "SOL"]
    assert v["funding"][0]["rate"]["text"] == "+0.0100%"
    assert v["basis_btc"]["text"] == "0.0005"
    assert v["oi_btc"] == {"value": pytest.approx(5.0), "text": "+5.00%"}

    assert len(v["pressure"]) == 1
    row = v["pressure"][0]
    assert row["symbol"] == "BTCUSDT" and row["name"] == "BTC"
    assert row["total"] == "$1k"                       # _fmt_usd(1000.0)
    assert row["longs_pct"] == pytest.approx(20.0)
    assert row["shorts_pct"] == pytest.approx(80.0)
    assert row["events"] == 2

    assert v["translation"]                            # tradutor presente com banco populado
    assert v["read_at"] == datetime.fromtimestamp(NOW_S).strftime("%H:%M")
    labels = [s["label"] for s in v["freshness"]["sources"]]
    assert labels == ["preco", "LSR", "OI", "basis", "funding", "liq"]
    assert v["freshness"]["stale_labels"] == []        # tudo recem-coletado na ancora


def test_macro_view_empty_db(conn):
    """Banco vazio -> view completa com n/d, sem excecao (validade e canonica)."""
    v = md.macro_view(conn, NOW_S)
    assert v["breadth"] == "n/d"
    assert v["majors"][0]["ret_24h"] == {"value": None, "text": "n/d"}
    assert v["vol_btc"] == "n/d"
    assert v["lsr"] == {"global": "n/d", "top": "n/d"}
    assert v["funding"][0]["rate"]["text"] == "n/d"
    assert v["pressure"] == []
    assert v["translation"] == []
    assert all(s["stale"] for s in v["freshness"]["sources"])
    assert set(v["freshness"]["stale_labels"]) == {"preco", "LSR", "OI", "basis", "funding", "liq"}


def test_macro_view_pressure_label_identical_to_telegram(conn):
    """Anti-divergencia (ajuste 2): mesmo banco -> rotulo da web aparece LITERAL
    na mensagem do Telegram (format_macro). Web == Telegram."""
    _seed_macro(conn)
    web_label = md.macro_view(conn, NOW_S)["pressure"][0]["label"]
    telegram_msg = mr.format_macro(mr.read_regime(conn), mr.read_pressure(conn))
    assert web_label in telegram_msg


# ---- Task 3: symbol_view + anti-sinal ----

def test_symbol_view_structure(conn):
    add_price(conn, "ETHUSDT", bucket_ts=NOW_S - 24 * HOUR, close=100.0)
    add_price(conn, "ETHUSDT", bucket_ts=NOW_S, close=108.0, volume=1000, taker_buy_base=550)
    add_funding(conn, "ETHUSDT", NOW_S, rate=0.0002)
    add_liq(conn, "ETHUSDT", NOW_MS, side="SELL", qty=2.0, price=100.0)

    v = md.symbol_view(conn, "ETHUSDT", NOW_S)
    assert v["symbol"] == "ETHUSDT" and v["name"] == "ETH"
    assert v["ret_24h"] == {"value": pytest.approx(8.0), "text": "+8.00%"}
    assert v["taker"] == "55.00%"
    assert v["funding"]["text"] == "+0.0200%"
    assert v["pressure"]["shorts_pct"] == pytest.approx(100.0)
    assert v["pressure"]["events"] == 1
    assert v["tem_mapa"] is True
    assert v["translation"]
    assert v["read_at"] == datetime.fromtimestamp(NOW_S).strftime("%H:%M")
    assert [s["label"] for s in v["freshness"]["sources"]] == ["preco", "LSR", "OI", "basis", "funding", "liq"]


def test_symbol_view_sem_liquidacoes_e_sem_mapa(conn):
    add_price(conn, "SOLUSDT", bucket_ts=NOW_S, close=100.0)
    v = md.symbol_view(conn, "SOLUSDT", NOW_S)
    assert v["pressure"] is None
    assert v["tem_mapa"] is False


def test_symbol_view_empty_db(conn):
    v = md.symbol_view(conn, "BTCUSDT", NOW_S)
    assert v["ret_24h"] == {"value": None, "text": "n/d"}
    assert v["lsr"] == {"global": "n/d", "top": "n/d"}
    assert v["funding"]["text"] == "n/d"
    assert v["pressure"] is None
    assert v["translation"] == []


def test_tem_mapa_espelha_mapa_js():
    assert md.MAP_SYMBOLS == ("BTCUSDT", "ETHUSDT")


def _all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _all_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _all_strings(v)


def test_views_sem_linguagem_de_sinal(conn):
    _seed_macro(conn)
    views = (md.macro_view(conn, NOW_S), md.symbol_view(conn, "BTCUSDT", NOW_S))
    for view in views:
        for s in _all_strings(view):
            low = s.lower()
            for w in FORBIDDEN_SIGNAL_WORDS:
                assert w not in low, f"view contem linguagem de sinal proibida: {w!r} em {s!r}"
