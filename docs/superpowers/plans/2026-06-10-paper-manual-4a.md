# Paper Manual 4a — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sub-fatia 4a do diário paper manual: tabela `paper_manual_trades`, módulo puro `paper_data.py` (criar/anular/fechar/listar com carimbo de contexto), tracker cron `scripts/paper_tracker.py`, página de registro `/raiox/paper` com gráfico de níveis e painel de condições.

**Architecture:** Molde das Fatias 1-3 do Trade Desk: backend puro testável (conn/`get_candles_fn`/`now_s` injetáveis) + rotas finas no `dashboard_server.py` + template server-side Jinja + JS local mínimo. Tracker é CLI idempotente rodado por cron com flock (padrão k_collector). Spec: `docs/superpowers/specs/2026-06-10-paper-manual-design.md`.

**Tech Stack:** Python 3.13, Flask, SQLite (WAL), pandas (DataFrame do `market.get_candles`), lightweight-charts local, pytest.

**Regras da casa (sobrepõem o fluxo padrão da skill):**
- **NÃO commitar por task.** Commit só com OK explícito do Gabriel, ao final, código e docs separados (regra do CLAUDE.md). Os steps de commit foram substituídos por "checkpoint: suite verde".
- Hook PostToolUse roda a suite inteira a cada Write/Edit de `.py` — espere o resultado do hook; os comandos `pytest ... -v` abaixo servem pra iterar num teste específico.
- Branch: `lab/trend-following-2026-06-02`.

---

## Constantes compartilhadas (referência pra todas as tasks)

- Fee: `FEE_ROUND_TRIP_PP = 0.2` (0,1% taker spot por lado, em pontos percentuais).
- Tolerância de entrada: `ENTRY_TOLERANCE = 0.005` (±0,5% do close do último candle 15m fechado).
- Janela de void: `VOID_WINDOW_S = 600`.
- Candle 15m: `CANDLE_S = 900`.
- PnL: long bruto = `(exit-entry)/entry*100`; short bruto = `(entry-exit)/entry*100`; net = bruto − 0,2.

---

### Task 1: `paper_data.py` — schema, validações e `create_trade` com carimbo

**Files:**
- Create: `paper_data.py`
- Test: `tests/test_paper_data.py`

- [ ] **Step 1: Escrever os testes de validação e criação (falham: módulo não existe)**

```python
"""Testes do paper_data (diário paper manual — Fatia 4a).
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
    ({"entry_price": "2700"}, "preco atual"),    # fora da tolerancia ±0,5% de 2500
    ({"entry_price": "abc"}, "numero"),
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
```

- [ ] **Step 2: Rodar e confirmar falha por módulo ausente**

Run: `cd ~/crypto_ai_bot && source .venv/bin/activate && python -m pytest tests/test_paper_data.py -v 2>&1 | tail -5`
Expected: `ModuleNotFoundError: No module named 'paper_data'` (erro de coleta).

- [ ] **Step 3: Implementar `paper_data.py` (schema + create_trade)**

