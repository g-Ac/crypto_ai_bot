import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import market_read as mr                              # FALHA aqui ate o modulo existir (RED)
from liquidation_store import SCHEMA as LIQ_SCHEMA    # cria k_liquidations
from k_collector import SCHEMA as K_SCHEMA            # cria k_ratios/k_prices/k_funding/k_oi/k_basis

NOW_S = 1_780_000_000          # ancora epoch s para os testes
NOW_MS = NOW_S * 1000
HOUR = 3600

# Vocabulario de SINAL proibido no output (guarda anti-drift): leitura NAO recomenda acao.
FORBIDDEN_SIGNAL_WORDS = (
    "compre", "comprar", "venda", "vender", "sinal",
    "entrada", "alvo", "stop", "longar", "shortar",
)


def assert_no_signal_language(msg: str):
    low = msg.lower()
    for w in FORBIDDEN_SIGNAL_WORDS:
        assert w not in low, f"output contem linguagem de sinal proibida: {w!r}"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(K_SCHEMA)
    c.executescript(LIQ_SCHEMA)
    yield c
    c.close()


def add_price(conn, symbol="BTCUSDT", bucket_ts=NOW_S, open_=100.0, close=100.0,
              high=None, low=None, volume=1000.0, taker_buy_base=500.0):
    high = high if high is not None else max(open_, close)
    low = low if low is not None else min(open_, close)
    conn.execute(
        "INSERT INTO k_prices (symbol,bucket_ts,open_price,close_price,high_price,low_price,"
        "volume,taker_buy_base,taker_buy_quote,collected_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (symbol, bucket_ts, open_, close, high, low, volume, taker_buy_base,
         taker_buy_base * close, NOW_S),
    )
    conn.commit()


def add_liq(conn, symbol="BTCUSDT", event_ts=NOW_MS, side="SELL", qty=1.0, price=100.0):
    conn.execute(
        "INSERT INTO k_liquidations (source,symbol,event_ts,side,qty,price,notional,collected_at)"
        " VALUES ('bybit',?,?,?,?,?,?,?)",
        (symbol, event_ts, side, qty, price, qty * price, NOW_S),
    )
    conn.commit()


def add_ratio(conn, symbol="BTCUSDT", bucket_ts=NOW_S, source="global_account", lsr=1.5):
    conn.execute(
        "INSERT INTO k_ratios (symbol,bucket_ts,source,long_short_ratio,long_account,"
        "short_account,collected_at) VALUES (?,?,?,?,?,?,?)",
        (symbol, bucket_ts, source, lsr, 0.6, 0.4, NOW_S),
    )
    conn.commit()


def add_funding(conn, symbol="BTCUSDT", funding_time=NOW_S, rate=0.0001):
    conn.execute(
        "INSERT INTO k_funding_rates (symbol,funding_time,funding_rate,mark_price,collected_at)"
        " VALUES (?,?,?,?,?)",
        (symbol, funding_time, rate, 100.0, NOW_S),
    )
    conn.commit()


def add_basis(conn, symbol="BTCUSDT", bucket_ts=NOW_S, basis_rate=0.0005):
    conn.execute(
        "INSERT INTO k_basis (symbol,bucket_ts,basis,basis_rate,index_price,futures_price,collected_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (symbol, bucket_ts, 1.0, basis_rate, 100.0, 100.5, NOW_S),
    )
    conn.commit()


def add_oi(conn, symbol="BTCUSDT", bucket_ts=NOW_S, oi=1000.0):
    conn.execute(
        "INSERT INTO k_open_interest (symbol,bucket_ts,sum_open_interest,"
        "sum_open_interest_value,collected_at) VALUES (?,?,?,?,?)",
        (symbol, bucket_ts, oi, oi * 100.0, NOW_S),
    )
    conn.commit()


def test_all_symbols_derives_from_db(conn):
    add_price(conn, "BTCUSDT")
    add_price(conn, "ETHUSDT")
    assert mr.all_symbols(conn) == ["BTCUSDT", "ETHUSDT"]


# ---- Task 2: read_pressure ----

