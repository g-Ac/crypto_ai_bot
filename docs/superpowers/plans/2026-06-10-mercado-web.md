# Aba Mercado no Trade Desk — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portar a leitura de mercado do Telegram (`/mercado` e `/mercado <SYM>`) para uma aba web "Mercado" no Trade Desk (porta 5000) — leitura, não sinal.

**Architecture:** Molde das Fatias 1-2 (Raio-X / Mapa): backend puro testável (`mercado_data.py`, consome o motor `market_read.py` SEM modificá-lo) + rotas finas em `dashboard_server.py` + templates Jinja server-side. Sem endpoint JSON novo, sem JS novo (exceto ~3 linhas de deep-link `?symbol=` no mapa.js). Spec aprovada: `docs/superpowers/specs/2026-06-10-mercado-web-design.md`.

**Tech Stack:** Python 3.13, Flask + Jinja2, SQLite (tabelas `k_*` no mesmo `bot.db`), pytest. Zero libs novas.

---

## Regras do projeto que ADAPTAM o template desta skill

1. **NÃO commitar por task.** CLAUDE.md: commit só quando Gabriel pedir. Spec: "Commit só com OK explícito" após validação visual. Todos os commits intermediários do template viram **um único commit final condicionado ao OK do Gabriel** (Task 8).
2. **NÃO rodar pytest manualmente após Write/Edit em `.py`.** O hook PostToolUse roda a suite inteira automaticamente. Os steps "verify RED/GREEN" significam: **observar a saída do hook** após o Write/Edit. Comandos pytest explícitos aparecem só onde é preciso conferir um teste isolado sem ter editado nada.
3. **Motor intocado:** `market_read.py` NÃO é modificado em nenhuma task. Importar helpers privados (`_pressure_label`, `_fmt_*`, `_sym_short`, `_fmt_age`) é decisão consciente da spec (ajuste 2) — o teste anti-divergência protege.

## Fatos do codebase que o executor precisa saber

- Tabelas `k_prices`, `k_ratios`, `k_funding_rates`, `k_open_interest`, `k_basis` são criadas por `SCHEMA` de `scripts/k_collector.py`; `k_liquidations` por `SCHEMA` de `liquidation_store.py`. Tudo mora no MESMO `bot.db` do bot (`db._get_conn()` serve).
- `database._get_conn()` já seta `row_factory = sqlite3.Row` (obrigatório pro `market_read`).
- `tests/` é um pacote (`tests/__init__.py` existe) → import entre testes é `from tests.test_market_read import ...`.
- `dashboard_server.py` já importa `time`, `redirect`, `render_template`, `db` — as rotas novas não precisam de import novo além de `mercado_data`.
- CSS global (`static/css/style.css`) já tem `.card`, `.card-header`, `.positive`, `.negative` — reusar.
- Jinja: `view.lsr['global']` via subscript (evita ambiguidade), e a chave de freshness chama `sources` (NUNCA `items` — `.items` em Jinja resolve pro método de dict).
- `mr._pressure_label`, `mr._fmt_usd`, `mr._fmt_pct`, `mr._fmt_num`, `mr._sym_short`, `mr._fmt_age` existem em `market_read.py` (linhas 263-308, 569-575).
- Lista canônica em `scripts/k_collector.py:38`: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, HYPEUSDT, LINKUSDT, AVAXUSDT, LTCUSDT, TRXUSDT, SUIUSDT, 1000PEPEUSDT.
- Dashboard sobe em porta alternativa com `DASHBOARD_PORT=5055 python dashboard_server.py` (env var lida em `runtime_config.py:70`).

## File Structure

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `mercado_data.py` | Create | Views prontas pra template (macro_view, symbol_view, normalize_symbol, lista canônica). Puro, testável, recebe `conn` e `now_s`. |
| `tests/test_mercado_data.py` | Create | Testes do módulo de views (banco in-memory, molde do test_market_read). |
| `tests/test_mercado_endpoints.py` | Create | Testes das rotas Flask (molde do test_raiox_endpoints, tempfile DB com schema k_*). |
| `templates/_mercado_macros.html` | Create | Macros Jinja compartilhadas (estilo, cor por sinal, barra split, blocos tradução/frescor). |
| `templates/mercado.html` | Create | Página macro. |
| `templates/mercado_symbol.html` | Create | Página zoom por símbolo. |
| `dashboard_server.py` | Modify (após linha 1604, rotas mapa) | 2 rotas finas. |
| `templates/base.html` | Modify (linhas 28 e 67) | Aba "Mercado" nos 2 navs. |
| `static/js/mapa.js` | Modify (após linha 14) | Deep-link `?symbol=`. |

