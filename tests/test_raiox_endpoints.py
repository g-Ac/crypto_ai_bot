import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DDL = """CREATE TABLE momentum_trades (
  id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT, direction TEXT, regime TEXT,
  entry_price REAL, exit_price REAL, sl_price REAL, tp1_price REAL, tp2_price REAL,
  exit_reason TEXT, duration_candles INTEGER, mfe_pct REAL, mae_pct REAL,
  pnl_pct REAL, net_pnl_pct REAL);"""


@pytest.fixture
def client(monkeypatch):
    fd, dbp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(dbp)
    conn.executescript(_DDL)
    conn.execute(
        "INSERT INTO momentum_trades (id,timestamp,symbol,direction,regime,entry_price,"
        "exit_price,sl_price,tp1_price,tp2_price,exit_reason,duration_candles,mfe_pct,"
        "mae_pct,pnl_pct,net_pnl_pct) VALUES (1,'2026-06-08T17:07:43+00:00','ETHUSDT',"
        "'LONG','TRENDING',1691.47,1676.55,1676.55,1706.22,1713.85,'sl_hit',3,0.37,-0.93,-0.78,-0.88)"
    )
    conn.commit()
    conn.close()

    fd, sp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(sp, "w") as f:
        json.dump({"positions": {}}, f)

    import database
    import dashboard_server

    monkeypatch.setattr(database, "DB_FILE", dbp)
    monkeypatch.setattr(dashboard_server, "MOMENTUM_STATE_FILE", sp, raising=False)
    dashboard_server.app.config["TESTING"] = True
    yield dashboard_server.app.test_client()
    os.unlink(dbp)
    os.unlink(sp)


def test_api_raiox_trades_ok(client):
    r = client.get("/api/raiox/trades")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["closed"][0]["id"] == 1
    assert data["closed"][0]["pnl_source"] == "net_pnl_pct"


def test_api_raiox_trade_detail_ok(client):
    r = client.get("/api/raiox/trade/1")
    data = r.get_json()
    assert data["ok"] is True
    assert data["trade"]["entry_time_estimated"] is True
    assert data["trade"]["entry_time_s"] == data["trade"]["exit_time_s"] - 3 * 15 * 60


def test_api_raiox_trade_detail_404(client):
    r = client.get("/api/raiox/trade/999")
    assert r.status_code == 404
    assert r.get_json()["ok"] is False


def test_candles_rejects_bad_symbol(client):
    r = client.get("/api/raiox/candles?symbol=FOOUSDT&interval=15m&start=1&end=2")
    assert r.status_code == 400
    assert r.get_json()["error"] == "symbol_invalido"


def test_candles_rejects_bad_interval(client):
    r = client.get("/api/raiox/candles?symbol=ETHUSDT&interval=3m&start=1&end=2")
    assert r.status_code == 400


def test_candles_rejects_start_ge_end(client):
    r = client.get("/api/raiox/candles?symbol=ETHUSDT&interval=15m&start=200&end=100")
    assert r.status_code == 400


def test_candles_ok(client, monkeypatch):
    # now dinamico: o endpoint escala o timeframe com base em int(time.time()) real
    # (janela now_real - start). Um now fixo vira time-bomb — conforme o relogio avanca,
    # a janela de 15m ultrapassa 1000 barras e o codigo escala para 1h. Mesmo padrao
    # dos test_candles_margin_* abaixo.
    import time as _time
    now = int(_time.time())
    rows = [{"time_s": now - i * 900, "open": 1, "high": 1, "low": 1, "close": 1} for i in range(50)]
    class _DF:
        def to_dict(self, orient):
            return rows
    monkeypatch.setattr("market.get_candles", lambda s, i, l: _DF())
    r = client.get(f"/api/raiox/candles?symbol=ETHUSDT&interval=15m&start={now-5*900}&end={now}")
    data = r.get_json()
    assert data["ok"] is True
    assert data["effective_interval"] == "15m"
    assert len(data["candles"]) > 0