def test_read_pressure_maps_side_correctly(conn):
    # BUY = long liquidado, SELL = short liquidado
    add_liq(conn, "BTCUSDT", NOW_MS, side="SELL", qty=3.0, price=100.0)   # 300 short
    add_liq(conn, "BTCUSDT", NOW_MS, side="BUY", qty=1.0, price=100.0)    # 100 long
    out = mr.read_pressure(conn, hours=24)
    assert len(out) == 1
    row = out[0]
    assert row["symbol"] == "BTCUSDT"
    assert row["longs_liq_usd"] == pytest.approx(100.0)
    assert row["shorts_liq_usd"] == pytest.approx(300.0)
    assert row["total_usd"] == pytest.approx(400.0)
    assert row["events"] == 2
    assert row["dominant_side"] == "SHORT"   # shorts liquidados dominam -> squeeze


def test_read_pressure_window_excludes_old(conn):
    add_liq(conn, "BTCUSDT", NOW_MS, side="SELL", qty=1.0, price=100.0)
    add_liq(conn, "BTCUSDT", NOW_MS - 25 * HOUR * 1000, side="BUY", qty=9.0, price=100.0)
    out = mr.read_pressure(conn, hours=24)
    assert out[0]["events"] == 1
    assert out[0]["longs_liq_usd"] == 0.0


def test_read_pressure_sorted_by_total_desc(conn):
    add_liq(conn, "BTCUSDT", NOW_MS, side="SELL", qty=1.0, price=100.0)   # 100
    add_liq(conn, "ETHUSDT", NOW_MS, side="SELL", qty=5.0, price=100.0)   # 500
    out = mr.read_pressure(conn, hours=24)
    assert [r["symbol"] for r in out] == ["ETHUSDT", "BTCUSDT"]


def test_read_pressure_empty_returns_empty_list(conn):
    assert mr.read_pressure(conn, hours=24) == []


# ---- Task 3: ret_pct, read_returns, read_breadth ----

def test_ret_pct_basic(conn):
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S - 24 * HOUR, open_=100, close=100.0)
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S, open_=110, close=110.0)
    assert mr.ret_pct(conn, "BTCUSDT", 24) == pytest.approx(10.0)


def test_ret_pct_robust_to_gap(conn):
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S - 26 * HOUR, open_=100, close=100.0)
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S, open_=120, close=120.0)
    assert mr.ret_pct(conn, "BTCUSDT", 24) == pytest.approx(20.0)


def test_ret_pct_insufficient_history_none(conn):
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S, open_=100, close=100.0)
    assert mr.ret_pct(conn, "BTCUSDT", 24) is None


def test_read_returns_maps_symbols(conn):
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S - 24 * HOUR, close=100.0)
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S, close=105.0)
    out = mr.read_returns(conn, ["BTCUSDT", "ETHUSDT"], 24)
    assert out["BTCUSDT"] == pytest.approx(5.0)
    assert out["ETHUSDT"] is None


def test_read_breadth_counts_up(conn):
    for sym, c0, c1 in [("BTCUSDT", 100, 110), ("ETHUSDT", 100, 90), ("SOLUSDT", 100, 101)]:
        add_price(conn, sym, bucket_ts=NOW_S - 24 * HOUR, close=float(c0))
        add_price(conn, sym, bucket_ts=NOW_S, close=float(c1))
    b = mr.read_breadth(conn, 24)
    assert b == {"up": 2, "total": 3, "pct_up": pytest.approx(2 / 3 * 100)}


# ---- Task 4: read_volatility, read_taker_ratio ----

def test_read_volatility_avg_range(conn):
    # duas velas: range 10% e 20% sobre open=100 -> media 15%
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S, open_=100, close=105, high=110, low=100)
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S - HOUR, open_=100, close=95, high=110, low=90)
    assert mr.read_volatility(conn, "BTCUSDT", 24) == pytest.approx(15.0)


def test_read_volatility_none_when_empty(conn):
    assert mr.read_volatility(conn, "BTCUSDT", 24) is None


def test_read_taker_ratio(conn):
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S, volume=1000, taker_buy_base=700)
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S - HOUR, volume=1000, taker_buy_base=500)
    assert mr.read_taker_ratio(conn, "BTCUSDT", 24) == pytest.approx(60.0)