```python
"""Diario paper manual (Fatia 4a do Trade Desk) — funcoes puras.

Registra teses de trade manual ANTES do resultado (tese imutavel), carimba o
contexto estrutural cru do market_read no momento do registro e acompanha via
scripts/paper_tracker.py. Mede o trader; NUNCA opina sobre o trade.

Spec: docs/superpowers/specs/2026-06-10-paper-manual-design.md
Nome da tabela e paper_manual_trades — paper_trades JA EXISTE (legado).
"""
from __future__ import annotations

import json
import sqlite3
import time

import market_read
from mercado_data import SUPPORTED_MARKET_SYMBOLS, normalize_symbol

FEE_ROUND_TRIP_PP = 0.2
ENTRY_TOLERANCE = 0.005
VOID_WINDOW_S = 600
CANDLE_S = 900

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_manual_trades (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at       INTEGER NOT NULL,
  symbol           TEXT NOT NULL,
  direction        TEXT NOT NULL CHECK(direction IN ('long','short')),
  entry_price      REAL NOT NULL,
  stop_price       REAL NOT NULL,
  target_price     REAL NOT NULL,
  thesis           TEXT NOT NULL,
  tags             TEXT,
  context_snapshot TEXT,
  status           TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed','void')),
  exit_reason      TEXT CHECK(exit_reason IN ('stop','target','manual')),
  exit_price       REAL,
  exit_ts          INTEGER,
  mfe_price        REAL,
  mae_price        REAL,
  last_checked_ts  INTEGER,
  void_reason      TEXT
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _last_closed_price(get_candles_fn, symbol: str, now_s: int) -> float | None:
    """Close do ultimo candle 15m FECHADO (open_time + 900 <= now)."""
    try:
        df = get_candles_fn(symbol, "15m", 3)
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    closed = df[[int(t.timestamp()) + CANDLE_S <= now_s for t in df["time"]]]
    if len(closed) == 0:
        return None
    return float(closed.iloc[-1]["close"])


def _normalize_tags(raw: str) -> str | None:
    tags = [t.strip().lower() for t in (raw or "").split(",") if t.strip()]
    return ",".join(tags) if tags else None


def _build_snapshot(conn: sqlite3.Connection, symbol: str, now_s: int) -> str:
    """Carimbo CRU do market_read; leitura que falhar vira None (nao bloqueia)."""
    def safe(fn):
        try:
            return fn()
        except Exception:
            return None
    pressure = safe(lambda: next(
        (p for p in market_read.read_pressure(conn, 24) if p.get("symbol") == symbol), None))
    snap = {
        "schema_version": 1,
        "regime": safe(lambda: market_read.read_regime(conn)),
        "symbol": safe(lambda: market_read.read_symbol(conn, symbol)),
        "pressure_symbol": pressure,
        "freshness": safe(lambda: market_read.read_freshness(conn, now_s)),
    }
    return json.dumps(snap, default=str)


def create_trade(conn: sqlite3.Connection, get_candles_fn, now_s: int, form: dict) -> dict:
    """Valida e insere um trade paper com carimbo. Retorna {ok, trade_id|errors}."""
    errors: list[str] = []
    symbol = normalize_symbol(form.get("symbol", ""))
    if symbol is None:
        errors.append("simbolo nao suportado")
    direction = form.get("direction", "")
    if direction not in ("long", "short"):
        errors.append("direcao invalida")
    thesis = (form.get("thesis") or "").strip()
    if not thesis:
        errors.append("tese e obrigatoria")
    prices: dict[str, float] = {}
    for field in ("entry_price", "stop_price", "target_price"):
        try:
            prices[field] = float(form.get(field, ""))
            if prices[field] <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{field} nao e numero valido")
    if errors:
        return {"ok": False, "errors": errors}

    entry, stop, target = prices["entry_price"], prices["stop_price"], prices["target_price"]
    if direction == "long" and not (stop < entry < target):
        errors.append("long exige stop < entrada < alvo")
    if direction == "short" and not (target < entry < stop):
        errors.append("short exige alvo < entrada < stop")

    ref = _last_closed_price(get_candles_fn, symbol, now_s)
    if ref is None:
        errors.append("preco atual indisponivel — registro bloqueado")
    elif abs(entry - ref) / ref > ENTRY_TOLERANCE:
        errors.append(f"entrada longe do preco atual ({ref:g}) — tolerancia ±0,5%")
    if errors:
        return {"ok": False, "errors": errors}

    cur = conn.execute(
        "INSERT INTO paper_manual_trades (created_at, symbol, direction, entry_price,"
        " stop_price, target_price, thesis, tags, context_snapshot, status,"
        " mfe_price, mae_price) VALUES (?,?,?,?,?,?,?,?,?,'open',?,?)",
        (now_s, symbol, direction, entry, stop, target, thesis,
         _normalize_tags(form.get("tags", "")),
         _build_snapshot(conn, symbol, now_s), entry, entry),
    )
    conn.commit()
    return {"ok": True, "trade_id": cur.lastrowid}
```

- [ ] **Step 4: Rodar os testes da task**

Run: `python -m pytest tests/test_paper_data.py -v 2>&1 | tail -15`
Expected: todos PASS. O hook PostToolUse confirma a suite inteira verde.

---

### Task 2: `paper_data.py` — void, fechamento manual e listagem

**Files:**
- Modify: `paper_data.py` (append)
- Test: `tests/test_paper_data.py` (append)

- [ ] **Step 1: Escrever os testes (falham: funções não existem)**

```python
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
    fechado = out["fechados"][0]
    assert fechado["id"] == t2
    assert fechado["pnl_gross_pct"] == pytest.approx(2.0)
    assert fechado["pnl_net_pct"] == pytest.approx(1.8)


def test_pnl_short(conn):
    assert paper_data.pnl_gross_pct("short", 2500.0, 2400.0) == pytest.approx(4.0)
    assert paper_data.pnl_gross_pct("long", 2500.0, 2400.0) == pytest.approx(-4.0)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest tests/test_paper_data.py -v 2>&1 | tail -8`
Expected: novos testes FAIL com `AttributeError: ... 'void_trade'`.

- [ ] **Step 3: Implementar void/close/list/pnl em `paper_data.py`**

