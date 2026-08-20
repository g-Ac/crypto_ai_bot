# Raio-X dos Trades — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Página web `/raiox/` no dashboard existente que mostra os trades do bot momentum como radiografia (gráfico de candle + entrada/SL/TP/saída + MFE/MAE), incluindo a posição aberta ao vivo — ferramenta de leitura, sem sinal nem recomendação.

**Architecture:** Backend puro em `raiox_data.py` (recebe `conn`/`state_path`/`get_candles_fn`, retorna dicts; testável sem Flask/rede). Endpoints finos `/api/raiox/*` em `dashboard_server.py`. Frontend vanilla com lightweight-charts servido localmente. Não toca no bot, no `/pip/`, no schema, nem no `market.py`.

**Tech Stack:** Python 3.13, Flask (já existe), sqlite3, pandas (via `market.get_candles`), pytest, lightweight-charts (JS, local).

---

## ⚙️ Convenção de processo (LER ANTES DE EXECUTAR)

1. **NÃO commitar sem OK explícito** (regra nº 8 do projeto). Cada task termina num **Checkpoint** (ler hook + `git diff`). Commit só quando o Gabriel disser.
2. **Hook-first.** O hook `PostToolUse` roda a suíte inteira (~975 testes, ~90s) e estoura o timeout de 60s. **Fonte de verdade = pytest focado** via `.venv/bin/python -m pytest tests/test_raiox_*.py`. A suíte completa roda 1× no fim (Task 10). Onde os steps trazem `pytest`, é o comando focado a rodar.
3. **Regras duras (do Gabriel):** não mexer em bot/main/momentum/`/pip/`/schema/`market.py`; não criar sinal/recomendação/score; lightweight-charts local (sem CDN); backend testável sem Flask; `entry_time` é estimado; PnL = `net_pnl_pct` com fallback `pnl_pct` (+ `pnl_source`).

---

## File Structure

- **Create** `raiox_data.py` (raiz) — leitura pura: tempo, trades, posição, candles wrapper, resumo factual.
- **Create** `tests/test_raiox_data.py` — testes unitários do backend (TDD).
- **Modify** `dashboard_server.py` — 4 rotas: `/raiox/`, `/api/raiox/trades`, `/api/raiox/trade/<id>`, `/api/raiox/candles`.
- **Create** `tests/test_raiox_endpoints.py` — testes de fumaça dos endpoints (DB/state temp).
- **Create** `templates/raiox.html` — página (estende `base.html`).
- **Create** `static/js/raiox.js` — frontend (feed + gráfico + ao vivo).
- **Create** `static/js/lightweight-charts.standalone.production.js` — lib local, versão fixa.
- **Modify** `templates/base.html` — item "Raio-X" no nav (desktop + mobile).

## Contrato de tipos (referência única)

```python
# raiox_data.py — constantes
MOMENTUM_INTERVAL_MIN = 15
VALID_SYMBOLS = {"BTCUSDT", "ETHUSDT"}
VALID_INTERVALS = ("15m", "1h", "4h", "1d")           # ordem = escala crescente
_INTERVAL_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
# frases de ACAO proibidas no texto factual (permite entrada/stop/alvo)
FORBIDDEN_ACTION_PHRASES = ("compre", "comprar", "venda agora", "vender agora",
                            "sinal", "recomendad", "operacao sugerida", "longar", "shortar")

_to_epoch_s(ts) -> int                  # ISO+tz ou 'YYYY-MM-DD HH:MM:SS' -> epoch s UTC
_pnl_of(row) -> tuple[float, str]       # (valor, 'net_pnl_pct'|'pnl_pct')
_exit_icon(exit_reason) -> str          # tp->🟢  sl->🔴  timeout->⏱️  outro->•
open_position(state_path) -> dict | None
list_trades(conn, state_path, limit=50) -> dict       # {"open": dict|None, "closed": [dict,...]}
trade_detail(conn, trade_id) -> dict | None
fetch_candles(symbol, interval, start_s, end_s, now_s, get_candles_fn, margin=20, max_bars=1000) -> dict
```

---

### Task 1: Scaffolding + normalização de tempo (`_to_epoch_s`)

TDD puro: teste primeiro, módulo depois (o import falha = RED).

**Files:** Test `tests/test_raiox_data.py`; Create `raiox_data.py`.

- [ ] **Step 1 (RED): criar `tests/test_raiox_data.py`**

```python
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import raiox_data as rx   # FALHA ate o modulo existir (RED)


def test_to_epoch_s_iso_with_tz():
    assert rx._to_epoch_s("2026-06-08T17:07:43+00:00") == 1780938463


def test_to_epoch_s_naive_space_format():
    # 'YYYY-MM-DD HH:MM:SS' tratado como UTC
    assert rx._to_epoch_s("2026-06-08 18:00:00") == 1780941600


def test_to_epoch_s_iso_with_microseconds():
    assert rx._to_epoch_s("2026-06-08T17:07:43.797916+00:00") == 1780938463


def test_to_epoch_s_nonzero_offset():
    # 14:07:43-03:00 == 17:07:43Z
    assert rx._to_epoch_s("2026-06-08T14:07:43-03:00") == 1780938463
```