def test_candles_adapter_normalizes_datetime64_ms(client, monkeypatch):
    import pandas as pd

    now = 1780941600
    times = pd.to_datetime([now - i * 900 for i in range(20)][::-1], unit="s").astype("datetime64[ms]")
    frame = pd.DataFrame({
        "time": times,
        "open": [1.0] * 20,
        "high": [1.0] * 20,
        "low": [1.0] * 20,
        "close": [1.0] * 20,
    })
    monkeypatch.setattr("market.get_candles", lambda s, i, l: frame)
    r = client.get(f"/api/raiox/candles?symbol=ETHUSDT&interval=15m&start={now-5*900}&end={now}")
    data = r.get_json()
    assert r.status_code == 200
    assert data["ok"] is True
    assert data["candles"]
    assert data["candles"][-1]["time"] == now


def test_candles_binance_down_returns_502(client, monkeypatch):
    def boom(s, i, l):
        raise Exception("binance down")
    monkeypatch.setattr("market.get_candles", boom)
    now = 1780941600
    r = client.get(f"/api/raiox/candles?symbol=ETHUSDT&interval=15m&start={now-5*900}&end={now}")
    assert r.status_code == 502
    assert r.get_json()["error"] == "binance_unavailable"


def test_candles_margin_param_widens_window(client, monkeypatch):
    import time as _time
    now = int(_time.time())
    rows = [{"time_s": now - i * 900, "open": 1, "high": 1, "low": 1, "close": 1}
            for i in range(400)][::-1]
    seen = []
    class _DF:
        def to_dict(self, orient):
            return rows
    def fake(s, i, limit):
        seen.append(limit)
        return _DF()
    monkeypatch.setattr("market.get_candles", fake)
    base = f"/api/raiox/candles?symbol=ETHUSDT&interval=15m&start={now-5*900}&end={now}"
    n_default = len(client.get(base).get_json()["candles"])
    d = client.get(base + "&margin=100").get_json()
    assert d["ok"] is True
    assert len(d["candles"]) > n_default          # margem maior = mais contexto retornado
    assert abs((seen[1] - seen[0]) - 80) <= 1     # margin 100 vs default 20 (now do server avanca)


def test_candles_margin_capped_at_300(client, monkeypatch):
    import time as _time
    now = int(_time.time())
    seen = []
    class _DF:
        def to_dict(self, orient):
            return []
    def fake(s, i, limit):
        seen.append(limit)
        return _DF()
    monkeypatch.setattr("market.get_candles", fake)
    base = f"/api/raiox/candles?symbol=ETHUSDT&interval=15m&start={now-5*900}&end={now}"
    assert client.get(base + "&margin=0").status_code == 200
    assert client.get(base + "&margin=10000").status_code == 200
    assert abs((seen[1] - seen[0]) - 300) <= 1    # cap silencioso em 300


def test_candles_margin_invalido_400(client):
    now = 1780941600
    r = client.get(f"/api/raiox/candles?symbol=ETHUSDT&interval=15m&start={now-5*900}&end={now}&margin=abc")
    assert r.status_code == 400
    assert r.get_json()["error"] == "param_invalido"


def test_raiox_page_renders(client):
    r = client.get("/raiox/")
    assert r.status_code == 200
    assert b"Raio-X" in r.data


def test_api_mapa_ok(client):
    r = client.get("/api/raiox/mapa?symbol=ETHUSDT")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["symbol"] == "ETHUSDT"
    assert len(d["trades"]) == 1
    t = d["trades"][0]
    assert t["id"] == 1 and t["result"] == "loss"
    assert t["entry_time_s"] < t["exit_time_s"]
    assert t["pnl_source"] == "net_pnl_pct"


def test_api_mapa_symbol_sem_trades(client):
    r = client.get("/api/raiox/mapa?symbol=BTCUSDT")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["trades"] == []


def test_api_mapa_symbol_invalido(client):
    r = client.get("/api/raiox/mapa?symbol=DOGEUSDT")
    assert r.status_code == 400
    assert r.get_json()["error"] == "symbol_invalido"


def test_mapa_page_renders(client):
    r = client.get("/raiox/mapa")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Mapa da Moeda" in html
    assert "mapa.js" in html