```python
def pnl_gross_pct(direction: str, entry: float, exit_price: float) -> float:
    if direction == "long":
        return (exit_price - entry) / entry * 100.0
    return (entry - exit_price) / entry * 100.0


def _get_open(conn: sqlite3.Connection, trade_id: int):
    return conn.execute(
        "SELECT * FROM paper_manual_trades WHERE id=? AND status='open'",
        (trade_id,)).fetchone()


def void_trade(conn: sqlite3.Connection, now_s: int, trade_id: int, reason: str) -> dict:
    row = _get_open(conn, trade_id)
    if row is None:
        return {"ok": False, "errors": ["trade nao encontrado ou nao esta aberto"]}
    if now_s - row["created_at"] > VOID_WINDOW_S:
        return {"ok": False, "errors": ["janela de anulacao (10 min) expirou"]}
    conn.execute("UPDATE paper_manual_trades SET status='void', void_reason=? WHERE id=?",
                 ((reason or "").strip() or "fat-finger", trade_id))
    conn.commit()
    return {"ok": True}


def close_manual(conn: sqlite3.Connection, get_candles_fn, now_s: int, trade_id: int) -> dict:
    row = _get_open(conn, trade_id)
    if row is None:
        return {"ok": False, "errors": ["trade nao encontrado ou nao esta aberto"]}
    price = _last_closed_price(get_candles_fn, row["symbol"], now_s)
    if price is None:
        return {"ok": False, "errors": ["preco atual indisponivel — tente de novo"]}
    conn.execute(
        "UPDATE paper_manual_trades SET status='closed', exit_reason='manual',"
        " exit_price=?, exit_ts=? WHERE id=?", (price, now_s, trade_id))
    conn.commit()
    return {"ok": True, "exit_price": price}


def _trade_view(row, now_s: int) -> dict:
    d = dict(row)
    entry = row["entry_price"]
    sign = 1.0 if row["direction"] == "long" else -1.0
    if row["mfe_price"] is not None:
        d["mfe_pct"] = sign * (row["mfe_price"] - entry) / entry * 100.0
    if row["mae_price"] is not None:
        d["mae_pct"] = sign * (row["mae_price"] - entry) / entry * 100.0
    d["idade_min"] = max(0, (now_s - row["created_at"]) // 60)
    d["can_void"] = row["status"] == "open" and now_s - row["created_at"] <= VOID_WINDOW_S
    d["tags_list"] = (row["tags"] or "").split(",") if row["tags"] else []
    if row["status"] == "closed":
        d["pnl_gross_pct"] = pnl_gross_pct(row["direction"], entry, row["exit_price"])
        d["pnl_net_pct"] = d["pnl_gross_pct"] - FEE_ROUND_TRIP_PP
    return d


def list_trades(conn: sqlite3.Connection, now_s: int, closed_limit: int = 20) -> dict:
    ensure_schema(conn)
    abertos = [_trade_view(r, now_s) for r in conn.execute(
        "SELECT * FROM paper_manual_trades WHERE status='open' ORDER BY created_at DESC")]
    fechados = [_trade_view(r, now_s) for r in conn.execute(
        "SELECT * FROM paper_manual_trades WHERE status='closed'"
        " ORDER BY exit_ts DESC LIMIT ?", (closed_limit,))]
    return {"abertos": abertos, "fechados": fechados}
```

- [ ] **Step 4: Rodar os testes da task**

Run: `python -m pytest tests/test_paper_data.py -v 2>&1 | tail -15`
Expected: todos PASS (Task 1 + Task 2). Checkpoint: suite verde via hook.

---

### Task 3: `scripts/paper_tracker.py` — tracker idempotente

**Files:**
- Create: `scripts/paper_tracker.py`
- Test: `tests/test_paper_tracker.py`

- [ ] **Step 1: Escrever os testes (falham: módulo não existe)**

```python
"""Testes do paper_tracker. Candles sinteticos via DataFrame pandas;
NOW_S e multiplo de 900 (boundary limpo) — derivado do test_market_read."""
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
from tests.test_market_read import HOUR, NOW_S, add_funding, add_price
from tests.test_paper_data import FORM_OK, fake_candles_fn

import paper_data
import paper_tracker

T0 = (NOW_S // 900) * 900          # boundary 15m <= NOW_S


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
    c.commit()
    return c


def mk_open_trade(conn, created_at, direction="long", entry=2500.0, stop=2450.0,
                  target=2600.0):
    form = dict(FORM_OK, direction=direction, entry_price=str(entry),
                stop_price=str(stop), target_price=str(target))
    res = paper_data.create_trade(conn, fake_candles_fn(close=entry), created_at, form)
    assert res["ok"], res
    return res["trade_id"]


def candles_df(specs):
    """specs: lista de (open_time_s, open, high, low, close)."""
    return pd.DataFrame([
        {"time": pd.Timestamp(t, unit="s"), "open": o, "high": h, "low": l,
         "close": c, "volume": 1.0} for t, o, h, l, c in specs])


def df_fn(df):
    return lambda symbol, interval, limit: df


def get(conn, tid):
    return conn.execute("SELECT * FROM paper_manual_trades WHERE id=?", (tid,)).fetchone()


def test_toca_alvo_fecha_no_alvo(conn):
    tid = mk_open_trade(conn, T0 - 100)            # boundary do trade = T0
    df = candles_df([(T0, 2500, 2550, 2480, 2540),
                     (T0 + 900, 2540, 2610, 2530, 2590)])
    out = paper_tracker.process_open_trades(conn, df_fn(df), T0 + 1800)
    row = get(conn, tid)
    assert row["status"] == "closed" and row["exit_reason"] == "target"
    assert row["exit_price"] == 2600.0 and row["exit_ts"] == T0 + 900
    assert out["closed"] == 1


def test_toca_stop_fecha_no_stop(conn):
    tid = mk_open_trade(conn, T0 - 100)
    df = candles_df([(T0, 2500, 2520, 2440, 2460)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["exit_reason"] == "stop" and row["exit_price"] == 2450.0


def test_candle_ambiguo_assume_stop(conn):
    tid = mk_open_trade(conn, T0 - 100)
    df = candles_df([(T0, 2500, 2650, 2400, 2550)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    assert get(conn, tid)["exit_reason"] == "stop"


def test_gap_fecha_no_open(conn):
    tid = mk_open_trade(conn, T0 - 100)
    df = candles_df([(T0, 2380, 2400, 2350, 2390)])   # abre abaixo do stop 2450
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["exit_reason"] == "stop" and row["exit_price"] == 2380.0


def test_short_toca_alvo(conn):
    tid = mk_open_trade(conn, T0 - 100, direction="short", entry=2500.0,
                        stop=2550.0, target=2400.0)
    df = candles_df([(T0, 2500, 2520, 2390, 2410)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["exit_reason"] == "target" and row["exit_price"] == 2400.0


def test_ignora_candle_pre_registro_e_parcial(conn):
    tid = mk_open_trade(conn, T0 + 60)               # registro DEPOIS de T0 abrir
    df = candles_df([(T0, 2500, 2700, 2300, 2510),   # toque "antes" do registro: ignora
                     (T0 + 900, 2510, 2530, 2495, 2520)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 1500)  # T0+900 ainda aberto
    row = get(conn, tid)
    assert row["status"] == "open" and row["last_checked_ts"] is None


def test_atualiza_mfe_mae_sem_fechar(conn):
    tid = mk_open_trade(conn, T0 - 100)
    df = candles_df([(T0, 2500, 2580, 2460, 2570)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["status"] == "open"
    assert row["mfe_price"] == 2580.0 and row["mae_price"] == 2460.0
    assert row["last_checked_ts"] == T0


def test_idempotente_rodar_duas_vezes(conn):
    mk_open_trade(conn, T0 - 100)
    df = candles_df([(T0, 2500, 2580, 2460, 2570)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    out2 = paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    assert out2 == {"checked": 1, "closed": 0}        # nada novo a varrer, nada muda


def test_sem_dados_mantem_aberto(conn):
    tid = mk_open_trade(conn, T0 - 100)
    out = paper_tracker.process_open_trades(conn, lambda *a: None, T0 + 900)
    assert get(conn, tid)["status"] == "open"
    assert out["checked"] == 1 and out["closed"] == 0
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest tests/test_paper_tracker.py -v 2>&1 | tail -5`
Expected: `ModuleNotFoundError: No module named 'paper_tracker'`.

