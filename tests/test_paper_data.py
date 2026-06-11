"""Testes do paper_data (diario paper manual — Fatia 4a).
Conn sqlite tempfile com schema k_* (pro carimbo) + paper_manual_trades."""
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from k_collector import SCHEMA as K_SCHEMA
from liquidation_store import SCHEMA as LIQ_SCHEMA
from tests.test_market_read import HOUR, NOW_S, add_funding, add_liq, add_price

import paper_data


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(K_SCHEMA)
    c.executescript(LIQ_SCHEMA)
    paper_data.ensure_schema(c)
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        add_price(c, sym, bucket_ts=NOW_S - 24 * HOUR, close=100.0)
        add_price(c, sym, bucket_ts=NOW_S, close=104.0, volume=1000, taker_buy_base=600)
        add_funding(c, sym, NOW_S, rate=0.0001)
    add_liq(c, "ETHUSDT", NOW_S * 1000, side="SELL", qty=8.0, price=100.0)
    c.commit()
    return c


def fake_candles_fn(close=2500.0, open_=2495.0, high=2510.0, low=2490.0, n=3):
    """get_candles_fn fake: DataFrame no formato do market.get_candles.
    Ultimo candle FECHADO termina exatamente em NOW_S (open NOW_S-900)."""
    def fn(symbol, interval, limit):
        rows = []
        for i in range(n):
            open_time_s = NOW_S - (n - i) * 900
            rows.append({"time": pd.Timestamp(open_time_s, unit="s"),
                         "open": open_, "high": high, "low": low,
                         "close": close, "volume": 10.0})
        return pd.DataFrame(rows)
    return fn


FORM_OK = {"symbol": "ETHUSDT", "direction": "long", "entry_price": "2500",
           "stop_price": "2450", "target_price": "2600",
           "thesis": "pullback segurou na media", "tags": "Pullback, zona-liq"}


def test_create_trade_ok_grava_carimbo_e_normaliza_tags(conn):
    res = paper_data.create_trade(conn, fake_candles_fn(), NOW_S, dict(FORM_OK))
    assert res["ok"] is True
    row = conn.execute("SELECT * FROM paper_manual_trades WHERE id=?",
                       (res["trade_id"],)).fetchone()
    assert row["status"] == "open"
    assert row["created_at"] == NOW_S
    assert row["tags"] == "pullback,zona-liq"
    assert row["mfe_price"] == row["entry_price"] == 2500.0
    snap = json.loads(row["context_snapshot"])
    assert snap["schema_version"] == 1
    assert snap["symbol"]["symbol"] == "ETHUSDT"
    assert snap["regime"] is not None
    assert snap["freshness"] is not None


def test_create_trade_short_niveis_invertidos(conn):
    form = dict(FORM_OK, direction="short", stop_price="2550", target_price="2400")
    res = paper_data.create_trade(conn, fake_candles_fn(), NOW_S, form)
    assert res["ok"] is True


@pytest.mark.parametrize("patch,erro", [
    ({"symbol": "FOOUSDT"}, "simbolo"),
    ({"thesis": "   "}, "tese"),
    ({"stop_price": "2520"}, "stop"),            # long: stop >= entry
    ({"target_price": "2480"}, "alvo"),          # long: target <= entry
    ({"entry_price": "2700"}, "preco atual"),    # fora da tolerancia +-0,5% de 2500
    ({"entry_price": "abc"}, "numero"),
    ({"target_price": "inf"}, "numero"),
    ({"stop_price": "nan"}, "numero"),
    ({"target_price": "1e999"}, "numero"),
    ({"entry_price": "0"}, "numero"),
    ({"entry_price": "-5"}, "numero"),
])
def test_create_trade_validacoes(conn, patch, erro):
    res = paper_data.create_trade(conn, fake_candles_fn(), NOW_S, dict(FORM_OK, **patch))
    assert res["ok"] is False
    assert any(erro in e for e in res["errors"])
    assert conn.execute("SELECT COUNT(*) FROM paper_manual_trades").fetchone()[0] == 0


