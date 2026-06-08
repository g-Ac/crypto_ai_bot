# Leitura de Mercado pro Spot (`/mercado`) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar um comando Telegram `/mercado` (macro) e `/mercado <SYM>` (zoom) que mostra, sob demanda, uma leitura de mercado (regime risco-on/off + mapa de pressão de liquidações) ancorada nos dados já coletados em `bot.db` — ferramenta de apoio à decisão manual de spot, sem operar nem sinalizar.

**Architecture:** Módulo novo `market_read.py` com **funções puras de leitura** (recebem `conn: sqlite3.Connection`, retornam `dict`/`list`) + **funções de formatação** (recebem dicts, retornam string HTML do Telegram). Zero schema novo, zero migration, zero alteração no loop principal. O handler em `telegram_commands.py` abre a conexão (via `database._get_conn()`), chama o módulo e devolve a string. Toda leitura é read-only sobre as tabelas `k_*`.

**Tech Stack:** Python 3.13, sqlite3 (stdlib), pytest. Telegram via HTML (`parse_mode="HTML"`), padrão já usado em `telegram_notifier.py`.

---

## ⚙️ Convenção de processo (LER ANTES DE EXECUTAR)

Duas regras do projeto que sobrescrevem o estilo default da skill:

1. **NÃO commitar sem OK explícito.** (Regra de conduta nº 8 do `CLAUDE.md`.) Nenhuma task faz `git commit`. Cada task termina num **Checkpoint**: hook verde + revisão do `git diff`. O commit só acontece quando o Gabriel disser "commita" — provavelmente agrupando tasks em commits lógicos no fim.

2. **Hook-first.** Há um hook `PostToolUse` que roda `pytest tests/ --tb=short -q` a cada `Write`/`Edit` em `.py`. **A fonte de verdade dos testes é o resultado do hook** — ler ele, não rodar pytest à toa. Onde os steps trazem `pytest ... -v`, é **fallback** (rodar só se o hook não mostrou aquele teste específico, ou para isolar um subconjunto). Validação final, suíte completa e a chamada real **sim** rodam manualmente (explícito nas tasks).

---

## Descoberta resolvida no design: o `side` estava invertido (NÃO re-inverter)

A spec marcava como "risco #1" a semântica do `side` em `k_liquidations`. Confirmado por 3 vias (doc oficial Bybit verbatim + teste discriminante de preço real + coerência econômica) que o campo é **"position side"** (lado da posição liquidada), não o lado da ordem executada:

- **`side='BUY'` = LONG liquidado** → cascata ↓ (pressão de baixa)
- **`side='SELL'` = SHORT liquidado** → squeeze ↑ (pressão de alta)

**A query "validada" da spec estava INVERTIDA.** O coletor (`bybit_liquidation_feed.py`, `liquidation_store.py`) grava o `S` cru da Bybit sem interpretar — a interpretação mora no `market_read.py`, isolada nas constantes `LIQ_LONG_SIDE`/`LIQ_SHORT_SIDE` (Task 1).

**Isto não é verdade eterna.** É a leitura correta *hoje*, ancorada em doc + dados (amostra ≈ 1 dia). A constante é o **ponto único** de correção se o feed mudar ou o coletor trocar de fonte. Manter a nota "revalidar com dados forward" — ver memória `bybit_liquidation_side`.

## Convenções de dados cristalizadas (validadas contra o `bot.db` real)

| Item | Valor confirmado | Consequência no código |
|---|---|---|
| `k_liquidations.event_ts` | epoch **ms** | janela 24h = `event_ts > ancora_ms - hours*3600*1000` |
| `k_prices.bucket_ts`, `k_ratios.bucket_ts`, `k_basis.bucket_ts`, `k_open_interest.bucket_ts` | epoch **s** (hourly) | janela = `bucket_ts > ancora_s - hours*3600` |
| `k_funding_rates.funding_time` | epoch **s** (granularidade **8h**) | pegar MAX por símbolo (não assumir horário global) |
| `collected_at` (todas) | epoch **s** | não usado nas leituras |
| `k_ratios.source` | `'global_account'` e `'top_position'` | filtrar por source; 1 linha por (symbol,bucket,source) |
| Âncora de "agora" | `MAX(event_ts)`/`MAX(bucket_ts)` da própria tabela | robusto a lag de coleta; determinístico em teste |

**Robustez a gaps:** retornos e variação de OI usam "valor no bucket `<=` (último − N horas)", não offset fixo de linhas (`ROW_NUMBER`), porque pode haver horas faltando.

---

## File Structure

- **Create:** `market_read.py` (raiz do projeto) — leitura pura + formatação. Responsabilidade única: ler `k_*` e formatar para Telegram. Recebe `conn` (sem I/O de conexão própria).
- **Modify:** `telegram_commands.py` — adicionar `_cmd_mercado(arg)`, registrar em `_HANDLERS`, ajustar `_handle_command` para repassar argumento ao handler que o aceitar (backward-compatible), e listar `/mercado` no `/ajuda`.
- **Create:** `tests/test_market_read.py` — testes das funções puras + formatação (conn in-memory, schemas reais reusados).
- **Create:** `tests/test_telegram_mercado.py` — testes do handler e do roteamento (tmp DB via monkeypatch `database.DB_FILE`).