*(Epochs conferidos no Python: `17:07:43Z`→1780938463, `18:00:00`→1780941600.)*

- [ ] **Step 2 (RED): confirmar falha** — `python -m pytest tests/test_raiox_data.py -q` → `ModuleNotFoundError: raiox_data`.

- [ ] **Step 3 (GREEN): criar `raiox_data.py`**

```python
"""
Leitura para o Raio-X dos Trades (pagina web /raiox/).

Funcoes PURAS: recebem conn / state_path / get_candles_fn e retornam dict/list.
Sem Flask, sem rede embutida na leitura de banco/state. NAO gera sinal nem recomendacao.
Mostra os trades do bot momentum como radiografia.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

MOMENTUM_INTERVAL_MIN = 15
VALID_SYMBOLS = {"BTCUSDT", "ETHUSDT"}
VALID_INTERVALS = ("15m", "1h", "4h", "1d")
_INTERVAL_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
FORBIDDEN_ACTION_PHRASES = ("compre", "comprar", "venda agora", "vender agora",
                            "sinal", "recomendad", "operacao sugerida", "longar", "shortar")


def _to_epoch_s(ts: str) -> int:
    """Converte timestamp p/ epoch s UTC. Aceita ISO+tz (qualquer offset), 'Z',
    microssegundos, e 'YYYY-MM-DD HH:MM:SS' (tratado como UTC). Usa fromisoformat
    pra parsear tz de verdade (nao descarta offset)."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)   # aceita espaco ou 'T', com/sem tz e micros
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp())
```

- [ ] **Step 4 (GREEN): confirmar passa** — `python -m pytest tests/test_raiox_data.py -q` → 3 PASS.

- [ ] **Step 5: Checkpoint (NÃO commitar)** — `git diff -- raiox_data.py tests/test_raiox_data.py`.

---

### Task 2: `open_position(state_path)`

**Files:** Modify `raiox_data.py`; Test `tests/test_raiox_data.py`.

- [ ] **Step 1 (RED): adicionar fixture de state + testes**

```python
import json as _json
import tempfile, os


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
```

- [ ] **Step 2 (RED):** `python -m pytest tests/test_raiox_data.py -k open_position -v` → FAIL (`AttributeError`).

- [ ] **Step 3 (GREEN): implementar**

```python
def open_position(state_path: str) -> dict | None:
    """Le a posicao aberta do momentum_state.json (so I/O de arquivo; sem rede).
    Retorna o 1o simbolo aberto ou None. Inclui open_time_s (epoch). PnL atual NAO entra aqui."""
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    positions = state.get("positions") or {}
    if not positions:
        return None
    symbol, pos = next(iter(positions.items()))
    return {
        "symbol": symbol,
        "direction": pos.get("direction"),
        "entry_price": pos.get("entry_price"),
        "sl_price": pos.get("sl_price"),
        "tp1_price": pos.get("tp1_price"),
        "tp2_price": pos.get("tp2_price"),
        "open_time_s": _to_epoch_s(pos["open_time"]) if pos.get("open_time") else None,
        "candles_elapsed": pos.get("candles_elapsed"),
        "regime": pos.get("regime"),
        "mfe_pct": pos.get("mfe_pct"),
        "mae_pct": pos.get("mae_pct"),
        "position_size_usd": pos.get("position_size_usd"),
    }
```

- [ ] **Step 4 (GREEN):** `python -m pytest tests/test_raiox_data.py -k open_position -v` → PASS.

- [ ] **Step 5: Checkpoint** — `git diff -- raiox_data.py tests/test_raiox_data.py`.

---

### Task 3: `_pnl_of`, `_exit_icon`, `list_trades(conn, state_path)`

**Files:** Modify `raiox_data.py`; Test `tests/test_raiox_data.py`.

**Escopo MVP (paginação):** `list_trades` mostra os **últimos 50** trades (`limit=50`, default). **Paginação completa (offset / "carregar mais") fica fora desta fatia** — decisão consciente, não esquecimento (a spec menciona "50 por vez"; aqui é "últimos 50", sem paginar).

- [ ] **Step 1 (RED): fixture de DB + testes**

```python
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
    cols = ",".join(k); ph = ",".join("?" * len(k))
    conn.execute(f"INSERT INTO momentum_trades ({cols}) VALUES ({ph})", tuple(k.values()))
    conn.commit()


def test_pnl_of_prefers_net():
    assert rx._pnl_of({"net_pnl_pct": -0.88, "pnl_pct": -0.78}) == (-0.88, "net_pnl_pct")
    assert rx._pnl_of({"net_pnl_pct": None, "pnl_pct": 0.5}) == (0.5, "pnl_pct")


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
        assert [t["id"] for t in out["closed"]] == [2, 1]          # mais recente primeiro
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
```

- [ ] **Step 2 (RED):** `python -m pytest tests/test_raiox_data.py -k "pnl_of or exit_icon or list_trades" -v` → FAIL.

- [ ] **Step 3 (GREEN): implementar**

