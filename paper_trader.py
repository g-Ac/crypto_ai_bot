import json
import os
import tempfile
from datetime import datetime, timedelta
from config import STOP_LOSS_MAP, STOP_LOSS_PCT, PAPER_INITIAL_CAPITAL, PAPER_MAX_POSITIONS, COOLDOWN_MINUTES
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
        sl_pct = STOP_LOSS_MAP.get(symbol, STOP_LOSS_PCT)

        # Check stop loss on open positions
        if symbol in state["positions"]:
            pos = state["positions"][symbol]
            entry = pos["entry_price"]

            if pos["type"] == "LONG":
                pnl_pct = ((price - entry) / entry) * 100
                sl_hit = pnl_pct <= -sl_pct
            else:
                pnl_pct = ((entry - price) / entry) * 100
                sl_hit = pnl_pct <= -sl_pct

            # Exit: stop loss
            if sl_hit:
                pnl_pct = -sl_pct
                msg = close_position(state, symbol, price, pnl_pct, "stop_loss")
                messages.append(msg)
                continue

            # Exit: opposite signal
            if (pos["type"] == "LONG" and decision == "SELL") or \
               (pos["type"] == "SHORT" and decision == "BUY"):
                msg = close_position(state, symbol, price, pnl_pct, "signal")
                messages.append(msg)
                # Fall through to open new position below

        # Open new position
        if decision in ["BUY", "SELL"] and symbol not in state["positions"]:
            # Check max simultaneous positions
            if len(state["positions"]) >= PAPER_MAX_POSITIONS:
                continue

            # Check cooldown after stop_loss
            cooldowns = state.get("cooldowns", {})
            if symbol in cooldowns:
                cooldown_end = datetime.fromisoformat(cooldowns[symbol]) + timedelta(minutes=COOLDOWN_MINUTES)
                if datetime.now() < cooldown_end:
                    remaining = int((cooldown_end - datetime.now()).total_seconds() / 60)
                    messages.append(f"PAPER: {symbol} em cooldown ({remaining}min restantes apos stop_loss)")
                    continue

            pos_type = "LONG" if decision == "BUY" else "SHORT"
            n_open = len(state["positions"]) + 1
            allocation = state["capital"] / n_open
            state["positions"][symbol] = {
                "type": pos_type,
                "entry_price": price,
                "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "sl_pct": sl_pct,
                "allocation": allocation,
            }

            messages.append(
                f"PAPER {pos_type} aberto: {symbol}\n"
                f"Entrada: {price:.4f} | SL: {sl_pct}%\n"
                f"Capital: ${state['capital']:.2f}"
            )

    save_state(state)
    return messages


def close_position(state, symbol, price, pnl_pct, reason):
    pos = state["positions"].pop(symbol)
    entry = pos["entry_price"]

    # Use allocation saved at entry time
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
        lines.append(f"Posicoes abertas: {len(state['positions'])}")
        for sym, pos in state["positions"].items():
            lines.append(f"  {sym}: {pos['type']} @ {pos['entry_price']:.4f}")

    return "\n".join(lines)