**Por que `market_read.py` na raiz:** o projeto não usa `src/`; módulos de topo são o padrão (`database.py`, `telegram_commands.py`). Leitura e formatação ficam juntas (mudam juntas); a separação de responsabilidade é por *função pura vs formatação*, não por arquivo.

---

## Contrato de tipos (referência única — usado por todas as tasks)

```python
# Constantes (Task 1)
LIQ_LONG_SIDE  = "BUY"   # Bybit allLiquidation: BUY = long liquidado
LIQ_SHORT_SIDE = "SELL"  # Bybit allLiquidation: SELL = short liquidado
MAJORS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

# Leitura (todas recebem conn: sqlite3.Connection com row_factory=sqlite3.Row)
all_symbols(conn) -> list[str]
ret_pct(conn, symbol: str, hours: int) -> float | None
read_returns(conn, symbols, hours: int) -> dict[str, float | None]
read_breadth(conn, hours: int = 24) -> dict          # {"up": int, "total": int, "pct_up": float|None}
read_volatility(conn, symbol: str, hours: int = 24) -> float | None   # média de (high-low)/open*100
read_taker_ratio(conn, symbol: str, hours: int = 24) -> float | None  # 100*sum(taker_buy_base)/sum(volume)
read_lsr(conn, symbol: str) -> dict                  # {"global": float|None, "top": float|None}
read_funding(conn, symbol: str) -> dict              # {"funding_rate": float|None, "funding_time": int|None}
read_basis(conn, symbol: str) -> dict                # {"basis_rate": float|None, "bucket_ts": int|None}
read_oi_change(conn, symbol: str, hours: int = 24) -> float | None     # % change do sum_open_interest
read_pressure(conn, hours: int = 24) -> list[dict]   # ver Task 2 p/ schema do dict
read_regime(conn) -> dict
read_symbol(conn, symbol: str) -> dict

# Formatação (puras: dict/list -> str HTML)
_fmt_usd(v) -> str ; _fmt_pct(v, signed=True) -> str ; _fmt_num(v, decimals=2) -> str
_sym_short(symbol) -> str ; _pressure_label(p: dict) -> str
format_macro(regime: dict, pressure: list[dict], top_n: int = 8) -> str
format_symbol(data: dict) -> str
```

---

### Task 1: Scaffolding em TDD puro (teste primeiro) + convenção do side + helpers de teste

TDD estrito: o teste vem antes do módulo. O import de `market_read` falha (RED) até o módulo existir.

**Files:**
- Test: `tests/test_market_read.py`
- Create: `market_read.py`

- [ ] **Step 1 (RED): criar `tests/test_market_read.py` com imports, helpers e o primeiro teste**

```python
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
```

- [ ] **Step 2 (RED): confirmar que falha** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -q`. Esperado: erro de coleta `ModuleNotFoundError: No module named 'market_read'`.

- [ ] **Step 3 (GREEN): criar `market_read.py` com cabeçalho, constantes e `all_symbols`**

```python
"""
Leitura de mercado sob demanda para apoio a decisao de spot manual (comando /mercado).

Funcoes PURAS de leitura (recebem conn, retornam dict/list) + formatacao (dict -> HTML Telegram).
NAO opera, NAO coleta, NAO sinaliza. Read-only sobre as tabelas k_*.

Convencao do side em k_liquidations (Bybit allLiquidation = "position side", confirmado 2026-06-08):
    BUY  = LONG  liquidado  -> cascata para baixo (pressao de baixa)
    SELL = SHORT liquidado  -> squeeze para cima  (pressao de alta)
Fonte: bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation
Coletor grava o 'S' cru (ver bybit_liquidation_feed.py); a interpretacao mora aqui.
Revalidar com dados forward (amostra inicial ~1 dia) -- esta constante e o ponto unico de correcao.
"""
from __future__ import annotations

import sqlite3

# Convencao do side -- ponto unico de verdade (corrigir SO aqui se o feed/fonte mudar)
LIQ_LONG_SIDE = "BUY"
LIQ_SHORT_SIDE = "SELL"

# Majors usados no termometro macro. Lista total e derivada do banco (all_symbols).
MAJORS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def all_symbols(conn: sqlite3.Connection) -> list[str]:
    """Simbolos efetivamente coletados (deriva do banco, nao hardcode)."""
    rows = conn.execute("SELECT DISTINCT symbol FROM k_prices ORDER BY symbol").fetchall()
    return [r[0] for r in rows]
```

- [ ] **Step 4 (GREEN): confirmar que passa** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py::test_all_symbols_derives_from_db -v`. Esperado: PASS.

- [ ] **Step 5: Checkpoint (NÃO commitar)** — hook verde. Revisar o diff; commit só com OK do Gabriel:

```bash
git diff -- market_read.py tests/test_market_read.py
git status --short
```

---

### Task 2: `read_pressure` — mapa de pressão de liquidações (instrumento 2, risco #1)

Schema do dict: `{"symbol": str, "longs_liq_usd": float, "shorts_liq_usd": float, "total_usd": float, "events": int, "dominant_side": "LONG"|"SHORT"}`.

**Files:** Modify `market_read.py`; Test `tests/test_market_read.py`.

- [ ] **Step 1 (RED): escrever os testes (convenção CORRETA do side)**

