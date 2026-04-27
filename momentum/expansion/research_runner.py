"""run_portfolio_backtest — pure function center of EXP-005.

Inputs: config, candles_by_symbol (already aligned), signal_fn (default: live adapter),
        capital_pool_usdt, risk_fraction.
Outputs: ExpansionResult with trades, decisions, portfolio peak, metrics.

No I/O. No network. No SQLite. Deterministic for same inputs.
Look-ahead protection: signals evaluated using candles up to t; trade opens at
candle t+1 close (execution_shift=1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional

import pandas as pd

from momentum.expansion.capital_pool import (
    PortfolioState,
    allocate_position_size,
    compute_slot_size,
    open_slot,
    close_slot,
)
from momentum.expansion.config import ExpansionConfig
from momentum.expansion.metrics import compute_portfolio_metrics


SignalFn = Callable[..., Optional[object]]


@dataclass(frozen=True)
class ExpansionResult:
    trades: list[dict]
    decisions: list[dict]
    final_capital_pool: float
    peak_concurrent_positions: int
    metrics: dict


def _ts_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _check_exit(
    *, position: dict, candle_high: float, candle_low: float,
    candle_close: float,
) -> tuple[Optional[str], float]:
    """Return (exit_reason, exit_price) or (None, 0.0) if no exit triggered."""
    if position["direction"] == "long":
        if candle_low <= position["sl"]:
            return ("SL", position["sl"])
        if candle_high >= position["tp2"]:
            return ("TP2", position["tp2"])
        if candle_high >= position["tp1"]:
            return ("TP1", position["tp1"])
    else:  # short
        if candle_high >= position["sl"]:
            return ("SL", position["sl"])
        if candle_low <= position["tp2"]:
            return ("TP2", position["tp2"])
        if candle_low <= position["tp1"]:
            return ("TP1", position["tp1"])
    return (None, 0.0)


def _pnl_pct(entry: float, exit_price: float, direction: str, slippage_pct: float) -> float:
    """PnL pct including slippage on entry and exit (per leg)."""
    if direction == "long":
        gross = (exit_price - entry) / entry * 100.0
    else:
        gross = (entry - exit_price) / entry * 100.0
    # 2 legs (entry + exit) of slippage
    return gross - 2.0 * slippage_pct


def run_portfolio_backtest(
    *,
    config: ExpansionConfig,
    candles_by_symbol: Mapping[str, pd.DataFrame],
    signal_fn: SignalFn,
    capital_pool_usdt: float,
    risk_fraction: float,
    regime_fn: Optional[Callable[[str], str]] = None,
    execution_shift: int = 1,
    slippage_override_pct: Optional[float] = None,
) -> ExpansionResult:
    """Pure backtest over multi-symbol portfolio under S-B allocation."""
    if not candles_by_symbol:
        raise ValueError("candles_by_symbol must not be empty")
    if set(candles_by_symbol.keys()) != set(config.universe):
        raise ValueError(
            f"candles keys {sorted(candles_by_symbol)} != universe {sorted(config.universe)}"
        )

    n_symbols = len(config.universe)
    slot = compute_slot_size(capital_pool_usdt, n_symbols)
    state = PortfolioState(capital_pool=capital_pool_usdt, slot_size=slot)
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    decisions: list[dict] = []

    # Determine common length (already aligned in upstream)
    n_candles = min(len(df) for df in candles_by_symbol.values())
    if n_candles < execution_shift + 2:
        raise ValueError(f"Not enough candles ({n_candles}) for execution_shift={execution_shift}")

    regime_resolver = regime_fn or (lambda sym: "TRENDING")

    # Iterate by candle index
    for i in range(n_candles - execution_shift):
        # Phase 1: manage open positions on candle i+execution_shift
        for sym in list(open_positions.keys()):
            df = candles_by_symbol[sym]
            mgmt_idx = i + execution_shift
            if mgmt_idx >= len(df):
                continue
            row = df.iloc[mgmt_idx]
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
            ts_ms = int(row["close_time_ms"])
            position = open_positions[sym]
            exit_reason, exit_price = _check_exit(
                position=position, candle_high=high, candle_low=low, candle_close=close,
            )
            position["candles_held"] = position.get("candles_held", 0) + 1
            if exit_reason is None and position["candles_held"] >= 96:  # 24h timeout
                exit_reason, exit_price = ("TIMEOUT", close)
            if exit_reason is not None:
                slip = slippage_override_pct if slippage_override_pct is not None else config.slippage_for(sym)
                pnl_pct = _pnl_pct(
                    entry=position["entry"], exit_price=exit_price,
                    direction=position["direction"], slippage_pct=slip,
                )
                trades.append({
                    "symbol": sym,
                    "direction": position["direction"],
                    "entry_ts": position["entry_ts"],
                    "exit_ts": _ts_to_iso(ts_ms),
                    "entry_price": position["entry"],
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "pnl_pct": pnl_pct,
                    "regime": position["regime"],
                    "bucket": config.bucket_for(sym),
                })
                close_slot(state, sym)
                del open_positions[sym]

        # Phase 2: emit signals from candle i (look-ahead protection)
        for sym in config.universe:
            if sym in open_positions:
                continue
            df = candles_by_symbol[sym]
            if i + 1 > len(df):
                continue
            history = df.iloc[: i + 1]
            ts_ms = int(history.iloc[-1]["close_time_ms"])
            ts_iso = _ts_to_iso(ts_ms)
            regime = regime_resolver(sym)
            sig = signal_fn(
                candles=history, symbol=sym, regime_label=regime, timestamp=ts_iso,
            )
            if sig is None:
                decisions.append({"symbol": sym, "ts": ts_iso, "blocked_by": "no_signal"})
                continue
            # Need execution candle (i + execution_shift)
            exec_idx = i + execution_shift
            if exec_idx >= len(df):
                decisions.append({"symbol": sym, "ts": ts_iso, "blocked_by": "no_exec_candle"})
                continue
            if not state.can_open():
                decisions.append({"symbol": sym, "ts": ts_iso, "blocked_by": "no_capital"})
                continue
            # Open at execution candle close
            exec_row = df.iloc[exec_idx]
            entry_price = float(exec_row["close"])
            try:
                open_slot(state, sym)
            except ValueError:
                decisions.append({"symbol": sym, "ts": ts_iso, "blocked_by": "no_capital"})
                continue
            # Normalize direction (enum or str) to a plain string used by _check_exit.
            raw_dir = getattr(sig, "direction", "long")
            direction_str = raw_dir.value if hasattr(raw_dir, "value") else str(raw_dir).lower()
            open_positions[sym] = {
                "direction": direction_str,
                "entry": entry_price,
                "sl": float(getattr(sig, "sl_price", entry_price * 0.98)),
                "tp1": float(getattr(sig, "tp1_price", entry_price * 1.02)),
                "tp2": float(getattr(sig, "tp2_price", entry_price * 1.05)),
                "entry_ts": _ts_to_iso(int(exec_row["close_time_ms"])),
                "regime": regime,
                "candles_held": 0,
            }
            decisions.append({"symbol": sym, "ts": ts_iso, "blocked_by": None})

    # Phase 3: force-close any positions still open at end of series
    for sym, position in list(open_positions.items()):
        df = candles_by_symbol[sym]
        last = df.iloc[-1]
        close = float(last["close"])
        ts_ms = int(last["close_time_ms"])
        slip = slippage_override_pct if slippage_override_pct is not None else config.slippage_for(sym)
        pnl_pct = _pnl_pct(
            entry=position["entry"], exit_price=close,
            direction=position["direction"], slippage_pct=slip,
        )
        trades.append({
            "symbol": sym,
            "direction": position["direction"],
            "entry_ts": position["entry_ts"],
            "exit_ts": _ts_to_iso(ts_ms),
            "entry_price": position["entry"],
            "exit_price": close,
            "exit_reason": "FORCE_CLOSE",
            "pnl_pct": pnl_pct,
            "regime": position["regime"],
            "bucket": config.bucket_for(sym),
        })
        close_slot(state, sym)
    open_positions.clear()

    metrics = compute_portfolio_metrics(trades)
    return ExpansionResult(
        trades=trades,
        decisions=decisions,
        final_capital_pool=state.capital_pool,
        peak_concurrent_positions=state.peak_concurrent,
        metrics=metrics,
    )
