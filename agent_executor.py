"""
Agent Executor — valida e executa as decisoes do Agent Brain.

Safety net: verifica SL, TP e timeout de TODAS as posicoes abertas
a cada ciclo, independente do resultado da chamada ao Claude.
"""
import os
import json
from datetime import datetime, timedelta
from config import (
    AGENT_INITIAL_CAPITAL,
    AGENT_RISK_PER_TRADE_PCT,
    AGENT_MAX_RISK_PER_TRADE_PCT,
    AGENT_MIN_CONFIDENCE,
    AGENT_MIN_RR,
    AGENT_POSITION_TIMEOUT_MIN,
    ATR_SL_FLOOR_PCT,
    COOLDOWN_MINUTES,
)
from telegram_notifier import send_telegram_message
import database as db

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BOT_DIR, "agent_state.json")


# ── STATE I/O ──────────────────────────────────────────────────────────────────

def load_agent_state() -> dict:
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "capital": float(AGENT_INITIAL_CAPITAL),
        "positions": {},
        "cooldowns": {},
        "last_updated": "",
    }


def save_agent_state(state: dict):
    state["last_updated"] = datetime.now().isoformat()
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


# ── VALIDATION ────────────────────────────────────────────────────────────────

def _validate_open(action: dict, agent_state: dict):
    """Retorna (ok: bool, motivo: str). Seis condicoes de validacao."""
    symbol = action.get("symbol", "")
    positions = agent_state.get("positions", {})
    capital = agent_state.get("capital", 0)
    cooldowns = agent_state.get("cooldowns", {})

    if len(positions) >= 3:
        return False, "maximo de 3 posicoes atingido"

    if symbol in positions:
        return False, f"ja existe posicao aberta em {symbol}"

    confidence = int(action.get("confidence", 0))
    if confidence < AGENT_MIN_CONFIDENCE:
        return False, f"confianca {confidence} < minimo {AGENT_MIN_CONFIDENCE}"

    sl_pct = float(action.get("sl_pct", 0))
    tp_pct = float(action.get("tp_pct", 0))
    if sl_pct <= 0 or tp_pct <= 0:
        return False, "sl_pct ou tp_pct invalido (deve ser > 0)"

    rr = tp_pct / sl_pct
    if rr < AGENT_MIN_RR:
        return False, f"R/R {rr:.2f} abaixo do minimo {AGENT_MIN_RR}"

    sl_eff = max(sl_pct, ATR_SL_FLOOR_PCT)
    risk_usd = capital * (AGENT_RISK_PER_TRADE_PCT / 100)
    pos_size = risk_usd / (sl_eff / 100)
    if pos_size > capital:
        return False, "capital insuficiente para este trade"

    if symbol in cooldowns:
        try:
            cd_until = datetime.fromisoformat(cooldowns[symbol])
            if datetime.now() < cd_until:
                mins = int((cd_until - datetime.now()).total_seconds() / 60)
                return False, f"cooldown ativo: {mins}min restantes"
        except Exception:
            pass

    return True, "ok"


# ── OPEN / CLOSE ──────────────────────────────────────────────────────────────

def _open_position(action: dict, agent_state: dict, market_data: dict):
    symbol = action["symbol"]
    pos_type = "LONG" if action["action"] == "OPEN_LONG" else "SHORT"
    price = float(market_data[symbol]["price"])

    sl_pct = max(float(action.get("sl_pct", ATR_SL_FLOOR_PCT)), ATR_SL_FLOOR_PCT)
    tp_pct = float(action.get("tp_pct", sl_pct * AGENT_MIN_RR))

    capital = agent_state["capital"]
    risk_usd = capital * (AGENT_RISK_PER_TRADE_PCT / 100)
    pos_size_usd = risk_usd / (sl_pct / 100)
    max_size = capital * (AGENT_MAX_RISK_PER_TRADE_PCT / 100) / (sl_pct / 100)
    pos_size_usd = min(pos_size_usd, max_size, capital)

    if pos_type == "LONG":
        sl_price = round(price * (1 - sl_pct / 100), 6)
        tp_price = round(price * (1 + tp_pct / 100), 6)
    else:
        sl_price = round(price * (1 + sl_pct / 100), 6)
        tp_price = round(price * (1 - tp_pct / 100), 6)

    agent_state["positions"][symbol] = {
        "type": pos_type,
        "entry_price": price,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "size_usd": round(pos_size_usd, 2),
        "opened_at": datetime.now().isoformat(),
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "confidence": action.get("confidence", 0),
    }

    msg = (
        f"[AGENT V2] ABRIU {pos_type} {symbol}\n"
        f"Preco: {price:.4f} | SL: {sl_price:.4f} ({sl_pct:.1f}%) | "
        f"TP: {tp_price:.4f} ({tp_pct:.1f}%)\n"
        f"Tamanho: ${pos_size_usd:.2f} | Conf: {action.get('confidence')}%\n"
        f"Motivo: {action.get('reason', '')}"
    )
    print(f"  {msg}")
    send_telegram_message(msg)


