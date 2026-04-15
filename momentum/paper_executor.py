"""Momentum Pullback paper trading executor.

Wraps the frozen v1.1 signal evaluator with capital management,
position tracking, and bot.db persistence. State persisted in
JSON file between cycles (same pattern as scalping_trader.py).

Governance: Paper Readiness Framework
  docs/superpowers/specs/2026-04-15-paper-readiness-framework.md
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone

from config import MOMENTUM_INITIAL_CAPITAL, MOMENTUM_MAX_POSITIONS
from momentum.momentum_trader import MomentumSignal
from momentum.config import MomentumOutcome
import database as db

logger = logging.getLogger("momentum.paper")

_state_lock = threading.Lock()

# Imported at module level but overridable in tests via monkeypatch
from runtime_config import MOMENTUM_STATE_FILE


def _default_state() -> dict:
    return {
        "capital": float(MOMENTUM_INITIAL_CAPITAL),
        "positions": {},
        "cooldowns": {},
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl_usd": 0.0,
        "hwm": float(MOMENTUM_INITIAL_CAPITAL),
    }


def load_state() -> dict:
    with _state_lock:
        if not os.path.exists(MOMENTUM_STATE_FILE):
            return _default_state()
        try:
            with open(MOMENTUM_STATE_FILE, "r") as f:
                state = json.load(f)
            # Ensure hwm exists (migration from older state files)
            if "hwm" not in state:
                state["hwm"] = max(state.get("capital", MOMENTUM_INITIAL_CAPITAL),
                                   MOMENTUM_INITIAL_CAPITAL)
            return state
        except (json.JSONDecodeError, ValueError):
            return _default_state()


def save_state(state: dict) -> None:
    # Update HWM before saving
    state["hwm"] = max(state.get("hwm", state["capital"]), state["capital"])
    with _state_lock:
        dir_name = os.path.dirname(MOMENTUM_STATE_FILE) or "."
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_name, delete=False, suffix=".tmp",
        ) as f:
            json.dump(state, f, indent=2)
            tmp = f.name
        os.replace(tmp, MOMENTUM_STATE_FILE)


def get_momentum_status() -> str:
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
        f"MOMENTUM PULLBACK | ${cap:.2f} | {total}t {w}W/{l}L WR={wr:.1f}% | PnL ${pnl:+.2f}",
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


def open_position(state: dict, signal: MomentumSignal, cycle_id: str) -> list[str]:
    """Open a paper position from a TRADE signal. Returns Telegram messages."""
    msgs: list[str] = []
    symbol = signal.symbol

    if symbol in state["positions"]:
        return msgs
    if len(state["positions"]) >= MOMENTUM_MAX_POSITIONS:
        return msgs
    if symbol in state.get("cooldowns", {}):
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
        "regime": signal.regime,
        "mfe_pct": 0.0,
        "mae_pct": 0.0,
        "candles_elapsed": 0,
    }

    try:
        _log_decision(signal, cycle_id, blocked_by="none")
    except Exception as e:
        logger.warning("Failed to log momentum decision: %s", e)

    sl_dist = abs(entry - sl) / entry * 100
    msg = (
        f"{symbol} {direction} @ {entry:.2f} | "
        f"SL={sl:.2f} ({sl_dist:.2f}%) TP1={tp1:.2f} TP2={tp2:.2f} | "
        f"Size=${size:.2f}"
    )
    msgs.append(msg)
    logger.info("OPEN %s", msg)

    return msgs


def _log_decision(signal: MomentumSignal, cycle_id: str, blocked_by: str = "none"):
    """Log a momentum decision to bot.db."""
    try:
        from audit_helpers import get_session_bucket, get_asset_bucket
        ts_dt = datetime.fromisoformat(signal.timestamp) if signal.timestamp else None
        session = get_session_bucket(ts_dt) if ts_dt else ""
        asset = get_asset_bucket(signal.symbol)
    except Exception:
        session = ""
        asset = ""

    db.insert_momentum_decision({
        "timestamp": signal.timestamp or "",
        "cycle_id": cycle_id,
        "symbol": signal.symbol,
        "regime": signal.regime,
        "outcome": signal.outcome.value,
        "direction": signal.direction.value,
        "blocked_by": blocked_by,
        "ema_fast_value": signal.ema_fast_value,
        "ema_slow_value": signal.ema_slow_value,
        "ema_gap_pct": signal.ema_gap_pct,
        "retracement_pct": signal.retracement_pct,
        "impulse_start_price": signal.impulse_start_price,
        "impulse_end_price": signal.impulse_end_price,
        "pullback_rejection": (
            signal.pullback_rejection.value if signal.pullback_rejection else ""
        ),
        "param_version": signal.param_version,
        "session_bucket": session,
        "asset_bucket": asset,
    })
