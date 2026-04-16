#!/usr/bin/env python3
"""Fase 3 v2: Validate Break & Retest on DOGEUSDT with maker fees.

Tests if the v2 pattern (entry on retest, tight SL below support)
produces viable trades where v1 (entry on burst) structurally failed.

Usage:
    cd ~/crypto_ai_bot && source .venv/bin/activate
    python scripts/fase3_v2_validation.py
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import ta

sys.path.insert(0, ".")
from config_1m import Config1m
from engines_1m.momentum_burst_v2 import MomentumBurstV2
from indicators_1m import add_indicators_1m
from market_1m import fetch_1m_historical
from risk_calculator_1m import calculate_viability

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────

SYMBOLS = ["DOGEUSDT"]
DAYS = 30
CONFIG = Config1m(max_risk_per_trade_usd=2.0, use_maker_orders=True)

_MIN_WARMUP = 70  # engine needs ~70 candles for swing detection


# ── HTF Filter ──────────────────────────────────────────────────────────

def build_htf_ema(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Resample 1m→5m and compute EMA8/EMA21."""
    df = df_1m.set_index("timestamp") if "timestamp" in df_1m.columns else df_1m
    df_5m = df.resample("5min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    df_5m["ema8_5m"] = ta.trend.ema_indicator(df_5m["close"], window=8)
    df_5m["ema21_5m"] = ta.trend.ema_indicator(df_5m["close"], window=21)
    return df_5m[["ema8_5m", "ema21_5m"]].dropna()


def check_htf_alignment(htf_ema: pd.DataFrame, candle_time, direction: str) -> bool:
    """Check 5m EMA alignment. Uses most recent completed 5m candle."""
    if htf_ema.empty:
        return False
    valid = htf_ema.index[htf_ema.index <= candle_time]
    if len(valid) == 0:
        return False
    last_5m = htf_ema.loc[valid[-1]]
    if direction == "LONG":
        return last_5m["ema8_5m"] > last_5m["ema21_5m"]
    else:
        return last_5m["ema8_5m"] < last_5m["ema21_5m"]


# ── Diagnostics ─────────────────────────────────────────────────────────

@dataclass
class Diagnostics:
    signals_detected: int = 0
    htf_filtered: int = 0
    viability_rejected_signal: int = 0
    viability_rejected_entry: int = 0
    trades_opened: int = 0
    tp1_hits: int = 0
    tp2_hits: int = 0
    trailing_sl_hits: int = 0
    sl_hits: int = 0
    timeouts: int = 0
    rejection_reasons: Dict[str, int] = field(default_factory=dict)

    def _add_rejection(self, reason: str):
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1


# ── Trade / Position ────────────────────────────────────────────────────

@dataclass
class Trade:
    symbol: str
    direction: str
    entry_price: float
    exit_price: float  # blended: 0.5*tp1 + 0.5*final for partial close
    sl_price: float
    tp1_price: float
    tp2_price: float
    exit_reason: str
    pnl_pct: float
    pnl_usd: float
    fee_usd: float
    notional_usd: float
    duration_candles: int
    metadata: dict = field(default_factory=dict)


@dataclass
class Position:
    symbol: str
    direction: str
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    entry_idx: int
    notional_usd: float
    fee_roundtrip_pct: float
    # Partial close tracking
    tp1_hit: bool = False
    tp1_exit_price: float = 0.0
    # Original SL for reference
    original_sl: float = 0.0
    metadata: dict = field(default_factory=dict)


# ── Backtest ────────────────────────────────────────────────────────────

def run_backtest(
    symbol: str,
    df_1m: pd.DataFrame,
    engine: MomentumBurstV2,
    config: Config1m,
    diag: Diagnostics,
) -> List[Trade]:
    if "time" in df_1m.columns and "timestamp" not in df_1m.columns:
        df_1m = df_1m.rename(columns={"time": "timestamp"})

    df_full = add_indicators_1m(df_1m.copy())
    htf_ema = build_htf_ema(df_1m)

    trades: List[Trade] = []
    pos: Optional[Position] = None
    pending_signal = None

    engine.reset_state(symbol)

    for i in range(_MIN_WARMUP, len(df_full)):
        candle = df_full.iloc[i]

        # 1. Check exit on open position
        if pos is not None:
            trade = _check_exit(pos, candle, i, diag)
            if trade is not None:
                trades.append(trade)
                pos = None

        # 2. Execute pending entry
        if pending_signal is not None and pos is None:
            entry_price = candle["open"]

            # Viability with actual entry price
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
                diag._add_rejection(viability.reason)
            else:
                diag.trades_opened += 1
                pos = Position(
                    symbol=symbol,
                    direction=pending_signal.direction.value,
                    entry_price=entry_price,
                    sl_price=pending_signal.sl_price,
                    tp1_price=pending_signal.tp1_price,
                    tp2_price=pending_signal.tp2_price,
                    entry_idx=i,
                    notional_usd=viability.notional_usd,
                    fee_roundtrip_pct=config.fee_roundtrip_pct,
                    original_sl=pending_signal.sl_price,
                    metadata=pending_signal.metadata,
                )

                # Check exit on entry candle
                trade = _check_exit(pos, candle, i, diag)
                if trade is not None:
                    trades.append(trade)
                    pos = None

            pending_signal = None

        # 3. Trailing stop update (after exit check)
        if pos is not None and pos.tp1_hit:
            atr = candle.get("atr14", 0)
            if atr > 0:
                close = candle["close"]
                if pos.direction == "LONG":
                    new_sl = close - 1.0 * atr
                    pos.sl_price = max(pos.sl_price, new_sl)
                else:
                    new_sl = close + 1.0 * atr
                    pos.sl_price = min(pos.sl_price, new_sl)

        # 4. Scan for signals (engine is stateful)
        #    Pass only last 120 candles (engine needs ~70 max) for performance
        if pos is None and pending_signal is None:
            window_start = max(0, i - 120)
            visible = df_full.iloc[window_start:i + 1]
            signal = engine.analyze(symbol, visible)
            if signal is not None and signal.valid:
                diag.signals_detected += 1

                # HTF filter (mandatory)
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
                    diag._add_rejection(viability.reason)

    # Force close remaining
    if pos is not None:
        last = df_full.iloc[-1]
        trade = _force_close(pos, last, len(df_full) - 1)
        trades.append(trade)
        diag.timeouts += 1

    return trades


def _check_exit(pos: Position, candle: pd.Series, idx: int, diag: Diagnostics) -> Optional[Trade]:
    """Check SL/TP1/TP2 hit. Handles partial close at TP1."""
    high, low = candle["high"], candle["low"]

    if pos.direction == "LONG":
        hit_sl = low <= pos.sl_price
        hit_tp1 = not pos.tp1_hit and high >= pos.tp1_price
        hit_tp2 = pos.tp1_hit and high >= pos.tp2_price
    else:
        hit_sl = high >= pos.sl_price
        hit_tp1 = not pos.tp1_hit and low <= pos.tp1_price
        hit_tp2 = pos.tp1_hit and low <= pos.tp2_price

    # TP1 hit (partial close — don't exit, just mark + move SL to breakeven)
    if hit_tp1 and not hit_sl:
        pos.tp1_hit = True
        pos.tp1_exit_price = pos.tp1_price
        pos.sl_price = pos.entry_price  # breakeven
        diag.tp1_hits += 1
        # Don't return trade — position still open for TP2/trailing
        # But if TP2 also hit on same candle, handle below
        if hit_tp2:
            diag.tp2_hits += 1
            blended_exit = 0.5 * pos.tp1_price + 0.5 * pos.tp2_price
            return _make_trade(pos, blended_exit, "TP2", idx)
        return None

    # TP1 and SL on same candle (before TP1 was marked)
    if hit_tp1 and hit_sl:
        # Proximity to open determines order
        open_price = candle["open"]
        if abs(open_price - pos.tp1_price) <= abs(open_price - pos.sl_price):
            # TP1 first, then maybe SL on remaining
            # Conservative: count as TP1 partial + SL on rest = blended
            blended_exit = 0.5 * pos.tp1_price + 0.5 * pos.sl_price
            diag.tp1_hits += 1
            diag.sl_hits += 1
            return _make_trade(pos, blended_exit, "TP1+SL", idx)
        else:
            diag.sl_hits += 1
            return _make_trade(pos, pos.sl_price, "SL", idx)

    # SL hit (full loss if before TP1, partial if after)
    if hit_sl:
        if pos.tp1_hit:
            # Already closed 50% at TP1, remaining 50% at SL (which is breakeven or trailing)
            blended_exit = 0.5 * pos.tp1_exit_price + 0.5 * pos.sl_price
            diag.trailing_sl_hits += 1
            return _make_trade(pos, blended_exit, "TRAILING", idx)
        else:
            diag.sl_hits += 1
            return _make_trade(pos, pos.sl_price, "SL", idx)

    # TP2 hit
    if hit_tp2:
        blended_exit = 0.5 * pos.tp1_exit_price + 0.5 * pos.tp2_price
        diag.tp2_hits += 1
        return _make_trade(pos, blended_exit, "TP2", idx)

    return None


def _force_close(pos: Position, candle: pd.Series, idx: int) -> Trade:
    if pos.tp1_hit:
        blended_exit = 0.5 * pos.tp1_exit_price + 0.5 * candle["close"]
        return _make_trade(pos, blended_exit, "END_OF_DATA", idx)
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
        sl_price=pos.original_sl,
        tp1_price=pos.tp1_price, tp2_price=pos.tp2_price,
        exit_reason=exit_reason,
        pnl_pct=pnl_usd / pos.notional_usd * 100 if pos.notional_usd > 0 else 0,
        pnl_usd=pnl_usd, fee_usd=fee_usd,
        notional_usd=pos.notional_usd,
        duration_candles=idx - pos.entry_idx,
        metadata=pos.metadata,
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

    print(f"\nConfig: fee_roundtrip={CONFIG.fee_roundtrip_pct}% (maker), "
          f"min_rr={CONFIG.min_rr_net}, risk=${CONFIG.max_risk_per_trade_usd}")
    print(f"Symbols: {SYMBOLS}, Days: {DAYS}\n")

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
        print("No data. Exiting.")
        return

    engine = MomentumBurstV2()

    # Run backtest
    all_trades = []
    all_diags = {}
    per_symbol = {}

    for symbol, df in data.items():
        diag = Diagnostics()
        logger.info("Running v2 Break & Retest on %s...", symbol)
        trades = run_backtest(symbol, df, engine, CONFIG, diag)
        logger.info("  → %d trades", len(trades))
        per_symbol[symbol] = trades
        all_trades.extend(trades)
        all_diags[symbol] = diag

    # Aggregate diagnostics
    total_diag = Diagnostics()
    for d in all_diags.values():
        total_diag.signals_detected += d.signals_detected
        total_diag.htf_filtered += d.htf_filtered
        total_diag.viability_rejected_signal += d.viability_rejected_signal
        total_diag.viability_rejected_entry += d.viability_rejected_entry
        total_diag.trades_opened += d.trades_opened
        total_diag.tp1_hits += d.tp1_hits
        total_diag.tp2_hits += d.tp2_hits
        total_diag.trailing_sl_hits += d.trailing_sl_hits
        total_diag.sl_hits += d.sl_hits
        total_diag.timeouts += d.timeouts
        for reason, count in d.rejection_reasons.items():
            total_diag.rejection_reasons[reason] = total_diag.rejection_reasons.get(reason, 0) + count

    metrics = compute_metrics(all_trades)

    # ── Print Results ───────────────────────────────────────────────────

    print("\n" + "=" * 80)
    print("FASE 3 v2: MOMENTUM BURST — BREAK & RETEST VALIDATION")
    print(f"Engine: MomentumBurstV2 (stateful, 3-phase)")
    print(f"Config: maker fees {CONFIG.fee_roundtrip_pct}%, "
          f"min_rr={CONFIG.min_rr_net}, sl=[{CONFIG.min_sl_distance_pct}-{CONFIG.max_sl_distance_pct}%]")
    print(f"Data: {DAYS}d, Symbols: {', '.join(data.keys())}")
    print("=" * 80)

    print(f"\n{'Metric':<25} {'Value':>12}")
    print("-" * 40)
    print(f"{'Trades':<25} {metrics['trades']:>12d}")
    print(f"{'Win Rate':<25} {metrics['win_rate']:>11.1f}%")
    print(f"{'Profit Factor':<25} {metrics['pf']:>12.2f}")
    print(f"{'P&L (USD)':<25} {metrics['pnl_usd']:>+12.2f}")
    print(f"{'Avg Win':<25} {metrics['avg_win']:>+12.2f}")
    print(f"{'Avg Loss':<25} {metrics['avg_loss']:>+12.2f}")
    print(f"{'Max Drawdown':<25} {metrics['max_dd']:>11.2f}%")
    print(f"{'Fees Paid':<25} {metrics['fees']:>12.2f}")
    print(f"{'Avg Duration (candles)':<25} {metrics['avg_dur']:>12.1f}")

    # ── Diagnostics ─────────────────────────────────────────────────────

    print("\n" + "=" * 80)
    print("DIAGNOSTICS: Signal Pipeline")
    print("=" * 80)
    d = total_diag
    print(f"  Retest signals detected:     {d.signals_detected:>6d}")
    print(f"  HTF filtered out:            {d.htf_filtered:>6d}")
    print(f"  Viability rejected (signal): {d.viability_rejected_signal:>6d}")
    print(f"  Viability rejected (entry):  {d.viability_rejected_entry:>6d}")
    print(f"  Trades opened:               {d.trades_opened:>6d}")

    if d.signals_detected > 0:
        pass_rate = d.trades_opened / d.signals_detected * 100
        print(f"  Pass rate:                   {pass_rate:>5.1f}%")

    # Exit breakdown
    print(f"\n  Exit breakdown:")
    print(f"    SL hits (full loss):       {d.sl_hits:>6d}")
    print(f"    TP1 hits (partial):        {d.tp1_hits:>6d}")
    print(f"    TP2 hits (full target):    {d.tp2_hits:>6d}")
    print(f"    Trailing SL (post-TP1):    {d.trailing_sl_hits:>6d}")
    print(f"    End of data:               {d.timeouts:>6d}")

    # Top rejection reasons
    if d.rejection_reasons:
        print(f"\n  Top rejection reasons:")
        categories = {}
        for reason, count in d.rejection_reasons.items():
            if "R:R liquido" in reason:
                categories["R:R too low"] = categories.get("R:R too low", 0) + count
            elif "Stop muito curto" in reason:
                categories["SL too tight"] = categories.get("SL too tight", 0) + count
            elif "Lucro esperado negativo" in reason:
                categories["Negative expected profit"] = categories.get("Negative expected profit", 0) + count
            elif "Fee impact" in reason:
                categories["Fee impact too high"] = categories.get("Fee impact too high", 0) + count
            elif "Stop muito largo" in reason:
                categories["SL too wide"] = categories.get("SL too wide", 0) + count
            else:
                categories[reason] = categories.get(reason, 0) + count
        for reason, count in sorted(categories.items(), key=lambda x: -x[1])[:8]:
            print(f"    {reason}: {count}")

    # ── Per-symbol ──────────────────────────────────────────────────────

    if any(len(t) > 0 for t in per_symbol.values()):
        print("\n--- Per-symbol breakdown ---")
        for symbol, trades in per_symbol.items():
            m = compute_metrics(trades)
            if m["trades"] > 0:
                wins = sum(1 for t in trades if t.pnl_usd > 0)
                losses = sum(1 for t in trades if t.pnl_usd <= 0)
                exits = {}
                for t in trades:
                    exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1
                exits_str = ", ".join(f"{k}:{v}" for k, v in sorted(exits.items()))
                print(f"  {symbol}: {m['trades']} trades (W:{wins} L:{losses}), "
                      f"WR={m['win_rate']:.0f}%, PF={m['pf']:.2f}, "
                      f"P&L=${m['pnl_usd']:+.2f} [{exits_str}]")

    # ── Sample trades ───────────────────────────────────────────────────

    if all_trades:
        print("\n--- Sample trades (first 10) ---")
        for i, t in enumerate(all_trades[:10]):
            print(f"  [{i+1}] {t.direction} {t.symbol} "
                  f"entry={t.entry_price:.6f} exit={t.exit_price:.6f} "
                  f"SL={t.sl_price:.6f} TP1={t.tp1_price:.6f} TP2={t.tp2_price:.6f} "
                  f"→ {t.exit_reason} P&L=${t.pnl_usd:+.3f} ({t.duration_candles}c) "
                  f"zone={t.metadata.get('zone_low','?')}-{t.metadata.get('zone_high','?')} "
                  f"burst={t.metadata.get('burst_extreme','?')}")

    # ── Verdict ─────────────────────────────────────────────────────────

    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)

    n_trades = metrics["trades"]
    pf = metrics["pf"]

    if n_trades >= 10 and pf >= 1.2:
        print(f"GO: {n_trades} trades, PF={pf:.2f} → Break & Retest tem edge!")
        print("  → Implementar v2 como engine de producao")
    elif n_trades >= 5 and 1.0 <= pf < 1.2:
        print(f"INCONCLUSIVO: {n_trades} trades, PF={pf:.2f}")
        print("  → Testar mais dias/pares antes de decidir")
    elif n_trades >= 5 and pf >= 1.2:
        print(f"INCONCLUSIVO (poucos trades): {n_trades} trades, PF={pf:.2f}")
        print("  → Testar mais dias/pares para confirmar")
    else:
        if n_trades == 0:
            print(f"NO-GO: 0 trades gerados")
        else:
            print(f"NO-GO: {n_trades} trades, PF={pf:.2f}")
        print("  → v2 Break & Retest nao viavel. Pivotar pro Engine 2 (Breakout)")

    print()


if __name__ == "__main__":
    main()