def test_create_trade_short_validacao_invertida(conn):
    form = dict(FORM_OK, direction="short", stop_price="2400", target_price="2550")
    res = paper_data.create_trade(conn, fake_candles_fn(), NOW_S, form)
    assert res["ok"] is False


def test_create_trade_preco_indisponivel_bloqueia(conn):
    def broken(symbol, interval, limit):
        return None
    res = paper_data.create_trade(conn, broken, NOW_S, dict(FORM_OK))
    assert res["ok"] is False
    assert any("preco" in e for e in res["errors"])


def test_create_trade_carimbo_falho_nao_bloqueia(conn, monkeypatch):
    import market_read
    monkeypatch.setattr(market_read, "read_regime",
                        lambda c: (_ for _ in ()).throw(RuntimeError("boom")))
    res = paper_data.create_trade(conn, fake_candles_fn(), NOW_S, dict(FORM_OK))
    assert res["ok"] is True
    snap = json.loads(conn.execute(
        "SELECT context_snapshot FROM paper_manual_trades WHERE id=?",
        (res["trade_id"],)).fetchone()[0])
    assert snap["regime"] is None
    assert snap["symbol"] is not None


# ---------------------------------------------------------------------------
# Task 2 — void, fechamento manual e listagem
# ---------------------------------------------------------------------------

def _mk_trade(conn, now_s=NOW_S, **kw):
    form = dict(FORM_OK, **{k: str(v) for k, v in kw.items()})
    res = paper_data.create_trade(conn, fake_candles_fn(), now_s, form)
    assert res["ok"], res
    return res["trade_id"]


def test_void_dentro_da_janela(conn):
    tid = _mk_trade(conn)
    res = paper_data.void_trade(conn, NOW_S + 599, tid, "digitei errado")
    assert res["ok"] is True
    row = conn.execute("SELECT status, void_reason FROM paper_manual_trades WHERE id=?",
                       (tid,)).fetchone()
    assert row["status"] == "void" and row["void_reason"] == "digitei errado"


def test_void_fora_da_janela_recusa(conn):
    tid = _mk_trade(conn)
    res = paper_data.void_trade(conn, NOW_S + 601, tid, "tarde demais")
    assert res["ok"] is False
    assert conn.execute("SELECT status FROM paper_manual_trades WHERE id=?",
                        (tid,)).fetchone()["status"] == "open"


def test_void_trade_inexistente_ou_fechado(conn):
    assert paper_data.void_trade(conn, NOW_S, 999, "x")["ok"] is False
    tid = _mk_trade(conn)
    paper_data.close_manual(conn, fake_candles_fn(close=2520.0), NOW_S + 100, tid)
    assert paper_data.void_trade(conn, NOW_S + 200, tid, "x")["ok"] is False


