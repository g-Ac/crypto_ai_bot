"""Testes das rotas da aba Paper. Molde do test_mercado_endpoints (tempfile DB
monkeypatchado em database.DB_FILE) + paper_manual_trades."""
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

from k_collector import SCHEMA as K_SCHEMA
from liquidation_store import SCHEMA as LIQ_SCHEMA
from tests.test_market_read import (
    HOUR, NOW_S, add_funding, add_price,
)
from tests.test_paper_data import fake_candles_fn

# Lista propria do paper: proibe RECOMENDACAO/imperativo da ferramenta.
# Difere da FORBIDDEN_SIGNAL_WORDS do mercado: "entrada/alvo/stop" la seriam
# a ferramenta sugerindo; aqui sao o vocabulario do formulario onde o USUARIO
# declara os proprios niveis (decisao na spec 2026-06-11).
PAPER_FORBIDDEN_WORDS = (
    "compre", "comprar", "venda", "vender", "sinal",
    "longar", "shortar", "recomend", "oportunidade",
)

import market_read as mr
import paper_data


@pytest.fixture
def client(monkeypatch):
    fd, dbp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(dbp)
    conn.row_factory = sqlite3.Row
    conn.executescript(K_SCHEMA)
    conn.executescript(LIQ_SCHEMA)
    paper_data.ensure_schema(conn)
    for sym in mr.MAJORS:
        add_price(conn, sym, bucket_ts=NOW_S - 24 * HOUR, close=100.0)
        add_price(conn, sym, bucket_ts=NOW_S, close=104.0, volume=1000, taker_buy_base=600)
        add_funding(conn, sym, NOW_S, rate=0.0001)
    conn.commit()
    conn.close()

    import database
    import dashboard_server

    monkeypatch.setattr(database, "DB_FILE", dbp)
    monkeypatch.setattr(dashboard_server, "_paper_candles_fn", fake_candles_fn())
    dashboard_server.app.config["TESTING"] = True
    yield dashboard_server.app.test_client()
    os.unlink(dbp)


def test_paper_page_renders(client):
    r = client.get("/raiox/paper")
    html = r.data.decode()
    assert r.status_code == 200
    assert "Registrar tese" in html
    assert "&lt;span" not in html


def test_paper_page_sem_linguagem_de_sinal(client):
    html = client.get("/raiox/paper").data.decode().lower()
    for word in PAPER_FORBIDDEN_WORDS:
        assert word not in html, f"linguagem de sinal no template: {word}"


def test_paper_criar_e_listar(client):
    r = client.post("/raiox/paper/criar", data={
        "symbol": "ETHUSDT", "direction": "long", "entry_price": "2500",
        "stop_price": "2450", "target_price": "2600", "thesis": "teste", "tags": ""})
    assert r.status_code == 302
    html = client.get("/raiox/paper?symbol=ETHUSDT").data.decode()
    assert "ETHUSDT" in html and "fechar agora" in html
    assert "aguardando 1o check do tracker" in html  # frescor do tracker visivel


def test_paper_criar_invalido_rerender_400(client):
    r = client.post("/raiox/paper/criar", data={
        "symbol": "ETHUSDT", "direction": "long", "entry_price": "2500",
        "stop_price": "2550", "target_price": "2600", "thesis": "x", "tags": ""})
    assert r.status_code == 400
    assert "stop" in r.data.decode()


def test_paper_post_sem_auth_401(client, monkeypatch):
    import dashboard_server
    monkeypatch.setattr(dashboard_server, "_AUTH_ENABLED", True)
    monkeypatch.setattr(dashboard_server, "_DASHBOARD_USER", "u")
    monkeypatch.setattr(dashboard_server, "_DASHBOARD_PASS", "p")
    r = client.post("/raiox/paper/criar", data={})
    assert r.status_code == 401


def test_paper_anular_e_fechar(client):
    client.post("/raiox/paper/criar", data={
        "symbol": "ETHUSDT", "direction": "long", "entry_price": "2500",
        "stop_price": "2450", "target_price": "2600", "thesis": "t", "tags": ""})
    assert client.post("/raiox/paper/1/fechar").status_code == 302
    client.post("/raiox/paper/criar", data={
        "symbol": "ETHUSDT", "direction": "long", "entry_price": "2500",
        "stop_price": "2450", "target_price": "2600", "thesis": "t2", "tags": ""})
    assert client.post("/raiox/paper/2/anular", data={"reason": "erro"}).status_code == 302


def test_nav_tem_paper_nos_dois_blocos(client):
    html = client.get("/raiox/paper").data.decode()
    assert html.count('href="/raiox/paper"') >= 2


def test_paper_criar_sem_symbol_400(client):
    r = client.post("/raiox/paper/criar", data={"direction": "long"})
    assert r.status_code == 400


def test_paper_criar_redirect_normaliza_symbol(client):
    r = client.post("/raiox/paper/criar", data={
        "symbol": "eth", "direction": "long", "entry_price": "2500",
        "stop_price": "2450", "target_price": "2600", "thesis": "t"})
    assert r.status_code == 302
    assert r.headers["Location"] == "/raiox/paper?symbol=ETHUSDT"


def test_paper_criar_repopula_form_em_erro(client):
    r = client.post("/raiox/paper/criar", data={
        "symbol": "ETHUSDT", "direction": "long", "entry_price": "2500",
        "stop_price": "2550", "target_price": "2600", "thesis": "minha tese longa"})
    assert r.status_code == 400
    html = r.data.decode()
    assert "minha tese longa" in html
    assert "&lt;span" not in html


def test_paper_criar_xss_escapado(client):
    r = client.post("/raiox/paper/criar", data={
        "symbol": "ETHUSDT", "direction": "long", "entry_price": "2500",
        "stop_price": "2550", "target_price": "2600",
        "thesis": "<script>alert(1)</script>"})
    assert r.status_code == 400
    html = r.data.decode()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_api_candles_aceita_simbolos_do_paper(client, monkeypatch):
    import dashboard_server
    monkeypatch.setattr(dashboard_server, "_binance_candles_adapter",
                        lambda s, i, l: fake_candles_fn()(s, i, l))
    # SOLUSDT e DOGEUSDT estao em PAPER_SYMBOLS: devem ser aceitos pelo endpoint de candles
    for sym in ("SOLUSDT", "DOGEUSDT"):
        r = client.get(f"/api/raiox/candles?symbol={sym}&interval=15m"
                       f"&start={NOW_S-3600}&end={NOW_S}")
        assert r.status_code != 400 or b"symbol_invalido" not in r.data, \
            f"{sym} deveria ser aceito mas retornou symbol_invalido"
    # 1000PEPEUSDT esta excluido de PAPER_SYMBOLS: deve ser rejeitado
    r = client.get(f"/api/raiox/candles?symbol=1000PEPEUSDT&interval=15m"
                   f"&start={NOW_S-3600}&end={NOW_S}")
    assert r.status_code == 400 and b"symbol_invalido" in r.data
