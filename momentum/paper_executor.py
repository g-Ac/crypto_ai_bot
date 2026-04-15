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

from config import MOMENTUM_INITIAL_CAPITAL

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
