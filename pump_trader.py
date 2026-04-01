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
    PUMP_DUMP_RETRACE_PCT, PUMP_CAPITAL, PUMP_MAX_POSITIONS,
    PUMP_DUMP_SPEED_PCT, PUMP_DUMP_SPEED_CANDLES,
)
from runtime_config import PUMP_STATE_FILE

STATE_FILE = PUMP_STATE_FILE


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


def get_recent_closes(symbol, num_candles=5):
    """Retorna lista de precos de fechamento dos ultimos N candles de 5m."""
    try:
        resp = requests.get(
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=5m&limit={num_candles}",
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return [float(c[4]) for c in data]
    except Exception:
        return None


def detect_dump(symbol, current_price, peak_price):
    """Detecta dump por magnitude E velocidade de queda.

    Retorna dict com detalhes se dump detectado, None caso contrario.
    Dois criterios (qualquer um dispara):
      1. Magnitude: retrace >= PUMP_DUMP_RETRACE_PCT do pico
      2. Velocidade: queda >= PUMP_DUMP_SPEED_PCT em PUMP_DUMP_SPEED_CANDLES candles
    """
    result = {"detected": False, "reason": None, "retrace_pct": 0.0, "speed_pct": 0.0}

    # Criterio 1: Magnitude de retrace do pico
    if peak_price > 0:
        retrace_pct = ((peak_price - current_price) / peak_price) * 100
        result["retrace_pct"] = retrace_pct
        if retrace_pct >= PUMP_DUMP_RETRACE_PCT:
            result["detected"] = True
            result["reason"] = (
                f"DUMP magnitude: retrace {retrace_pct:.2f}% do pico "
                f"(threshold: {PUMP_DUMP_RETRACE_PCT}%)"
            )
            return result

    # Criterio 2: Velocidade de queda (queda rapida em poucos candles)
    closes = get_recent_closes(symbol, num_candles=PUMP_DUMP_SPEED_CANDLES + 1)
    if closes and len(closes) >= 2:
        recent_high = max(closes[:-1])  # maior preco nos candles anteriores
        if recent_high > 0:
            speed_drop = ((recent_high - current_price) / recent_high) * 100
            result["speed_pct"] = speed_drop
            if speed_drop >= PUMP_DUMP_SPEED_PCT:
                result["detected"] = True
                result["reason"] = (
                    f"DUMP velocidade: queda {speed_drop:.2f}% em "
                    f"{PUMP_DUMP_SPEED_CANDLES} candles "
                    f"(threshold: {PUMP_DUMP_SPEED_PCT}%)"
                )
                return result

    return result


def open_position(symbol, direction, price, volume_ratio):
    """Open a new pump/dump position."""
    state = load_state()

    if symbol in state["positions"]:
        return None  # ja tem posicao

    if len(state["positions"]) >= PUMP_MAX_POSITIONS:
        return None  # limite de posicoes simultaneas

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
    """Check all open positions for exits.

    Ordem de prioridade de saida:
      1. Dump detection (saida de emergencia - mais agressivo)
      2. Trailing stop (protecao normal de lucro)
      3. Timeout (tempo maximo em posicao)
    """
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
            pnl_pct = ((price - entry) / entry) * 100
            drop_from_peak = ((pos["peak_price"] - price) / pos["peak_price"]) * 100
            trailing_hit = drop_from_peak >= pos["trailing_stop"]
        else:  # SHORT
            if price < pos.get("trough_price", entry):
                pos["trough_price"] = price
            pnl_pct = ((entry - price) / entry) * 100
            rise_from_trough = (
                ((price - pos.get("trough_price", entry))
                 / pos.get("trough_price", entry)) * 100
            )
            trailing_hit = rise_from_trough >= pos["trailing_stop"]

        # Update pump high
        if price > pos.get("pump_high", 0):
            pos["pump_high"] = price

        # --- Exit conditions (ordem de prioridade) ---
        exit_reason = None
        dump_info = None

        # 1. DUMP DETECTION -- saida de emergencia, checada ANTES do trailing
        #    Para LONG: detecta dump no ativo (preco caindo rapido)
        #    Para SHORT: detecta pump reverso (preco subindo rapido)
        if pos_type == "LONG":
            dump_info = detect_dump(symbol, price, pos["peak_price"])
        else:
            # Para SHORT, invertemos: detectar pump reverso (alta rapida)
            dump_info = detect_dump(symbol, pos.get("trough_price", entry), price)

        if dump_info and dump_info["detected"]:
            exit_reason = "dump_detected"
            print(
                f"  [DUMP] {symbol} {pos_type}: {dump_info['reason']} | "
                f"retrace={dump_info['retrace_pct']:.2f}% "
                f"speed={dump_info['speed_pct']:.2f}%"
            )

        # 2. TRAILING STOP -- protecao normal de lucro
        if not exit_reason and trailing_hit:
            exit_reason = "trailing_stop"
            if pos_type == "LONG":
                print(
                    f"  [TRAILING] {symbol} LONG: drop_from_peak={drop_from_peak:.2f}% "
                    f">= trailing={pos['trailing_stop']}%"
                )
            else:
                print(
                    f"  [TRAILING] {symbol} SHORT: rise_from_trough="
                    f"{rise_from_trough:.2f}% >= trailing={pos['trailing_stop']}%"
                )

        # 3. TIMEOUT
        if not exit_reason and duration >= PUMP_MAX_POSITION_TIME:
            exit_reason = "timeout"
            print(f"  [TIMEOUT] {symbol} {pos_type}: {duration:.0f}min >= {PUMP_MAX_POSITION_TIME}min")

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

            # Flag de dump com detalhes extras no trade log
            if exit_reason == "dump_detected" and dump_info:
                trade["dump_retrace_pct"] = round(dump_info["retrace_pct"], 2)
                trade["dump_speed_pct"] = round(dump_info["speed_pct"], 2)
                trade["dump_reason"] = dump_info["reason"]

            try:
                log_trade(trade)
            except Exception as db_err:
                print(f"  [ERRO] Falha ao salvar trade no banco (pump): {db_err}")

            wr = (state["wins"] / state["total_trades"]) * 100

            # Mensagem diferenciada para dump vs trailing
            if exit_reason == "dump_detected":
                exit_label = f"DUMP DETECTADO ({dump_info['reason']})"
            elif exit_reason == "trailing_stop":
                exit_label = "trailing_stop"
            else:
                exit_label = exit_reason

            msg = (
                f"[PUMP TRADE] {pos_type} fechado: {symbol}\n"
                f"Entrada: {entry:.6f} | Saida: {price:.6f}\n"
                f"P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
                f"Motivo: {exit_label} | Duracao: {duration:.0f}min\n"
                f"Capital: ${state['capital']:.2f} | "
                f"Trades: {state['total_trades']} | WR: {wr:.1f}%"
            )
            messages.append(msg)

            # Apos fechar LONG por trailing com lucro > 5%, considerar SHORT
            if pos_type == "LONG" and exit_reason in ("trailing_stop", "dump_detected") and pnl_pct > 5:
                rsi = get_rsi(symbol)
                if rsi and rsi > PUMP_RSI_EXHAUSTION:
                    closed.append({
                        "symbol": symbol, "action": "SHORT", "price": price,
                        "volume_ratio": pos["volume_ratio_at_entry"],
                    })

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
