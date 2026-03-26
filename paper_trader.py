import json
import os
import tempfile
import requests
import pandas as pd
import ta
from datetime import datetime, timedelta
from config import (
    STOP_LOSS_MAP, STOP_LOSS_PCT, PAPER_INITIAL_CAPITAL,
    PAPER_MAX_POSITIONS, PAPER_REWARD_RATIO, COOLDOWN_MINUTES,
    ATR_SL_MULTIPLIER, ATR_TP_MULTIPLIER, ATR_SL_FLOOR_PCT,
)
import database as db

STATE_FILE = "paper_state.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "capital": PAPER_INITIAL_CAPITAL,
            "positions": {},
            "cooldowns": {},
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
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


def get_atr_1h(symbol, period=14):
    """Calcula ATR no timeframe 1h para SL/TP dinamico."""
    try:
        resp = requests.get(
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=1h&limit={period + 5}",
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore",
        ])
        for col in ["high", "low", "close"]:
            df[col] = df[col].astype(float)
        atr = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=period
        ).average_true_range()
        return atr.iloc[-1]
    except Exception:
        return None


def log_trade(trade):
    db.insert_paper_trade(trade)


def process_signals(results):
    """Process all signals from a cycle and manage paper positions."""
    state = load_state()
    messages = []

    for result in results:
        symbol = result["symbol"]
        price = result["price"]
        decision = result["decision"]

        # ── Checar posicao aberta ──────────────────────────────────────
        if symbol in state["positions"]:
            pos = state["positions"][symbol]
            entry = pos["entry_price"]
            sl_price = pos.get("sl_price")
            tp_price = pos.get("tp_price")
            sl_pct = pos.get("sl_pct", STOP_LOSS_MAP.get(symbol, STOP_LOSS_PCT))

            if pos["type"] == "LONG":
                pnl_pct = ((price - entry) / entry) * 100
                sl_hit = (price <= sl_price) if sl_price else (pnl_pct <= -sl_pct)
                tp_hit = (price >= tp_price) if tp_price else False
            else:
                pnl_pct = ((entry - price) / entry) * 100
                sl_hit = (price >= sl_price) if sl_price else (pnl_pct <= -sl_pct)
                tp_hit = (price <= tp_price) if tp_price else False

            # Saida: stop loss
            if sl_hit:
                if sl_price:
                    pnl_pct = (
                        ((sl_price - entry) / entry) * 100 if pos["type"] == "LONG"
                        else ((entry - sl_price) / entry) * 100
                    )
                else:
                    pnl_pct = -sl_pct
                msg = close_position(state, symbol, price, pnl_pct, "stop_loss")
                messages.append(msg)
                continue

            # Saida: take profit
            if tp_hit:
                pnl_pct = (
                    ((tp_price - entry) / entry) * 100 if pos["type"] == "LONG"
                    else ((entry - tp_price) / entry) * 100
                )
                msg = close_position(state, symbol, price, pnl_pct, "take_profit")
                messages.append(msg)
                # Fall through para abrir nova posicao abaixo

            # Saida: sinal oposto
            elif (pos["type"] == "LONG" and decision == "SELL") or \
                 (pos["type"] == "SHORT" and decision == "BUY"):
                msg = close_position(state, symbol, price, pnl_pct, "signal")
                messages.append(msg)
                # Fall through para abrir nova posicao abaixo

        # ── Abrir nova posicao ─────────────────────────────────────────
        if decision in ["BUY", "SELL"] and symbol not in state["positions"]:
            # Limite de posicoes simultaneas
            if len(state["positions"]) >= PAPER_MAX_POSITIONS:
                continue

            # Cooldown apos stop_loss
            cooldowns = state.get("cooldowns", {})
            if symbol in cooldowns:
                cooldown_end = datetime.fromisoformat(cooldowns[symbol]) + timedelta(minutes=COOLDOWN_MINUTES)
                if datetime.now() < cooldown_end:
                    remaining = int((cooldown_end - datetime.now()).total_seconds() / 60)
                    messages.append(f"PAPER: {symbol} em cooldown ({remaining}min restantes apos stop_loss)")
                    continue

            pos_type = "LONG" if decision == "BUY" else "SHORT"

            # SL/TP dinamico via ATR 1h
            atr = get_atr_1h(symbol)
            if atr:
                sl_pct = max((atr * ATR_SL_MULTIPLIER / price) * 100, ATR_SL_FLOOR_PCT)
                tp_pct = (atr * ATR_TP_MULTIPLIER / price) * 100
            else:
                sl_pct = max(STOP_LOSS_MAP.get(symbol, STOP_LOSS_PCT), ATR_SL_FLOOR_PCT)
                tp_pct = sl_pct * PAPER_REWARD_RATIO

            if pos_type == "LONG":
                sl_price = price * (1 - sl_pct / 100)
                tp_price = price * (1 + tp_pct / 100)
            else:
                sl_price = price * (1 + sl_pct / 100)
                tp_price = price * (1 - tp_pct / 100)

            n_open = len(state["positions"]) + 1
            allocation = state["capital"] / n_open
            state["positions"][symbol] = {
                "type": pos_type,
                "entry_price": price,
                "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "sl_pct": round(sl_pct, 2),
                "sl_price": round(sl_price, 6),
                "tp_price": round(tp_price, 6),
                "allocation": allocation,
            }

            messages.append(
                f"PAPER {pos_type} aberto: {symbol}\n"
                f"Entrada: {price:.4f} | SL: {sl_price:.4f} (-{sl_pct:.1f}%) | TP: {tp_price:.4f}\n"
                f"Capital: ${state['capital']:.2f}"
            )

    save_state(state)
    return messages