---

### Task 1: `mercado_data` — lista canônica + `normalize_symbol`

**Files:**
- Create: `tests/test_mercado_data.py`
- Create: `mercado_data.py`

- [ ] **Step 1: Criar `tests/test_mercado_data.py` com os testes de paridade e normalização**

```python
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
```

- [ ] **Step 2: Confirmar RED no hook**

O hook PostToolUse roda a suite após o Write. Esperado: `tests/test_mercado_data.py` falha na coleta com `ModuleNotFoundError: No module named 'mercado_data'`. O resto da suite (~693 testes) segue verde.

- [ ] **Step 3: Criar `mercado_data.py` com a lista canônica e `normalize_symbol` (mínimo pra ficar verde)**

```python
"""
Views da aba Mercado do Trade Desk (porta 5000).

Monta dicts prontos pra template Jinja consumindo o motor validado do
market_read.py SEM modifica-lo. Leitura, NAO sinal: sem score, sem veredito.

Validade de simbolo vem da lista canonica (copia de scripts/k_collector.SYMBOLS,
teste de paridade garante sync) — NUNCA de all_symbols(conn): em banco vazio a
lista do banco e vazia e quebraria o requisito "banco vazio renderiza n/d".

Helpers privados do market_read (_pressure_label, _fmt_*) sao importados de
proposito (spec 2026-06-10, ajuste 2): a decisao e nao tocar no motor, e o
teste anti-divergencia denuncia se o rotulo web divergir do Telegram.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

import market_read as mr

# Copia canonica de scripts/k_collector.SYMBOLS (teste de paridade garante sync)
SUPPORTED_MARKET_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "HYPEUSDT", "LINKUSDT", "AVAXUSDT",
    "LTCUSDT", "TRXUSDT", "SUIUSDT", "1000PEPEUSDT",
)

# Espelho de SYMBOLS em static/js/mapa.js (o Mapa da Moeda so cobre BTC/ETH)
MAP_SYMBOLS = ("BTCUSDT", "ETHUSDT")


def normalize_symbol(raw) -> str | None:
    """'BTC' -> 'BTCUSDT', 'btcusdt' -> 'BTCUSDT'; None se nao esta na lista canonica.
    Borda conhecida: 'PEPE' -> 'PEPEUSDT' -> None (lista tem 1000PEPEUSDT)."""
    token = (raw or "").strip().upper()
    if not token:
        return None
    symbol = token if token.endswith("USDT") else f"{token}USDT"
    return symbol if symbol in SUPPORTED_MARKET_SYMBOLS else None
```

- [ ] **Step 4: Confirmar GREEN no hook**

Esperado: suite inteira verde (os 2 grupos novos passam).

---

### Task 2: `mercado_data.macro_view`

**Files:**
- Modify: `tests/test_mercado_data.py` (adicionar testes ao final)
- Modify: `mercado_data.py` (adicionar helpers + macro_view)

- [ ] **Step 1: Adicionar testes de `macro_view` ao final de `tests/test_mercado_data.py`**

```python
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
```

- [ ] **Step 2: Confirmar RED no hook**

Esperado: os 3 testes novos falham com `AttributeError: module 'mercado_data' has no attribute 'macro_view'`. Resto verde.

- [ ] **Step 3: Adicionar helpers + `macro_view` ao final de `mercado_data.py`**

