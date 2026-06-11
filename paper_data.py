"""Diario paper manual (Fatia 4a do Trade Desk) — funcoes puras.

Registra teses de trade manual ANTES do resultado (tese imutavel), carimba o
contexto estrutural cru do market_read no momento do registro e acompanha via
scripts/paper_tracker.py. Mede o trader; NUNCA opina sobre o trade.

Spec: docs/superpowers/specs/2026-06-10-paper-manual-design.md
Nome da tabela e paper_manual_trades — paper_trades JA EXISTE (legado).
"""
from __future__ import annotations

import json
import math
import sqlite3
import time

import mercado_data
import market_read
from mercado_data import SUPPORTED_MARKET_SYMBOLS, normalize_symbol

# Universo do paper: SUPPORTED menos 1000PEPEUSDT (nao existe na API spot;
# toda a infra de preco do paper e spot: validacao, tracker, grafico).
PAPER_SYMBOLS = tuple(s for s in SUPPORTED_MARKET_SYMBOLS if s != "1000PEPEUSDT")

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
    df = df.sort_values("time")
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
    ensure_schema(conn)
    errors: list[str] = []
    symbol = normalize_symbol(form.get("symbol", ""))
    if symbol is None or symbol not in PAPER_SYMBOLS:
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
            if not math.isfinite(prices[field]) or prices[field] <= 0:
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
        errors.append(f"entrada longe do preco atual ({ref:g}) — tolerancia +-0,5%")
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


def pnl_gross_pct(direction: str, entry: float, exit_price: float) -> float:
    if direction == "long":
        return (exit_price - entry) / entry * 100.0
    return (entry - exit_price) / entry * 100.0


def _get_open(conn: sqlite3.Connection, trade_id: int):
    return conn.execute(
        "SELECT * FROM paper_manual_trades WHERE id=? AND status='open'",
        (trade_id,)).fetchone()


def void_trade(conn: sqlite3.Connection, now_s: int, trade_id: int, reason: str) -> dict:
    ensure_schema(conn)
    row = _get_open(conn, trade_id)
    if row is None:
        return {"ok": False, "errors": ["trade nao encontrado ou nao esta aberto"]}
    if now_s - row["created_at"] > VOID_WINDOW_S:
        return {"ok": False, "errors": ["janela de anulacao (10 min) expirou"]}
    cur = conn.execute(
        "UPDATE paper_manual_trades SET status='void', void_reason=?"
        " WHERE id=? AND status='open'",
        ((reason or "").strip() or "fat-finger", trade_id))
    if cur.rowcount != 1:
        return {"ok": False, "errors": ["trade nao encontrado ou nao esta aberto"]}
    conn.commit()
    return {"ok": True}


def close_manual(conn: sqlite3.Connection, get_candles_fn, now_s: int, trade_id: int) -> dict:
    ensure_schema(conn)
    row = _get_open(conn, trade_id)
    if row is None:
        return {"ok": False, "errors": ["trade nao encontrado ou nao esta aberto"]}
    price = _last_closed_price(get_candles_fn, row["symbol"], now_s)
    if price is None:
        return {"ok": False, "errors": ["preco atual indisponivel — tente de novo"]}
    cur = conn.execute(
        "UPDATE paper_manual_trades SET status='closed', exit_reason='manual',"
        " exit_price=?, exit_ts=? WHERE id=? AND status='open'",
        (price, now_s, trade_id))
    if cur.rowcount != 1:
        return {"ok": False, "errors": ["trade nao encontrado ou nao esta aberto"]}
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
    # Frescor do tracker: unica sinalizacao na UI de que o cron esta vivo.
    d["checked_min_ago"] = (
        max(0, (now_s - row["last_checked_ts"]) // 60)
        if row["last_checked_ts"] is not None else None
    )
    d["can_void"] = row["status"] == "open" and now_s - row["created_at"] <= VOID_WINDOW_S
    d["tags_list"] = row["tags"].split(",") if row["tags"] else []
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


def registro_view(conn: sqlite3.Connection, now_s: int, symbol_raw: str) -> dict:
    """Dados da pagina de registro: simbolo selecionado, condicoes (view do
    /mercado -- descritiva, mesma leitura que vira carimbo), abertos/fechados."""
    sym_raw = normalize_symbol(symbol_raw or "")
    # Constrain symbol to PAPER_SYMBOLS (e.g. ?symbol=1000PEPE falls back to BTCUSDT)
    symbol = sym_raw if (sym_raw and sym_raw in PAPER_SYMBOLS) else "BTCUSDT"
    try:
        condicoes = mercado_data.symbol_view(conn, symbol, now_s)
    except Exception:
        condicoes = None
    trades = list_trades(conn, now_s)
    return {
        "symbol": symbol,
        "symbols": PAPER_SYMBOLS,
        "condicoes": condicoes,
        "abertos": trades["abertos"],
        "fechados": trades["fechados"],
        "read_at": time.strftime("%d/%m %H:%M", time.localtime(now_s)),
    }