```python
def _pnl_of(row) -> tuple[float, str]:
    net = row["net_pnl_pct"] if "net_pnl_pct" in row.keys() else row.get("net_pnl_pct") if isinstance(row, dict) else None
    if net is not None:
        return float(net), "net_pnl_pct"
    return float(row["pnl_pct"]), "pnl_pct"


def _exit_icon(exit_reason: str) -> str:
    r = (exit_reason or "").lower()
    if "tp" in r:
        return "🟢"
    if "sl" in r:
        return "🔴"
    if "timeout" in r:
        return "⏱️"
    return "•"


def list_trades(conn, state_path: str, limit: int = 50) -> dict:
    """Posicao aberta (do state) + trades fechados (resumo, mais recente primeiro)."""
    rows = conn.execute(
        "SELECT id, timestamp, symbol, direction, exit_reason, pnl_pct, net_pnl_pct "
        "FROM momentum_trades ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    closed = []
    for r in rows:
        pnl, source = _pnl_of(r)
        closed.append({
            "id": r["id"], "symbol": r["symbol"], "direction": r["direction"],
            "exit_reason": r["exit_reason"], "exit_icon": _exit_icon(r["exit_reason"]),
            "pnl_pct": pnl, "pnl_source": source, "timestamp_s": _to_epoch_s(r["timestamp"]),
        })
    return {"open": open_position(state_path), "closed": closed}
```

*(Nota: `_pnl_of` aceita tanto `sqlite3.Row` quanto `dict` — o teste usa dict; `list_trades` passa Row. A checagem `"net_pnl_pct" in row.keys()` cobre Row; o ramo dict cobre o teste unitário.)*

- [ ] **Step 4 (GREEN):** `python -m pytest tests/test_raiox_data.py -k "pnl_of or exit_icon or list_trades" -v` → PASS.

- [ ] **Step 5: Checkpoint** — `git diff`.

---

### Task 4: `trade_detail(conn, id)` + resumo factual + guarda anti-sinal

**Files:** Modify `raiox_data.py`; Test `tests/test_raiox_data.py`.

- [ ] **Step 1 (RED): testes (incl. anti-sinal com nuance)**

```python
def test_trade_detail_estimates_entry_time(trades_conn):
    _ins(trades_conn, id=5, timestamp="2026-06-08T17:07:43+00:00", symbol="ETHUSDT",
         direction="LONG", regime="TRENDING", entry_price=1691.47, sl_price=1676.55,
         tp1_price=1706.22, tp2_price=1713.85, exit_price=1676.55, exit_reason="sl_hit",
         duration_candles=3, mfe_pct=0.37, mae_pct=-0.93, net_pnl_pct=-0.88, pnl_pct=-0.78)
    d = rx.trade_detail(trades_conn, 5)
    assert d["exit_time_s"] == rx._to_epoch_s("2026-06-08T17:07:43+00:00")
    assert d["entry_time_s"] == d["exit_time_s"] - 3 * 15 * 60      # 3 velas de 15m
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
    # termos legitimos do raio-x sao permitidos
    assert "entrada" in summary or "saida" in summary
```

- [ ] **Step 2 (RED):** `python -m pytest tests/test_raiox_data.py -k "trade_detail or trade_summary" -v` → FAIL.

- [ ] **Step 3 (GREEN): implementar**

```python
def _trade_summary(d: dict) -> str:
    """Resumo factual do trade (sem frase de acao). Usa 'entrada/saida/stop/alvo' (legitimos)."""
    mins = (d["duration_candles"] or 0) * MOMENTUM_INTERVAL_MIN
    dur = f"{d['duration_candles']} velas (~{mins}min)"
    pnl = f"{d['pnl_pct']:+.2f}% ({'net' if d['pnl_source']=='net_pnl_pct' else 'bruto'})"
    mfe = f"+{d['mfe_pct']:.2f}%" if d.get("mfe_pct") is not None else "n/d"
    mae = f"{d['mae_pct']:.2f}%" if d.get("mae_pct") is not None else "n/d"
    return (f"{d['direction']} · entrada estimada {d['entry_price']} · "
            f"saida {d['exit_price']} ({d['exit_reason']}) · durou {dur} · "
            f"resultado {pnl} · foi a {mfe} a favor e {mae} contra · regime {d['regime']}")


def trade_detail(conn, trade_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM momentum_trades WHERE id=?", (trade_id,)).fetchone()
    if row is None:
        return None
    pnl, source = _pnl_of(row)
    exit_s = _to_epoch_s(row["timestamp"])
    dur = row["duration_candles"] or 0
    d = {
        "id": row["id"], "symbol": row["symbol"], "direction": row["direction"],
        "regime": row["regime"], "entry_price": row["entry_price"], "exit_price": row["exit_price"],
        "sl_price": row["sl_price"], "tp1_price": row["tp1_price"], "tp2_price": row["tp2_price"],
        "exit_reason": row["exit_reason"], "duration_candles": dur,
        "mfe_pct": row["mfe_pct"], "mae_pct": row["mae_pct"],
        "pnl_pct": pnl, "pnl_source": source,
        "exit_time_s": exit_s,
        "entry_time_s": exit_s - dur * MOMENTUM_INTERVAL_MIN * 60,
        "entry_time_estimated": True,
    }
    d["summary"] = _trade_summary(d)
    return d
```