```python
def _num(value, text: str) -> dict:
    """Par valor cru + texto formatado: o template colore pelo sinal de value."""
    return {"value": value, "text": text}


def _fmt_funding(rate) -> dict:
    return _num(rate, f"{rate * 100:+.4f}%" if rate is not None else "n/d")


def _pressure_row(p: dict) -> dict:
    """Linha do mapa de pressao pronta pra barra split CSS + rotulo do Telegram."""
    total = p.get("total_usd") or 0.0
    return {
        "symbol": p["symbol"],
        "name": mr._sym_short(p["symbol"]),
        "total": mr._fmt_usd(p["total_usd"]),
        "label": mr._pressure_label(p),          # EXATAMENTE o rotulo do Telegram
        "longs_pct": 100.0 * p["longs_liq_usd"] / total if total else 0.0,
        "shorts_pct": 100.0 * p["shorts_liq_usd"] / total if total else 0.0,
        "events": p["events"],
    }


def _freshness_view(fresh: dict) -> dict:
    """Chave 'sources' (nao 'items': .items em Jinja resolve pro metodo de dict)."""
    sources = [{"label": lbl, "age": mr._fmt_age(d["age_s"]), "stale": d["stale"]}
               for lbl, d in fresh.items()]
    return {"sources": sources,
            "stale_labels": [s["label"] for s in sources if s["stale"]]}


def _read_at(now_s: int) -> str:
    """Hora local do servidor, como o resto do dashboard."""
    return datetime.fromtimestamp(now_s).strftime("%H:%M")


def macro_view(conn: sqlite3.Connection, now_s: int) -> dict:
    """Leitura macro pronta pra mercado.html. Componentes, NAO veredito."""
    regime = mr.read_regime(conn)
    pressure = mr.read_pressure(conn, 24)
    majors = []
    for sym in mr.MAJORS:
        r24 = regime["returns_24h"].get(sym)
        r7 = regime["returns_7d"].get(sym)
        majors.append({
            "symbol": sym,
            "name": mr._sym_short(sym),
            "ret_24h": _num(r24, mr._fmt_pct(r24)),
            "ret_7d": _num(r7, mr._fmt_pct(r7)),
        })
    b = regime["breadth_24h"]
    funding = [{"name": mr._sym_short(sym),
                "rate": _fmt_funding(regime["funding"].get(sym, {}).get("funding_rate"))}
               for sym in mr.MAJORS]
    return {
        "majors": majors,
        "breadth": f"{b['up']}/{b['total']}" if b["total"] else "n/d",
        "vol_btc": mr._fmt_pct(regime["volatility_btc"], signed=False),
        "taker_btc": mr._fmt_pct(regime["taker_btc"], signed=False),
        "lsr": {"global": mr._fmt_num(regime["lsr_btc"]["global"]),
                "top": mr._fmt_num(regime["lsr_btc"]["top"])},
        "funding": funding,
        "basis_btc": _num(regime["basis_btc"]["basis_rate"],
                          mr._fmt_num(regime["basis_btc"]["basis_rate"], 4)),
        "oi_btc": _num(regime["oi_change_btc"], mr._fmt_pct(regime["oi_change_btc"])),
        "pressure": [_pressure_row(p) for p in pressure],
        "translation": mr.translate_macro(regime, pressure),
        "freshness": _freshness_view(mr.read_freshness(conn, now_s)),
        "read_at": _read_at(now_s),
    }
```

- [ ] **Step 4: Confirmar GREEN no hook**

---

### Task 3: `mercado_data.symbol_view` + anti-sinal das views

**Files:**
- Modify: `tests/test_mercado_data.py` (adicionar testes ao final)
- Modify: `mercado_data.py` (adicionar symbol_view)

- [ ] **Step 1: Adicionar testes ao final de `tests/test_mercado_data.py`**

```python
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
    assert v["tem_mapa"] is True                     # ETHUSDT esta no Mapa da Moeda
    assert v["translation"]
    assert v["read_at"] == datetime.fromtimestamp(NOW_S).strftime("%H:%M")
    assert [s["label"] for s in v["freshness"]["sources"]] == \
        ["preco", "LSR", "OI", "basis", "funding", "liq"]


def test_symbol_view_sem_liquidacoes_e_sem_mapa(conn):
    add_price(conn, "SOLUSDT", bucket_ts=NOW_S, close=100.0)
    v = md.symbol_view(conn, "SOLUSDT", NOW_S)
    assert v["pressure"] is None
    assert v["tem_mapa"] is False                    # so BTCUSDT/ETHUSDT tem mapa


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
    """Percorre recursivamente todas as strings de uma view."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _all_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _all_strings(v)


def test_views_sem_linguagem_de_sinal(conn):
    """Anti-drift: nenhuma string das views contem vocabulario de sinal."""
    _seed_macro(conn)
    views = (md.macro_view(conn, NOW_S), md.symbol_view(conn, "BTCUSDT", NOW_S))
    for view in views:
        for s in _all_strings(view):
            low = s.lower()
            for w in FORBIDDEN_SIGNAL_WORDS:
                assert w not in low, f"view contem linguagem de sinal proibida: {w!r} em {s!r}"
```

- [ ] **Step 2: Confirmar RED no hook**

