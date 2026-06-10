import json as _json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import raiox_data as rx


def test_to_epoch_s_iso_with_tz():
    assert rx._to_epoch_s("2026-06-08T17:07:43+00:00") == 1780938463


def test_to_epoch_s_naive_space_format():
    assert rx._to_epoch_s("2026-06-08 18:00:00") == 1780941600


def test_to_epoch_s_iso_with_microseconds():
    assert rx._to_epoch_s("2026-06-08T17:07:43.797916+00:00") == 1780938463


def test_to_epoch_s_nonzero_offset():
    assert rx._to_epoch_s("2026-06-08T14:07:43-03:00") == 1780938463


def _write_state(positions: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        _json.dump({"positions": positions, "capital": 1000.0}, f)
    return path


def test_open_position_present():
    path = _write_state({"ETHUSDT": {
        "entry_price": 1691.45, "sl_price": 1676.55, "tp1_price": 1706.22,
        "tp2_price": 1713.8, "direction": "LONG", "open_time": "2026-06-08 18:00:00",
        "candles_elapsed": 9, "regime": "TRENDING", "position_size_usd": 1096.25,
        "mfe_pct": 0.06, "mae_pct": -0.75,
    }})
    try:
        p = rx.open_position(path)
        assert p["symbol"] == "ETHUSDT"
        assert p["direction"] == "LONG"
        assert p["entry_price"] == 1691.45
        assert p["open_time_s"] == rx._to_epoch_s("2026-06-08 18:00:00")
        assert p["sl_price"] == 1676.55 and p["tp1_price"] == 1706.22
        assert p["position_size_usd"] == 1096.25
    finally:
        os.unlink(path)


def test_open_position_none_when_empty():
    path = _write_state({})
    try:
        assert rx.open_position(path) is None
    finally:
        os.unlink(path)


def test_open_position_none_when_file_missing():
    assert rx.open_position("/tmp/nao_existe_raiox.json") is None


_TRADES_DDL = """
CREATE TABLE momentum_trades (
  id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT, direction TEXT, regime TEXT,
  entry_price REAL, exit_price REAL, sl_price REAL, tp1_price REAL, tp2_price REAL,
  exit_reason TEXT, duration_candles INTEGER, mfe_pct REAL, mae_pct REAL,
  pnl_pct REAL, net_pnl_pct REAL
);
"""


@pytest.fixture
def trades_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_TRADES_DDL)
    yield conn
    conn.close()


def _ins(conn, **k):
    cols = ",".join(k)
    ph = ",".join("?" * len(k))
    conn.execute(f"INSERT INTO momentum_trades ({cols}) VALUES ({ph})", tuple(k.values()))
    conn.commit()


def test_pnl_of_prefers_net():
    assert rx._pnl_of({"net_pnl_pct": -0.88, "pnl_pct": -0.78}) == (-0.88, "net_pnl_pct")
    assert rx._pnl_of({"net_pnl_pct": None, "pnl_pct": 0.5}) == (0.5, "pnl_pct")


def test_classify_result_win_loss_fee_ate():
    assert rx._classify_result(0.49, 0.59) == "win"      # net > 0
    assert rx._classify_result(-0.88, -0.78) == "loss"   # net <= 0, bruto <= 0
    assert rx._classify_result(-0.05, 0.05) == "fee_ate" # bruto > 0, net <= 0


def test_classify_result_bordas_zero():
    assert rx._classify_result(0.0, 0.10) == "fee_ate"   # net == 0 com bruto positivo: fee comeu
    assert rx._classify_result(0.0, 0.0) == "loss"       # tudo zero: loss
    assert rx._classify_result(0.01, 0.0) == "win"       # net positivo manda, mesmo bruto zero


def test_exit_icon():
    assert rx._exit_icon("tp1_hit") == "🟢"
    assert rx._exit_icon("sl_hit") == "🔴"
    assert rx._exit_icon("timeout") == "⏱️"