- [ ] **Step 4 (GREEN):** `python -m pytest tests/test_raiox_data.py -k "trade_detail or trade_summary" -v` → PASS.

- [ ] **Step 5: Checkpoint** — `git diff`.

---

### Task 5: `fetch_candles` (wrapper start/end + escala de TF + filtro)

**Files:** Modify `raiox_data.py`; Test `tests/test_raiox_data.py`.

- [ ] **Step 1 (RED): testes com `get_candles_fn` fake (sem rede)**

```python
def _fake_candles(rows):
    """Cria um fake de market.get_candles: (symbol, interval, limit) -> objeto com itertuples-like.
    rows: lista de (epoch_s, o, h, l, c). Retorna os ultimos `limit`."""
    class _DF:
        def __init__(self, data): self._d = data
        def to_dict(self, orient):  # orient='records'
            return [{"time_s": t, "open": o, "high": h, "low": l, "close": c}
                    for (t, o, h, l, c) in self._d]
    def fn(symbol, interval, limit):
        return _DF(rows[-limit:])
    return fn


def test_fetch_candles_filters_range_15m():
    now = 1780941600
    rows = [(now - i * 900, 100, 101, 99, 100) for i in range(200)][::-1]  # 200 velas 15m
    fn = _fake_candles(rows)
    start = now - 10 * 900
    end = now
    out = rx.fetch_candles("ETHUSDT", "15m", start, end, now, get_candles_fn=fn)
    assert out["ok"] is True
    assert out["effective_interval"] == "15m"
    assert all(start - 20 * 900 <= c["time"] <= end + 20 * 900 for c in out["candles"])


def test_fetch_candles_escalates_tf_when_too_old():
    now = 1780941600
    # janela de 60 dias: 15m (~5760) e 1h (~1440) nao cabem em 1000 velas;
    # menor TF que cabe = 4h (~380). NAO 1d (que cabe mas nao e o menor).
    start = now - 60 * 86400
    rows = [(now - i * 14400, 100, 101, 99, 100) for i in range(500)][::-1]  # 500 velas de 4h
    fn = _fake_candles(rows)
    out = rx.fetch_candles("ETHUSDT", "15m", start, now, now, get_candles_fn=fn)
    assert out["ok"] is True
    assert out["effective_interval"] == "4h"


def test_fetch_candles_error_when_window_absurd():
    now = 1780941600
    start = now - 4000 * 86400  # ~11 anos: nem 1d cabe em 1000 velas
    fn = _fake_candles([(now, 1, 1, 1, 1)])
    out = rx.fetch_candles("ETHUSDT", "15m", start, now, now, get_candles_fn=fn)
    assert out["ok"] is False
    assert out["error"] == "janela_muito_longa"
```

- [ ] **Step 2 (RED):** `python -m pytest tests/test_raiox_data.py -k fetch_candles -v` → FAIL.

- [ ] **Step 3 (GREEN): implementar**

```python
import math


def _choose_interval(start_s: int, now_s: int, requested: str, margin: int, max_bars: int) -> str | None:
    """Menor TF (>= requested) cujo range [start, now] caiba em max_bars velas. None se nem 1d cabe."""
    start_idx = VALID_INTERVALS.index(requested)
    for interval in VALID_INTERVALS[start_idx:]:
        tf = _INTERVAL_SECONDS[interval]
        bars = (now_s - start_s) / tf + margin
        if bars <= max_bars:
            return interval
    return None


def fetch_candles(symbol, interval, start_s, end_s, now_s, get_candles_fn,
                  margin: int = 20, max_bars: int = 1000) -> dict:
    """Wrapper sobre get_candles (que so aceita limit). Escala TF se a janela for longa demais e
    filtra pro range. get_candles_fn injetavel p/ teste. NAO altera market.py."""
    if start_s >= end_s:
        return {"ok": False, "error": "intervalo_invalido", "message": "start >= end"}
    eff = _choose_interval(start_s, now_s, interval, margin, max_bars)
    if eff is None:
        return {"ok": False, "error": "janela_muito_longa",
                "message": "janela longa demais até para velas diárias"}
    tf = _INTERVAL_SECONDS[eff]
    limit = min(max_bars, math.ceil((now_s - start_s) / tf) + margin)
    df = get_candles_fn(symbol, eff, limit)
    records = df.to_dict("records")
    lo, hi = start_s - margin * tf, end_s + margin * tf
    candles = [{"time": r["time_s"], "open": r["open"], "high": r["high"],
                "low": r["low"], "close": r["close"]}
               for r in records if lo <= r["time_s"] <= hi]
    return {"ok": True, "symbol": symbol, "interval": interval,
            "effective_interval": eff, "candles": candles}
```

*(Nota: o fake de teste expõe `time_s`; a integração real converte o `time` do DataFrame da Binance — ver Task 7, onde o endpoint adapta `market.get_candles`.)*

- [ ] **Step 4 (GREEN):** `python -m pytest tests/test_raiox_data.py -k fetch_candles -v` → PASS.

