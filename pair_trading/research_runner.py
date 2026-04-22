"""Pair trading backtest — candle-by-candle simulation.

Look-ahead protection: decision at candle T uses close prices up to T;
execution happens at T+execution_shift using that candle's close (shift=1 = next
candle close, simulating "enter on next close"). execution_shift=0 is diagnostic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from pair_trading.config import PairConfig
from pair_trading.pair_trader import (
    PairAction, PairPosition, decide,
)
from pair_trading.research_db import (
    close_trade, get_open_trade, insert_decision, insert_trade,
)
from pair_trading.spread_calculator import compute_snapshot


def _ts_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _pnl_pct_per_leg(
    entry_price: float, exit_price: float, is_long: bool
) -> float:
    """Percentage P&L for one leg, without fees."""
    if is_long:
        return (exit_price - entry_price) / entry_price * 100.0
    return (entry_price - exit_price) / entry_price * 100.0


def run_backtest(
    *,
    db_path: str | Path,
    config: PairConfig,
    btc_close: np.ndarray,
    eth_close: np.ndarray,
    close_times_ms: np.ndarray,
    regime_fn: Callable[[int], str] = lambda idx: "UNKNOWN",
    session_fn: Callable[[int], str] = lambda idx: "",
    execution_shift: int = 1,
) -> dict:
    """Run a full backtest over the provided aligned series.

    Args:
        execution_shift: 1 (correct, default) = enter/exit on next candle close.
                         0 (diagnostic) = enter/exit on same candle (look-ahead leak).

    Returns: summary dict with counts.
    """
    warmup = config.window_candles + config.zscore_window_candles
    n = len(btc_close)
    assert len(eth_close) == n and len(close_times_ms) == n

    open_trade_id: Optional[int] = None
    entry_btc = entry_eth = 0.0
    entry_direction: Optional[PairAction] = None
    entry_candles_held = 0
    entry_z = 0.0
    decisions_recorded = 0
    trades_opened = 0
    trades_closed = 0

    for t in range(warmup, n):
        # Use data up to t (inclusive close)
        btc_win = btc_close[: t + 1]
        eth_win = eth_close[: t + 1]
        snap = compute_snapshot(
            btc_win[-warmup:], eth_win[-warmup:],
            window=config.window_candles,
            zscore_window=config.zscore_window_candles,
        )

        # Build PairPosition if trade open
        position = None
        if open_trade_id is not None:
            position = PairPosition(
                direction=entry_direction,
                entry_z=entry_z,
                candles_held=entry_candles_held,
            )

        decision = decide(snap, position, config, circuit_breaker_active=False)

        # Determine execution index
        exec_idx = min(t + execution_shift, n - 1)
        exec_btc = float(btc_close[exec_idx])
        exec_eth = float(eth_close[exec_idx])

        # Record decision
        insert_decision(db_path, {
            "timestamp": _ts_iso(int(close_times_ms[t])),
            "z_score": float(snap.z_score) if snap.is_valid else None,
            "cum_spread": float(snap.cum_spread),
            "rolling_mean": float(snap.rolling_mean),
            "rolling_std": float(snap.rolling_std),
            "correlation": float(snap.correlation),
            "btc_regime": regime_fn(t),
            "action_taken": decision.action.value,
            "blocked_by": decision.blocked_by,
            "position_id": open_trade_id,
        })
        decisions_recorded += 1

        # Execute decision
        if decision.action in (
            PairAction.OPEN_LONG_BTC_SHORT_ETH,
            PairAction.OPEN_SHORT_BTC_LONG_ETH,
        ):
            if open_trade_id is None and exec_idx < n:
                open_trade_id = insert_trade(db_path, {
                    "entry_time": _ts_iso(int(close_times_ms[exec_idx])),
                    "direction": decision.action.value,
                    "entry_btc": exec_btc,
                    "entry_eth": exec_eth,
                    "entry_z": float(snap.z_score),
                    "capital_at_entry": config.total_capital_usd,
                    "btc_regime_entry": regime_fn(t),
                    "session_entry": session_fn(t),
                })
                entry_btc = exec_btc
                entry_eth = exec_eth
                entry_direction = decision.action
                entry_z = float(snap.z_score)
                entry_candles_held = 0
                trades_opened += 1
        elif decision.action in (
            PairAction.CLOSE_TP, PairAction.CLOSE_SL, PairAction.CLOSE_TIMEOUT,
        ):
            if open_trade_id is not None and exec_idx < n:
                # Compute P&L
                is_long_btc = (entry_direction == PairAction.OPEN_LONG_BTC_SHORT_ETH)
                pnl_btc = _pnl_pct_per_leg(entry_btc, exec_btc, is_long_btc)
                pnl_eth = _pnl_pct_per_leg(entry_eth, exec_eth, not is_long_btc)
                # Cost drag: 2 legs * 2 sides * (fees + slippage)
                # Default: fees=0.04% → 0.16% RT. Slippage adds on top.
                cost_per_side = config.fees_taker_pct + config.slippage_pct
                total_cost = cost_per_side * 4
                pnl_total = (pnl_btc + pnl_eth) / 2.0 - total_cost
                pnl_usd = pnl_total / 100.0 * config.total_capital_usd

                close_trade(db_path, open_trade_id, {
                    "exit_time": _ts_iso(int(close_times_ms[exec_idx])),
                    "exit_btc": exec_btc,
                    "exit_eth": exec_eth,
                    "exit_z": float(snap.z_score),
                    "exit_reason": decision.action.value,
                    "pnl_btc_pct": pnl_btc,
                    "pnl_eth_pct": pnl_eth,
                    "pnl_total_pct": pnl_total,
                    "pnl_usd": pnl_usd,
                    "candles_held": entry_candles_held,
                })
                open_trade_id = None
                entry_direction = None
                trades_closed += 1
        elif decision.action == PairAction.HOLD:
            entry_candles_held += 1

    # Force-close any still-open trade at end of series (timeout at last candle).
    if open_trade_id is not None:
        last_idx = n - 1
        exit_btc = float(btc_close[last_idx])
        exit_eth = float(eth_close[last_idx])
        is_long_btc = (entry_direction == PairAction.OPEN_LONG_BTC_SHORT_ETH)
        pnl_btc = _pnl_pct_per_leg(entry_btc, exit_btc, is_long_btc)
        pnl_eth = _pnl_pct_per_leg(entry_eth, exit_eth, not is_long_btc)
        cost_per_side = config.fees_taker_pct + config.slippage_pct
        total_cost = cost_per_side * 4
        pnl_total = (pnl_btc + pnl_eth) / 2.0 - total_cost
        pnl_usd = pnl_total / 100.0 * config.total_capital_usd
        # Recompute snapshot at last candle for exit_z
        final_snap = compute_snapshot(
            btc_close[-warmup:], eth_close[-warmup:],
            window=config.window_candles,
            zscore_window=config.zscore_window_candles,
        )
        close_trade(db_path, open_trade_id, {
            "exit_time": _ts_iso(int(close_times_ms[last_idx])),
            "exit_btc": exit_btc,
            "exit_eth": exit_eth,
            "exit_z": float(final_snap.z_score) if final_snap.is_valid else 0.0,
            "exit_reason": PairAction.CLOSE_TIMEOUT.value,
            "pnl_btc_pct": pnl_btc,
            "pnl_eth_pct": pnl_eth,
            "pnl_total_pct": pnl_total,
            "pnl_usd": pnl_usd,
            "candles_held": entry_candles_held,
        })
        trades_closed += 1

    return {
        "decisions_recorded": decisions_recorded,
        "trades_opened": trades_opened,
        "trades_closed": trades_closed,
    }