- [ ] **Step 3: Implementar `scripts/paper_tracker.py`**

```python
"""Tracker do diario paper manual — cron */15 com flock (padrao k_collector).

Para cada trade aberto em paper_manual_trades, varre candles 15m FECHADOS
desde o ultimo check e aplica as regras da spec (2026-06-10-paper-manual-design.md):
toque de stop/alvo por high/low, candle ambiguo = stop (pessimista), gap = fill
no open, MFE/MAE, primeiro candle valido = boundary 15m apos o registro.
Idempotente: reprocessar a mesma janela e no-op.

Uso:
    python scripts/paper_tracker.py
Cron:
    */15 * * * * /usr/bin/flock -n /tmp/paper_tracker.lock \
      /home/pi/crypto_ai_bot/.venv/bin/python \
      /home/pi/crypto_ai_bot/scripts/paper_tracker.py \
      >> /home/pi/crypto_ai_bot/logs/paper_tracker.log 2>&1
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import paper_data
from paper_data import CANDLE_S

DB_PATH = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")
MAX_CANDLES = 1000


def _first_boundary(created_at: int) -> int:
    return ((created_at + CANDLE_S - 1) // CANDLE_S) * CANDLE_S


def _check_candle(direction: str, open_p: float, high: float, low: float,
                  stop: float, target: float):
    """Retorna (exit_reason, exit_price) ou None. Ambiguo => stop (pessimista)."""
    if direction == "long":
        hit_stop, hit_target = low <= stop, high >= target
        if hit_stop:
            return ("stop", open_p if open_p <= stop else stop)
        if hit_target:
            return ("target", open_p if open_p >= target else target)
    else:
        hit_stop, hit_target = high >= stop, low <= target
        if hit_stop:
            return ("stop", open_p if open_p >= stop else stop)
        if hit_target:
            return ("target", open_p if open_p <= target else target)
    return None


def _process_trade(conn: sqlite3.Connection, get_candles_fn, now_s: int, row) -> bool:
    """Processa 1 trade aberto; retorna True se fechou."""
    start = (row["last_checked_ts"] + CANDLE_S if row["last_checked_ts"] is not None
             else _first_boundary(row["created_at"]))
    if start + CANDLE_S > now_s:
        return False                       # nenhum candle fechado novo
    try:
        need = min(MAX_CANDLES, (now_s - start) // CANDLE_S + 2)
        df = get_candles_fn(row["symbol"], "15m", int(need))
    except Exception:
        return False
    if df is None or len(df) == 0:
        return False

    mfe, mae = row["mfe_price"], row["mae_price"]
    direction = row["direction"]
    closed = False
    last_processed = row["last_checked_ts"]
    for _, c in df.sort_values("time").iterrows():
        open_time = int(c["time"].timestamp())
        if open_time < start or open_time + CANDLE_S > now_s:
            continue                       # fora da janela ou candle ainda aberto
        high, low, open_p = float(c["high"]), float(c["low"]), float(c["open"])
        if direction == "long":
            mfe, mae = max(mfe, high), min(mae, low)
        else:
            mfe, mae = min(mfe, low), max(mae, high)
        last_processed = open_time
        hit = _check_candle(direction, open_p, high, low,
                            row["stop_price"], row["target_price"])
        if hit is not None:
            conn.execute(
                "UPDATE paper_manual_trades SET status='closed', exit_reason=?,"
                " exit_price=?, exit_ts=?, mfe_price=?, mae_price=?, last_checked_ts=?"
                " WHERE id=?",
                (hit[0], hit[1], open_time, mfe, mae, open_time, row["id"]))
            closed = True
            break
    if not closed and last_processed != row["last_checked_ts"]:
        conn.execute(
            "UPDATE paper_manual_trades SET mfe_price=?, mae_price=?, last_checked_ts=?"
            " WHERE id=?", (mfe, mae, last_processed, row["id"]))
    conn.commit()
    return closed


def process_open_trades(conn: sqlite3.Connection, get_candles_fn, now_s: int) -> dict:
    paper_data.ensure_schema(conn)
    rows = conn.execute("SELECT * FROM paper_manual_trades WHERE status='open'").fetchall()
    closed = sum(1 for r in rows if _process_trade(conn, get_candles_fn, now_s, r))
    return {"checked": len(rows), "closed": closed}


def main() -> int:
    import market
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        out = process_open_trades(conn, market.get_candles, int(time.time()))
        print(f"[paper_tracker] {time.strftime('%Y-%m-%d %H:%M:%S')} "
              f"checked={out['checked']} closed={out['closed']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Rodar os testes da task**

Run: `python -m pytest tests/test_paper_tracker.py -v 2>&1 | tail -15`
Expected: todos PASS. Checkpoint: suite verde via hook.

---

### Task 4: `registro_view` + rotas + extensão do `/api/raiox/candles`

**Files:**
- Modify: `paper_data.py` (append `registro_view`)
- Modify: `dashboard_server.py` (4 rotas novas + 1 linha no `api_raiox_candles`)
- Test: `tests/test_paper_data.py` e `tests/test_paper_endpoints.py` (novo)

- [ ] **Step 1: Teste do `registro_view` (append em test_paper_data.py)**

```python
def test_registro_view_monta_condicoes_e_listas(conn):
    _mk_trade(conn)
    view = paper_data.registro_view(conn, NOW_S + 60, "ETHUSDT")
    assert view["symbol"] == "ETHUSDT"
    assert list(view["symbols"]) == list(paper_data.SUPPORTED_MARKET_SYMBOLS)
    assert view["condicoes"] is not None        # symbol_view do mercado_data
    assert len(view["abertos"]) == 1
    assert view["read_at"]