- [ ] **Step 5: Checkpoint** — `git diff`.

---

### Task 6: Endpoints `/api/raiox/trades` e `/api/raiox/trade/<id>`

**Files:** Modify `dashboard_server.py`; Test `tests/test_raiox_endpoints.py` (criar).

- [ ] **Step 1 (RED): criar `tests/test_raiox_endpoints.py`**

```python
import json, os, sqlite3, sys, tempfile
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
    fd, dbp = tempfile.mkstemp(suffix=".db"); os.close(fd)
    conn = sqlite3.connect(dbp)
    conn.executescript(_DDL)
    conn.execute("INSERT INTO momentum_trades (id,timestamp,symbol,direction,regime,entry_price,"
                 "exit_price,sl_price,tp1_price,tp2_price,exit_reason,duration_candles,mfe_pct,"
                 "mae_pct,pnl_pct,net_pnl_pct) VALUES (1,'2026-06-08T17:07:43+00:00','ETHUSDT',"
                 "'LONG','TRENDING',1691.47,1676.55,1676.55,1706.22,1713.85,'sl_hit',3,0.37,-0.93,-0.78,-0.88)")
    conn.commit(); conn.close()
    fd, sp = tempfile.mkstemp(suffix=".json"); os.close(fd)
    json.dump({"positions": {}}, open(sp, "w"))
    monkeypatch.setattr("database.DB_FILE", dbp)
    monkeypatch.setattr("dashboard_server.MOMENTUM_STATE_FILE", sp, raising=False)
    import dashboard_server
    dashboard_server.app.config["TESTING"] = True
    yield dashboard_server.app.test_client()
    os.unlink(dbp); os.unlink(sp)


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
```

- [ ] **Step 2 (RED):** `python -m pytest tests/test_raiox_endpoints.py -k "trades_ok or trade_detail" -v` → FAIL (rotas não existem).

- [ ] **Step 3 (GREEN): adicionar import e rotas em `dashboard_server.py`**

No topo (junto dos outros imports): `import raiox_data` e `from runtime_config import MOMENTUM_STATE_FILE`. (Conferir se `MOMENTUM_STATE_FILE` já vem no bloco `from runtime_config import (...)` das linhas 48-63; se não, adicionar lá.)

Adicionar as rotas (perto das outras `/api/*`):

```python
@app.route("/api/raiox/trades")
def api_raiox_trades():
    conn = db._get_conn()
    try:
        out = raiox_data.list_trades(conn, MOMENTUM_STATE_FILE)
    finally:
        conn.close()
    return jsonify({"ok": True, **out})


@app.route("/api/raiox/trade/<int:trade_id>")
def api_raiox_trade(trade_id):
    conn = db._get_conn()
    try:
        d = raiox_data.trade_detail(conn, trade_id)
    finally:
        conn.close()
    if d is None:
        return jsonify({"ok": False, "error": "not_found", "message": "trade nao encontrado"}), 404
    return jsonify({"ok": True, "trade": d})
```

- [ ] **Step 4 (GREEN):** `python -m pytest tests/test_raiox_endpoints.py -k "trades_ok or trade_detail" -v` → PASS.

- [ ] **Step 5: Checkpoint** — `git diff -- dashboard_server.py tests/test_raiox_endpoints.py`.

---

### Task 7: Endpoint `/api/raiox/candles` (validação rígida + adapta `market.get_candles`)

**Files:** Modify `dashboard_server.py`; Test `tests/test_raiox_endpoints.py`.

- [ ] **Step 1 (RED): testes de validação + sucesso (com `get_candles` monkeypatchado)**

```python
def test_candles_rejects_bad_symbol(client):
    r = client.get("/api/raiox/candles?symbol=DOGEUSDT&interval=15m&start=1&end=2")
    assert r.status_code == 400
    assert r.get_json()["error"] == "symbol_invalido"


def test_candles_rejects_bad_interval(client):
    r = client.get("/api/raiox/candles?symbol=ETHUSDT&interval=3m&start=1&end=2")
    assert r.status_code == 400


def test_candles_rejects_start_ge_end(client):
    r = client.get("/api/raiox/candles?symbol=ETHUSDT&interval=15m&start=200&end=100")
    assert r.status_code == 400


def test_candles_ok(client, monkeypatch):
    import pandas as pd
    now = 1780941600
    rows = [{"time_s": now - i * 900, "open": 1, "high": 1, "low": 1, "close": 1} for i in range(50)]
    class _DF:
        def to_dict(self, orient): return rows
    monkeypatch.setattr("market.get_candles", lambda s, i, l: _DF())
    r = client.get(f"/api/raiox/candles?symbol=ETHUSDT&interval=15m&start={now-5*900}&end={now}")
    data = r.get_json()
    assert data["ok"] is True
    assert data["effective_interval"] == "15m"
    assert len(data["candles"]) > 0


def test_candles_binance_down_returns_502(client, monkeypatch):
    def boom(s, i, l): raise Exception("binance down")
    monkeypatch.setattr("market.get_candles", boom)
    now = 1780941600
    r = client.get(f"/api/raiox/candles?symbol=ETHUSDT&interval=15m&start={now-5*900}&end={now}")
    assert r.status_code == 502
    assert r.get_json()["error"] == "binance_unavailable"
```

