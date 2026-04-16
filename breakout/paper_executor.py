"""Breakout 5m paper trading executor.

Wraps BreakoutEngine5m with capital management, position tracking,
and bot.db persistence. State persisted in JSON file between cycles
(same pattern as momentum/paper_executor.py).

Partial close logic: TP1 hit -> move SL to breakeven, continue for TP2.
Blended exit on TP2 = 0.5*tp1 + 0.5*tp2.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

from config import BREAKOUT_INITIAL_CAPITAL, BREAKOUT_MAX_POSITIONS
from engines_5m.breakout import BreakoutEngine5m
from indicators_5m import add_indicators_5m
from signal_types import Signal
import database as db

logger = logging.getLogger("breakout.paper")

_state_lock = threading.Lock()
_engine = BreakoutEngine5m()

# Imported at module level but overridable in tests via monkeypatch
from runtime_config import BREAKOUT_STATE_FILE

# Constants
FEE_ROUNDTRIP_PCT = 0.08   # 0.08% roundtrip fee
TIMEOUT_CANDLES = 60        # 60 candles = 5 hours at 5m
COOLDOWN_CYCLES = 2         # 2 cycles cooldown on loss


def _default_state() -> dict:
    return {
        "capital": float(BREAKOUT_INITIAL_CAPITAL),
        "positions": {},
        "cooldowns": {},
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl_usd": 0.0,
        "hwm": float(BREAKOUT_INITIAL_CAPITAL),
    }


def load_state() -> dict:
    with _state_lock:
        if not os.path.exists(BREAKOUT_STATE_FILE):
            return _default_state()
        try:
            with open(BREAKOUT_STATE_FILE, "r") as f:
                state = json.load(f)
            if "hwm" not in state:
                state["hwm"] = max(state.get("capital", BREAKOUT_INITIAL_CAPITAL),
                                   BREAKOUT_INITIAL_CAPITAL)
            return state
        except (json.JSONDecodeError, ValueError):
            return _default_state()


def save_state(state: dict) -> None:
    state["hwm"] = max(state.get("hwm", state["capital"]), state["capital"])
    with _state_lock:
        dir_name = os.path.dirname(BREAKOUT_STATE_FILE) or "."
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_name, delete=False, suffix=".tmp",
        ) as f:
            json.dump(state, f, indent=2)
            tmp = f.name
        os.replace(tmp, BREAKOUT_STATE_FILE)


def get_breakout_status() -> str:
    state = load_state()
    cap = state["capital"]
    w = state["wins"]
    l = state["losses"]
    total = state["total_trades"]
    pnl = state["total_pnl_usd"]
    wr = (w / total * 100) if total > 0 else 0
    positions = state.get("positions", {})
    n_pos = len(positions)
    hwm = state.get("hwm", cap)
    dd_pct = ((hwm - cap) / hwm * 100) if hwm > 0 else 0

    lines = [
        f"BREAKOUT 5M | ${cap:.2f} | {total}t {w}W/{l}L WR={wr:.1f}% | PnL ${pnl:+.2f}",
        f"  HWM=${hwm:.2f} DD={dd_pct:.1f}% | Pos={n_pos}",
    ]
    if positions:
        for sym, pos in positions.items():
            lines.append(
                f"  {sym} {pos['direction']} @ {pos['entry_price']:.2f}"
            )
    return "\n".join(lines)


def _calculate_position_size(capital: float, entry: float, sl: float) -> float:
    """Size position so that a full SL hit loses ~2% of capital."""
    sl_distance_pct = abs(entry - sl) / entry * 100
    if sl_distance_pct <= 0:
        return 0.0
    risk_amount = capital * 0.02  # 2% risk per trade
    position_size = risk_amount / (sl_distance_pct / 100)
    return min(position_size, capital)


def _check_position_conflict(symbol: str) -> bool:
    """Check if momentum has an open position on this symbol."""
    try:
        from momentum.paper_executor import load_state as load_momentum_state
        momentum_state = load_momentum_state()
        return symbol in momentum_state.get("positions", {})
    except Exception:
        return False


def open_position(state: dict, signal: Signal, cycle_id: str) -> list[str]:
    """Open a paper position from a breakout Signal. Returns Telegram messages."""
    msgs: list[str] = []
    symbol = signal.symbol

    if symbol in state["positions"]:
        return msgs
    if len(state["positions"]) >= BREAKOUT_MAX_POSITIONS:
        return msgs
    if symbol in state.get("cooldowns", {}):
        return msgs
    if _check_position_conflict(symbol):
        return msgs

    entry = signal.entry_price
    sl = signal.sl_price
    tp1 = signal.tp1_price
    tp2 = signal.tp2_price
    direction = signal.direction.value

    size = _calculate_position_size(state["capital"], entry, sl)
    if size <= 0:
        return msgs

    state["positions"][symbol] = {
        "direction": direction,
        "entry_price": entry,
        "sl_price": sl,
        "tp1_price": tp1,
        "tp2_price": tp2,
        "position_size_usd": round(size, 2),
        "open_time": signal.timestamp,
        "mfe_pct": 0.0,
        "mae_pct": 0.0,
        "candles_elapsed": 0,
        "tp1_hit": False,
    }

    try:
        _log_decision(signal, cycle_id, blocked_by="none")
    except Exception as e:
        logger.warning("Failed to log breakout decision: %s", e)

    sl_dist = abs(entry - sl) / entry * 100
    msg = (
        f"BREAKOUT {symbol} {direction} @ {entry:.2f} | "
        f"SL={sl:.2f} ({sl_dist:.2f}%) TP1={tp1:.2f} TP2={tp2:.2f} | "
        f"Size=${size:.2f}"
    )
    msgs.append(msg)
    logger.info("OPEN %s", msg)

    return msgs


def manage_positions(state: dict, candles: dict[str, dict],
                     new_candle_symbols: set[str] | None = None) -> list[str]:
    """Check all open positions against current candles. Returns messages.

    Partial close logic:
    - TP1 hit -> move SL to breakeven, continue for TP2
    - TP2 hit -> close with blended price (0.5*tp1 + 0.5*tp2)
    - SL hit -> close at SL
    - Timeout (60 candles) -> close at current price
    """
    msgs: list[str] = []
    closed_symbols: list[str] = []

    for symbol, pos in list(state["positions"].items()):
        candle = candles.get(symbol)
        if candle is None:
            continue

        high = candle["high"]
        low = candle["low"]
        close = candle["close"]

        entry = pos["entry_price"]
        sl = pos["sl_price"]
        tp1 = pos["tp1_price"]
        tp2 = pos["tp2_price"]
        direction = pos["direction"]
        tp1_hit = pos.get("tp1_hit", False)

        # Update MFE/MAE
        if direction == "LONG":
            current_pnl_pct = (high - entry) / entry * 100
            current_loss_pct = (entry - low) / entry * 100
        else:
            current_pnl_pct = (entry - low) / entry * 100
            current_loss_pct = (high - entry) / entry * 100

        pos["mfe_pct"] = max(pos.get("mfe_pct", 0), current_pnl_pct)
        pos["mae_pct"] = max(pos.get("mae_pct", 0), current_loss_pct)

        # Check exits
        exit_reason = None
        exit_price = 0.0

        if direction == "LONG":
            # Check SL
            if low <= sl:
                exit_reason = "sl" if not tp1_hit else "breakeven"
                exit_price = sl
            # Check TP2 (after TP1 already hit)
            elif tp1_hit and high >= tp2:
                exit_reason = "tp2"
                exit_price = 0.5 * tp1 + 0.5 * tp2  # blended
            # Check TP1
            elif not tp1_hit and high >= tp1:
                pos["tp1_hit"] = True
                pos["sl_price"] = entry  # move SL to breakeven
                logger.info("TP1 hit %s LONG — SL moved to breakeven", symbol)
                continue
        else:  # SHORT
            # Check SL
            if high >= sl:
                exit_reason = "sl" if not tp1_hit else "breakeven"
                exit_price = sl
            # Check TP2 (after TP1 already hit)
            elif tp1_hit and low <= tp2:
                exit_reason = "tp2"
                exit_price = 0.5 * tp1 + 0.5 * tp2  # blended
            # Check TP1
            elif not tp1_hit and low <= tp1:
                pos["tp1_hit"] = True
                pos["sl_price"] = entry  # move SL to breakeven
                logger.info("TP1 hit %s SHORT — SL moved to breakeven", symbol)
                continue

        # Check timeout
        if exit_reason is None and pos.get("candles_elapsed", 0) >= TIMEOUT_CANDLES:
            exit_reason = "timeout"
            exit_price = close

        if exit_reason is not None:
            # Calculate PnL
            if direction == "LONG":
                pnl_pct = (exit_price - entry) / entry * 100
            else:
                pnl_pct = (entry - exit_price) / entry * 100

            # Deduct fees
            pnl_pct -= FEE_ROUNDTRIP_PCT

            pnl_usd = pos["position_size_usd"] * pnl_pct / 100
            state["capital"] += pnl_usd
            state["total_pnl_usd"] += pnl_usd
            state["total_trades"] += 1

            if pnl_pct > 0:
                state["wins"] += 1
            elif pnl_pct < 0:
                state["losses"] += 1
                state.setdefault("cooldowns", {})[symbol] = COOLDOWN_CYCLES

            try:
                db.insert_breakout_trade({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry,
                    "exit_price": exit_price,
                    "sl_price": pos.get("sl_price", sl),
                    "tp1_price": tp1,
                    "tp2_price": tp2,
                    "position_size_usd": pos["position_size_usd"],
                    "pnl_pct": round(pnl_pct, 4),
                    "pnl_usd": round(pnl_usd, 2),
                    "exit_reason": exit_reason,
                    "capital_after": round(state["capital"], 2),
                    "param_version": "breakout-5m-v1.0",
                    "duration_candles": pos.get("candles_elapsed", 0),
                    "mfe_pct": round(pos.get("mfe_pct", 0), 4),
                    "mae_pct": round(pos.get("mae_pct", 0), 4),
                })
            except Exception as e:
                logger.warning("Failed to log breakout trade: %s", e)

            msg = (
                f"CLOSE {symbol} {direction} | "
                f"{exit_reason} @ {exit_price:.2f} | "
                f"PnL {pnl_pct:+.2f}% (${pnl_usd:+.2f}) | "
                f"Cap ${state['capital']:.2f}"
            )
            msgs.append(msg)
            logger.info(msg)
            closed_symbols.append(symbol)
        else:
            # Increment candle counter
            if new_candle_symbols is None or symbol in new_candle_symbols:
                pos["candles_elapsed"] = pos.get("candles_elapsed", 0) + 1

    for sym in closed_symbols:
        del state["positions"][sym]

    return msgs


def _log_decision(signal: Signal, cycle_id: str, blocked_by: str = "none"):
    """Log a breakout decision to bot.db."""
    metadata = signal.metadata or {}
    db.insert_breakout_decision({
        "timestamp": signal.timestamp or "",
        "cycle_id": cycle_id,
        "symbol": signal.symbol,
        "direction": signal.direction.value,
        "blocked_by": blocked_by,
        "range_pct": metadata.get("range_pct", 0),
        "bb_bandwidth": metadata.get("bb_bandwidth", 0),
        "vol_ratio": metadata.get("vol_ratio", 0),
        "body_ratio": metadata.get("body_ratio", 0),
        "lookback": metadata.get("lookback", 0),
        "param_version": "breakout-5m-v1.0",
    })


def _tick_cooldowns(state: dict) -> None:
    """Decrement cooldown counters. Remove expired ones."""
    expired = []
    for symbol, remaining in state.get("cooldowns", {}).items():
        remaining -= 1
        if remaining <= 0:
            expired.append(symbol)
        else:
            state["cooldowns"][symbol] = remaining
    for sym in expired:
        del state["cooldowns"][sym]


def process_breakout_cycle(
    symbols: list[str],
    open_new: bool = True,
    candle_fn: Optional[Callable] = None,
) -> list[str]:
    """One full breakout cycle: evaluate signals + manage positions.

    Args:
        symbols: Symbols to evaluate.
        open_new: If False, only manage existing positions (circuit breaker).
        candle_fn: Override for testing. (symbol, interval, limit) -> DataFrame.

    Returns:
        List of Telegram-ready messages.
    """
    if candle_fn is None:
        from market import get_candles
        candle_fn = get_candles

    state = load_state()
    msgs: list[str] = []
    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candle_cache: dict[str, dict] = {}
    new_candle_symbols: set[str] = set()
    last_candle_ts = state.get("last_candle_ts", {})

    for symbol in symbols:
        candles = candle_fn(symbol, "5m", 100)
        if candles is None or len(candles) == 0:
            continue

        last = candles.iloc[-1]
        candle_ts = str(last.get("time", ""))
        candle_cache[symbol] = {
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
            "time": candle_ts,
        }

        # Dedup: skip if same candle as last cycle
        if candle_ts != last_candle_ts.get(symbol, ""):
            new_candle_symbols.add(symbol)
            last_candle_ts[symbol] = candle_ts
        else:
            continue

        # Add indicators and run engine
        candles = add_indicators_5m(candles)
        signal = _engine.analyze(symbol, candles)

        if signal is not None and signal.valid and open_new:
            entry_msgs = open_position(state, signal, cycle_id)
            msgs.extend(entry_msgs)
            if not entry_msgs:
                # Signal was blocked
                blocked = "max_positions" if len(state["positions"]) >= BREAKOUT_MAX_POSITIONS else "cooldown_or_conflict"
                try:
                    _log_decision(signal, cycle_id, blocked_by=blocked)
                except Exception as e:
                    logger.warning("Failed to log breakout decision: %s", e)
        elif signal is not None and signal.valid and not open_new:
            try:
                _log_decision(signal, cycle_id, blocked_by="suspended")
            except Exception as e:
                logger.warning("Failed to log breakout decision: %s", e)

    # Tick cooldowns when at least one new candle arrived
    if new_candle_symbols:
        _tick_cooldowns(state)

    # Manage existing positions
    exit_msgs = manage_positions(state, candle_cache, new_candle_symbols)
    msgs.extend(exit_msgs)

    state["last_candle_ts"] = last_candle_ts
    save_state(state)
    return msgs