def test_registro_view_simbolo_invalido_cai_pra_btc(conn):
    view = paper_data.registro_view(conn, NOW_S, "FOO")
    assert view["symbol"] == "BTCUSDT"
```

- [ ] **Step 2: Implementar `registro_view` em `paper_data.py`**

```python
def registro_view(conn: sqlite3.Connection, now_s: int, symbol_raw: str) -> dict:
    """Dados da pagina de registro: simbolo selecionado, condicoes (view do
    /mercado — descritiva, mesma leitura que vira carimbo), abertos/fechados."""
    import mercado_data
    ensure_schema(conn)
    symbol = normalize_symbol(symbol_raw or "") or "BTCUSDT"
    try:
        condicoes = mercado_data.symbol_view(conn, symbol, now_s)
    except Exception:
        condicoes = None
    trades = list_trades(conn, now_s)
    return {
        "symbol": symbol,
        "symbols": SUPPORTED_MARKET_SYMBOLS,
        "condicoes": condicoes,
        "abertos": trades["abertos"],
        "fechados": trades["fechados"],
        "read_at": time.strftime("%d/%m %H:%M", time.localtime(now_s)),
    }
```

Run: `python -m pytest tests/test_paper_data.py -v 2>&1 | tail -8` — Expected: PASS.

- [ ] **Step 3: Testes de endpoint (novo arquivo, molde do test_mercado_endpoints)**

```python
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
    FORBIDDEN_SIGNAL_WORDS, HOUR, NOW_S, add_funding, add_price,
)
from tests.test_paper_data import fake_candles_fn

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
    for word in FORBIDDEN_SIGNAL_WORDS:
        assert word not in html, f"linguagem de sinal no template: {word}"


def test_paper_criar_e_listar(client):
    r = client.post("/raiox/paper/criar", data={
        "symbol": "ETHUSDT", "direction": "long", "entry_price": "2500",
        "stop_price": "2450", "target_price": "2600", "thesis": "teste", "tags": ""})
    assert r.status_code == 302
    html = client.get("/raiox/paper?symbol=ETHUSDT").data.decode()
    assert "ETHUSDT" in html and "fechar agora" in html


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


def test_api_candles_aceita_14_simbolos(client, monkeypatch):
    import dashboard_server
    monkeypatch.setattr(dashboard_server, "_binance_candles_adapter",
                        lambda s, i, l: fake_candles_fn()(s, i, l))
    r = client.get(f"/api/raiox/candles?symbol=SOLUSDT&interval=15m"
                   f"&start={NOW_S-3600}&end={NOW_S}")
    assert r.status_code != 400 or b"symbol_invalido" not in r.data