def test_read_taker_ratio_none_when_empty(conn):
    assert mr.read_taker_ratio(conn, "BTCUSDT", 24) is None


# ---- Task 5: read_lsr, read_funding, read_basis, read_oi_change ----

def test_read_lsr_separates_sources(conn):
    add_ratio(conn, "BTCUSDT", NOW_S, source="global_account", lsr=1.8)
    add_ratio(conn, "BTCUSDT", NOW_S, source="top_position", lsr=1.2)
    add_ratio(conn, "BTCUSDT", NOW_S - HOUR, source="global_account", lsr=9.9)  # antigo, ignorar
    out = mr.read_lsr(conn, "BTCUSDT")
    assert out == {"global": pytest.approx(1.8), "top": pytest.approx(1.2)}


def test_read_lsr_empty(conn):
    assert mr.read_lsr(conn, "BTCUSDT") == {"global": None, "top": None}


def test_read_funding_latest(conn):
    add_funding(conn, "BTCUSDT", NOW_S, rate=0.0001)
    add_funding(conn, "BTCUSDT", NOW_S - 8 * HOUR, rate=0.0009)
    out = mr.read_funding(conn, "BTCUSDT")
    assert out["funding_rate"] == pytest.approx(0.0001)
    assert out["funding_time"] == NOW_S


def test_read_basis_latest(conn):
    add_basis(conn, "BTCUSDT", NOW_S, basis_rate=0.0005)
    assert mr.read_basis(conn, "BTCUSDT")["basis_rate"] == pytest.approx(0.0005)


def test_read_oi_change(conn):
    add_oi(conn, "BTCUSDT", bucket_ts=NOW_S - 24 * HOUR, oi=1000.0)
    add_oi(conn, "BTCUSDT", bucket_ts=NOW_S, oi=1100.0)
    assert mr.read_oi_change(conn, "BTCUSDT", 24) == pytest.approx(10.0)


def test_read_oi_change_none_insufficient(conn):
    add_oi(conn, "BTCUSDT", bucket_ts=NOW_S, oi=1000.0)
    assert mr.read_oi_change(conn, "BTCUSDT", 24) is None


# ---- Task 6: read_regime ----

def test_read_regime_assembles_components(conn):
    for sym in mr.MAJORS:
        add_price(conn, sym, bucket_ts=NOW_S - 24 * HOUR, close=100.0)
        add_price(conn, sym, bucket_ts=NOW_S, close=105.0, volume=1000, taker_buy_base=600)
        add_funding(conn, sym, NOW_S, rate=0.0001)
    add_ratio(conn, "BTCUSDT", NOW_S, source="global_account", lsr=1.7)
    add_ratio(conn, "BTCUSDT", NOW_S, source="top_position", lsr=1.2)
    add_basis(conn, "BTCUSDT", NOW_S, basis_rate=0.0005)
    add_oi(conn, "BTCUSDT", bucket_ts=NOW_S - 24 * HOUR, oi=1000.0)
    add_oi(conn, "BTCUSDT", bucket_ts=NOW_S, oi=1050.0)

    r = mr.read_regime(conn)
    assert r["returns_24h"]["BTCUSDT"] == pytest.approx(5.0)
    assert set(r["returns_24h"]) == set(mr.MAJORS)
    assert r["breadth_24h"]["up"] == 3
    assert r["taker_btc"] == pytest.approx(60.0)
    assert r["lsr_btc"]["global"] == pytest.approx(1.7)
    assert r["funding"]["BTCUSDT"]["funding_rate"] == pytest.approx(0.0001)
    assert r["basis_btc"]["basis_rate"] == pytest.approx(0.0005)
    assert r["oi_change_btc"] == pytest.approx(5.0)


def test_read_regime_handles_empty_db(conn):
    r = mr.read_regime(conn)
    assert r["returns_24h"] == {s: None for s in mr.MAJORS}
    assert r["breadth_24h"] == {"up": 0, "total": 0, "pct_up": None}
    assert r["oi_change_btc"] is None


# ---- Task 7: read_symbol ----