```python
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
```

- [ ] **Step 2 (RED): confirmar falha** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k read_pressure -v` → `AttributeError: read_pressure`.

- [ ] **Step 3 (GREEN): implementar `read_pressure`**

```python
def read_pressure(conn: sqlite3.Connection, hours: int = 24) -> list[dict]:
    """Liquidacoes por simbolo na janela (default 24h), ancoradas no evento mais recente.

    BUY=long liquidado, SELL=short liquidado (ver cabecalho). dominant_side e o lado
    MAIS liquidado: 'LONG' (cascata para baixo) ou 'SHORT' (squeeze para cima).
    """
    anchor = conn.execute("SELECT MAX(event_ts) FROM k_liquidations").fetchone()[0]
    if anchor is None:
        return []
    cutoff = anchor - hours * 3600 * 1000  # event_ts em ms
    rows = conn.execute(
        f"""
        SELECT symbol,
               SUM(CASE WHEN side='{LIQ_LONG_SIDE}'  THEN notional ELSE 0 END) AS longs_liq,
               SUM(CASE WHEN side='{LIQ_SHORT_SIDE}' THEN notional ELSE 0 END) AS shorts_liq,
               COUNT(*) AS events
        FROM k_liquidations
        WHERE event_ts > ?
        GROUP BY symbol
        HAVING SUM(notional) > 0
        ORDER BY SUM(notional) DESC
        """,
        (cutoff,),
    ).fetchall()
    out = []
    for r in rows:
        longs = r["longs_liq"] or 0.0
        shorts = r["shorts_liq"] or 0.0
        out.append({
            "symbol": r["symbol"],
            "longs_liq_usd": longs,
            "shorts_liq_usd": shorts,
            "total_usd": longs + shorts,
            "events": r["events"],
            "dominant_side": "LONG" if longs >= shorts else "SHORT",
        })
    return out
```

*(`LIQ_LONG_SIDE`/`LIQ_SHORT_SIDE` são constantes internas controladas, não input do usuário — sem risco de injeção.)*

- [ ] **Step 4 (GREEN): confirmar passa** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k read_pressure -v` → 4 PASS.

- [ ] **Step 5: Checkpoint (NÃO commitar)** — `git diff -- market_read.py tests/test_market_read.py` ; `git status --short`.

---

### Task 3: `ret_pct`, `read_returns`, `read_breadth` — tendência macro

**Files:** Modify `market_read.py`; Test `tests/test_market_read.py`.

- [ ] **Step 1 (RED): escrever os testes (robusto a gaps)**

```python
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
```