def close_position(state, symbol, price, pnl_pct, reason):
    pos = state["positions"].pop(symbol)
    entry = pos["entry_price"]

    allocation = pos.get("allocation", state["capital"] / max(len(state["positions"]) + 1, 1))
    pnl_usd = allocation * (pnl_pct / 100)

    state["capital"] += pnl_usd
    state["total_trades"] += 1
    state["total_pnl"] += pnl_pct

    if pnl_pct > 0:
        state["wins"] += 1
    else:
        state["losses"] += 1

    if reason == "stop_loss":
        state.setdefault("cooldowns", {})[symbol] = datetime.now().isoformat()

    wr = (state["wins"] / state["total_trades"]) * 100 if state["total_trades"] > 0 else 0

    trade = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "type": pos["type"],
        "entry_price": entry,
        "exit_price": price,
        "sl_price": pos.get("sl_price"),
        "tp_price": pos.get("tp_price"),
        "pnl_pct": pnl_pct,
        "pnl_usd": pnl_usd,
        "exit_reason": reason,
        "capital_after": state["capital"],
    }
    log_trade(trade)

    return (
        f"PAPER {pos['type']} fechado: {symbol}\n"
        f"Entrada: {entry:.4f} | Saida: {price:.4f}\n"
        f"P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
        f"Motivo: {reason}\n"
        f"Capital: ${state['capital']:.2f} | "
        f"Trades: {state['total_trades']} | WR: {wr:.1f}%"
    )


def get_status():
    """Return current paper trading status."""
    state = load_state()
    wr = (state["wins"] / state["total_trades"]) * 100 if state["total_trades"] > 0 else 0
    ret = ((state["capital"] - PAPER_INITIAL_CAPITAL) / PAPER_INITIAL_CAPITAL) * 100

    lines = [
        f"Capital: ${state['capital']:.2f} ({ret:+.2f}%)",
        f"Trades: {state['total_trades']} | W:{state['wins']} L:{state['losses']} | WR: {wr:.1f}%",
    ]

    if state["positions"]:
        lines.append(f"Posicoes abertas: {len(state['positions'])}/{PAPER_MAX_POSITIONS}")
        for sym, pos in state["positions"].items():
            sl = f"{pos['sl_price']:.4f}" if pos.get("sl_price") else f"-{pos.get('sl_pct', '?')}%"
            tp = f"{pos['tp_price']:.4f}" if pos.get("tp_price") else "n/a"
            lines.append(f"  {sym}: {pos['type']} @ {pos['entry_price']:.4f} | SL: {sl} | TP: {tp}")

    return "\n".join(lines)