```

Run: `python -m pytest tests/test_paper_endpoints.py -v 2>&1 | tail -5`
Expected: FAIL (rotas/template não existem).

- [ ] **Step 4: Rotas em `dashboard_server.py`** (após as rotas do mercado, antes de `/legacy`)

```python
import paper_data  # junto dos imports raiox_data/mercado_data no topo

# get_candles_fn das rotas paper — indirecao p/ monkeypatch nos testes
_paper_candles_fn = market.get_candles


@app.route("/raiox/paper")
def paper_page():
    conn = db._get_conn()
    try:
        view = paper_data.registro_view(conn, int(time.time()),
                                        request.args.get("symbol", "BTCUSDT"))
    finally:
        conn.close()
    return render_template("paper.html", view=view, active_page="paper", errors=None)


@app.route("/raiox/paper/criar", methods=["POST"])
@require_post_auth
def paper_criar():
    now_s = int(time.time())
    conn = db._get_conn()
    try:
        res = paper_data.create_trade(conn, _paper_candles_fn, now_s,
                                      request.form.to_dict())
        if res["ok"]:
            return redirect(f"/raiox/paper?symbol={request.form.get('symbol', 'BTCUSDT')}")
        view = paper_data.registro_view(conn, now_s,
                                        request.form.get("symbol", "BTCUSDT"))
    finally:
        conn.close()
    return render_template("paper.html", view=view, active_page="paper",
                           errors=res["errors"]), 400


@app.route("/raiox/paper/<int:trade_id>/anular", methods=["POST"])
@require_post_auth
def paper_anular(trade_id):
    conn = db._get_conn()
    try:
        paper_data.void_trade(conn, int(time.time()), trade_id,
                              request.form.get("reason", ""))
    finally:
        conn.close()
    return redirect("/raiox/paper")


@app.route("/raiox/paper/<int:trade_id>/fechar", methods=["POST"])
@require_post_auth
def paper_fechar(trade_id):
    conn = db._get_conn()
    try:
        paper_data.close_manual(conn, _paper_candles_fn, int(time.time()), trade_id)
    finally:
        conn.close()
    return redirect("/raiox/paper")
```

E no `api_raiox_candles`, trocar a validação de símbolo:

```python
    if (symbol not in raiox_data.VALID_SYMBOLS
            and symbol not in mercado_data.SUPPORTED_MARKET_SYMBOLS):
        return jsonify({"ok": False, "error": "symbol_invalido", "message": "simbolo nao suportado"}), 400
```

- [ ] **Step 5: Template `templates/paper.html` + nav (Task 5 traz o JS)**

Template estende `base.html`, segue a estrutura do mockup aprovado. Esqueleto completo (classes/ids são contrato com `paper.js`):

```html
{% extends "base.html" %}
{% block title %}Paper — Trade Desk{% endblock %}
{% block content %}
<div class="paper-wrap">
  {% if errors %}
  <div class="paper-errors">{% for e in errors %}<div>⚠️ {{ e }}</div>{% endfor %}</div>
  {% endif %}

  <div class="paper-grid">
    <div class="paper-chart-col">
      <div class="paper-chart-head">
        <select id="paper-symbol-nav">
          {% for s in view.symbols %}
          <option value="{{ s }}" {% if s == view.symbol %}selected{% endif %}>{{ s }}</option>
          {% endfor %}
        </select>
        <span class="paper-tfs"><button data-tf="15m">15m</button><button data-tf="1h">1h</button><button class="active" data-tf="4h">4h</button><button data-tf="1d">1d</button></span>
      </div>
      <div id="paper-chart" data-symbol="{{ view.symbol }}"></div>
      <p class="hint">clique no gráfico preenche o nível selecionado</p>
    </div>

    <form class="paper-form" method="post" action="/raiox/paper/criar">
      <input type="hidden" name="symbol" value="{{ view.symbol }}">
      <label>direção</label>
      <div class="dir-toggle">
        <label><input type="radio" name="direction" value="long" checked> long</label>
        <label><input type="radio" name="direction" value="short"> short (tese)</label>
      </div>
      <label>entrada <input name="entry_price" id="f-entry" required></label>
      <label>stop <input name="stop_price" id="f-stop" required></label>
      <label>alvo <input name="target_price" id="f-target" required></label>
      <div id="rr-line" class="hint">R:R —</div>
      <label>tese (obrigatória) <textarea name="thesis" rows="2" required></textarea></label>
      <label>tags <input name="tags" placeholder="pullback, zona-liq"></label>
      <button type="submit">Registrar tese</button>
    </form>
  </div>

  <section class="paper-condicoes">
    <h3>Condições agora — {{ view.symbol }} <small>será gravado junto com a tese</small></h3>
    {% if view.condicoes %}{% include "_paper_condicoes.html" %}{% else %}<p>n/d</p>{% endif %}
  </section>

  <section class="paper-abertos">
    <h3>Abertos ({{ view.abertos|length }})</h3>
    {% for t in view.abertos %}
    <div class="paper-trade-row" data-created="{{ t.created_at }}">
      <strong>{{ t.symbol }}</strong> <span class="badge">{{ t.direction }}</span>
      <span>entrada {{ t.entry_price }}</span>
      {% if t.mfe_pct is defined %}<span class="positive">MFE {{ "%.1f"|format(t.mfe_pct) }}%</span>{% endif %}
      {% if t.mae_pct is defined %}<span class="negative">MAE {{ "%.1f"|format(t.mae_pct) }}%</span>{% endif %}
      {% if t.can_void %}
      <form method="post" action="/raiox/paper/{{ t.id }}/anular"><button>anular</button></form>
      {% endif %}
      <form method="post" action="/raiox/paper/{{ t.id }}/fechar"><button>fechar agora</button></form>
    </div>
    {% else %}<p>nenhum trade aberto</p>{% endfor %}
  </section>

  <section class="paper-fechados">
    <h3>Fechados recentes</h3>
    {% for t in view.fechados %}
    <div class="paper-trade-row">
      <strong>{{ t.symbol }}</strong> <span class="badge">{{ t.direction }}</span>
      <span>{{ t.exit_reason }}</span>
      <span class="{{ 'positive' if t.pnl_net_pct > 0 else 'negative' }}">net {{ "%.2f"|format(t.pnl_net_pct) }}%</span>
    </div>
    {% else %}<p>nenhum ainda — registre a primeira tese</p>{% endfor %}
  </section>
