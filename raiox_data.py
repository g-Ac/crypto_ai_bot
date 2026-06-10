"""
Leitura para o Raio-X dos Trades (pagina web /raiox/).

Funcoes puras: recebem conn / state_path / get_candles_fn e retornam dict/list.
Sem Flask, sem rede embutida na leitura de banco/state. Nao gera sinal nem recomendacao.
Mostra os trades do bot momentum como radiografia.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

MOMENTUM_INTERVAL_MIN = 15
VALID_SYMBOLS = {"BTCUSDT", "ETHUSDT"}
VALID_INTERVALS = ("15m", "1h", "4h", "1d")
_INTERVAL_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
FORBIDDEN_ACTION_PHRASES = (
    "compre", "comprar", "venda agora", "vender agora", "sinal",
    "recomendad", "operacao sugerida", "operação sugerida", "longar", "shortar",
)


def _to_epoch_s(ts: str) -> int:
    """Converte timestamp para epoch segundos UTC.

    Aceita ISO com timezone/offset, ISO com microssegundos, sufixo Z e
    'YYYY-MM-DD HH:MM:SS' naive tratado como UTC.
    """
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp())


def _row_get(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        if key in row.keys():
            return row[key]
    except AttributeError:
        pass
    return default


def _pnl_of(row) -> tuple[float, str]:
    net = _row_get(row, "net_pnl_pct")
    if net is not None:
        return float(net), "net_pnl_pct"
    pnl = _row_get(row, "pnl_pct", 0.0)
    return float(pnl), "pnl_pct"


def _classify_result(pnl_net: float, pnl_bruto: float) -> str:
    """Classifica o resultado do trade: win / loss / fee_ate (bruto positivo que a fee comeu)."""
    if pnl_net > 0:
        return "win"
    if pnl_bruto > 0:
        return "fee_ate"
    return "loss"


def _exit_icon(exit_reason: str) -> str:
    r = (exit_reason or "").lower()
    if "tp" in r:
        return "🟢"
    if "sl" in r:
        return "🔴"
    if "timeout" in r:
        return "⏱️"
    return "•"


def open_position(state_path: str) -> dict | None:
    """Le a posicao aberta do momentum_state.json (sem rede)."""
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
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


def list_trades(conn, state_path: str, limit: int = 50) -> dict:
    """Posicao aberta (state) + ultimos trades fechados, mais recente primeiro."""
    rows = conn.execute(
        "SELECT id, timestamp, symbol, direction, exit_reason, pnl_pct, net_pnl_pct "
        "FROM momentum_trades ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    closed = []
    for r in rows:
        pnl, source = _pnl_of(r)
        closed.append({
            "id": r["id"],
            "symbol": r["symbol"],
            "direction": r["direction"],
            "exit_reason": r["exit_reason"],
            "exit_icon": _exit_icon(r["exit_reason"]),
            "pnl_pct": pnl,
            "pnl_source": source,
            "timestamp_s": _to_epoch_s(r["timestamp"]),
        })
    return {"open": open_position(state_path), "closed": closed}


def _trade_summary(d: dict) -> str:
    """Resumo factual do trade (sem frase de acao)."""
    mins = (d["duration_candles"] or 0) * MOMENTUM_INTERVAL_MIN
    dur = f"{d['duration_candles']} velas (~{mins}min)"
    pnl_label = "net" if d["pnl_source"] == "net_pnl_pct" else "bruto"
    pnl = f"{d['pnl_pct']:+.2f}% ({pnl_label})"
    mfe = f"+{d['mfe_pct']:.2f}%" if d.get("mfe_pct") is not None else "n/d"
    mae = f"{d['mae_pct']:.2f}%" if d.get("mae_pct") is not None else "n/d"
    return (
        f"{d['direction']} · entrada estimada {d['entry_price']} · "
        f"saida {d['exit_price']} ({d['exit_reason']}) · durou {dur} · "
        f"resultado {pnl} · foi a {mfe} a favor e {mae} contra · regime {d['regime']}"
    )


def trade_detail(conn, trade_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM momentum_trades WHERE id=?", (trade_id,)).fetchone()
    if row is None:
        return None
    pnl, source = _pnl_of(row)
    exit_s = _to_epoch_s(row["timestamp"])
    dur = row["duration_candles"] or 0
    d = {
        "id": row["id"],
        "symbol": row["symbol"],
        "direction": row["direction"],
        "regime": row["regime"],
        "entry_price": row["entry_price"],
        "exit_price": row["exit_price"],
        "sl_price": row["sl_price"],
        "tp1_price": row["tp1_price"],
        "tp2_price": row["tp2_price"],
        "exit_reason": row["exit_reason"],
        "duration_candles": dur,
        "mfe_pct": row["mfe_pct"],
        "mae_pct": row["mae_pct"],
        "pnl_pct": pnl,
        "pnl_source": source,
        "exit_time_s": exit_s,
        "entry_time_s": exit_s - dur * MOMENTUM_INTERVAL_MIN * 60,
        "entry_time_estimated": True,
    }
    d["summary"] = _trade_summary(d)
    return d


def trades_overlay(conn, symbol: str) -> dict:
    """Todos os trades fechados de um simbolo como pontos de plotagem do mapa.

    entry_time_s e ESTIMADO (timestamp - duration_candles * 15min), igual ao trade_detail.
    Sem net_pnl_pct no row, classifica pelo bruto (nunca vira fee_ate).
    """
    rows = conn.execute(
        "SELECT id, timestamp, direction, entry_price, exit_price, "
        "duration_candles, pnl_pct, net_pnl_pct "
        "FROM momentum_trades WHERE symbol=? ORDER BY id ASC", (symbol,)
    ).fetchall()
    trades = []
    for r in rows:
        pnl, source = _pnl_of(r)
        exit_s = _to_epoch_s(r["timestamp"])
        dur = r["duration_candles"] or 0
        bruto = float(_row_get(r, "pnl_pct") or 0.0)
        net = _row_get(r, "net_pnl_pct")
        trades.append({
            "id": r["id"],
            "direction": r["direction"],
            "entry_time_s": exit_s - dur * MOMENTUM_INTERVAL_MIN * 60,
            "entry_price": r["entry_price"],
            "exit_time_s": exit_s,
            "exit_price": r["exit_price"],
            "result": _classify_result(float(net) if net is not None else bruto, bruto),
            "pnl_pct": pnl,
            "pnl_source": source,
        })
    return {"ok": True, "symbol": symbol, "trades": trades}


def _choose_interval(start_s: int, now_s: int, requested: str, margin: int, max_bars: int) -> str | None:
    start_idx = VALID_INTERVALS.index(requested)
    for interval in VALID_INTERVALS[start_idx:]:
        tf = _INTERVAL_SECONDS[interval]
        bars = (now_s - start_s) / tf + margin
        if bars <= max_bars:
            return interval
    return None


def fetch_candles(symbol, interval, start_s, end_s, now_s, get_candles_fn,
                  margin: int = 20, max_bars: int = 1000) -> dict:
    """Wrapper sobre get_candles(symbol, interval, limit).

    Escala o timeframe se a janela for longa demais e filtra para o range com margem.
    get_candles_fn e injetavel para teste. Nao altera market.py.
    """
    if start_s >= end_s:
        return {"ok": False, "error": "intervalo_invalido", "message": "start >= end"}
    eff = _choose_interval(start_s, now_s, interval, margin, max_bars)
    if eff is None:
        return {
            "ok": False,
            "error": "janela_muito_longa",
            "message": "janela longa demais ate para velas diarias",
        }
    tf = _INTERVAL_SECONDS[eff]
    limit = min(max_bars, math.ceil((now_s - start_s) / tf) + margin)
    df = get_candles_fn(symbol, eff, limit)
    records = df.to_dict("records")
    lo, hi = start_s - margin * tf, end_s + margin * tf
    candles = [
        {
            "time": int(r["time_s"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        for r in records
        if lo <= int(r["time_s"]) <= hi
    ]
    return {
        "ok": True,
        "symbol": symbol,
        "interval": interval,
        "effective_interval": eff,
        "candles": candles,
    }
