"""Research Mode runner for Momentum Pullback.

One-cycle function: evaluates signals, records decisions, opens/manages
paper trades. No loop, no supervisor wiring — called externally.

Data sources (candle_fn, regime_fn) are injectable for testing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from momentum.config import MomentumConfig, MomentumDirection, MomentumOutcome
from momentum.momentum_trader import MomentumSignal, evaluate_momentum_pullback
from momentum.research_db import (
    close_trade,
    get_open_trades,
    insert_decision,
    insert_trade,
    update_trade_mfe_mae,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_research_cycle(
    symbols: List[str],
    db_path: str | Path,
    config: MomentumConfig,
    *,
    candle_fn: Optional[Callable] = None,
    regime_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Execute one research cycle: evaluate signals + manage positions.

    Args:
        symbols: Symbols to evaluate (e.g. ["BTCUSDT", "ETHUSDT"]).
        db_path: Path to the research SQLite database.
        config: Frozen momentum parameters.
        candle_fn: (symbol, interval, limit) -> DataFrame. Defaults to
                   market.get_candles.
        regime_fn: (symbol) -> dict with "regime_label". Defaults to
                   htf.get_htf_regime.

    Returns:
        Summary dict: decisions_recorded, trades_opened, trades_closed.
    """
    if candle_fn is None:
        from market import get_candles
        candle_fn = get_candles
    if regime_fn is None:
        from htf import get_htf_regime
        regime_fn = get_htf_regime

    candle_cache: Dict[str, pd.DataFrame] = {}
    decisions_recorded = 0
    trades_opened = 0

    # --- Phase 1: evaluate signals, record decisions, open trades ---
    for symbol in symbols:
        candles = candle_fn(symbol, "15m", 100)
        if candles is None or len(candles) == 0:
            continue

        candle_cache[symbol] = candles
        regime_data = regime_fn(symbol)
        regime = (
            regime_data.get("regime_label", "UNKNOWN")
            if isinstance(regime_data, dict)
            else str(regime_data)
        )

        ts = _extract_timestamp(candles)

        signal = evaluate_momentum_pullback(
            candles, regime, config, symbol=symbol, timestamp=ts,
        )

        decision_id = insert_decision(db_path, _signal_to_decision(signal, regime))
        decisions_recorded += 1

        if signal.outcome == MomentumOutcome.TRADE:
            open_positions = get_open_trades(db_path)
            already_open = any(t["symbol"] == symbol for t in open_positions)
            if not already_open:
                insert_trade(db_path, _signal_to_trade(signal, decision_id, regime))
                trades_opened += 1

    # --- Phase 2: manage open positions ---
    trades_closed = _manage_positions(db_path, config, candle_cache, candle_fn)

    return {
        "decisions_recorded": decisions_recorded,
        "trades_opened": trades_opened,
        "trades_closed": trades_closed,
    }


# ---------------------------------------------------------------------------
# Position management
# ---------------------------------------------------------------------------

def _manage_positions(
    db_path: str | Path,
    config: MomentumConfig,
    candle_cache: Dict[str, pd.DataFrame],
    candle_fn: Callable,
) -> int:
    """Check open trades against current candles. Returns count of closed."""
    open_trades = get_open_trades(db_path)
    closed = 0

    for trade in open_trades:
        symbol = trade["symbol"]
        candles = candle_cache.get(symbol)
        if candles is None:
            candles = candle_fn(symbol, "15m", 100)
        if candles is None or len(candles) == 0:
            continue

        last = candles.iloc[-1]
        high = float(last["high"])
        low = float(last["low"])
        close_price = float(last["close"])
        ts = _extract_timestamp(candles)
        duration = _compute_duration(trade["timestamp"], ts)

        result = check_exit(
            direction=trade["direction"],
            entry_price=trade["entry_price"],
            sl_price=trade["sl_price"],
            tp1_price=trade["tp1_price"],
            tp2_price=trade["tp2_price"],
            candle_high=high,
            candle_low=low,
            candle_close=close_price,
            current_mfe=trade["mfe_pct"],
            current_mae=trade["mae_pct"],
            duration_candles=duration,
            timeout_candles=config.timeout_candles,
            breakeven_trigger_pct=config.breakeven_trigger_pct,
        )

        if result["closed"]:
            close_trade(
                db_path,
                trade["id"],
                exit_price=result["exit_price"],
                exit_reason=result["exit_reason"],
                exit_timestamp=ts,
                pnl_pct=result["pnl_pct"],
                duration_candles=duration,
                mfe_pct=result["mfe_pct"],
                mae_pct=result["mae_pct"],
                retested_impulse_end=result["retested_impulse_end"],
                lost_pullback_extreme=result["lost_pullback_extreme"],
            )
            closed += 1
        else:
            update_trade_mfe_mae(
                db_path, trade["id"], result["mfe_pct"], result["mae_pct"],
            )

    return closed


# ---------------------------------------------------------------------------
# check_exit — pure function, no DB, no side effects
# ---------------------------------------------------------------------------