</div>
<script src="/static/js/lightweight-charts.standalone.production.js"></script>
<script src="/static/js/paper.js"></script>
{% endblock %}
```

`templates/_paper_condicoes.html`: renderiza `view.condicoes` (estrutura do `symbol_view` — espelhar os campos usados em `mercado_symbol.html`, versão compacta em grid; **reusar macros de `_mercado_macros.html`** pra valores com sinal — lição Jinja: span dentro de macro, nunca concatenado). Incluir frescor (`view.condicoes.freshness`) e tradução.

Nav em `templates/base.html` (os 2 blocos, igual feito pra Mercado):

```html
<li><a href="/raiox/paper" {% if active_page == 'paper' %}class="active"{% endif %}>Paper</a></li>
```
```html
<a href="/raiox/paper" {% if active_page == 'paper' %}class="active"{% endif %}>Paper</a>
```

- [ ] **Step 6: Rodar os testes de endpoint**

Run: `python -m pytest tests/test_paper_endpoints.py -v 2>&1 | tail -12`
Expected: todos PASS. Atenção ao anti-sinal: se falhar, a palavra proibida está no template — reescrever o texto, nunca relaxar o teste.

---

### Task 5: `static/js/paper.js` — gráfico, níveis clicáveis, R:R, countdown

**Files:**
- Create: `static/js/paper.js`
- Modify: `static/css/style.css` (classes `.paper-*`, seguir o padrão visual das classes `.mercado-*`/`.raiox-*` existentes — grid 2 colunas, cards, badges)

- [ ] **Step 1: Implementar `paper.js`**

```javascript
// Aba Paper — grafico com niveis clicaveis + R:R + countdown void.
// Reusa /api/raiox/candles (mesma fonte do Raio-X). Sem lib nova.
const PP = { chart: null, series: null, lines: {}, activeField: "f-entry", tf: "4h" };
const pq = (s) => document.querySelector(s);
const SYMBOL = pq("#paper-chart").dataset.symbol;
const TF_SEC = { "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 };
const LINE_STYLE = {
  "f-entry": { color: "#378ADD", title: "entrada" },
  "f-stop": { color: "#E24B4A", title: "stop" },
  "f-target": { color: "#639922", title: "alvo" },
};

function initChart() {
  const el = pq("#paper-chart");
  PP.chart = LightweightCharts.createChart(el, { height: 360, layout: { background: { color: "transparent" } } });
  PP.series = PP.chart.addCandlestickSeries();
  PP.chart.subscribeClick((param) => {
    if (!param.point) return;
    const price = PP.series.coordinateToPrice(param.point.y);
    if (price == null) return;
    const input = pq("#" + PP.activeField);
    input.value = Number(price.toPrecision(6));
    input.dispatchEvent(new Event("input"));
  });
}

async function loadCandles() {
  const end = Math.floor(Date.now() / 1000);
  const start = end - 60 * 86400;
  const url = `/api/raiox/candles?symbol=${SYMBOL}&interval=${PP.tf}&start=${start}&end=${end}&margin=0`;
  const res = await fetch(url);
  const data = await res.json();
  if (data.ok) PP.series.setData(data.candles);
}

function refreshLine(fieldId) {
  const v = parseFloat(pq("#" + fieldId).value);
  if (PP.lines[fieldId]) { PP.series.removePriceLine(PP.lines[fieldId]); PP.lines[fieldId] = null; }
  if (!isFinite(v) || v <= 0) return;
  const st = LINE_STYLE[fieldId];
  PP.lines[fieldId] = PP.series.createPriceLine({ price: v, color: st.color, lineStyle: 2, title: st.title });
}

function refreshRR() {
  const e = parseFloat(pq("#f-entry").value), s = parseFloat(pq("#f-stop").value), t = parseFloat(pq("#f-target").value);
  const out = pq("#rr-line");
  if (![e, s, t].every((x) => isFinite(x) && x > 0) || e === s) { out.textContent = "R:R —"; return; }
  const risk = Math.abs(e - s) / e * 100, reward = Math.abs(t - e) / e * 100;
  out.textContent = `risco ${risk.toFixed(1)}% · retorno ${reward.toFixed(1)}% · R:R 1 : ${(reward / risk).toFixed(1)}`;
}

function initForm() {
  ["f-entry", "f-stop", "f-target"].forEach((id) => {
    const input = pq("#" + id);
    input.addEventListener("focus", () => { PP.activeField = id; });
    input.addEventListener("input", () => { refreshLine(id); refreshRR(); });
  });
  pq("#paper-symbol-nav").addEventListener("change", (ev) => {
    window.location = "/raiox/paper?symbol=" + ev.target.value;
  });
  document.querySelectorAll(".paper-tfs button").forEach((b) => {
    b.addEventListener("click", (ev) => {
      ev.preventDefault();
      document.querySelectorAll(".paper-tfs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      PP.tf = b.dataset.tf;
      loadCandles();
    });
  });
}

function initVoidCountdown() {
  document.querySelectorAll(".paper-trade-row[data-created]").forEach((row) => {
    const btn = row.querySelector('form[action$="/anular"] button');
    if (!btn) return;
    const tick = () => {
      const left = 600 - (Math.floor(Date.now() / 1000) - Number(row.dataset.created));
      if (left <= 0) { btn.closest("form").remove(); return; }
      btn.textContent = `anular (${Math.ceil(left / 60)} min)`;
      setTimeout(tick, 15000);
    };
    tick();
  });
}

initChart();
initForm();
initVoidCountdown();
loadCandles();
```

Nota: confirmar no `raiox.js` o formato exato de `data.candles` consumido pelo `setData` (time/open/high/low/close) e copiar a mesma conversão se o raiox fizer alguma — anti-divergência.

- [ ] **Step 2: Suite verde (hook) + py_compile do dashboard**

Run: `python -c "import dashboard_server; print('OK')"`
Expected: `OK`. Suite inteira verde via hook.

---

### Task 6: cron, deploy de validação e checklist visual

**Files:**
- Modify: crontab do pi (via `crontab -l` + append)

- [ ] **Step 1: Instalar o cron do tracker**

```bash
(crontab -l; echo '*/15 * * * * /usr/bin/flock -n /tmp/paper_tracker.lock /home/pi/crypto_ai_bot/.venv/bin/python /home/pi/crypto_ai_bot/scripts/paper_tracker.py >> /home/pi/crypto_ai_bot/logs/paper_tracker.log 2>&1') | crontab -
crontab -l | grep paper_tracker
```
Expected: linha instalada (uma só).

- [ ] **Step 2: Rodar o tracker uma vez à mão (banco real, zero trades)**

Run: `python scripts/paper_tracker.py`
Expected: `[paper_tracker] ... checked=0 closed=0` (nenhum trade ainda; valida import de `market` e conexão real).

- [ ] **Step 3: Subir instância de validação na 5055**

```bash
cd ~/crypto_ai_bot && source .venv/bin/activate && DASHBOARD_PORT=5055 python dashboard_server.py > /tmp/dashboard_5055.log 2>&1 & echo "PID: $!"
sleep 6 && curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:5055/raiox/paper
```
Expected: `HTTP 200`. **Anotar o PID pro kill posterior.**

- [ ] **Step 4: Checklist de validação visual (Gabriel, na 5055)**

1. `/raiox/paper` abre com gráfico BTC e nav "Paper" ativa (desktop + hamburger mobile).
2. Trocar símbolo pra ETH → gráfico e condições acompanham.
3. Clicar nos campos entrada/stop/alvo e depois no gráfico → linhas azul/vermelha/verde aparecem; R:R atualiza.
4. Painel "condições agora" mostra leituras + tradução + frescor.
5. Registrar tese real (entrada ±0,5% do preço atual) → trade aparece em "Abertos" com botões anular (countdown) e fechar agora.
6. Tentar registrar com stop acima da entrada (long) → erro claro, formulário re-renderiza.
7. "fechar agora" fecha com close do último 15m; "anular" some após 10 min.
8. Console JS sem erros.

- [ ] **Step 5: Aguardar OK explícito do Gabriel → commit (código e docs separados) → restart cryptobot → validar na 5000 → matar 5055**

---

## Self-review do plano (feito na escrita)

- **Cobertura da spec (4a)**: tabela ✓ (Task 1), validações ✓ (T1), carimbo cru com falha→null ✓ (T1), void 10min ✓ (T2), close manual ✓ (T2), fees no list ✓ (T2), tracker com todas as regras (boundary, ambíguo=stop, gap=open, MFE/MAE, idempotência, sem dados) ✓ (T3), rotas+auth ✓ (T4), extensão candles pros 14 ✓ (T4), template+nav+anti-sinal+anti-escape ✓ (T4), JS níveis/R:R/countdown ✓ (T5), cron flock ✓ (T6). Espelho = 4b, fora deste plano (plano próprio depois).
- **Tipos consistentes**: `create_trade/void_trade/close_manual` retornam `{ok, ...}`; `get_candles_fn(symbol, interval, limit) -> DataFrame`; `process_open_trades -> {checked, closed}`.
- **Sem placeholders**: único item delegado é a conferência do formato de `data.candles` no raiox.js (nota explícita na Task 5, anti-divergência) e o `_paper_condicoes.html` espelhando `mercado_symbol.html` (contrato definido: campos do `symbol_view` + macros existentes).