Esperado: 4 testes novos falham com `AttributeError: ... no attribute 'symbol_view'` (o `test_tem_mapa_espelha_mapa_js` já passa — MAP_SYMBOLS existe da Task 1).

- [ ] **Step 3: Adicionar `symbol_view` ao final de `mercado_data.py`**

```python
def symbol_view(conn: sqlite3.Connection, symbol: str, now_s: int) -> dict:
    """Zoom de uma moeda pronto pra mercado_symbol.html (sem veredito).
    `symbol` ja deve vir normalizado (normalize_symbol na rota)."""
    data = mr.read_symbol(conn, symbol)
    p = data["pressure"]
    return {
        "symbol": data["symbol"],
        "name": mr._sym_short(data["symbol"]),
        "ret_24h": _num(data["ret_24h"], mr._fmt_pct(data["ret_24h"])),
        "ret_7d": _num(data["ret_7d"], mr._fmt_pct(data["ret_7d"])),
        "vol": mr._fmt_pct(data["volatility_24h"], signed=False),
        "taker": mr._fmt_pct(data["taker_24h"], signed=False),
        "lsr": {"global": mr._fmt_num(data["lsr"]["global"]),
                "top": mr._fmt_num(data["lsr"]["top"])},
        "funding": _fmt_funding(data["funding"].get("funding_rate")),
        "basis": _num(data["basis"]["basis_rate"],
                      mr._fmt_num(data["basis"]["basis_rate"], 4)),
        "oi": _num(data["oi_change_24h"], mr._fmt_pct(data["oi_change_24h"])),
        "pressure": _pressure_row(p) if p else None,
        "translation": mr.translate_symbol(data),
        "freshness": _freshness_view(mr.read_freshness(conn, now_s)),
        "read_at": _read_at(now_s),
        "tem_mapa": data["symbol"] in MAP_SYMBOLS,
    }
```

- [ ] **Step 4: Confirmar GREEN no hook**

---

### Task 4: rota macro `/raiox/mercado` + templates `mercado.html` e `_mercado_macros.html`

**Files:**
- Create: `tests/test_mercado_endpoints.py`
- Modify: `dashboard_server.py` (inserir após a rota `api_raiox_mapa`, linha 1604)
- Create: `templates/_mercado_macros.html`
- Create: `templates/mercado.html`

- [ ] **Step 1: Criar `tests/test_mercado_endpoints.py` com o teste da página macro**

```python
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
    assert 'href="/raiox/mercado/BTCUSDT"' in html      # moeda clicavel -> zoom


def test_mercado_page_macro_sem_linguagem_de_sinal(client):
    low = client.get("/raiox/mercado").get_data(as_text=True).lower()
    for w in FORBIDDEN_SIGNAL_WORDS:
        assert w not in low, f"HTML macro contem linguagem de sinal proibida: {w!r}"
```

- [ ] **Step 2: Confirmar RED no hook**

Esperado: os 2 testes novos falham — `/raiox/mercado` retorna 404 (`assert 404 == 200`). Resto verde.

- [ ] **Step 3: Criar `templates/_mercado_macros.html`**

```html
{# Macros compartilhadas das paginas Mercado (macro e zoom). Leitura, nao veredito. #}

{% macro styles() %}
<style>
  .met-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; margin-top:10px; }
  .met .label { font-size:12px; opacity:.65; }
  .met .value { font-family:'JetBrains Mono',monospace; font-size:15px; }
  .liq-bar { display:flex; height:10px; border-radius:5px; overflow:hidden; background:#222; min-width:120px; max-width:220px; }
  .liq-bar .longs { background:#ef5350; }   /* longs liquidados = cascata (vermelho) */
  .liq-bar .shorts { background:#26a69a; }  /* shorts liquidados = squeeze (verde) */
  .mercado-table { width:100%; border-collapse:collapse; }
  .mercado-table th, .mercado-table td { padding:6px 10px; text-align:left; border-bottom:1px solid rgba(255,255,255,.06); }
  .stale { color:#ffb84d; }
</style>
{% endmacro %}

{% macro cls(m) -%}
{{ 'positive' if m.value is not none and m.value > 0 else 'negative' if m.value is not none and m.value < 0 else '' }}
{%- endmacro %}

{% macro met(label, value_html) %}
<div class="met"><div class="label">{{ label }}</div><div class="value">{{ value_html }}</div></div>
{% endmacro %}

{% macro pressure_bar(p) %}
<div class="liq-bar" title="{{ p.label }}">
  <div class="longs" style="width:{{ p.longs_pct }}%"></div>
  <div class="shorts" style="width:{{ p.shorts_pct }}%"></div>
</div>
{% endmacro %}

{% macro translation_block(lines) %}
<section class="card">
  <h2>🔍 Em palavras</h2>
  {% if lines %}
  <ul>{% for ln in lines %}<li>{{ ln }}</li>{% endfor %}</ul>
  {% else %}
  <p><i>sem dados suficientes pra traduzir</i></p>
  {% endif %}
</section>
{% endmacro %}

{% macro freshness_block(f) %}
<section class="card">
  <h2>🕐 Frescor</h2>
  <p>
    {%- for s in f.sources -%}
      <span class="{{ 'stale' if s.stale else '' }}">{{ s.label }} {{ s.age }}</span>
      {%- if not loop.last %} · {% endif -%}
    {%- endfor -%}
  </p>
  {% if f.stale_labels %}
  <p class="stale">⚠️ {{ f.stale_labels|join(', ') }} atrasado(s) — coletor pode ter caído, leia com cautela.</p>
  {% endif %}
</section>
{% endmacro %}
```