- [ ] **Step 2 (RED):** `python -m pytest tests/test_raiox_endpoints.py -k candles -v` → FAIL.

- [ ] **Step 3 (GREEN): implementar a rota** (adapta o DataFrame da Binance pro formato do wrapper)

```python
import time as _time
import market


def _binance_candles_adapter(symbol, interval, limit):
    """Adapta market.get_candles (DataFrame com 'time' datetime) -> objeto com to_dict('records')
    contendo 'time_s' em epoch s. Mantido aqui pra nao alterar market.py."""
    df = market.get_candles(symbol, interval, limit)
    df = df.copy()
    df["time_s"] = (df["time"].astype("int64") // 1_000_000_000)  # ns -> s
    class _Rec:
        def to_dict(self, orient):
            return df[["time_s", "open", "high", "low", "close"]].to_dict(orient)
    return _Rec()


@app.route("/api/raiox/candles")
def api_raiox_candles():
    symbol = request.args.get("symbol", "")
    interval = request.args.get("interval", "")
    if symbol not in raiox_data.VALID_SYMBOLS:
        return jsonify({"ok": False, "error": "symbol_invalido", "message": "símbolo não suportado"}), 400
    if interval not in raiox_data.VALID_INTERVALS:
        return jsonify({"ok": False, "error": "interval_invalido", "message": "timeframe inválido"}), 400
    try:
        start_s = int(request.args.get("start", "0"))
        end_s = int(request.args.get("end", "0"))
    except ValueError:
        return jsonify({"ok": False, "error": "param_invalido", "message": "start/end inválidos"}), 400
    if start_s >= end_s:
        return jsonify({"ok": False, "error": "intervalo_invalido", "message": "start >= end"}), 400
    try:
        out = raiox_data.fetch_candles(symbol, interval, start_s, end_s, int(_time.time()),
                                       get_candles_fn=_binance_candles_adapter)
    except Exception:
        return jsonify({"ok": False, "error": "binance_unavailable",
                        "message": "não consegui carregar os candles agora"}), 502
    if not out["ok"]:
        return jsonify(out), 400
    return jsonify(out)
```

- [ ] **Step 4 (GREEN):** `python -m pytest tests/test_raiox_endpoints.py -v` → todos PASS.

- [ ] **Step 5: Checkpoint** — `git diff`.

---

### Task 8: Lib lightweight-charts local + página `/raiox/` + nav

Frontend: sem teste unitário (validação no checklist da Task 10). Código real, sem CDN.

**Files:** Create `static/js/lightweight-charts.standalone.production.js`; Create `templates/raiox.html`; Modify `dashboard_server.py`, `templates/base.html`.

- [ ] **Step 1: baixar a lib (versão fixa, local)**

```bash
cd ~/crypto_ai_bot
curl -L -o static/js/lightweight-charts.standalone.production.js \
  https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js
wc -c static/js/lightweight-charts.standalone.production.js   # esperado: ~150KB+
head -c 80 static/js/lightweight-charts.standalone.production.js  # confere que e JS, nao HTML de erro
```
(Versão fixada: **lightweight-charts 4.2.0**. Se `curl` ao unpkg falhar, baixar manualmente e colocar no mesmo caminho — não usar CDN no HTML.)

- [ ] **Step 2: rota da página em `dashboard_server.py`**

```python
@app.route("/raiox/")
def raiox_page():
    return render_template("raiox.html", active_page="raiox")
```

- [ ] **Step 3: adicionar item no nav — `templates/base.html`**

Nav desktop (após a linha do System, ~linha 26):
```html
            <li><a href="/raiox/" {% if active_page == 'raiox' %}class="active"{% endif %}>Raio-X</a></li>
```
Nav mobile (após o System, ~linha 63):
```html
      <a href="/raiox/" {% if active_page == 'raiox' %}class="active"{% endif %}>Raio-X</a>
```

- [ ] **Step 4: criar `templates/raiox.html`** (estende base; estrutura simples: posição aberta no topo, feed à esquerda, gráfico+resumo à direita)

```html
{% extends "base.html" %}
{% block content %}
<!-- lightweight-charts 4.2.0 (local, sem CDN) -->
<script src="/static/js/lightweight-charts.standalone.production.js"></script>
<div class="raiox-wrap" style="display:flex;gap:16px;flex-wrap:wrap">
  <div style="flex:1;min-width:280px">
    <h2>🩻 Raio-X dos Trades</h2>
    <div id="open-pos"></div>
    <ul id="trade-feed" style="list-style:none;padding:0"></ul>
  </div>
  <div style="flex:2;min-width:340px">
    <div id="tf-buttons"></div>
    <div id="chart" style="height:420px"></div>
    <pre id="trade-summary" style="white-space:pre-wrap"></pre>
  </div>
</div>
<script src="/static/js/raiox.js"></script>
{% endblock %}
```
(Conferir no `base.html` que existe um `{% block content %}` — se o nome do bloco for outro, usar o nome real do projeto.)