def test_close_manual_usa_ultimo_close_e_aplica_net(conn):
    tid = _mk_trade(conn)
    res = paper_data.close_manual(conn, fake_candles_fn(close=2550.0), NOW_S + 3600, tid)
    assert res["ok"] is True
    row = conn.execute("SELECT * FROM paper_manual_trades WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "closed" and row["exit_reason"] == "manual"
    assert row["exit_price"] == 2550.0 and row["exit_ts"] == NOW_S + 3600


def test_close_manual_preco_indisponivel_mantem_aberto(conn):
    tid = _mk_trade(conn)
    res = paper_data.close_manual(conn, lambda *a: None, NOW_S + 100, tid)
    assert res["ok"] is False
    assert conn.execute("SELECT status FROM paper_manual_trades WHERE id=?",
                        (tid,)).fetchone()["status"] == "open"


def test_list_trades_abertos_e_fechados(conn):
    t1 = _mk_trade(conn)
    t2 = _mk_trade(conn, symbol="BTCUSDT", entry_price=2500, stop_price=2450,
                   target_price=2600)
    paper_data.close_manual(conn, fake_candles_fn(close=2550.0), NOW_S + 3600, t2)
    out = paper_data.list_trades(conn, NOW_S + 700)
    assert [t["id"] for t in out["abertos"]] == [t1]
    aberto = out["abertos"][0]
    assert aberto["can_void"] is False and aberto["idade_min"] >= 11
    assert aberto["checked_min_ago"] is None  # nunca checado pelo tracker
    fechado = out["fechados"][0]
    assert fechado["id"] == t2
    assert fechado["pnl_gross_pct"] == pytest.approx(2.0)
    assert fechado["pnl_net_pct"] == pytest.approx(1.8)


def test_pnl_short(conn):
    assert paper_data.pnl_gross_pct("short", 2500.0, 2400.0) == pytest.approx(4.0)
    assert paper_data.pnl_gross_pct("long", 2500.0, 2400.0) == pytest.approx(-4.0)


# ---------------------------------------------------------------------------
# Task 4 — registro_view
# ---------------------------------------------------------------------------

def test_registro_view_monta_condicoes_e_listas(conn):
    _mk_trade(conn)
    view = paper_data.registro_view(conn, NOW_S + 60, "ETHUSDT")
    assert view["symbol"] == "ETHUSDT"
    assert list(view["symbols"]) == list(paper_data.PAPER_SYMBOLS)
    assert view["condicoes"] is not None        # symbol_view do mercado_data
    assert len(view["abertos"]) == 1
    assert view["read_at"]


def test_registro_view_simbolo_invalido_cai_pra_btc(conn):
    view = paper_data.registro_view(conn, NOW_S, "FOO")
    assert view["symbol"] == "BTCUSDT"


def test_create_trade_1000pepe_rejeitado(conn):
    """1000PEPEUSDT esta excluido de PAPER_SYMBOLS (sem API spot): deve falhar."""
    form = dict(FORM_OK, symbol="1000PEPEUSDT")
    res = paper_data.create_trade(conn, fake_candles_fn(), NOW_S, form)
    assert res["ok"] is False
    assert any("simbolo" in e for e in res["errors"])


def test_registro_view_1000pepe_cai_pra_btc(conn):
    """?symbol=1000PEPE deve cair para BTCUSDT pois nao esta em PAPER_SYMBOLS."""
    view = paper_data.registro_view(conn, NOW_S, "1000PEPEUSDT")
    assert view["symbol"] == "BTCUSDT"


# ---------------------------------------------------------------------------
# Fix M4 — edge tests
# ---------------------------------------------------------------------------

def fake_candles_fn_open_last(prev_close=2500.0, last_close=9999.0, now_s=NOW_S):
    """Last candle opens at now_s-300, which is NOT closed (open_time+900 > now_s).
    Previous candle is fully closed and has prev_close."""
    def fn(symbol, interval, limit):
        rows = [
            {"time": pd.Timestamp(now_s - 2 * 900, unit="s"),
             "open": 2495.0, "high": 2510.0, "low": 2490.0,
             "close": prev_close, "volume": 10.0},
            {"time": pd.Timestamp(now_s - 900, unit="s"),
             "open": 2495.0, "high": 2510.0, "low": 2490.0,
             "close": prev_close, "volume": 10.0},
            # opens at now_s-300: open_time + 900 = now_s+600 > now_s => still open
            {"time": pd.Timestamp(now_s - 300, unit="s"),
             "open": 9990.0, "high": 9999.0, "low": 9980.0,
             "close": last_close, "volume": 10.0},
        ]
        return pd.DataFrame(rows)
    return fn


def test_last_candle_still_open_uses_previous_close(conn):
    """When last candle is not yet closed, _last_closed_price must use previous."""
    # entry 2500 should be accepted (within tolerance of prev_close=2500)
    res = paper_data.create_trade(
        conn, fake_candles_fn_open_last(prev_close=2500.0, last_close=9999.0),
        NOW_S, dict(FORM_OK))
    assert res["ok"] is True


def test_inclusive_tolerance_edge(conn):
    """entry_price exactly at +0.5% of ref (2512.5) must be accepted."""
    res = paper_data.create_trade(
        conn, fake_candles_fn(), NOW_S,
        dict(FORM_OK, entry_price="2512.5", stop_price="2450", target_price="2600"))
    assert res["ok"] is True