- [ ] **Step 4: Criar `templates/mercado.html`**

```html
{% extends "base.html" %}
{% import "_mercado_macros.html" as mm %}
{% block title %}Mercado{% endblock %}
{% block head %}{{ mm.styles() }}{% endblock %}
{% block content %}

<section class="card">
  <div class="card-header">
    <h1>📊 Mercado</h1>
    <p>Componentes, não veredito · Leitura de {{ view.read_at }} ·
       <a href="/raiox/mercado">↻ atualizar</a></p>
  </div>

  <h2>🌡️ Termômetro</h2>
  <div class="met-grid">
    {% for m in view.majors %}
    {{ mm.met(m.name ~ ' 24h / 7d',
              '<span class="' ~ mm.cls(m.ret_24h) ~ '">' ~ m.ret_24h.text ~ '</span> / <span class="'
              ~ mm.cls(m.ret_7d) ~ '">' ~ m.ret_7d.text ~ '</span>') }}
    {% endfor %}
    {{ mm.met('Amplitude (verdes 24h)', view.breadth) }}
    {{ mm.met('Range médio BTC 24h', view.vol_btc) }}
    {{ mm.met('Taker buy BTC 24h', view.taker_btc) }}
    {{ mm.met('LSR BTC global / top', view.lsr['global'] ~ ' / ' ~ view.lsr['top']) }}
    {% for f in view.funding %}
    {{ mm.met('Funding ' ~ f.name,
              '<span class="' ~ mm.cls(f.rate) ~ '">' ~ f.rate.text ~ '</span>') }}
    {% endfor %}
    {{ mm.met('Basis BTC', '<span class="' ~ mm.cls(view.basis_btc) ~ '">' ~ view.basis_btc.text ~ '</span>') }}
    {{ mm.met('ΔOI BTC 24h', '<span class="' ~ mm.cls(view.oi_btc) ~ '">' ~ view.oi_btc.text ~ '</span>') }}
  </div>
</section>

<section class="card">
  <h2>🔥 Pressão 24h <small>(liquidações, maior notional primeiro)</small></h2>
  {% if view.pressure %}
  <table class="mercado-table">
    <thead><tr><th>Moeda</th><th>Total</th><th>Split longs/shorts</th><th>Leitura</th><th>Eventos</th></tr></thead>
    <tbody>
      {% for p in view.pressure %}
      <tr>
        <td><a href="/raiox/mercado/{{ p.symbol }}">{{ p.name }}</a></td>
        <td>{{ p.total }}</td>
        <td>{{ mm.pressure_bar(p) }}</td>
        <td>{{ p.label }}</td>
        <td>{{ p.events }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p><i>sem dados de liquidação na janela</i></p>
  {% endif %}
</section>

{{ mm.translation_block(view.translation) }}
{{ mm.freshness_block(view.freshness) }}

{% endblock %}
```

**Nota sobre `mm.met(...)`:** as strings com HTML passadas pra macro são marcadas pelo Jinja como inseguras e seriam escapadas. Para o `<span>` interno renderizar, a macro `met` precisa de `{{ value_html|safe }}`. Como `value_html` contém APENAS valores formatados pelo backend (sem input de usuário), `|safe` é aceitável aqui. Ajuste a macro `met` em `_mercado_macros.html` para:

```html
{% macro met(label, value_html) %}
<div class="met"><div class="label">{{ label }}</div><div class="value">{{ value_html|safe }}</div></div>
{% endmacro %}
```

(Já criar o arquivo com `|safe` direto no Step 3 — esta nota existe pra explicar o porquê.)

- [ ] **Step 5: Adicionar a rota em `dashboard_server.py`**

Inserir `import mercado_data` junto aos imports do topo (após `import raiox_data`, linha 35):

```python
import mercado_data
```

Inserir a rota após `api_raiox_mapa` (após a linha 1604, antes de `@app.route("/legacy")`):

```python
@app.route("/raiox/mercado")
def mercado_page():
    conn = db._get_conn()
    try:
        view = mercado_data.macro_view(conn, int(time.time()))
    finally:
        conn.close()
    return render_template("mercado.html", view=view, active_page="mercado")
```

- [ ] **Step 6: Confirmar GREEN no hook**

Esperado: suite inteira verde. Se `test_mercado_page_renders` falhar com 500, inspecionar o traceback do Jinja (provável typo em nome de chave da view — conferir contra o contrato das Tasks 2-3).

---

### Task 5: rota zoom `/raiox/mercado/<symbol>` + template `mercado_symbol.html`

**Files:**
- Modify: `tests/test_mercado_endpoints.py` (adicionar testes ao final)
- Modify: `dashboard_server.py` (adicionar rota após `mercado_page`)
- Create: `templates/mercado_symbol.html`

- [ ] **Step 1: Adicionar testes ao final de `tests/test_mercado_endpoints.py`**

```python
def test_mercado_zoom_aceita_curto_e_completo(client):
    for path in ("/raiox/mercado/BTC", "/raiox/mercado/BTCUSDT"):
        r = client.get(path)
        assert r.status_code == 200, path
        html = r.get_data(as_text=True)
        assert "🔎 BTC" in html
        assert "Em palavras" in html and "Frescor" in html
        assert 'href="/raiox/mapa?symbol=BTCUSDT"' in html   # tem_mapa -> link pro Mapa


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
```

- [ ] **Step 2: Confirmar RED no hook**

Esperado: 4 testes novos falham com 404 (rota não existe). Resto verde.

- [ ] **Step 3: Criar `templates/mercado_symbol.html`**

```html
{% extends "base.html" %}
{% import "_mercado_macros.html" as mm %}
{% block title %}Mercado — {{ view.name }}{% endblock %}
{% block head %}{{ mm.styles() }}{% endblock %}
{% block content %}

<section class="card">
  <div class="card-header">
    <h1>🔎 {{ view.name }}</h1>
    <p>
      <a href="/raiox/mercado">← voltar à leitura macro</a>
      {% if view.tem_mapa %} · <a href="/raiox/mapa?symbol={{ view.symbol }}">ver no Mapa da Moeda</a>{% endif %}
      · Leitura de {{ view.read_at }} ·
      <a href="/raiox/mercado/{{ view.symbol }}">↻ atualizar</a>
    </p>
  </div>

  <div class="met-grid">
    {{ mm.met('Retorno 24h / 7d',
              '<span class="' ~ mm.cls(view.ret_24h) ~ '">' ~ view.ret_24h.text ~ '</span> / <span class="'
              ~ mm.cls(view.ret_7d) ~ '">' ~ view.ret_7d.text ~ '</span>') }}
    {{ mm.met('Range médio 24h', view.vol) }}
    {{ mm.met('Taker buy 24h', view.taker) }}
    {{ mm.met('LSR global / top', view.lsr['global'] ~ ' / ' ~ view.lsr['top']) }}
    {{ mm.met('Funding', '<span class="' ~ mm.cls(view.funding) ~ '">' ~ view.funding.text ~ '</span>') }}
    {{ mm.met('Basis', '<span class="' ~ mm.cls(view.basis) ~ '">' ~ view.basis.text ~ '</span>') }}
    {{ mm.met('ΔOI 24h', '<span class="' ~ mm.cls(view.oi) ~ '">' ~ view.oi.text ~ '</span>') }}
  </div>
</section>

<section class="card">
  <h2>🔥 Pressão 24h <small>(liquidações da moeda)</small></h2>
  {% if view.pressure %}
  <table class="mercado-table">
    <thead><tr><th>Total</th><th>Split longs/shorts</th><th>Leitura</th><th>Eventos</th></tr></thead>
    <tbody>
      <tr>
        <td>{{ view.pressure.total }}</td>
        <td>{{ mm.pressure_bar(view.pressure) }}</td>
        <td>{{ view.pressure.label }}</td>
        <td>{{ view.pressure.events }}</td>
      </tr>
    </tbody>
  </table>
  {% else %}
  <p><i>sem liquidações na janela</i></p>
  {% endif %}
</section>

{{ mm.translation_block(view.translation) }}
{{ mm.freshness_block(view.freshness) }}

{% endblock %}
```

