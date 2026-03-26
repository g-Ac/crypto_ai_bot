"""
Pump Trader - gerencia posicoes em moedas com volume anormal.
Estrategia:
  1. Pump detectado -> LONG com trailing stop
  2. Pump exauriu -> SHORT com trailing stop
"""
import json
import os
import tempfile
import requests
import pandas as pd
import ta
from datetime import datetime
import database as db
from config import (
    PUMP_TRAILING_STOP, PUMP_MAX_POSITION_TIME,
    PUMP_POSITION_SIZE_PCT, PUMP_RSI_EXHAUSTION,
    PUMP_DUMP_RETRACE_PCT, PUMP_CAPITAL, PUMP_INITIAL_CAPITAL,
)

STATE_FILE = "pump_positions.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "capital": PUMP_CAPITAL,
            "positions": {},
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
        }
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    data = json.dumps(state, indent=4, default=str)
    dir_name = os.path.dirname(os.path.abspath(STATE_FILE))
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as f:
        f.write(data)
        tmp_path = f.name
    os.replace(tmp_path, STATE_FILE)


def log_trade(trade):
    db.insert_pump_trade(trade)


def get_current_price(symbol):
    try:
        resp = requests.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
            timeout=5,
        )
        if resp.status_code == 200:
            return float(resp.json()["price"])
    except Exception:
        pass
    return None


def get_rsi(symbol, period=6):
    """RSI curto para detectar exaustao rapida."""
    try:
        resp = requests.get(
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=5m&limit=30",
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        closes = pd.Series([float(c[4]) for c in data])
        rsi = ta.momentum.RSIIndicator(close=closes, window=period).rsi()
        return rsi.iloc[-1]
    except Exception:
        return None


def open_position(symbol, direction, price, volume_ratio):
    """Open a new pump/dump position."""
    state = load_state()

    if symbol in state["positions"]:
        return None  # ja tem posicao

    allocation = state["capital"] * (PUMP_POSITION_SIZE_PCT / 100)

    state["positions"][symbol] = {
        "type": direction,
        "entry_price": price,
        "entry_time": datetime.now().isoformat(),
        "peak_price": price,
        "trough_price": price,
        "trailing_stop": PUMP_TRAILING_STOP,
        "volume_ratio_at_entry": volume_ratio,
        "allocation": allocation,
        "pump_high": price,  # track the highest point of the pump
    }

    save_state(state)

    return (
        f"[PUMP TRADE] {direction} aberto: {symbol}\n"
        f"Entrada: {price:.6f}\n"
        f"Volume: {volume_ratio}x a media\n"
        f"Trailing stop: {PUMP_TRAILING_STOP}%\n"
        f"Capital alocado: ${allocation:.2f}"
    )


def check_positions():
    """Check all open positions for exits."""
    state = load_state()
    messages = []
    closed = []

    for symbol, pos in list(state["positions"].items()):
        price = get_current_price(symbol)
        if price is None:
            continue

        entry = pos["entry_price"]
        pos_type = pos["type"]
        entry_time = datetime.fromisoformat(pos["entry_time"])
        duration = (datetime.now() - entry_time).total_seconds() / 60

        # Update peak/trough
        if pos_type == "LONG":
            if price > pos["peak_price"]:
                pos["peak_price"] = price
            # P&L from entry
            pnl_pct = ((price - entry) / entry) * 100
            # Trailing: distance from peak
            drop_from_peak = ((pos["peak_price"] - price) / pos["peak_price"]) * 100
            trailing_hit = drop_from_peak >= pos["trailing_stop"]

        else:  # SHORT
            if price < pos.get("trough_price", entry):
                pos["trough_price"] = price
            pnl_pct = ((entry - price) / entry) * 100
            rise_from_trough = ((price - pos.get("trough_price", entry)) / pos.get("trough_price", entry)) * 100
            trailing_hit = rise_from_trough >= pos["trailing_stop"]

        # Update pump high for dump detection later
        if price > pos.get("pump_high", 0):
            pos["pump_high"] = price

        # Exit conditions
        exit_reason = None

        if trailing_hit:
            exit_reason = "trailing_stop"
        elif duration >= PUMP_MAX_POSITION_TIME:
            exit_reason = "timeout"

        if exit_reason:
            allocation = pos["allocation"]
            pnl_usd = allocation * (pnl_pct / 100)
            state["capital"] += pnl_usd
            state["total_trades"] += 1

            if pnl_pct > 0:
                state["wins"] += 1
            else:
                state["losses"] += 1

            trade = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "type": pos_type,
                "entry_price": entry,
                "exit_price": price,
                "pnl_pct": pnl_pct,
                "pnl_usd": pnl_usd,
                "exit_reason": exit_reason,
                "duration_min": round(duration, 1),
                "peak_price": pos.get("peak_price", entry),
                "capital_after": state["capital"],
            }
            log_trade(trade)

            wr = (state["wins"] / state["total_trades"]) * 100

            msg = (
                f"[PUMP TRADE] {pos_type} fechado: {symbol}\n"
                f"Entrada: {entry:.6f} | Saida: {price:.6f}\n"
                f"P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
                f"Motivo: {exit_reason} | Duracao: {duration:.0f}min\n"
                f"Capital: ${state['capital']:.2f} | "
                f"Trades: {state['total_trades']} | WR: {wr:.1f}%"
            )
            messages.append(msg)

            # Check if we should enter dump after closing a pump long
            if pos_type == "LONG" and exit_reason == "trailing_stop" and pnl_pct > 5:
                pump_high = pos.get("pump_high", entry)
                retrace = ((pump_high - price) / pump_high) * 100
                if retrace >= PUMP_DUMP_RETRACE_PCT * 0.5:
                    # Potential dump starting - check RSI
                    rsi = get_rsi(symbol)
                    if rsi and rsi > PUMP_RSI_EXHAUSTION * 0.9:
                        closed.append({"symbol": symbol, "action": "SHORT", "price": price,
                                       "volume_ratio": pos["volume_ratio_at_entry"]})

            del state["positions"][symbol]

    save_state(state)

    # Open dump positions if detected
    for c in closed:
        msg = open_position(c["symbol"], "SHORT", c["price"], c["volume_ratio"])
        if msg:
            messages.append(msg)

    return messages


