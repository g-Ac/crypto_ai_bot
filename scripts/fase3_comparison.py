#!/usr/bin/env python3
"""Fase 3: Compare MomentumBurst SL/TP variants.

4 variants tested on 30d BTC+ETH data:
  Baseline: relaxed thresholds (ATR 1.5x, vol 2.0x, body 0.55, TP 5.0*ATR)
  Fix A:    SL = entry - 1.5*ATR, trailing stop, hard TP 3.0*ATR
  Fix B:    HTF 5m EMA filter, original SL/TP from spec
  Fix C:    Fix A + Fix B combined

Usage:
    cd ~/crypto_ai_bot && source .venv/bin/activate
    python scripts/fase3_comparison.py
"""
from __future__ import annotations

import logging
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import ta

# Project imports
sys.path.insert(0, ".")
from config_1m import Config1m
from engines_1m.base import Engine1m
from indicators_1m import add_indicators_1m
from market_1m import fetch_1m_historical
from risk_calculator_1m import calculate_viability
from signal_types import Direction, Signal

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
DAYS = 30
CONFIG = Config1m(max_risk_per_trade_usd=2.0)  # standard spec thresholds


# ── Variant Engines ─────────────────────────────────────────────────────

class MomentumBurstBaseline(Engine1m):
    """Relaxed thresholds + TP at 5.0*ATR to make R:R viable."""
    name = "baseline_relaxed"
    version = "1.0"

    ATR_MULTIPLE_MIN = 1.5
    VOLUME_MULTIPLE_MIN = 2.0
    BODY_RATIO_MIN = 0.55
    SL_ATR_MULT = 0.3
    TP_ATR_MULT = 5.0
    RSI_LOW = 30.0
    RSI_HIGH = 70.0

    def analyze(self, symbol, df_1m, **kw):
        return _burst_analyze(self, df_1m, symbol)

    def required_indicators(self):
        return _REQUIRED


class MomentumBurstFixA(Engine1m):
    """Fix A: SL = entry - 1.5*ATR, hard TP = entry + 3.0*ATR."""
    name = "fix_a"
    version = "1.0"

    ATR_MULTIPLE_MIN = 2.0
    VOLUME_MULTIPLE_MIN = 2.5
    BODY_RATIO_MIN = 0.65
    SL_ATR_MULT = 1.5       # SL from ENTRY, not from candle low
    TP_ATR_MULT = 3.0       # hard TP
    SL_FROM_ENTRY = True    # flag for entry-based SL
    RSI_LOW = 30.0
    RSI_HIGH = 70.0

    def analyze(self, symbol, df_1m, **kw):
        return _burst_analyze(self, df_1m, symbol)

    def required_indicators(self):
        return _REQUIRED


class MomentumBurstFixB(Engine1m):
    """Fix B: Original spec SL/TP + HTF 5m EMA filter."""
    name = "fix_b"
    version = "1.0"

    ATR_MULTIPLE_MIN = 2.0
    VOLUME_MULTIPLE_MIN = 2.5
    BODY_RATIO_MIN = 0.65
    SL_ATR_MULT = 0.3       # original: low - 0.3*ATR
    TP_ATR_MULT = 1.5       # original TP
    RSI_LOW = 30.0
    RSI_HIGH = 70.0

    def analyze(self, symbol, df_1m, **kw):
        return _burst_analyze(self, df_1m, symbol)

    def required_indicators(self):
        return _REQUIRED


class MomentumBurstFixC(Engine1m):
    """Fix C: Fix A SL/TP + HTF filter."""
    name = "fix_c"
    version = "1.0"

    ATR_MULTIPLE_MIN = 2.0
    VOLUME_MULTIPLE_MIN = 2.5
    BODY_RATIO_MIN = 0.65
    SL_ATR_MULT = 1.5
    TP_ATR_MULT = 3.0
    SL_FROM_ENTRY = True
    RSI_LOW = 30.0
    RSI_HIGH = 70.0

    def analyze(self, symbol, df_1m, **kw):
        return _burst_analyze(self, df_1m, symbol)

    def required_indicators(self):
        return _REQUIRED