def check_exit(
    *,
    direction: str,
    entry_price: float,
    sl_price: float,
    tp1_price: float,
    tp2_price: float,
    candle_high: float,
    candle_low: float,
    candle_close: float,
    current_mfe: float,
    current_mae: float,
    duration_candles: int,
    timeout_candles: int,
    breakeven_trigger_pct: float = 0.0,
) -> Dict[str, Any]:
    """Evaluate whether an open trade should close on this candle.

    Pure function — no DB, no network. Suitable for unit testing.

    Exit priority (conservative): SL > TP2 > TP1 > timeout.
    SL first because if a candle spans both SL and TP, we assume
    the adverse move happened first (worst-case for research).

    breakeven_trigger_pct: fraction (0.0-1.0) of TP1 distance. Once
        cumulative MFE reaches this fraction, the effective SL moves to
        entry_price. 0.0 = disabled (v1 default).

    Returns dict:
        closed (bool), exit_price, exit_reason, pnl_pct,
        mfe_pct, mae_pct, retested_impulse_end, lost_pullback_extreme.
    """
    is_long = direction == "LONG"

    # --- Update running MFE / MAE ---
    if is_long:
        candle_mfe = (candle_high - entry_price) / entry_price * 100
        candle_mae = (candle_low - entry_price) / entry_price * 100
    else:
        candle_mfe = (entry_price - candle_low) / entry_price * 100
        candle_mae = (entry_price - candle_high) / entry_price * 100

    mfe = max(current_mfe, candle_mfe)
    mae = min(current_mae, candle_mae)

    # --- Breakeven stop: tighten SL to entry after MFE threshold ---
    effective_sl = sl_price
    if breakeven_trigger_pct > 0:
        tp1_distance = abs(tp1_price - entry_price)
        trigger_distance = breakeven_trigger_pct * tp1_distance
        mfe_in_price = mfe / 100 * entry_price
        if mfe_in_price >= trigger_distance:
            effective_sl = entry_price

    # --- Hit checks ---
    if is_long:
        sl_hit = candle_low <= effective_sl
        tp2_hit = candle_high >= tp2_price
        tp1_hit = candle_high >= tp1_price
    else:
        sl_hit = candle_high >= effective_sl
        tp2_hit = candle_low <= tp2_price
        tp1_hit = candle_low <= tp1_price

    # --- Exit priority: SL > TP2 > TP1 > timeout ---
    if sl_hit:
        pnl = _pnl(is_long, entry_price, effective_sl)
        reason = "breakeven" if effective_sl == entry_price else "sl_hit"
        return _exit(
            effective_sl, reason, pnl, mfe, mae,
            retested=tp1_hit, lost=(effective_sl != entry_price),
        )

    if tp2_hit:
        pnl = _pnl(is_long, entry_price, tp2_price)
        return _exit(
            tp2_price, "tp2_hit", pnl, mfe, mae,
            retested=True, lost=False,
        )

    if tp1_hit:
        pnl = _pnl(is_long, entry_price, tp1_price)
        return _exit(
            tp1_price, "tp1_hit", pnl, mfe, mae,
            retested=True, lost=False,
        )

    if duration_candles >= timeout_candles:
        pnl = _pnl(is_long, entry_price, candle_close)
        return _exit(
            candle_close, "timeout", pnl, mfe, mae,
            retested=False, lost=False,
        )

    # --- No exit ---
    return {
        "closed": False,
        "exit_price": 0.0,
        "exit_reason": "",
        "pnl_pct": 0.0,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "retested_impulse_end": False,
        "lost_pullback_extreme": False,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pnl(is_long: bool, entry: float, exit: float) -> float:
    if is_long:
        return (exit - entry) / entry * 100
    return (entry - exit) / entry * 100


def _exit(
    price: float,
    reason: str,
    pnl: float,
    mfe: float,
    mae: float,
    *,
    retested: bool,
    lost: bool,
) -> Dict[str, Any]:
    return {
        "closed": True,
        "exit_price": price,
        "exit_reason": reason,
        "pnl_pct": pnl,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "retested_impulse_end": retested,
        "lost_pullback_extreme": lost,
    }


def _signal_to_decision(signal: MomentumSignal, regime: str) -> dict:
    """Convert MomentumSignal to a decision dict for the DB."""
    ts_dt = _parse_ts(signal.timestamp)
    session = _safe_session_bucket(ts_dt)
    asset = _safe_asset_bucket(signal.symbol)

    return {
        "timestamp": signal.timestamp or "",
        "symbol": signal.symbol,
        "regime": regime,
        "session_bucket": session,
        "asset_bucket": asset,
        "outcome": signal.outcome.value,
        "direction": signal.direction.value,
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
    }


def _signal_to_trade(signal: MomentumSignal, decision_id: int, regime: str) -> dict:
    """Convert a TRADE signal to a trade dict for the DB."""
    ts_dt = _parse_ts(signal.timestamp)
    session = _safe_session_bucket(ts_dt)

    return {
        "decision_id": decision_id,
        "timestamp": signal.timestamp or "",
        "symbol": signal.symbol,
        "direction": signal.direction.value,
        "regime": regime,
        "session_bucket": session,
        "entry_price": signal.entry_price,
        "sl_price": signal.sl_price,
        "tp1_price": signal.tp1_price,
        "tp2_price": signal.tp2_price,
        "param_version": signal.param_version,
    }


def _extract_timestamp(candles: pd.DataFrame) -> str:
    """Get the last candle's timestamp as ISO string."""
    if "timestamp" in candles.columns:
        return str(candles["timestamp"].iloc[-1])
    if "time" in candles.columns:
        return str(candles["time"].iloc[-1])
    return ""


def _compute_duration(open_ts: str, current_ts: str) -> int:
    """Number of 15m candles between two timestamps."""
    try:
        t_open = pd.Timestamp(open_ts)
        t_current = pd.Timestamp(current_ts)
        diff_minutes = (t_current - t_open).total_seconds() / 60
        return max(0, int(diff_minutes / 15))
    except Exception:
        return 0


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Best-effort parse a timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        return pd.Timestamp(ts_str).to_pydatetime().replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _safe_session_bucket(ts_dt: Optional[datetime]) -> str:
    try:
        from audit_helpers import get_session_bucket
        return get_session_bucket(ts_dt)
    except Exception:
        return ""


def _safe_asset_bucket(symbol: str) -> str:
    try:
        from audit_helpers import get_asset_bucket
        return get_asset_bucket(symbol)
    except Exception:
        return ""