- [ ] **Step 2 (RED): confirmar falha** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k "ret_pct or read_returns or breadth" -v`.

- [ ] **Step 3 (GREEN): implementar**

```python
def _latest_close(conn: sqlite3.Connection, symbol: str):
    row = conn.execute(
        "SELECT bucket_ts, close_price FROM k_prices WHERE symbol=? ORDER BY bucket_ts DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    return (row["bucket_ts"], row["close_price"]) if row else (None, None)


def ret_pct(conn: sqlite3.Connection, symbol: str, hours: int) -> float | None:
    """Retorno % entre o close mais recente e o close em (mais_recente - hours).
    Robusto a gaps: usa o bucket com bucket_ts <= alvo (o mais recente que satisfaz)."""
    latest_ts, latest_close = _latest_close(conn, symbol)
    if latest_ts is None or not latest_close:
        return None
    target = latest_ts - hours * 3600
    row = conn.execute(
        "SELECT close_price FROM k_prices WHERE symbol=? AND bucket_ts<=? ORDER BY bucket_ts DESC LIMIT 1",
        (symbol, target),
    ).fetchone()
    if not row or not row["close_price"]:
        return None
    return 100.0 * (latest_close / row["close_price"] - 1)


def read_returns(conn: sqlite3.Connection, symbols, hours: int) -> dict:
    return {s: ret_pct(conn, s, hours) for s in symbols}


def read_breadth(conn: sqlite3.Connection, hours: int = 24) -> dict:
    """Amplitude: quantos dos simbolos coletados estao positivos na janela."""
    up = 0
    total = 0
    for s in all_symbols(conn):
        r = ret_pct(conn, s, hours)
        if r is not None:
            total += 1
            if r > 0:
                up += 1
    return {"up": up, "total": total, "pct_up": (100.0 * up / total if total else None)}
```

- [ ] **Step 4 (GREEN): confirmar passa** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k "ret_pct or read_returns or breadth" -v`.

- [ ] **Step 5: Checkpoint (NÃO commitar)** — `git diff -- market_read.py tests/test_market_read.py` ; `git status --short`.

---

### Task 4: `read_volatility` + `read_taker_ratio` — volatilidade e pressão compradora

**Files:** Modify `market_read.py`; Test `tests/test_market_read.py`.

- [ ] **Step 1 (RED): escrever os testes**

```python
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
```

- [ ] **Step 2 (RED): confirmar falha** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k "volatility or taker" -v`.

- [ ] **Step 3 (GREEN): implementar**

```python
def _window_cutoff(conn: sqlite3.Connection, symbol: str, hours: int):
    latest_ts, _ = _latest_close(conn, symbol)
    return None if latest_ts is None else latest_ts - hours * 3600


def read_volatility(conn: sqlite3.Connection, symbol: str, hours: int = 24) -> float | None:
    """Volatilidade = media de (high-low)/open*100 nas velas da janela."""
    cutoff = _window_cutoff(conn, symbol, hours)
    if cutoff is None:
        return None
    rows = conn.execute(
        "SELECT open_price, high_price, low_price FROM k_prices WHERE symbol=? AND bucket_ts>?",
        (symbol, cutoff),
    ).fetchall()
    vals = [100.0 * (r["high_price"] - r["low_price"]) / r["open_price"]
            for r in rows if r["open_price"]]
    return sum(vals) / len(vals) if vals else None


def read_taker_ratio(conn: sqlite3.Connection, symbol: str, hours: int = 24) -> float | None:
    """% do volume que foi taker comprador (>50% = pressao compradora)."""
    cutoff = _window_cutoff(conn, symbol, hours)
    if cutoff is None:
        return None
    row = conn.execute(
        "SELECT SUM(taker_buy_base) tb, SUM(volume) v FROM k_prices WHERE symbol=? AND bucket_ts>?",
        (symbol, cutoff),
    ).fetchone()
    if not row or not row["v"]:
        return None
    return 100.0 * (row["tb"] or 0.0) / row["v"]
```

- [ ] **Step 4 (GREEN): confirmar passa** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k "volatility or taker" -v`.

- [ ] **Step 5: Checkpoint (NÃO commitar)** — `git diff -- market_read.py tests/test_market_read.py` ; `git status --short`.

---

### Task 5: `read_lsr`, `read_funding`, `read_basis`, `read_oi_change` — crowding e alavancagem

`read_lsr` retorna só `{"global", "top"}` — sem `bucket_ts` (o output não usa timestamp, e um único `bucket_ts` para duas sources seria ambíguo).

**Files:** Modify `market_read.py`; Test `tests/test_market_read.py`.

- [ ] **Step 1 (RED): escrever os testes**

```python
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
```

- [ ] **Step 2 (RED): confirmar falha** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k "lsr or funding or basis or oi_change" -v`.

- [ ] **Step 3 (GREEN): implementar**

```python
def read_lsr(conn: sqlite3.Connection, symbol: str) -> dict:
    """Long/short ratio mais recente por source ('global_account' e 'top_position')."""
    out = {"global": None, "top": None}
    for source, key in (("global_account", "global"), ("top_position", "top")):
        row = conn.execute(
            "SELECT long_short_ratio FROM k_ratios WHERE symbol=? AND source=? "
            "ORDER BY bucket_ts DESC LIMIT 1",
            (symbol, source),
        ).fetchone()
        if row:
            out[key] = row["long_short_ratio"]
    return out


def read_funding(conn: sqlite3.Connection, symbol: str) -> dict:
    """Funding rate mais recente (funding_time em epoch s, granularidade 8h)."""
    row = conn.execute(
        "SELECT funding_time, funding_rate FROM k_funding_rates WHERE symbol=? "
        "ORDER BY funding_time DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if not row:
        return {"funding_rate": None, "funding_time": None}
    return {"funding_rate": row["funding_rate"], "funding_time": row["funding_time"]}


def read_basis(conn: sqlite3.Connection, symbol: str) -> dict:
    """Basis rate mais recente (futures vs index)."""
    row = conn.execute(
        "SELECT bucket_ts, basis_rate FROM k_basis WHERE symbol=? ORDER BY bucket_ts DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if not row:
        return {"basis_rate": None, "bucket_ts": None}
    return {"basis_rate": row["basis_rate"], "bucket_ts": row["bucket_ts"]}


def read_oi_change(conn: sqlite3.Connection, symbol: str, hours: int = 24) -> float | None:
    """% de variacao do sum_open_interest entre agora e (agora - hours). Robusto a gaps."""
    row = conn.execute(
        "SELECT bucket_ts, sum_open_interest FROM k_open_interest WHERE symbol=? "
        "ORDER BY bucket_ts DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if not row or not row["sum_open_interest"]:
        return None
    latest_ts, latest_oi = row["bucket_ts"], row["sum_open_interest"]
    prev = conn.execute(
        "SELECT sum_open_interest FROM k_open_interest WHERE symbol=? AND bucket_ts<=? "
        "ORDER BY bucket_ts DESC LIMIT 1",
        (symbol, latest_ts - hours * 3600),
    ).fetchone()
    if not prev or not prev["sum_open_interest"]:
        return None
    return 100.0 * (latest_oi / prev["sum_open_interest"] - 1)
```

- [ ] **Step 4 (GREEN): confirmar passa** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k "lsr or funding or basis or oi_change" -v`.

- [ ] **Step 5: Checkpoint (NÃO commitar)** — `git diff -- market_read.py tests/test_market_read.py` ; `git status --short`.

---

### Task 6: `read_regime` — compõe o termômetro macro (instrumento 1)

Schema: `{"returns_24h": dict, "returns_7d": dict, "breadth_24h": dict, "volatility_btc": float|None, "taker_btc": float|None, "lsr_btc": dict, "funding": dict[str,dict], "basis_btc": dict, "oi_change_btc": float|None}`. Microestrutura pesada em BTC; funding dos 3 majors; breadth dos 14.

**Files:** Modify `market_read.py`; Test `tests/test_market_read.py`.

- [ ] **Step 1 (RED): escrever o teste**

```python
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
```

- [ ] **Step 2 (RED): confirmar falha** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k regime -v`.

- [ ] **Step 3 (GREEN): implementar**

```python
def read_regime(conn: sqlite3.Connection) -> dict:
    """Termometro macro: componentes lado a lado (SEM veredito). Micro pesada em BTC."""
    return {
        "returns_24h": read_returns(conn, MAJORS, 24),
        "returns_7d": read_returns(conn, MAJORS, 24 * 7),
        "breadth_24h": read_breadth(conn, 24),
        "volatility_btc": read_volatility(conn, "BTCUSDT", 24),
        "taker_btc": read_taker_ratio(conn, "BTCUSDT", 24),
        "lsr_btc": read_lsr(conn, "BTCUSDT"),
        "funding": {s: read_funding(conn, s) for s in MAJORS},
        "basis_btc": read_basis(conn, "BTCUSDT"),
        "oi_change_btc": read_oi_change(conn, "BTCUSDT", 24),
    }
```

- [ ] **Step 4 (GREEN): confirmar passa** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k regime -v`.

- [ ] **Step 5: Checkpoint (NÃO commitar)** — `git diff -- market_read.py tests/test_market_read.py` ; `git status --short`.

---

### Task 7: `read_symbol` — zoom por moeda

Schema: `{"symbol", "ret_24h", "ret_7d", "lsr", "funding", "basis", "oi_change_24h", "volatility_24h", "taker_24h", "pressure"}` (`pressure` = dict do `read_pressure` para o símbolo, ou `{}`).

**Files:** Modify `market_read.py`; Test `tests/test_market_read.py`.

- [ ] **Step 1 (RED): escrever o teste**

```python
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
```

- [ ] **Step 2 (RED): confirmar falha** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k read_symbol -v`.

- [ ] **Step 3 (GREEN): implementar**

```python
def read_symbol(conn: sqlite3.Connection, symbol: str) -> dict:
    """Tudo de uma moeda num lugar (zoom do /mercado <SYM>)."""
    symbol = symbol.upper()
    pressure = next((p for p in read_pressure(conn, 24) if p["symbol"] == symbol), {})
    return {
        "symbol": symbol,
        "ret_24h": ret_pct(conn, symbol, 24),
        "ret_7d": ret_pct(conn, symbol, 24 * 7),
        "lsr": read_lsr(conn, symbol),
        "funding": read_funding(conn, symbol),
        "basis": read_basis(conn, symbol),
        "oi_change_24h": read_oi_change(conn, symbol, 24),
        "volatility_24h": read_volatility(conn, symbol, 24),
        "taker_24h": read_taker_ratio(conn, symbol, 24),
        "pressure": pressure,
    }
```

- [ ] **Step 4 (GREEN): confirmar passa** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k read_symbol -v`.

- [ ] **Step 5: Checkpoint (NÃO commitar)** — `git diff -- market_read.py tests/test_market_read.py` ; `git status --short`.

---

### Task 8: Formatação macro — helpers + `format_macro`

**Atenção anti-sinal:** ao escrever os formatadores, NÃO introduzir vocabulário de ação/ordem (nada de "comprador/vendedor/sinal/entrada/alvo/stop"). Usar "Taker buy", "Pressao", "cascata/squeeze". O teste `assert_no_signal_language` (Task 1) trava isso.

**Files:** Modify `market_read.py`; Test `tests/test_market_read.py`.

- [ ] **Step 1 (RED): escrever os testes (conteúdo-chave + rótulo + anti-sinal, não layout)**

```python
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
```

- [ ] **Step 2 (RED): confirmar falha** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k "fmt or pressure_label or format_macro" -v`.

- [ ] **Step 3 (GREEN): implementar**

```python
def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "n/d"
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.2f}M"
    if a >= 1e3:
        return f"${v / 1e3:.0f}k"
    return f"${v:.0f}"


def _fmt_pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "n/d"
    return f"{v:+.2f}%" if signed else f"{v:.2f}%"


def _fmt_num(v: float | None, decimals: int = 2) -> str:
    return "n/d" if v is None else f"{v:.{decimals}f}"


def _sym_short(symbol: str) -> str:
    """BTCUSDT -> BTC para exibicao compacta."""
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _pressure_label(p: dict) -> str:
    """Lado dominante: LONG liquidado=cascata baixa (vermelho); SHORT=squeeze alta (verde)."""
    total = p.get("total_usd") or 0.0
    if p.get("dominant_side") == "LONG":
        share = 100.0 * p["longs_liq_usd"] / total if total else 0.0
        return f"\U0001f534 longs {share:.0f}% (cascata ↓)"
    share = 100.0 * p["shorts_liq_usd"] / total if total else 0.0
    return f"\U0001f7e2 shorts {share:.0f}% (squeeze ↑)"


def format_macro(regime: dict, pressure: list[dict], top_n: int = 8) -> str:
    """Termometro macro + mapa de pressao em HTML. Mostra componentes, NAO veredito."""
    lines = ["\U0001f4ca <b>Leitura de Mercado</b>", ""]

    # --- Tendencia (majors) ---
    lines.append("\U0001f4c8 <b>Tendencia</b> (24h / 7d)")
    for sym in MAJORS:
        r24 = regime["returns_24h"].get(sym)
        r7 = regime["returns_7d"].get(sym)
        lines.append(f"  {_sym_short(sym)}: <code>{_fmt_pct(r24)}</code> / <code>{_fmt_pct(r7)}</code>")
    b = regime["breadth_24h"]
    breadth = f"{b['up']}/{b['total']}" if b["total"] else "n/d"
    lines.append(f"  Amplitude: <code>{breadth}</code> positivos 24h")
    lines.append("")

    # --- Volatilidade / fluxo (BTC) ---
    lines.append("\U0001f300 <b>Vol &amp; Fluxo</b> (BTC, 24h)")
    lines.append(f"  Range medio: <code>{_fmt_pct(regime['volatility_btc'], signed=False)}</code>")
    lines.append(f"  Taker buy: <code>{_fmt_pct(regime['taker_btc'], signed=False)}</code>")
    lines.append("")

    # --- Crowding / alavancagem (BTC) ---
    lsr = regime["lsr_btc"]
    fr = regime["funding"].get("BTCUSDT", {}).get("funding_rate")
    fr_str = f"{fr * 100:+.4f}%" if fr is not None else "n/d"
    lines.append("\U0001f9ed <b>Posicionamento</b> (BTC)")
    lines.append(f"  LSR global/top: <code>{_fmt_num(lsr['global'])}</code> / <code>{_fmt_num(lsr['top'])}</code>")
    lines.append(f"  Funding: <code>{fr_str}</code>")
    lines.append(f"  Basis: <code>{_fmt_num(regime['basis_btc']['basis_rate'], 4)}</code>")
    lines.append(f"  OI 24h: <code>{_fmt_pct(regime['oi_change_btc'])}</code>")
    lines.append("")

    # --- Mapa de pressao (liquidacoes) ---
    lines.append("\U0001f525 <b>Pressao 24h</b> (liquidacoes)")
    if not pressure:
        lines.append("  <i>sem dados</i>")
    else:
        for p in pressure[:top_n]:
            lines.append(f"  {_sym_short(p['symbol'])}: {_fmt_usd(p['total_usd'])} — "
                         f"{_pressure_label(p)} · {p['events']}ev")
    return "\n".join(lines)
```

- [ ] **Step 4 (GREEN): confirmar passa** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k "fmt or pressure_label or format_macro" -v`.

- [ ] **Step 5: Checkpoint (NÃO commitar)** — `git diff -- market_read.py tests/test_market_read.py` ; `git status --short`.

---

### Task 9: `format_symbol` — zoom por moeda

Usa o helper `assert_no_signal_language` definido no topo de `tests/test_market_read.py` (Task 1).

**Files:** Modify `market_read.py`; Test `tests/test_market_read.py`.

- [ ] **Step 1 (RED): escrever o teste**

```python
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
```

- [ ] **Step 2 (RED): confirmar falha** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k format_symbol -v`.

- [ ] **Step 3 (GREEN): implementar**

```python
def format_symbol(data: dict) -> str:
    """Zoom de uma moeda em HTML (sem veredito)."""
    sym = _sym_short(data["symbol"])
    lsr = data["lsr"]
    fr = data["funding"].get("funding_rate")
    fr_str = f"{fr * 100:+.4f}%" if fr is not None else "n/d"
    lines = [
        f"\U0001f50e <b>{sym}</b>",
        "",
        f"Retorno: <code>{_fmt_pct(data['ret_24h'])}</code> 24h · "
        f"<code>{_fmt_pct(data['ret_7d'])}</code> 7d",
        f"Range medio 24h: <code>{_fmt_pct(data['volatility_24h'], signed=False)}</code>",
        f"Taker buy 24h: <code>{_fmt_pct(data['taker_24h'], signed=False)}</code>",
        "",
        f"LSR global/top: <code>{_fmt_num(lsr['global'])}</code> / <code>{_fmt_num(lsr['top'])}</code>",
        f"Funding: <code>{fr_str}</code>",
        f"Basis: <code>{_fmt_num(data['basis']['basis_rate'], 4)}</code>",
        f"OI 24h: <code>{_fmt_pct(data['oi_change_24h'])}</code>",
        "",
    ]
    p = data["pressure"]
    if p:
        lines.append(f"\U0001f525 Pressao 24h: {_fmt_usd(p['total_usd'])} — "
                     f"{_pressure_label(p)} · {p['events']}ev")
    else:
        lines.append("\U0001f525 Pressao 24h: <i>sem liquidacoes</i>")
    return "\n".join(lines)
```

- [ ] **Step 4 (GREEN): confirmar passa** — ler o hook. _Fallback:_ `python -m pytest tests/test_market_read.py -k format_symbol -v`.

- [ ] **Step 5: Checkpoint (NÃO commitar)** — `git diff -- market_read.py tests/test_market_read.py` ; `git status --short`.

---

### Task 10: Handler Telegram `/mercado [SYM]` + roteamento com argumento

O dispatch atual (`_handle_command`) chama `handler()` sem argumentos. Para suportar `/mercado BTCUSDT`, o dispatch passa o argumento **apenas para handlers que o aceitam** (via `inspect.signature`), preservando 100% dos handlers existentes. O símbolo é extraído do texto **original** (não-lowercased) para preservar o case.

**Files:** Modify `telegram_commands.py`; Test `tests/test_telegram_mercado.py` (criar).

- [ ] **Step 1 (RED): criar `tests/test_telegram_mercado.py`**

```python
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

from liquidation_store import SCHEMA as LIQ_SCHEMA
from k_collector import SCHEMA as K_SCHEMA

NOW_S = 1_780_000_000
NOW_MS = NOW_S * 1000
HOUR = 3600


@pytest.fixture
def market_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(K_SCHEMA)
    conn.executescript(LIQ_SCHEMA)
    # BTC sobe 5% em 24h + 1 liquidacao de short
    conn.execute("INSERT INTO k_prices (symbol,bucket_ts,open_price,close_price,high_price,"
                 "low_price,volume,taker_buy_base,taker_buy_quote,collected_at) "
                 "VALUES ('BTCUSDT',?,100,100,100,100,1000,600,60000,?)",
                 (NOW_S - 24 * HOUR, NOW_S))
    conn.execute("INSERT INTO k_prices (symbol,bucket_ts,open_price,close_price,high_price,"
                 "low_price,volume,taker_buy_base,taker_buy_quote,collected_at) "
                 "VALUES ('BTCUSDT',?,100,105,106,99,1000,600,63000,?)", (NOW_S, NOW_S))
    conn.execute("INSERT INTO k_liquidations (source,symbol,event_ts,side,qty,price,notional,"
                 "collected_at) VALUES ('bybit','BTCUSDT',?,'SELL',5,100,500,?)", (NOW_MS, NOW_S))
    conn.commit()
    conn.close()
    monkeypatch.setattr("database.DB_FILE", path)
    yield path
    os.unlink(path)


def test_cmd_mercado_macro(market_db):
    from telegram_commands import _cmd_mercado
    msg = _cmd_mercado("")
    assert "Leitura de Mercado" in msg
    assert "BTC" in msg
    assert "+5.00%" in msg


def test_cmd_mercado_symbol_zoom(market_db):
    from telegram_commands import _cmd_mercado
    msg = _cmd_mercado("btcusdt")          # case-insensitive
    assert "BTC" in msg
    assert "Pressao" in msg


def test_cmd_mercado_unknown_symbol(market_db):
    from telegram_commands import _cmd_mercado
    msg = _cmd_mercado("FOOBAR")
    assert "FOOBAR" in msg
    assert "Disponiveis" in msg           # mensagem amigavel
    assert "BTC" in msg                   # lista os coletados


def test_handle_command_routes_mercado_with_arg(market_db):
    import telegram_commands as tc
    out = tc._handle_command("/mercado BTCUSDT")
    assert out is not None and "BTC" in out


def test_handle_command_legacy_handlers_still_work(monkeypatch):
    import telegram_commands as tc
    monkeypatch.setitem(tc._HANDLERS, "/ping_test", lambda: "pong")
    assert tc._handle_command("/ping_test") == "pong"
```

- [ ] **Step 2 (RED): confirmar falha** — ler o hook. _Fallback:_ `python -m pytest tests/test_telegram_mercado.py -v` (`_cmd_mercado` não existe; `/mercado` não roteia).

- [ ] **Step 3 (GREEN): `import inspect` + ajustar `_handle_command`**

Garantir `import inspect` no topo de `telegram_commands.py`. Substituir o corpo de `_handle_command` (linhas ~309-321) por:

```python
def _handle_command(text: str):
    raw = text.strip()
    cmd = raw.lower().split()[0]
    if "@" in cmd:
        cmd = cmd.split("@")[0]
    handler = _HANDLERS.get(cmd)
    if not handler:
        return None
    # argumento = resto do texto ORIGINAL (preserva case do simbolo)
    parts = raw.split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    try:
        if inspect.signature(handler).parameters:
            return handler(arg)
        return handler()
    except Exception as e:
        return f"❌ <b>Erro ao executar {cmd}:</b>\n<code>{e}</code>"
```

- [ ] **Step 4 (GREEN): adicionar `_cmd_mercado` e registrar em `_HANDLERS`**

```python
def _cmd_mercado(arg: str = ""):
    """Leitura de mercado sob demanda. Sem arg = macro; com arg = zoom no simbolo."""
    import database as db
    import market_read as mr

    conn = db._get_conn()
    try:
        token = arg.strip().upper()
        if not token:
            return mr.format_macro(mr.read_regime(conn), mr.read_pressure(conn))
        symbol = token if token.endswith("USDT") else f"{token}USDT"  # aceita "BTC" ou "BTCUSDT"
        known = set(mr.all_symbols(conn))
        if symbol not in known:
            disponiveis = ", ".join(mr._sym_short(s) for s in sorted(known))
            return (f"❓ <b>{token}</b> nao esta entre os simbolos coletados.\n"
                    f"<i>Disponiveis:</i> {disponiveis}")
        return mr.format_symbol(mr.read_symbol(conn, symbol))
    finally:
        conn.close()
```

Registrar no dict `_HANDLERS` (junto dos demais): `    "/mercado": _cmd_mercado,`

- [ ] **Step 5 (GREEN): confirmar passa** — ler o hook. _Fallback:_ `python -m pytest tests/test_telegram_mercado.py -v` → 5 PASS.

- [ ] **Step 6: Checkpoint (NÃO commitar)** — `git diff -- telegram_commands.py tests/test_telegram_mercado.py` ; `git status --short`.

---

### Task 11: `/mercado` no `/ajuda` + validação real + suíte completa

**Files:** Modify `telegram_commands.py` (texto do `/ajuda`); Modify `CLAUDE.md` (lista de comandos) — *opcional, doc*.

- [ ] **Step 1: atualizar o texto de `_cmd_ajuda`**

Localizar `_cmd_ajuda` e acrescentar a linha do novo comando, no mesmo estilo HTML das outras:

```python
        "\U0001f4ca /mercado [SIMBOLO] - Leitura de mercado (regime + pressao); com simbolo = zoom",
```

- [ ] **Step 2: ler o hook** — toda a suíte de mercado verde. _Fallback:_ `python -m pytest tests/test_market_read.py tests/test_telegram_mercado.py -v`.

- [ ] **Step 3: validação com 1 chamada REAL (`feedback_test_external_apis_early`)**

Rodar contra o `bot.db` de produção (read-only) e inspecionar o output renderizado:

```bash
cd ~/crypto_ai_bot && source .venv/bin/activate
python -c "
import database as db, market_read as mr
conn = db._get_conn()
print('=== MACRO ===')
print(mr.format_macro(mr.read_regime(conn), mr.read_pressure(conn)))
print()
print('=== ZOOM BTC ===')
print(mr.format_symbol(mr.read_symbol(conn, 'BTCUSDT')))
conn.close()
"
```

Conferir manualmente:
- Números batem com as queries de sanidade (ret 24h ≈ valores conhecidos; pressão coerente com o preço).
- **Rótulo do side correto:** em janela de alta, lado dominante = **shorts (squeeze ↑)**; em queda, **longs (cascata ↓)**.
- Mensagem < 4096 chars e HTML bem-formado.

- [ ] **Step 4: suíte completa (zero regressão)** — rodar manualmente (validação final):

```bash
python -m pytest tests/ --tb=short -q
```
Esperado: toda a suíte passa (handlers legados intactos).

- [ ] **Step 5: Checkpoint final (NÃO commitar)** — `git diff` ; `git status --short`. Apresentar o resumo ao Gabriel e aguardar "commita" (provável agrupamento em commits lógicos).

- [ ] **Step 6: Deploy (só após o Gabriel pedir)** — `sudo systemctl restart cryptobot` + validar `/mercado` vivo no Telegram (`feedback_deploy`). NÃO automático.

---

## Self-Review (executado contra a spec + feedback do Gabriel)

**1. Cobertura da spec:**
- ✅ Dor 1 (risco-on/off) → `read_regime` + `format_macro` (Tasks 6, 8).
- ✅ Dor 2 (onde está a pressão) → `read_pressure` + mapa (Tasks 2, 8).
- ✅ Dor 3 (ancorar no dado) → ambos sob demanda.
- ✅ Instrumento 1 — tendência, vol, taker, LSR (global+top), funding, basis, OI: Tasks 3-6.
- ✅ Instrumento 2 — liquidações por moeda, split de lado, eventos, ranking, dominância: Task 2.
- ✅ `/mercado <SYM>` zoom: Tasks 7, 9, 10.
- ✅ Arquitetura (`market_read.py` puro + handler reusa conexão; sem schema/migration/loop): respeitada.
- ✅ Não-objetivos: sem web, sem alertas, sem agente/LLM, sem veredito (teste `assert_no_signal_language` em 10 palavras).

**2. Ajustes do Gabriel incorporados:**
- ✅ Side `BUY=long/SELL=short` em constante única + nota "revalidar forward / não é eterno".
- ✅ Macro enxuto (BTC micro + majors + breadth); micro individual no zoom.
- ✅ Majors = BTC/ETH/SOL.
- ✅ Rótulo 🔴 cascata ↓ / 🟢 squeeze ↑ com texto explícito.
- ✅ **Sem commit em nenhuma task** — checkpoints com `git diff`/`git status` (regra nº 8).
- ✅ Task 1 TDD puro (teste → RED → módulo).
- ✅ Comandos manuais como **fallback** do hook (seção "Convenção de processo").
- ✅ `test_cmd_mercado_unknown_symbol` endurecido (exige "Disponiveis" + "BTC").
- ✅ Anti-sinal expandido para 10 palavras.
- ✅ `read_lsr` sem `bucket_ts` (campo ambíguo removido).

**3. Placeholders:** nenhum "TBD"/"handle edge cases" — código real e expected em cada step. Funções vazias só nos steps RED (proposital).

**4. Consistência de tipos:** assinaturas conferidas contra o "Contrato de tipos". Chaves de `read_pressure` (`longs_liq_usd`/`shorts_liq_usd`/`total_usd`/`events`/`dominant_side`) idênticas entre Tasks 2, 7, 8, 9. `read_lsr` → `{"global","top"}` consumido em Tasks 6/8/9. Helpers `_fmt_*`/`_sym_short`/`_pressure_label` definidos na Task 8, usados nas Tasks 8-9.
