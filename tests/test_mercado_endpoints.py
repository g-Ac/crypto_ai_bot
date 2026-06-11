"""Testes das rotas da aba Mercado. Molde do test_raiox_endpoints (tempfile DB
monkeypatchado em database.DB_FILE), com schema k_* + seed via helpers do
test_market_read."""
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
    FORBIDDEN_SIGNAL_WORDS, HOUR, NOW_MS, NOW_S, add_funding, add_liq, add_price,
)

import market_read as mr


@pytest.fixture
def client(monkeypatch):
    fd, dbp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(dbp)
    conn.row_factory = sqlite3.Row
    conn.executescript(K_SCHEMA)
    conn.executescript(LIQ_SCHEMA)
    # Seed minimo: majors com 2 buckets (ret 24h calculavel), funding, 1 liq.
    for sym in mr.MAJORS:
        add_price(conn, sym, bucket_ts=NOW_S - 24 * HOUR, close=100.0)
        add_price(conn, sym, bucket_ts=NOW_S, close=104.0, volume=1000, taker_buy_base=600)
        add_funding(conn, sym, NOW_S, rate=0.0001)
    add_liq(conn, "BTCUSDT", NOW_MS, side="SELL", qty=8.0, price=100.0)
    conn.commit()
    conn.close()

    import database
    import dashboard_server

    monkeypatch.setattr(database, "DB_FILE", dbp)
    dashboard_server.app.config["TESTING"] = True
    yield dashboard_server.app.test_client()
    os.unlink(dbp)


def test_mercado_page_renders(client):
    r = client.get("/raiox/mercado")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for chave in ("Termômetro", "Pressão 24h", "Em palavras", "Frescor", "Leitura de"):
        assert chave in html, f"pagina macro sem o bloco {chave!r}"
    assert 'href="/raiox/mercado/BTCUSDT"' in html
    # Spans coloridos renderizam como HTML vivo (seed: ret +4% -> positive).
    # Regressao: concat ~ com Markup escapava os literais <span> antes do |safe.
    assert 'class="positive"' in html
    assert "&lt;span" not in html


def test_mercado_page_macro_sem_linguagem_de_sinal(client):
    low = client.get("/raiox/mercado").get_data(as_text=True).lower()
    for w in FORBIDDEN_SIGNAL_WORDS:
        assert w not in low, f"HTML macro contem linguagem de sinal proibida: {w!r}"


def test_mercado_zoom_aceita_curto_e_completo(client):
    for path in ("/raiox/mercado/BTC", "/raiox/mercado/BTCUSDT"):
        r = client.get(path)
        assert r.status_code == 200, path
        html = r.get_data(as_text=True)
        assert "🔎 BTC" in html
        assert "Em palavras" in html and "Frescor" in html
        assert 'href="/raiox/mapa?symbol=BTCUSDT"' in html
        assert 'class="positive"' in html, path     # ret 24h +4% do seed
        assert "&lt;span" not in html, path


def test_mercado_zoom_doge_valido_renderiza_nd(client):
    # DOGEUSDT esta nos 14 canonicos; sem dado no banco -> renderiza com n/d
    r = client.get("/raiox/mercado/DOGE")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "🔎 DOGE" in html
    assert "n/d" in html
    # DOGE nao tem Mapa da Moeda — sem deep-link. (O nav SEMPRE contem
    # href="/raiox/mapa", entao o assert mira no link COM query string.)
    assert 'href="/raiox/mapa?symbol=' not in html


def test_mercado_zoom_invalido_redirect(client):
    r = client.get("/raiox/mercado/FOO")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/raiox/mercado")


def test_mercado_zoom_sem_linguagem_de_sinal(client):
    low = client.get("/raiox/mercado/BTCUSDT").get_data(as_text=True).lower()
    for w in FORBIDDEN_SIGNAL_WORDS:
        assert w not in low, f"HTML zoom contem linguagem de sinal proibida: {w!r}"


def test_nav_tem_mercado_nos_dois_blocos(client):
    # /raiox/ e pagina neutra (nao contem outros links pra /raiox/mercado):
    # exatamente 2 ocorrencias = nav desktop + nav mobile.
    html = client.get("/raiox/").get_data(as_text=True)
    assert html.count('href="/raiox/mercado"') == 2