- [ ] **Step 4: Adicionar a rota em `dashboard_server.py` (logo após `mercado_page`)**

```python
@app.route("/raiox/mercado/<symbol>")
def mercado_symbol_page(symbol):
    sym = mercado_data.normalize_symbol(symbol)
    if sym is None:
        return redirect("/raiox/mercado")
    conn = db._get_conn()
    try:
        view = mercado_data.symbol_view(conn, sym, int(time.time()))
    finally:
        conn.close()
    return render_template("mercado_symbol.html", view=view, active_page="mercado")
```

- [ ] **Step 5: Confirmar GREEN no hook**

---

### Task 6: aba "Mercado" nos 2 navs do `base.html`

**Files:**
- Modify: `tests/test_mercado_endpoints.py` (adicionar teste ao final)
- Modify: `templates/base.html:28` (nav desktop) e `templates/base.html:67` (nav mobile)

- [ ] **Step 1: Adicionar teste ao final de `tests/test_mercado_endpoints.py`**

```python
def test_nav_tem_mercado_nos_dois_blocos(client):
    # /raiox/ e pagina neutra (nao contem outros links pra /raiox/mercado):
    # exatamente 2 ocorrencias = nav desktop + nav mobile.
    html = client.get("/raiox/").get_data(as_text=True)
    assert html.count('href="/raiox/mercado"') == 2
```

- [ ] **Step 2: Confirmar RED no hook**

Esperado: o teste novo falha com `assert 0 == 2`.

- [ ] **Step 3: Editar `templates/base.html`**

No nav desktop, após a linha 28 (`<li><a href="/raiox/mapa" ...>Mapa</a></li>`), adicionar:

```html
            <li><a href="/raiox/mercado" {% if active_page == 'mercado' %}class="active"{% endif %}>Mercado</a></li>
```

No nav mobile, após a linha 67 (`<a href="/raiox/mapa" ...>Mapa</a>`), adicionar:

```html
      <a href="/raiox/mercado" {% if active_page == 'mercado' %}class="active"{% endif %}>Mercado</a>
```

- [ ] **Step 4: Confirmar GREEN no hook**

(Editar `.html` não dispara o hook de pytest — rodar manualmente APENAS neste caso:)

Run: `cd ~/crypto_ai_bot && source .venv/bin/activate && python -m pytest tests/test_mercado_endpoints.py -v`
Expected: todos PASS, incluindo `test_nav_tem_mercado_nos_dois_blocos`.

---

### Task 7: deep-link `?symbol=` no `static/js/mapa.js`

**Files:**
- Modify: `static/js/mapa.js` (após a linha 14, antes de `const q = ...`)

JS não tem suite — a validação é visual (Task 8). Mudança mínima, sem refactor.

- [ ] **Step 1: Inserir o deep-link após a linha 14 (`const FALLBACK_DAYS = 30;`)**

```js
// Deep-link ?symbol= (ETH ou ETHUSDT): pré-seleciona se suportado; senão mantém BTC.
const QS_RAW = (new URLSearchParams(location.search).get("symbol") || "").trim().toUpperCase();
const QS_SYM = QS_RAW && !QS_RAW.endsWith("USDT") ? QS_RAW + "USDT" : QS_RAW;
if (SYMBOLS.includes(QS_SYM)) MP.symbol = QS_SYM;
```

**Atenção à ordem:** `SYMBOLS` é declarado na linha 10 e `MP` na linha 3 — ambos antes da linha 14, então a inserção é válida. Não mover o bloco pra antes da linha 10.

- [ ] **Step 2: Sanity rápido de sintaxe**

Run: `node --check ~/crypto_ai_bot/static/js/mapa.js 2>/dev/null || python3 -c "print('node ausente — validar no console do browser na Task 8')"`
Expected: sem erro de sintaxe (ou mensagem de fallback se node não estiver instalado no Pi).