_REQUIRED = ["atr14", "ema8", "ema21", "rsi14", "vol_ratio", "body_ratio", "range", "is_green"]


def _burst_analyze(engine, df_1m, symbol):
    """Shared burst detection logic — parameterized by engine attributes."""
    if len(df_1m) < 25:
        return None

    last = df_1m.iloc[-1]
    required_vals = [last.get("atr14"), last.get("ema8"), last.get("ema21"),
                     last.get("rsi14"), last.get("vol_ratio"), last.get("body_ratio")]
    if any(v is None or pd.isna(v) for v in required_vals):
        return None

    atr = last["atr14"]
    if atr <= 0:
        return None

    candle_range = last["range"]
    atr_multiple = candle_range / atr
    if atr_multiple < engine.ATR_MULTIPLE_MIN:
        return None

    vol_ratio = last["vol_ratio"]
    if pd.isna(vol_ratio) or vol_ratio < engine.VOLUME_MULTIPLE_MIN:
        return None

    body_ratio = last["body_ratio"]
    if pd.isna(body_ratio) or body_ratio < engine.BODY_RATIO_MIN:
        return None

    ema8 = last["ema8"]
    ema21 = last["ema21"]
    is_green = last["is_green"]

    if ema8 > ema21 and is_green:
        direction = Direction.LONG
    elif ema8 < ema21 and not is_green:
        direction = Direction.SHORT
    else:
        return None

    rsi = last["rsi14"]
    if rsi < engine.RSI_LOW or rsi > engine.RSI_HIGH:
        return None

    entry_price = last["close"]

    sl_from_entry = getattr(engine, "SL_FROM_ENTRY", False)
    if direction == Direction.LONG:
        if sl_from_entry:
            sl_price = entry_price - engine.SL_ATR_MULT * atr
        else:
            sl_price = last["low"] - engine.SL_ATR_MULT * atr
        tp1_price = entry_price + engine.TP_ATR_MULT * atr
    else:
        if sl_from_entry:
            sl_price = entry_price + engine.SL_ATR_MULT * atr
        else:
            sl_price = last["high"] + engine.SL_ATR_MULT * atr
        tp1_price = entry_price - engine.TP_ATR_MULT * atr

    sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100
    tp_distance_pct = abs(tp1_price - entry_price) / entry_price * 100
    rr_ratio = tp_distance_pct / sl_distance_pct if sl_distance_pct > 0 else 0

    strength = min(1.0, (
        min(atr_multiple / 4.0, 0.4) +
        min(vol_ratio / 5.0, 0.3) +
        min(body_ratio, 0.3)
    ))

    from datetime import datetime, timezone
    timestamp = str(last.get("timestamp", datetime.now(timezone.utc).isoformat()))

    return Signal(
        direction=direction, strength=strength, timestamp=timestamp,
        source=engine.name, symbol=symbol, price=entry_price,
        entry_price=entry_price, sl_price=sl_price,
        tp1_price=tp1_price, tp2_price=tp1_price,
        sl_distance_pct=sl_distance_pct, rr_ratio=rr_ratio,
        valid=True, reason="Momentum burst detected",
        metadata={
            "atr_multiple": round(atr_multiple, 2),
            "volume_multiple": round(vol_ratio, 2),
            "body_ratio": round(body_ratio, 3),
            "rsi": round(rsi, 1),
            "atr": round(atr, 6),
        },
    )


# ── HTF Filter ──────────────────────────────────────────────────────────