def test_read_symbol_aggregates(conn):
    add_price(conn, "ETHUSDT", bucket_ts=NOW_S - 24 * HOUR, close=100.0)
    add_price(conn, "ETHUSDT", bucket_ts=NOW_S, close=108.0, volume=1000, taker_buy_base=550)
    add_funding(conn, "ETHUSDT", NOW_S, rate=0.0002)
    add_liq(conn, "ETHUSDT", NOW_MS, side="SELL", qty=2.0, price=100.0)  # short liq

    d = mr.read_symbol(conn, "ethusdt")  # case-insensitive
    assert d["symbol"] == "ETHUSDT"
    assert d["ret_24h"] == pytest.approx(8.0)
    assert d["funding"]["funding_rate"] == pytest.approx(0.0002)
    assert d["taker_24h"] == pytest.approx(55.0)
    assert d["pressure"]["dominant_side"] == "SHORT"
    assert d["pressure"]["shorts_liq_usd"] == pytest.approx(200.0)


def test_read_symbol_no_liquidations(conn):
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S, close=100.0)
    d = mr.read_symbol(conn, "BTCUSDT")
    assert d["pressure"] == {}


# ---- Task 8: formatacao macro ----

def test_fmt_helpers():
    assert mr._fmt_usd(1_500_000) == "$1.50M"
    assert mr._fmt_usd(2400) == "$2k"
    assert mr._fmt_usd(None) == "n/d"
    assert mr._fmt_pct(3.5) == "+3.50%"
    assert mr._fmt_pct(None) == "n/d"


def test_pressure_label_long_is_cascade_down():
    p = {"dominant_side": "LONG", "longs_liq_usd": 80.0, "shorts_liq_usd": 20.0, "total_usd": 100.0}
    label = mr._pressure_label(p)
    assert "long" in label.lower()
    assert "↓" in label  # cascata para baixo


def test_pressure_label_short_is_squeeze_up():
    p = {"dominant_side": "SHORT", "longs_liq_usd": 20.0, "shorts_liq_usd": 80.0, "total_usd": 100.0}
    label = mr._pressure_label(p)
    assert "short" in label.lower()
    assert "↑" in label  # squeeze para cima


def test_format_macro_contains_components(conn):
    for sym in mr.MAJORS:
        add_price(conn, sym, bucket_ts=NOW_S - 24 * HOUR, close=100.0)
        add_price(conn, sym, bucket_ts=NOW_S, close=104.0)
    add_liq(conn, "BTCUSDT", NOW_MS, side="SELL", qty=10.0, price=100.0)
    msg = mr.format_macro(mr.read_regime(conn), mr.read_pressure(conn))
    assert "Mercado" in msg
    assert "BTC" in msg
    assert "+4.00%" in msg
    assert "<b>" in msg and "</b>" in msg
    assert len(msg) < 4096            # cabe numa mensagem do Telegram
    assert_no_signal_language(msg)    # guarda anti-drift


def test_format_macro_empty_db_is_graceful(conn):
    msg = mr.format_macro(mr.read_regime(conn), mr.read_pressure(conn))
    assert "n/d" in msg
    assert len(msg) < 4096
    assert_no_signal_language(msg)


# ---- Task 9: format_symbol ----

def test_format_symbol_contains_fields(conn):
    add_price(conn, "ETHUSDT", bucket_ts=NOW_S - 24 * HOUR, close=100.0)
    add_price(conn, "ETHUSDT", bucket_ts=NOW_S, close=106.0)
    add_funding(conn, "ETHUSDT", NOW_S, rate=0.0002)
    add_liq(conn, "ETHUSDT", NOW_MS, side="BUY", qty=3.0, price=100.0)  # longs liquidados

    msg = mr.format_symbol(mr.read_symbol(conn, "ETHUSDT"))
    assert "ETH" in msg
    assert "+6.00%" in msg
    assert "long" in msg.lower()        # rotulo de pressao correto (BUY=long)
    assert "<b>" in msg
    assert len(msg) < 4096
    assert_no_signal_language(msg)


def test_format_symbol_no_pressure(conn):
    add_price(conn, "BTCUSDT", bucket_ts=NOW_S, close=100.0)
    msg = mr.format_symbol(mr.read_symbol(conn, "BTCUSDT"))
    assert "BTC" in msg
    assert len(msg) < 4096
    assert_no_signal_language(msg)
