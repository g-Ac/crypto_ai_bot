"""Testes das rotas /api/rotulagem/* — guarda o invariante CEGO.

O detalhe do trade (raiox_data.trade_detail) carrega exit_reason/pnl/sl/tp; o
endpoint /next NUNCA pode repassar isso, senao o resultado vaza pro olho e o
experimento morre. Aqui trade_detail e mockado devolvendo TUDO de proposito.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture
def client(monkeypatch):
    fd, dbp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(dbp)
    conn.execute("CREATE TABLE momentum_trades (id INTEGER PRIMARY KEY, timestamp TEXT)")
    conn.execute("INSERT INTO momentum_trades (id, timestamp) VALUES (1, '2026-04-16T08:00:00+00:00')")
    conn.commit()
    conn.close()

    import database
    import dashboard_server
    import raiox_data

    monkeypatch.setattr(database, "DB_FILE", dbp)
    # trade_detail devolve TUDO (inclusive o resultado) — o endpoint tem que filtrar.
    monkeypatch.setattr(raiox_data, "trade_detail", lambda conn, tid: {
        "symbol": "BTCUSDT", "direction": "LONG", "entry_time_s": 1776326400,
        "exit_reason": "timeout", "pnl_pct": -0.25, "exit_price": 74600.0,
        "sl_price": 74451.0, "tp1_price": 75267.0, "tp2_price": 75468.0,
        "mfe_pct": 0.4, "mae_pct": -0.6, "exit_time_s": 1776340000,
    })
    monkeypatch.setattr(dashboard_server, "_rotulagem_candles_fn",
                        lambda s, e, i="15m", n=80: [
                            {"time": e - 900 * (n - k), "open": 100.0, "high": 101.0,
                             "low": 99.0, "close": 100.5} for k in range(n)])
    dashboard_server.app.config["TESTING"] = True
    yield dashboard_server.app.test_client()
    os.unlink(dbp)


_RESULT_FIELDS = ("exit_reason", "exit_price", "pnl_pct", "net_pnl_pct", "sl_price",
                  "tp1_price", "tp2_price", "mfe_pct", "mae_pct", "exit_time_s")


def test_next_nao_vaza_resultado(client):
    d = client.get("/api/rotulagem/next").get_json()
    assert d["ok"] is True and d["done"] is False
    assert d["trade_id"] == 1
    assert d["symbol"] == "BTCUSDT" and d["direction"] == "LONG"
    assert len(d["candles"]) == 80
    for f in _RESULT_FIELDS:
        assert f not in d, f"VAZOU campo de resultado no payload cego: {f}"


def test_label_grava_e_avanca_progresso(client):
    r = client.post("/api/rotulagem/label", json={
        "trade_id": 1, "verdict": "gostei", "cues": {"empurrao": True}, "exit_price_guess": 75000})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    d = client.get("/api/rotulagem/next").get_json()
    assert d["done"] is True  # so havia 1 trade e agora esta rotulado
    assert d["progress"] == {"done": 1, "total": 1}


def test_label_verdict_invalido_400(client):
    r = client.post("/api/rotulagem/label", json={"trade_id": 1, "verdict": "talvez"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