def build_htf_ema(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Resample 1m → 5m and compute EMA8/EMA21 on the 5m.

    Returns DataFrame indexed by 5m timestamp with ema8_5m, ema21_5m columns.
    """
    df = df_1m.set_index("timestamp") if "timestamp" in df_1m.columns else df_1m
    df_5m = df.resample("5min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()

    df_5m["ema8_5m"] = ta.trend.ema_indicator(df_5m["close"], window=8)
    df_5m["ema21_5m"] = ta.trend.ema_indicator(df_5m["close"], window=21)
    return df_5m[["ema8_5m", "ema21_5m"]].dropna()


def check_htf_alignment(htf_ema: pd.DataFrame, candle_time, direction: str) -> bool:
    """Check if 5m EMA alignment matches trade direction.

    Uses the most recent completed 5m candle BEFORE the signal candle.
    """
    if htf_ema.empty:
        return False

    # Find most recent 5m candle at or before signal time
    valid = htf_ema.index[htf_ema.index <= candle_time]
    if len(valid) == 0:
        return False

    last_5m = htf_ema.loc[valid[-1]]
    ema8 = last_5m["ema8_5m"]
    ema21 = last_5m["ema21_5m"]

    if direction == "LONG":
        return ema8 > ema21
    else:
        return ema8 < ema21


# ── Backtest with Trailing Stop ─────────────────────────────────────────

@dataclass
class Trade:
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    sl_price: float
    tp_price: float
    exit_reason: str
    pnl_pct: float
    pnl_usd: float
    fee_usd: float
    notional_usd: float
    duration_candles: int


@dataclass
class Position:
    symbol: str
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float       # hard TP
    entry_idx: int
    notional_usd: float
    fee_roundtrip_pct: float
    use_trailing: bool = False
    initial_sl: float = 0.0


@dataclass
class Diagnostics:
    signals_detected: int = 0
    htf_filtered: int = 0
    viability_rejected_signal: int = 0
    viability_rejected_entry: int = 0
    rejection_reasons: Dict[str, int] = field(default_factory=dict)
    trades_opened: int = 0


def run_variant(
    symbol: str,
    df_1m: pd.DataFrame,
    engine: Engine1m,
    config: Config1m,
    use_htf_filter: bool = False,
    use_trailing: bool = False,
    diag: Diagnostics | None = None,
) -> List[Trade]:
    """Run backtest for one variant on one symbol."""
    if diag is None:
        diag = Diagnostics()

    # Normalize columns
    if "time" in df_1m.columns and "timestamp" not in df_1m.columns:
        df_1m = df_1m.rename(columns={"time": "timestamp"})

    df_full = add_indicators_1m(df_1m.copy())

    # Build HTF EMAs if needed
    htf_ema = None
    if use_htf_filter:
        htf_ema = build_htf_ema(df_1m)

    trades: List[Trade] = []
    pos: Optional[Position] = None
    pending_signal = None
    _MIN_WARMUP = 25

    for i in range(_MIN_WARMUP, len(df_full)):
        candle = df_full.iloc[i]

        # 1. Check exit on open position
        if pos is not None:
            trade = _check_exit(pos, candle, i)
            if trade is not None:
                trades.append(trade)
                pos = None

        # 2. Execute pending entry
        if pending_signal is not None and pos is None:
            entry_price = candle["open"]

            # B1: Re-validate with actual entry price
            viability = calculate_viability(
                symbol=symbol, entry_price=entry_price,
                sl_price=pending_signal.sl_price,
                tp_price=pending_signal.tp1_price,
                max_risk_per_trade_usd=config.max_risk_per_trade_usd,
                min_rr_net=config.min_rr_net,
                max_fee_impact_pct=config.max_fee_impact_pct,
                min_sl_distance_pct=config.min_sl_distance_pct,
                max_sl_distance_pct=config.max_sl_distance_pct,
            )

            if not viability.viable:
                diag.viability_rejected_entry += 1
                reason = viability.reason
                diag.rejection_reasons[reason] = diag.rejection_reasons.get(reason, 0) + 1

            if viability.viable:
                direction = pending_signal.direction.value
                atr = candle.get("atr14", 0)

                # For trailing variants (Fix A/C): recalculate SL/TP from actual entry
                if use_trailing and atr > 0:
                    sl_mult = getattr(engine, "SL_ATR_MULT", 1.5)
                    tp_mult = getattr(engine, "TP_ATR_MULT", 3.0)
                    if direction == "LONG":
                        sl = entry_price - sl_mult * atr
                        tp = entry_price + tp_mult * atr
                    else:
                        sl = entry_price + sl_mult * atr
                        tp = entry_price - tp_mult * atr
                else:
                    sl = pending_signal.sl_price
                    tp = pending_signal.tp1_price

                diag.trades_opened += 1
                pos = Position(
                    symbol=symbol, direction=direction,
                    entry_price=entry_price, sl_price=sl, tp_price=tp,
                    entry_idx=i, notional_usd=viability.notional_usd,
                    fee_roundtrip_pct=config.fee_roundtrip_pct,
                    use_trailing=use_trailing, initial_sl=sl,
                )

                # B3: Check exit on entry candle
                trade = _check_exit(pos, candle, i)
                if trade is not None:
                    trades.append(trade)
                    pos = None

            pending_signal = None

        # 3. Trailing stop update (after exit check, before next candle)
        if pos is not None and pos.use_trailing:
            atr = candle.get("atr14", 0)
            if atr > 0:
                close = candle["close"]
                if pos.direction == "LONG":
                    new_sl = close - 1.0 * atr
                    pos.sl_price = max(pos.sl_price, new_sl)
                else:
                    new_sl = close + 1.0 * atr
                    pos.sl_price = min(pos.sl_price, new_sl)

        # 4. Scan for signals
        if pos is None and pending_signal is None:
            visible = df_full.iloc[:i + 1]
            signal = engine.analyze(symbol, visible)
            if signal is not None and signal.valid:
                diag.signals_detected += 1

                # HTF filter
                if use_htf_filter and htf_ema is not None:
                    candle_time = candle.get("timestamp", candle.name)
                    if not check_htf_alignment(htf_ema, candle_time, signal.direction.value):
                        diag.htf_filtered += 1
                        continue

                # Viability check at signal price
                viability = calculate_viability(
                    symbol=symbol, entry_price=signal.entry_price,
                    sl_price=signal.sl_price, tp_price=signal.tp1_price,
                    max_risk_per_trade_usd=config.max_risk_per_trade_usd,
                    min_rr_net=config.min_rr_net,
                    max_fee_impact_pct=config.max_fee_impact_pct,
                    min_sl_distance_pct=config.min_sl_distance_pct,
                    max_sl_distance_pct=config.max_sl_distance_pct,
                )
                if viability.viable:
                    pending_signal = signal
                else:
                    diag.viability_rejected_signal += 1
                    reason = viability.reason
                    diag.rejection_reasons[reason] = diag.rejection_reasons.get(reason, 0) + 1

    # Force close remaining position
    if pos is not None:
        last = df_full.iloc[-1]
        trade = _force_close(pos, last, len(df_full) - 1)
        trades.append(trade)

    return trades


def _check_exit(pos: Position, candle: pd.Series, idx: int) -> Optional[Trade]:
    """Check SL/TP hit. Returns Trade if closed."""
    high = candle["high"]
    low = candle["low"]

    if pos.direction == "LONG":
        hit_sl = low <= pos.sl_price
        hit_tp = high >= pos.tp_price
    else:
        hit_sl = high >= pos.sl_price
        hit_tp = low <= pos.tp_price

    if not hit_sl and not hit_tp:
        return None

    if hit_sl and hit_tp:
        open_price = candle["open"]
        if abs(open_price - pos.tp_price) <= abs(open_price - pos.sl_price):
            exit_price, exit_reason = pos.tp_price, "TP"
        else:
            exit_price, exit_reason = pos.sl_price, "SL"
    elif hit_sl:
        exit_price, exit_reason = pos.sl_price, "SL"
    else:
        exit_price, exit_reason = pos.tp_price, "TP"

    return _make_trade(pos, exit_price, exit_reason, idx)


def _force_close(pos: Position, candle: pd.Series, idx: int) -> Trade:
    return _make_trade(pos, candle["close"], "END_OF_DATA", idx)


def _make_trade(pos: Position, exit_price: float, exit_reason: str, idx: int) -> Trade:
    if pos.direction == "LONG":
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
    else:
        pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100

    pnl_before_fees = pnl_pct / 100 * pos.notional_usd
    fee_usd = pos.notional_usd * pos.fee_roundtrip_pct / 100
    pnl_usd = pnl_before_fees - fee_usd

    return Trade(
        symbol=pos.symbol, direction=pos.direction,
        entry_price=pos.entry_price, exit_price=exit_price,
        sl_price=pos.sl_price, tp_price=pos.tp_price,
        exit_reason=exit_reason,
        pnl_pct=pnl_usd / pos.notional_usd * 100 if pos.notional_usd > 0 else 0,
        pnl_usd=pnl_usd, fee_usd=fee_usd,
        notional_usd=pos.notional_usd,
        duration_candles=idx - pos.entry_idx,
    )


# ── Metrics ─────────────────────────────────────────────────────────────

def compute_metrics(trades: List[Trade]) -> dict:
    if not trades:
        return {
            "trades": 0, "win_rate": 0, "pf": 0, "pnl_usd": 0,
            "avg_win": 0, "avg_loss": 0, "max_dd": 0,
            "fees": 0, "avg_dur": 0,
        }

    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    gross_profit = sum(t.pnl_usd for t in wins)
    gross_loss = abs(sum(t.pnl_usd for t in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0)

    # Max drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cumulative += t.pnl_pct
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) * 100,
        "pf": pf,
        "pnl_usd": sum(t.pnl_usd for t in trades),
        "avg_win": np.mean([t.pnl_usd for t in wins]) if wins else 0,
        "avg_loss": np.mean([t.pnl_usd for t in losses]) if losses else 0,
        "max_dd": max_dd,
        "fees": sum(t.fee_usd for t in trades),
        "avg_dur": np.mean([t.duration_candles for t in trades]),
    }


# ── Main ────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    # Fetch data
    data = {}
    for symbol in SYMBOLS:
        logger.info("Fetching %dd 1m data for %s...", DAYS, symbol)
        df = fetch_1m_historical(symbol, days=DAYS)
        if df.empty:
            logger.warning("No data for %s — skipping", symbol)
            continue
        logger.info("  %s: %d candles", symbol, len(df))
        data[symbol] = df

    if not data:
        print("No data fetched. Exiting.")
        return

    # Define variants
    variants = {
        "Baseline (relaxed)": {
            "engine": MomentumBurstBaseline(),
            "htf": False,
            "trailing": False,
        },
        "Fix A (SL/TP + trail)": {
            "engine": MomentumBurstFixA(),
            "htf": False,
            "trailing": True,
        },
        "Fix B (HTF filter)": {
            "engine": MomentumBurstFixB(),
            "htf": True,
            "trailing": False,
        },
        "Fix C (A + B)": {
            "engine": MomentumBurstFixC(),
            "htf": True,
            "trailing": True,
        },
    }

    # Run all variants — store per-symbol trades + diagnostics for breakdown
    results = {}
    per_symbol_trades = {}  # {variant_name: {symbol: [trades]}}
    all_diags = {}  # {variant_name: Diagnostics}
    for name, cfg in variants.items():
        per_symbol_trades[name] = {}
        all_trades = []
        diag = Diagnostics()
        for symbol, df in data.items():
            logger.info("Running %-22s on %s...", name, symbol)
            trades = run_variant(
                symbol=symbol, df_1m=df,
                engine=cfg["engine"], config=CONFIG,
                use_htf_filter=cfg["htf"],
                use_trailing=cfg["trailing"],
                diag=diag,
            )
            logger.info("  → %d trades", len(trades))
            per_symbol_trades[name][symbol] = trades
            all_trades.extend(trades)

        results[name] = compute_metrics(all_trades)
        all_diags[name] = diag

    # Print comparison table
    print("\n" + "=" * 90)
    print("FASE 3: MOMENTUM BURST VARIANT COMPARISON")
    print(f"Data: {DAYS}d, Symbols: {', '.join(data.keys())}")
    print(f"Config: risk=${CONFIG.max_risk_per_trade_usd}, min_rr={CONFIG.min_rr_net}, "
          f"fee={CONFIG.fee_roundtrip_pct}%, max_sl={CONFIG.max_sl_distance_pct}%")
    print("=" * 90)

    header = f"{'Variant':<24} {'Trades':>6} {'WR%':>6} {'PF':>6} {'P&L $':>8} " \
             f"{'AvgWin':>8} {'AvgLoss':>8} {'MaxDD%':>7} {'Fees$':>7} {'AvgDur':>6}"
    print(header)
    print("-" * 90)

    for name, m in results.items():
        row = (
            f"{name:<24} "
            f"{m['trades']:>6d} "
            f"{m['win_rate']:>5.1f}% "
            f"{m['pf']:>6.2f} "
            f"{m['pnl_usd']:>+8.2f} "
            f"{m['avg_win']:>+8.2f} "
            f"{m['avg_loss']:>+8.2f} "
            f"{m['max_dd']:>6.2f}% "
            f"{m['fees']:>7.2f} "
            f"{m['avg_dur']:>6.1f}"
        )
        print(row)

    print("=" * 90)

    # Verdict
    viable = [(n, m) for n, m in results.items() if m["pf"] > 1.0 and m["trades"] >= 10]
    if viable:
        best = max(viable, key=lambda x: x[1]["pf"])
        print(f"\nMelhor: {best[0]} (PF={best[1]['pf']:.2f}, {best[1]['trades']} trades)")
    else:
        print("\nNenhum fix produziu PF > 1.0 com volume suficiente.")
        print("Momentum Burst nao tem edge no 1-min. Partir pro Engine 2 (Breakout).")

    # Diagnostics: why variants produced 0 trades
    print("\n" + "=" * 90)
    print("DIAGNOSTICS: Signal → Trade Pipeline")
    print("=" * 90)
    diag_header = (
        f"{'Variant':<24} {'Signals':>8} {'HTF Filt':>9} "
        f"{'Viab Rej':>9} {'Entry Rej':>10} {'Opened':>8}"
    )
    print(diag_header)
    print("-" * 90)
    for name, d in all_diags.items():
        print(
            f"{name:<24} "
            f"{d.signals_detected:>8d} "
            f"{d.htf_filtered:>9d} "
            f"{d.viability_rejected_signal:>9d} "
            f"{d.viability_rejected_entry:>10d} "
            f"{d.trades_opened:>8d}"
        )

    # Rejection reasons breakdown
    print("\n--- Rejection Reasons ---")
    for name, d in all_diags.items():
        if d.rejection_reasons:
            print(f"\n{name}:")
            for reason, count in sorted(d.rejection_reasons.items(), key=lambda x: -x[1]):
                print(f"  {reason}: {count}")

    # Per-symbol breakdown (using cached trades)
    print("\n--- Per-symbol breakdown ---")
    for name in results:
        if results[name]["trades"] == 0:
            continue
        print(f"\n{name}:")
        for symbol in data:
            trades = per_symbol_trades[name].get(symbol, [])
            m = compute_metrics(trades)
            if m["trades"] > 0:
                wins = sum(1 for t in trades if t.pnl_usd > 0)
                losses = sum(1 for t in trades if t.pnl_usd <= 0)
                exit_reasons = {}
                for t in trades:
                    exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1
                reasons_str = ", ".join(f"{k}:{v}" for k, v in sorted(exit_reasons.items()))
                print(f"  {symbol}: {m['trades']} trades (W:{wins} L:{losses}), "
                      f"WR={m['win_rate']:.0f}%, PF={m['pf']:.2f}, "
                      f"P&L=${m['pnl_usd']:+.2f} [{reasons_str}]")


if __name__ == "__main__":
    main()