def test_list_trades_closed_sorted_desc_with_pnl_source(trades_conn):
    _ins(trades_conn, id=1, timestamp="2026-06-08T15:04:30+00:00", symbol="ETHUSDT",
         direction="LONG", exit_reason="tp1_hit", net_pnl_pct=0.92, pnl_pct=1.0)
    _ins(trades_conn, id=2, timestamp="2026-06-08T17:07:43+00:00", symbol="ETHUSDT",
         direction="LONG", exit_reason="sl_hit", net_pnl_pct=-0.88, pnl_pct=-0.78)
    path = _write_state({})
    try:
        out = rx.list_trades(trades_conn, path)
        assert out["open"] is None
        assert [t["id"] for t in out["closed"]] == [2, 1]
        assert out["closed"][0]["pnl_pct"] == -0.88
        assert out["closed"][0]["pnl_source"] == "net_pnl_pct"
        assert out["closed"][0]["exit_icon"] == "🔴"
    finally:
        os.unlink(path)


def test_list_trades_includes_open(trades_conn):
    path = _write_state({"ETHUSDT": {"entry_price": 1691.45, "direction": "LONG",
                                     "open_time": "2026-06-08 18:00:00", "sl_price": 1676.55,
                                     "tp1_price": 1706.22, "tp2_price": 1713.8}})
    try:
        out = rx.list_trades(trades_conn, path)
        assert out["open"]["symbol"] == "ETHUSDT"
    finally:
        os.unlink(path)


def test_trade_detail_estimates_entry_time(trades_conn):
    _ins(trades_conn, id=5, timestamp="2026-06-08T17:07:43+00:00", symbol="ETHUSDT",
         direction="LONG", regime="TRENDING", entry_price=1691.47, sl_price=1676.55,
         tp1_price=1706.22, tp2_price=1713.85, exit_price=1676.55, exit_reason="sl_hit",
         duration_candles=3, mfe_pct=0.37, mae_pct=-0.93, net_pnl_pct=-0.88, pnl_pct=-0.78)
    d = rx.trade_detail(trades_conn, 5)
    assert d["exit_time_s"] == rx._to_epoch_s("2026-06-08T17:07:43+00:00")
    assert d["entry_time_s"] == d["exit_time_s"] - 3 * 15 * 60
    assert d["entry_time_estimated"] is True
    assert d["pnl_pct"] == -0.88 and d["pnl_source"] == "net_pnl_pct"
    assert d["entry_price"] == 1691.47 and d["sl_price"] == 1676.55


def test_trade_detail_none_when_absent(trades_conn):
    assert rx.trade_detail(trades_conn, 999) is None


def test_trade_summary_is_factual_no_action_words(trades_conn):
    _ins(trades_conn, id=6, timestamp="2026-06-08T17:07:43+00:00", symbol="ETHUSDT",
         direction="LONG", regime="TRENDING", entry_price=1691.47, sl_price=1676.55,
         tp1_price=1706.22, tp2_price=1713.85, exit_price=1676.55, exit_reason="sl_hit",
         duration_candles=3, mfe_pct=0.37, mae_pct=-0.93, net_pnl_pct=-0.88, pnl_pct=-0.78)
    summary = rx.trade_detail(trades_conn, 6)["summary"].lower()
    for w in rx.FORBIDDEN_ACTION_PHRASES:
        assert w not in summary, f"resumo contem frase de acao: {w!r}"
    assert "entrada" in summary or "saida" in summary


def _fake_candles(rows):
    class _DF:
        def __init__(self, data):
            self._d = data
        def to_dict(self, orient):
            return [{"time_s": t, "open": o, "high": h, "low": l, "close": c}
                    for (t, o, h, l, c) in self._d]
    def fn(symbol, interval, limit):
        return _DF(rows[-limit:])
    return fn


def test_fetch_candles_filters_range_15m():
    now = 1780941600
    rows = [(now - i * 900, 100, 101, 99, 100) for i in range(200)][::-1]
    fn = _fake_candles(rows)
    start = now - 10 * 900
    end = now
    out = rx.fetch_candles("ETHUSDT", "15m", start, end, now, get_candles_fn=fn)
    assert out["ok"] is True
    assert out["effective_interval"] == "15m"
    assert all(start - 20 * 900 <= c["time"] <= end + 20 * 900 for c in out["candles"])


def test_fetch_candles_escalates_tf_when_too_old():
    now = 1780941600
    start = now - 60 * 86400
    rows = [(now - i * 14400, 100, 101, 99, 100) for i in range(500)][::-1]
    fn = _fake_candles(rows)
    out = rx.fetch_candles("ETHUSDT", "15m", start, now, now, get_candles_fn=fn)
    assert out["ok"] is True
    assert out["effective_interval"] == "4h"