def _close_position(symbol: str, pos: dict, price: float, reason: str, agent_state: dict):
    pos_type = pos["type"]
    entry = float(pos["entry_price"])
    size_usd = float(pos.get("size_usd", 0))

    if pos_type == "LONG":
        pnl_pct = (price - entry) / entry * 100
    else:
        pnl_pct = (entry - price) / entry * 100

    pnl_usd = size_usd * (pnl_pct / 100)
    capital_after = round(agent_state["capital"] + pnl_usd, 2)

    agent_state["capital"] = capital_after
    del agent_state["positions"][symbol]

    if reason == "stop_loss":
        agent_state.setdefault("cooldowns", {})[symbol] = (
            datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)
        ).isoformat()

    db.insert_agent_trade({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "type": pos_type,
        "entry_price": entry,
        "sl_price": pos.get("sl_price"),
        "tp_price": pos.get("tp_price"),
        "position_size_usd": size_usd,
        "exit_price": price,
        "pnl_pct": round(pnl_pct, 4),
        "pnl_usd": round(pnl_usd, 2),
        "exit_reason": reason,
        "analyst_confidence": pos.get("confidence", 0),
        "capital_after": capital_after,
    })

    emoji = "✅" if pnl_pct > 0 else "❌"
    msg = (
        f"{emoji} [AGENT V2] FECHOU {pos_type} {symbol}\n"
        f"Motivo: {reason}\n"
        f"Entrada: {entry:.4f} → Saida: {price:.4f}\n"
        f"PnL: {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
        f"Capital: ${capital_after:.2f}"
    )
    print(f"  {msg}")
    send_telegram_message(msg)


# ── SAFETY NET ────────────────────────────────────────────────────────────────

def check_stops(agent_state: dict, market_data: dict):
    """
    Verifica SL, TP e timeout para TODAS as posicoes abertas.
    Roda sempre, mesmo que o Claude tenha falhado.
    """
    positions = dict(agent_state.get("positions", {}))

    for symbol, pos in positions.items():
        if symbol not in market_data:
            continue

        price = float(market_data[symbol]["price"])
        pos_type = pos["type"]
        sl_price = pos.get("sl_price")
        tp_price = pos.get("tp_price")
        opened_at_str = pos.get("opened_at", "")
        reason = None

        if opened_at_str and AGENT_POSITION_TIMEOUT_MIN > 0:
            try:
                opened_at = datetime.fromisoformat(opened_at_str)
                age_min = (datetime.now() - opened_at).total_seconds() / 60
                if age_min >= AGENT_POSITION_TIMEOUT_MIN:
                    reason = "timeout"
            except Exception:
                pass

        if reason is None and sl_price:
            sl = float(sl_price)
            if pos_type == "LONG" and price <= sl:
                reason = "stop_loss"
            elif pos_type == "SHORT" and price >= sl:
                reason = "stop_loss"

        if reason is None and tp_price:
            tp = float(tp_price)
            if pos_type == "LONG" and price >= tp:
                reason = "take_profit"
            elif pos_type == "SHORT" and price <= tp:
                reason = "take_profit"

        if reason:
            _close_position(symbol, pos, price, reason, agent_state)


# ── MAIN ENTRY ────────────────────────────────────────────────────────────────

def execute_decisions(decisions: dict, agent_state: dict, market_data: dict):
    """
    Executa as decisoes do Claude apos validacao.
    O safety net (check_stops) roda PRIMEIRO, antes de qualquer nova entrada.
    Salva o estado ao final.
    """
    # Safety net sempre primeiro
    check_stops(agent_state, market_data)

    for action in decisions.get("actions", []):
        act = action.get("action", "")
        symbol = action.get("symbol", "")

        if not symbol or symbol not in market_data:
            continue

        if act in ("OPEN_LONG", "OPEN_SHORT"):
            ok, reason = _validate_open(action, agent_state)
            if ok:
                _open_position(action, agent_state, market_data)
            else:
                print(f"  [AGENT V2] {symbol} rejeitado: {reason}")

        elif act == "CLOSE":
            if symbol in agent_state.get("positions", {}):
                pos = agent_state["positions"][symbol]
                price = float(market_data[symbol]["price"])
                _close_position(symbol, pos, price, "claude_close", agent_state)

    save_agent_state(agent_state)
