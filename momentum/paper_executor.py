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
from typing import Callable, Optional

from config import (
    MOMENTUM_INITIAL_CAPITAL, MOMENTUM_MAX_POSITIONS,
    MOMENTUM_PAPER_ENTRY_FEE_RATE, MOMENTUM_PAPER_EXIT_FEE_RATE,
    MOMENTUM_PAPER_LIQUIDITY, MOMENTUM_PAPER_FEE_MODEL,
)
from momentum.momentum_trader import MomentumSignal, evaluate_momentum_pullback
from momentum.config import MomentumOutcome, MomentumConfig
from momentum.fees import compute_trade_costs
from momentum.research_runner import check_exit
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
        "total_fee_usd": 0.0,
        "total_net_pnl_usd": 0.0,
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
            # Migracao suave: acumuladores de custo podem faltar em state antigo.
            # Trades passados foram brutos (fee nao medida) => net == bruto ate aqui.
            state.setdefault("total_fee_usd", 0.0)
            state.setdefault("total_net_pnl_usd", state.get("total_pnl_usd", 0.0))
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
    total_fee = state.get("total_fee_usd", 0.0)
    net_cap = cap - total_fee          # capital liquido derivado (capital bruto - fees)
    net_pnl = pnl - total_fee
    wr = (w / total * 100) if total > 0 else 0
    positions = state.get("positions", {})
    n_pos = len(positions)
    hwm = state.get("hwm", cap)
    dd_pct = ((hwm - cap) / hwm * 100) if hwm > 0 else 0

    lines = [
        f"MOMENTUM PULLBACK | ${cap:.2f} | {total}t {w}W/{l}L WR={wr:.1f}% | PnL ${pnl:+.2f}",
        f"  Net=${net_cap:.2f} (PnL ${net_pnl:+.2f}, fees ${total_fee:.2f})",
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


def open_position(state: dict, signal: MomentumSignal, cycle_id: str,
                  regime_data: Optional[dict] = None) -> list[str]:
    """Open a paper position from a TRADE signal. Returns Telegram messages."""
    msgs: list[str] = []
    symbol = signal.symbol

    if symbol in state["positions"]:
        return msgs
    if len(state["positions"]) >= MOMENTUM_MAX_POSITIONS:
        return msgs
    if symbol in state.get("cooldowns", {}):
        return msgs

    # Position router: check if breakout engine has position on this symbol
    try:
        from breakout.paper_executor import load_state as load_breakout_state
        breakout_state = load_breakout_state()
        if symbol in breakout_state.get("positions", {}):
            return msgs
    except Exception:
        pass

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
        _log_decision(signal, cycle_id, blocked_by="none", regime_data=regime_data)
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


def manage_positions(state: dict, candles: dict[str, dict],
                     new_candle_symbols: set[str] | None = None) -> list[str]:
    """Check all open positions against current candles. Returns messages.

    new_candle_symbols: set of symbols where a new 15m candle has closed.
    candles_elapsed only increments for these symbols (avoids 5m overcounting).
    If None, increments for all (backward-compat / tests).
    """
    msgs: list[str] = []
    config = MomentumConfig()
    closed_symbols: list[str] = []

    for symbol, pos in list(state["positions"].items()):
        candle = candles.get(symbol)
        if candle is None:
            continue

        result = check_exit(
            direction=pos["direction"],
            entry_price=pos["entry_price"],
            sl_price=pos["sl_price"],
            tp1_price=pos["tp1_price"],
            tp2_price=pos["tp2_price"],
            candle_high=candle["high"],
            candle_low=candle["low"],
            candle_close=candle["close"],
            current_mfe=pos.get("mfe_pct", 0),
            current_mae=pos.get("mae_pct", 0),
            duration_candles=pos.get("candles_elapsed", 0),
            timeout_candles=config.timeout_candles,
            breakeven_trigger_pct=config.breakeven_trigger_pct,
        )

        if result["closed"]:
            pnl_pct = result["pnl_pct"]
            pnl_usd = pos["position_size_usd"] * pnl_pct / 100
            state["capital"] += pnl_usd          # capital BRUTO governa o sizing v1.1
            state["total_pnl_usd"] += pnl_usd
            state["total_trades"] += 1

            # Custo de execucao: gross -> net. O capital bruto NAO muda (sizing
            # v1.1 intocado); a fee acumula a parte para derivar o net no status.
            costs = compute_trade_costs(
                gross_pnl_pct=pnl_pct,
                position_size_usd=pos["position_size_usd"],
                entry_fee_rate=MOMENTUM_PAPER_ENTRY_FEE_RATE,
                exit_fee_rate=MOMENTUM_PAPER_EXIT_FEE_RATE,
                fee_model=MOMENTUM_PAPER_FEE_MODEL,
            )
            # Acumula a partir do pnl_usd bruto (nao arredondado) menos a fee,
            # mantendo a identidade total_net == total_pnl - total_fee exata.
            state["total_fee_usd"] = state.get("total_fee_usd", 0.0) + costs["total_fee_usd"]
            state["total_net_pnl_usd"] = (
                state.get("total_net_pnl_usd", 0.0) + (pnl_usd - costs["total_fee_usd"])
            )

            if pnl_pct > 0:
                state["wins"] += 1
            elif pnl_pct < 0:
                state["losses"] += 1
                state.setdefault("cooldowns", {})[symbol] = 2
            # else: breakeven — counted in total_trades but neither win nor loss

            try:
                db.insert_momentum_trade({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "symbol": symbol,
                    "direction": pos["direction"],
                    "regime": pos.get("regime", ""),
                    "entry_price": pos["entry_price"],
                    "exit_price": result["exit_price"],
                    "sl_price": pos["sl_price"],
                    "tp1_price": pos["tp1_price"],
                    "tp2_price": pos["tp2_price"],
                    "position_size_usd": pos["position_size_usd"],
                    "pnl_pct": round(pnl_pct, 4),
                    "pnl_usd": round(pnl_usd, 2),
                    "exit_reason": result["exit_reason"],
                    "capital_after": round(state["capital"], 2),
                    "param_version": "momentum-pullback-v1.1",
                    "duration_candles": pos.get("candles_elapsed", 0),
                    "mfe_pct": round(result["mfe_pct"], 4),
                    "mae_pct": round(result["mae_pct"], 4),
                    # Custo de execucao (gross/fee/net em USD, % e bps)
                    **costs,
                    "entry_liquidity_assumption": MOMENTUM_PAPER_LIQUIDITY,
                    "exit_liquidity_assumption": MOMENTUM_PAPER_LIQUIDITY,
                })
            except Exception as e:
                logger.warning("Failed to log momentum trade: %s", e)

            msg = (
                f"CLOSE {symbol} {pos['direction']} | "
                f"{result['exit_reason']} @ {result['exit_price']:.2f} | "
                f"PnL {pnl_pct:+.2f}% (${pnl_usd:+.2f}) | "
                f"Cap ${state['capital']:.2f}"
            )
            msgs.append(msg)
            logger.info(msg)
            closed_symbols.append(symbol)
        else:
            pos["mfe_pct"] = result["mfe_pct"]
            pos["mae_pct"] = result["mae_pct"]
            # Only count candle if a new 15m candle has closed
            if new_candle_symbols is None or symbol in new_candle_symbols:
                pos["candles_elapsed"] = pos.get("candles_elapsed", 0) + 1

    for sym in closed_symbols:
        del state["positions"][sym]

    return msgs


def _log_decision(signal: MomentumSignal, cycle_id: str, blocked_by: str = "none",
                  regime_data: Optional[dict] = None):
    """Log a momentum decision to bot.db."""
    try:
        from audit_helpers import get_session_bucket, get_asset_bucket
        ts_dt = datetime.fromisoformat(signal.timestamp) if signal.timestamp else None
        session = get_session_bucket(ts_dt) if ts_dt else ""
        asset = get_asset_bucket(signal.symbol)
    except Exception:
        session = ""
        asset = ""

    rd = regime_data or {}

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
        "adx_slope_3": float(rd.get("adx_slope_3", 0.0) or 0.0),
        "di_spread": float(rd.get("di_spread", 0.0) or 0.0),
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


def process_momentum_cycle(
    symbols: list[str],
    open_new: bool = True,
    *,
    candle_fn: Optional[Callable] = None,
    regime_fn: Optional[Callable] = None,
) -> list[str]:
    """One full momentum cycle: evaluate signals + manage positions.

    Args:
        symbols: Symbols to evaluate.
        open_new: If False, only manage existing positions (circuit breaker).
        candle_fn: Override for testing. (symbol, interval, limit) -> DataFrame.
        regime_fn: Override for testing. (symbol) -> dict with regime_label.

    Returns:
        List of Telegram-ready messages.
    """
    if candle_fn is None:
        from market import get_candles
        candle_fn = get_candles
    if regime_fn is None:
        regime_fn = _regime_fn_default

    state = load_state()
    msgs: list[str] = []
    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candle_cache: dict[str, dict] = {}
    new_candle_symbols: set[str] = set()
    last_candle_ts = state.get("last_candle_ts", {})

    # Phase 1: evaluate new 15m candle signals per symbol.
    # The bot loop runs every 5m, but momentum decisions are candle-close based.
    # Re-evaluating the same 15m candle would duplicate decision logs and distort
    # smoke-test evidence, so we only score/log on genuinely new 15m closes.
    for symbol in symbols:
        candles = candle_fn(symbol, "15m", 100)
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

        # Track whether this is a new 15m candle (vs same candle seen last cycle)
        if candle_ts != last_candle_ts.get(symbol, ""):
            new_candle_symbols.add(symbol)
            last_candle_ts[symbol] = candle_ts
        else:
            continue

        regime_data = regime_fn(symbol)
        regime = (
            regime_data.get("regime_label", "UNKNOWN")
            if isinstance(regime_data, dict)
            else str(regime_data)
        )

        signal = evaluate_momentum_pullback(
            candles, regime, MomentumConfig(),
            symbol=symbol,
            timestamp=str(last.get("time", "")),
        )

        regime_data_dict = regime_data if isinstance(regime_data, dict) else None

        if signal.outcome == MomentumOutcome.TRADE and open_new:
            entry_msgs = open_position(state, signal, cycle_id, regime_data=regime_data_dict)
            msgs.extend(entry_msgs)
            if not entry_msgs:
                blocked = "max_positions" if len(state["positions"]) >= MOMENTUM_MAX_POSITIONS else "cooldown"
                _log_decision(signal, cycle_id, blocked_by=blocked, regime_data=regime_data_dict)
        else:
            blocked = signal.outcome.value if signal.outcome != MomentumOutcome.TRADE else "suspended"
            _log_decision(signal, cycle_id, blocked_by=blocked, regime_data=regime_data_dict)

    # Only tick cooldowns when at least one new 15m candle arrived
    if new_candle_symbols:
        _tick_cooldowns(state)

    # Phase 2: manage existing positions
    exit_msgs = manage_positions(state, candle_cache, new_candle_symbols)
    msgs.extend(exit_msgs)

    state["last_candle_ts"] = last_candle_ts
    save_state(state)
    return msgs


def _regime_fn_default(symbol: str) -> dict:
    from htf import get_htf_regime
    return get_htf_regime(symbol)