def test_fetch_candles_error_when_window_absurd():
    now = 1780941600
    start = now - 4000 * 86400
    fn = _fake_candles([(now, 1, 1, 1, 1)])
    out = rx.fetch_candles("ETHUSDT", "15m", start, now, now, get_candles_fn=fn)
    assert out["ok"] is False
    assert out["error"] == "janela_muito_longa"


def test_trades_overlay_filters_symbol_and_classifies(trades_conn):
    _ins(trades_conn, id=1, timestamp="2026-06-01T12:00:00+00:00", symbol="BTCUSDT",
         direction="LONG", entry_price=100000.0, exit_price=101000.0,
         duration_candles=4, pnl_pct=1.0, net_pnl_pct=0.9)        # win
    _ins(trades_conn, id=2, timestamp="2026-06-02T12:00:00+00:00", symbol="BTCUSDT",
         direction="SHORT", entry_price=101000.0, exit_price=102000.0,
         duration_candles=2, pnl_pct=-0.99, net_pnl_pct=-1.09)    # loss
    _ins(trades_conn, id=3, timestamp="2026-06-03T12:00:00+00:00", symbol="BTCUSDT",
         direction="LONG", entry_price=102000.0, exit_price=102050.0,
         duration_candles=8, pnl_pct=0.05, net_pnl_pct=-0.05)     # fee_ate
    _ins(trades_conn, id=4, timestamp="2026-06-04T12:00:00+00:00", symbol="ETHUSDT",
         direction="LONG", entry_price=1700.0, exit_price=1717.0,
         duration_candles=3, pnl_pct=1.0, net_pnl_pct=0.9)        # outro simbolo: fora
    out = rx.trades_overlay(trades_conn, "BTCUSDT")
    assert out["ok"] is True and out["symbol"] == "BTCUSDT"
    assert [t["id"] for t in out["trades"]] == [1, 2, 3]          # ordem temporal crescente
    assert [t["result"] for t in out["trades"]] == ["win", "loss", "fee_ate"]
    t1 = out["trades"][0]
    assert t1["exit_time_s"] == rx._to_epoch_s("2026-06-01T12:00:00+00:00")
    assert t1["entry_time_s"] == t1["exit_time_s"] - 4 * 15 * 60  # estimativa igual a do trade_detail
    assert t1["entry_time_s"] < t1["exit_time_s"]
    assert t1["direction"] == "LONG"
    assert t1["entry_price"] == 100000.0 and t1["exit_price"] == 101000.0
    assert t1["pnl_pct"] == 0.9 and t1["pnl_source"] == "net_pnl_pct"


def test_trades_overlay_empty_when_no_trades(trades_conn):
    out = rx.trades_overlay(trades_conn, "BTCUSDT")
    assert out["ok"] is True and out["symbol"] == "BTCUSDT"
    assert out["trades"] == []


def test_trades_overlay_net_null_classifica_pelo_bruto(trades_conn):
    _ins(trades_conn, id=1, timestamp="2026-06-01T12:00:00+00:00", symbol="BTCUSDT",
         direction="LONG", entry_price=100.0, exit_price=101.0,
         duration_candles=1, pnl_pct=1.0, net_pnl_pct=None)
    t = rx.trades_overlay(trades_conn, "BTCUSDT")["trades"][0]
    assert t["result"] == "win"            # sem net nao existe "fee_ate": classifica pelo bruto
    assert t["pnl_pct"] == 1.0 and t["pnl_source"] == "pnl_pct"


def test_trades_overlay_factual_no_action_words(trades_conn):
    _ins(trades_conn, id=1, timestamp="2026-06-01T12:00:00+00:00", symbol="BTCUSDT",
         direction="LONG", entry_price=100.0, exit_price=101.0,
         duration_candles=1, pnl_pct=1.0, net_pnl_pct=0.9)
    blob = _json.dumps(rx.trades_overlay(trades_conn, "BTCUSDT"), ensure_ascii=False).lower()
    for w in rx.FORBIDDEN_ACTION_PHRASES:
        assert w not in blob, f"overlay contem frase de acao: {w!r}"