- [ ] **Step 5: teste de fumaça da página** — adicionar em `tests/test_raiox_endpoints.py` (usa o `client` da Task 6):

```python
def test_raiox_page_renders(client):
    r = client.get("/raiox/")
    assert r.status_code == 200
    assert b"Raio-X" in r.data
```

Rodar: `python -m pytest tests/test_raiox_endpoints.py -k page_renders -v` → PASS. Se falhar com erro de template (bloco inexistente), ajustar o nome do `{% block %}` em `raiox.html` pro nome real usado no `base.html`.

- [ ] **Step 6: Checkpoint** — `git diff -- dashboard_server.py templates/base.html tests/test_raiox_endpoints.py` ; `git status --short` (lib + raiox.html novos).

---

### Task 9: Frontend `raiox.js` — feed + gráfico + raio-x + ao vivo

**Files:** Create `static/js/raiox.js`.

- [ ] **Step 1: criar `static/js/raiox.js`**

```javascript
// Raio-X dos Trades — frontend (vanilla). Le /api/raiox/* e plota com lightweight-charts 4.2.0.
const $ = (s) => document.querySelector(s);
let chart, candleSeries, priceLines = [], liveTimer = null, current = null, currentTf = "15m";

const TF = ["15m", "1h", "4h", "1d"];

function fmtTime(s) {
  return new Date(s * 1000).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function initChart() {
  chart = LightweightCharts.createChart($("#chart"), {
    height: 420, layout: { background: { color: "#0d0d0d" }, textColor: "#ccc" },
    grid: { vertLines: { color: "#1c1c1c" }, horzLines: { color: "#1c1c1c" } },
    timeScale: { timeVisible: true },
  });
  candleSeries = chart.addCandlestickSeries();
  $("#tf-buttons").innerHTML = TF.map(t => `<button data-tf="${t}">${t}</button>`).join(" ");
  $("#tf-buttons").querySelectorAll("button").forEach(b =>
    b.onclick = () => current && loadChart(current, b.dataset.tf));
}

function clearLines() { priceLines.forEach(l => candleSeries.removePriceLine(l)); priceLines = []; }

function addLine(price, color, title) {
  if (price == null) return;
  priceLines.push(candleSeries.createPriceLine({ price, color, lineWidth: 1, title }));
}

async function loadFeed() {
  const r = await fetch("/api/raiox/trades"); const d = await r.json();
  if (!d.ok) return;
  const op = d.open;
  $("#open-pos").innerHTML = op
    ? `<div class="open-card">🟢 ABERTA: ${op.symbol} ${op.direction} · entrou ${op.entry_price}
        <button id="live-btn">ver ao vivo →</button></div>`
    : "<div>nenhuma posição aberta</div>";
  if (op) $("#live-btn").onclick = () => openLive(op);
  $("#trade-feed").innerHTML = d.closed.map(t =>
    `<li data-id="${t.id}" class="trade-row">${t.exit_icon} ${t.symbol} ${t.direction} ·
      ${t.pnl_pct.toFixed(2)}% · ${t.exit_reason} · ${fmtTime(t.timestamp_s)}</li>`).join("");
  $("#trade-feed").querySelectorAll("li").forEach(li =>
    li.onclick = () => openTrade(li.dataset.id));
}

async function openTrade(id) {
  stopLive();
  const r = await fetch(`/api/raiox/trade/${id}`); const d = await r.json();
  if (!d.ok) return;
  current = { kind: "closed", t: d.trade };
  $("#trade-summary").textContent = d.trade.summary;
  await loadChart(current, "15m");
}

function openLive(op) {
  stopLive();                                  // evita timers duplicados ao clicar varias vezes
  current = { kind: "open", t: op };
  $("#trade-summary").textContent = `${op.symbol} ${op.direction} · entrada ${op.entry_price} · ao vivo`;
  loadChart(current, "15m");
  liveTimer = setInterval(() => loadChart(current, currentTf), 30000);
}
function stopLive() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } }

function setMarkers(ctx, t) {
  const entryTime = ctx.kind === "closed" ? t.entry_time_s : t.open_time_s;
  const markers = [{
    time: entryTime,
    position: t.direction === "LONG" ? "belowBar" : "aboveBar",
    color: "#26a69a", shape: t.direction === "LONG" ? "arrowUp" : "arrowDown",
    text: "entrada estimada",
  }];
  if (ctx.kind === "closed") {                  // posicao viva: so marcador de entrada
    markers.push({
      time: t.exit_time_s,
      position: t.direction === "LONG" ? "aboveBar" : "belowBar",
      color: "#ef5350", shape: "circle", text: t.exit_reason,
    });
  }
  candleSeries.setMarkers(markers);
}

async function loadChart(ctx, tf) {
  currentTf = tf;
  const t = ctx.t;
  const entry = ctx.kind === "closed" ? t.entry_time_s : t.open_time_s;
  const exit = ctx.kind === "closed" ? t.exit_time_s : Math.floor(Date.now() / 1000);
  const url = `/api/raiox/candles?symbol=${t.symbol}&interval=${tf}&start=${entry}&end=${exit}`;
  const r = await fetch(url); const d = await r.json();
  if (!d.ok) { $("#trade-summary").textContent += `\n(candles indisponíveis: ${d.message})`; return; }
  candleSeries.setData(d.candles);
  chart.timeScale().fitContent();              // enquadra a janela do trade
  clearLines();
  addLine(t.entry_price, "#26a69a", "entrada");
  addLine(t.sl_price, "#ef5350", "stop");
  addLine(t.tp1_price, "#42a5f5", "TP1");
  addLine(t.tp2_price, "#42a5f5", "TP2");
  setMarkers(ctx, t);                          // setas de entrada (estimada) e saida
  if (ctx.kind === "open") {
    const last = d.candles[d.candles.length - 1];
    if (last) {
      const pnl = ((last.close - t.entry_price) / t.entry_price * 100) * (t.direction === "LONG" ? 1 : -1);
      $("#trade-summary").textContent =
        `${t.symbol} ${t.direction} · entrada ${t.entry_price} · agora ${last.close} · PnL ${pnl.toFixed(2)}% · ao vivo`;
    }
  }
  if (d.effective_interval !== tf)
    $("#trade-summary").textContent += `\n(janela longa: mostrando em ${d.effective_interval})`;
}

initChart();
loadFeed();
```