def check_dump_entry(symbol, pump_data):
    """Check if a pumped coin is ready for dump entry."""
    state = load_state()

    if symbol in state["positions"]:
        return None

    price = get_current_price(symbol)
    if price is None:
        return None

    rsi = get_rsi(symbol)
    if rsi is None:
        return None

    # Conditions for dump entry:
    # 1. RSI very high (exhaustion)
    # 2. Price starting to retrace from pump high
    if rsi >= PUMP_RSI_EXHAUSTION:
        return {
            "symbol": symbol,
            "price": price,
            "rsi": rsi,
            "ready": True,
            "reason": f"RSI {rsi:.0f} indica exaustao",
        }

    return None


def get_status():
    state = load_state()
    wr = (state["wins"] / state["total_trades"]) * 100 if state["total_trades"] > 0 else 0
    ret = ((state["capital"] - PUMP_CAPITAL) / PUMP_CAPITAL) * 100

    lines = [
        f"[PUMP] Capital: ${state['capital']:.2f} ({ret:+.2f}%)",
        f"[PUMP] Trades: {state['total_trades']} | W:{state['wins']} L:{state['losses']} | WR: {wr:.1f}%",
    ]

    if state["positions"]:
        lines.append(f"[PUMP] Posicoes abertas: {len(state['positions'])}")
        for sym, pos in state["positions"].items():
            price = get_current_price(sym)
            if price:
                entry = pos["entry_price"]
                if pos["type"] == "LONG":
                    pnl = ((price - entry) / entry) * 100
                else:
                    pnl = ((entry - price) / entry) * 100
                lines.append(f"  {sym}: {pos['type']} @ {entry:.6f} | Atual: {price:.6f} | P&L: {pnl:+.2f}%")

    return "\n".join(lines)
