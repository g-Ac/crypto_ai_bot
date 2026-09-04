"""
Livro de paper trading MANUAL do Raio-X (separado do bot).

Isolado de proposito: NAO importa nem altera paper_trader, estrategia, momentum,
schema do bot, nem market.py. Persiste num JSON proprio injetado por caminho.
Funcoes puras/injetaveis (price_fn) para teste. Sem rede embutida.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

DEFAULT_START_BALANCE = 10000.0
MIN_LEVERAGE = 1.0
MAX_LEVERAGE = 125.0
SIDES = ("LONG", "SHORT")


def empty_book(start_balance: float = DEFAULT_START_BALANCE) -> dict:
    return {
        "start_balance": float(start_balance),
        "balance": float(start_balance),
        "next_id": 1,
        "positions": [],
        "closed": [],
    }


def load_book(path: str, start_balance: float = DEFAULT_START_BALANCE) -> dict:
    try:
        with open(path) as f:
            book = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return empty_book(start_balance)
    for k, v in empty_book(start_balance).items():
        book.setdefault(k, v)
    return book


def save_book(path: str, book: dict) -> None:
    data = json.dumps(book, indent=2, default=str)
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=d, delete=False, suffix=".tmp") as f:
        f.write(data)
        tmp = f.name
    os.replace(tmp, path)


def used_margin(book: dict) -> float:
    return sum(float(p["margin_usd"]) for p in book["positions"])


def available_balance(book: dict) -> float:
    return float(book["balance"]) - used_margin(book)


def liq_price(side: str, entry: float, leverage: float) -> float:
    """Preco de liquidacao aproximado (ignora taxas/funding)."""
    frac = 1.0 / leverage
    return entry * (1 - frac) if side == "LONG" else entry * (1 + frac)


def position_pnl(pos: dict, price: float) -> dict:
    entry = float(pos["entry_price"])
    direction = 1.0 if pos["side"] == "LONG" else -1.0
    move_pct = (price - entry) / entry * 100.0 * direction
    pnl_usd = float(pos["notional_usd"]) * move_pct / 100.0
    pnl_pct_margin = move_pct * float(pos["leverage"])
    return {
        "price": round(price, 2),
        "move_pct": round(move_pct, 4),
        "pnl_usd": round(pnl_usd, 2),
        "pnl_pct": round(pnl_pct_margin, 2),
        "liq_price": round(liq_price(pos["side"], entry, float(pos["leverage"])), 2),
    }


def _validate_levels(side: str, entry: float, sl, tp):
    if sl is not None:
        if side == "LONG" and not (sl < entry):
            raise ValueError("sl_invalido")
        if side == "SHORT" and not (sl > entry):
            raise ValueError("sl_invalido")
    if tp is not None:
        if side == "LONG" and not (tp > entry):
            raise ValueError("tp_invalido")
        if side == "SHORT" and not (tp < entry):
            raise ValueError("tp_invalido")


def open_order(book: dict, *, symbol, side, entry_price, margin_usd, leverage,
               sl_price=None, tp_price=None, now_s=None) -> dict:
    """Abre uma posicao paper manual. Levanta ValueError(codigo) se invalido."""
    side = (side or "").upper()
    if side not in SIDES:
        raise ValueError("side_invalido")
    entry = float(entry_price)
    margin = float(margin_usd)
    lev = float(leverage)
    if entry <= 0:
        raise ValueError("entry_invalido")
    if margin <= 0:
        raise ValueError("margin_invalido")
    if not (MIN_LEVERAGE <= lev <= MAX_LEVERAGE):
        raise ValueError("leverage_invalido")
    sl = float(sl_price) if sl_price not in (None, "") else None
    tp = float(tp_price) if tp_price not in (None, "") else None
    _validate_levels(side, entry, sl, tp)
    if margin > available_balance(book) + 1e-9:
        raise ValueError("saldo_insuficiente")
    notional = margin * lev
    pos = {
        "id": int(book["next_id"]),
        "symbol": symbol,
        "side": side,
        "entry_price": round(entry, 2),
        "margin_usd": round(margin, 2),
        "leverage": lev,
        "notional_usd": round(notional, 2),
        "qty": round(notional / entry, 8),
        "sl_price": round(sl, 2) if sl is not None else None,
        "tp_price": round(tp, 2) if tp is not None else None,
        "open_time_s": int(now_s if now_s is not None else time.time()),
        "status": "open",
    }
    book["next_id"] = int(book["next_id"]) + 1
    book["positions"].append(pos)
    return pos


def close_position(book: dict, pos_id: int, price: float, reason: str = "manual", now_s=None) -> dict | None:
    idx = next((i for i, p in enumerate(book["positions"]) if int(p["id"]) == int(pos_id)), None)
    if idx is None:
        return None
    pos = book["positions"].pop(idx)
    pnl = position_pnl(pos, float(price))
    pos = dict(pos)
    pos.update({
        "status": "closed",
        "exit_price": round(float(price), 2),
        "exit_reason": reason,
        "pnl_usd": pnl["pnl_usd"],
        "pnl_pct": pnl["pnl_pct"],
        "close_time_s": int(now_s if now_s is not None else time.time()),
    })
    book["balance"] = round(float(book["balance"]) + pnl["pnl_usd"], 2)
    book["closed"].insert(0, pos)
    return pos


def _hit_level(pos: dict, price: float):
    """Retorna (reason, fill_price) se o preco cruzou SL/TP, senao None."""
    side = pos["side"]
    sl = pos.get("sl_price")
    tp = pos.get("tp_price")
    if side == "LONG":
        if sl is not None and price <= sl:
            return "sl_hit", sl
        if tp is not None and price >= tp:
            return "tp_hit", tp
    else:
        if sl is not None and price >= sl:
            return "sl_hit", sl
        if tp is not None and price <= tp:
            return "tp_hit", tp
    return None


def mark_and_autoclose(book: dict, price_fn, now_s=None) -> list:
    """Marca a mercado e fecha automaticamente quem bateu SL/TP.

    price_fn(symbol) -> preco atual (float) ou None se indisponivel.
    Retorna lista de fechamentos automaticos ocorridos.
    """
    auto = []
    for pos in list(book["positions"]):
        price = price_fn(pos["symbol"])
        if price is None:
            continue
        hit = _hit_level(pos, float(price))
        if hit:
            reason, fill = hit
            closed = close_position(book, pos["id"], fill, reason, now_s=now_s)
            if closed:
                auto.append(closed)
    return auto


def view(book: dict, price_fn) -> dict:
    """Monta a visao para a API: posicoes abertas com PnL atual + resumo."""
    open_rows = []
    unrealized = 0.0
    for pos in book["positions"]:
        price = price_fn(pos["symbol"])
        row = dict(pos)
        if price is not None:
            row["mark"] = position_pnl(pos, float(price))
            unrealized += row["mark"]["pnl_usd"]
        else:
            row["mark"] = None
        open_rows.append(row)
    return {
        "start_balance": round(float(book["start_balance"]), 2),
        "balance": round(float(book["balance"]), 2),
        "used_margin": round(used_margin(book), 2),
        "available": round(available_balance(book), 2),
        "unrealized_usd": round(unrealized, 2),
        "equity": round(float(book["balance"]) + unrealized, 2),
        "positions": open_rows,
        "closed": book["closed"][:50],
    }


def reset_book(path: str, start_balance: float = DEFAULT_START_BALANCE) -> dict:
    book = empty_book(start_balance)
    save_book(path, book)
    return book