- [ ] **Step 2: sanidade de sintaxe JS** (sem rodar o navegador ainda):
```bash
cd ~/crypto_ai_bot && node --check static/js/raiox.js && echo "js ok"
```
Expected: `js ok` (sem erro de sintaxe).

- [ ] **Step 3: Checkpoint** — `git status --short` (raiox.js novo).

---

### Task 10: Validação real + suíte completa + checklist

**Files:** nenhum novo — validação.

- [ ] **Step 1: suíte focada do Raio-X** — `python -m pytest tests/test_raiox_data.py tests/test_raiox_endpoints.py -v` → tudo PASS.

- [ ] **Step 2: suíte completa (zero regressão)** — `python -m pytest tests/ --tb=short -q`. Esperado: tudo passa (não toquei em bot/momentum/`/pip/`).

- [ ] **Step 3: reiniciar o serviço e validar ao vivo**
```bash
sudo systemctl restart cryptobot && sleep 14
sudo systemctl status cryptobot --no-pager | grep Active
python3 -c "import requests; print('trades', requests.get('http://localhost:5000/api/raiox/trades', timeout=10).status_code)"
python3 -c "import requests; print('trade1', requests.get('http://localhost:5000/api/raiox/trade/1', timeout=10).status_code)"
```

- [ ] **Step 4: checklist visual (abrir no navegador `http://<ip-do-pi>:5000/raiox/`)**
  - [ ] feed carrega; trade fechado recente abre o Raio-X
  - [ ] candles aparecem; linhas entry/SL/TP; marcador/linha de saída
  - [ ] seletor 1h/4h/1d recarrega (mostra `effective_interval` se escalou)
  - [ ] posição aberta: "ver ao vivo" funciona e PnL aparece após o candle
  - [ ] sem posição aberta: tela não quebra
  - [ ] console do navegador sem erro JS
  - [ ] `/api/raiox/candles?...` retorna candles ou erro estruturado

- [ ] **Step 5: Checkpoint final (NÃO commitar)** — `git status --short` ; `git diff --stat`. Apresentar ao Gabriel; commit/push só com OK.

---

## Self-Review

**1. Cobertura da spec:**
- ✅ raiox_data.py puro/testável (Tasks 1-5); endpoints finos (6-7); frontend local (8-9).
- ✅ Wrapper de candles sem mexer no market.py (Task 5 + adapter na Task 7).
- ✅ Escala de TF + limite 1000 + janela longa (Task 5).
- ✅ entry_time estimado + flag (Task 4).
- ✅ PnL net→pnl + pnl_source (Tasks 3, 4).
- ✅ Posição aberta sem rede (Task 2); PnL ao vivo no frontend (Task 9).
- ✅ Validação rígida do /candles (Task 7).
- ✅ Anti-sinal com nuance (Task 4 — proíbe ação, permite entrada/stop/alvo).
- ✅ lightweight-charts local versão fixa (Task 8); nav (Task 8); sem CDN.
- ✅ Testes monkeypatch DB/state (Task 6); checklist objetivo (Task 10).
- ✅ Não toca bot/`/pip/`/schema/market.py.

**2. Placeholders:** nenhum — código real e comandos com expected em cada step. (1 typo proposital corrigido inline na Task 1: `sys.path.insert(0, str(_ROOT))`.)

**3. Consistência de tipos:** `_to_epoch_s`, `_pnl_of`, `open_position`, `list_trades`, `trade_detail`, `fetch_candles` — assinaturas idênticas entre contrato, implementação e endpoints. Chaves dos dicts (`entry_time_s`, `pnl_source`, `effective_interval`, `candles[].time`) consistentes entre backend, endpoints e `raiox.js`.

## Notas de execução
- Hook roda a suíte inteira (estoura 60s) — usar pytest focado; suíte completa na Task 10.
- Frontend não tem teste unitário (gráfico é visual) — validar pelo checklist da Task 10.
- Sem commits automáticos; checkpoints com `git diff`.