---

### Task 8: verificação completa + validação visual na 5055 + (após OK) commit

**Files:** nenhum novo — verificação e rito de entrega.

- [ ] **Step 1: Suite completa + health check de imports**

Run: `cd ~/crypto_ai_bot && source .venv/bin/activate && python -m pytest tests/ --tb=short -q && python -c 'import main; import supervisor; import dashboard_server; print("OK")'`
Expected: todos os testes PASS (≥ 715: ~693 existentes + ~22 novos) e `OK` no final.

- [ ] **Step 2: Subir instância de validação na 5055**

Run: `cd ~/crypto_ai_bot && source .venv/bin/activate && DASHBOARD_PORT=5055 python dashboard_server.py` (em background; anotar o PID para derrubar depois)
Expected: log do Flask servindo em `0.0.0.0:5055`. Descobrir o IP do Pi com `hostname -I` para acessar de fora.

- [ ] **Step 3: Checklist visual (Claude in Chrome em `http://<ip-do-pi>:5055`)**

1. `/raiox/mercado` → aba **Mercado** destacada no nav (desktop; conferir hamburger/mobile também).
2. Macro: termômetro com números e cores por sinal, mapa de pressão com barras split, "Em palavras", "Frescor" com idades.
3. Clicar numa moeda da tabela de pressão → abre o zoom da moeda certa.
4. Zoom de ETH (`/raiox/mercado/ETH`) → link "ver no Mapa da Moeda" → mapa abre **pré-selecionado em ETH** (deep-link `?symbol=ETHUSDT`).
5. `/raiox/mapa?symbol=ETH` (forma curta) → também pré-seleciona ETH; `/raiox/mapa?symbol=FOO` → fica em BTC.
6. `/raiox/mercado/FOO` → redireciona pro macro.
7. Botão "↻ atualizar" recarrega e o "Leitura de HH:MM" avança.
8. Console do browser limpo (sem erros JS) nas 3 páginas (macro, zoom, mapa).
9. Derrubar a instância 5055 ao final.

- [ ] **Step 4: Reportar ao Gabriel e AGUARDAR OK explícito**

Resumo do que foi visto na 5055 + screenshot se útil. **Não commitar sem o OK.**

- [ ] **Step 5 (somente após OK do Gabriel): commit seletivo**

```bash
cd ~/crypto_ai_bot
git add mercado_data.py tests/test_mercado_data.py tests/test_mercado_endpoints.py \
        templates/_mercado_macros.html templates/mercado.html templates/mercado_symbol.html \
        templates/base.html static/js/mapa.js dashboard_server.py \
        docs/superpowers/specs/2026-06-10-mercado-web-design.md \
        docs/superpowers/plans/2026-06-10-mercado-web.md
git commit -m "feat: aba Mercado no Trade Desk (port web do /mercado)

Leitura macro + zoom por simbolo server-side sobre o motor market_read
(intocado). Lista canonica de simbolos com teste de paridade, rotulo de
pressao identico ao Telegram (teste anti-divergencia), guarda anti-sinal
nas views e no HTML. Deep-link ?symbol= no Mapa da Moeda.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 6 (após commit): restart produção + validação na 5000**

```bash
sudo systemctl restart cryptobot
sleep 10
curl -s http://localhost:5000/api/status | python3 -m json.tool | head -5
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/raiox/mercado
```

Expected: status JSON respondendo e `200` na página Mercado. Gabriel valida visualmente na 5000.

---

## Riscos conhecidos (e onde o plano os trata)

| Risco | Tratamento |
|---|---|
| Divergência web vs Telegram | Reuso do motor + teste `test_macro_view_pressure_label_identical_to_telegram` (Task 2) |
| Drift pra sinal | `FORBIDDEN_SIGNAL_WORDS` sobre views (Task 3) e sobre HTML das 2 páginas (Tasks 4-5) |
| Banco vazio quebrar página | Validade canônica (Task 1) + testes `*_empty_db` (Tasks 2-3) + `test_mercado_zoom_doge_valido_renderiza_nd` (Task 5) |
| `.items` do Jinja sombreado por método de dict | Chave `sources` no freshness (decisão registrada na Task 2) |
| Autoescape do Jinja quebrar spans coloridos | `|safe` na macro `met`, justificado (Task 4, nota) |
| Hook PostToolUse "falhando" durante RED | Comportamento esperado e documentado no topo do plano |
