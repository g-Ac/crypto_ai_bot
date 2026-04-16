#!/usr/bin/env python3
"""Fase 3 Final: Breakout Engine validation on DOGEUSDT.

Last test for 1-min viability. If PF < 1.0, the 1-min chapter closes.

Usage:
    cd ~/crypto_ai_bot && source .venv/bin/activate
    python scripts/fase3_breakout_validation.py
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
from engines_1m.breakout import BreakoutEngine
from indicators_1m import add_indicators_1m
from market_1m import fetch_1m_historical
from risk_calculator_1m import calculate_viability

logger = logging.getLogger(__name__)

SYMBOLS = ["DOGEUSDT"]
DAYS = 30
CONFIG = Config1m(max_risk_per_trade_usd=2.0, use_maker_orders=True)

_MIN_WARMUP = 35


# ── HTF Filter ──────────────────────────────────────────────────────────

def build_htf_ema(df_1m: pd.DataFrame) -> pd.DataFrame:
    df = df_1m.set_index("timestamp") if "timestamp" in df_1m.columns else df_1m
    df_5m = df.resample("5min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    df_5m["ema8_5m"] = ta.trend.ema_indicator(df_5m["close"], window=8)
    df_5m["ema21_5m"] = ta.trend.ema_indicator(df_5m["close"], window=21)
    return df_5m[["ema8_5m", "ema21_5m"]].dropna()


def check_htf_alignment(htf_ema: pd.DataFrame, candle_time, direction: str) -> bool:
    if htf_ema.empty:
        return False
    valid = htf_ema.index[htf_ema.index <= candle_time]
    if len(valid) == 0:
        return False
    last_5m = htf_ema.loc[valid[-1]]
    if direction == "LONG":
        return last_5m["ema8_5m"] > last_5m["ema21_5m"]
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
    rejection_reasons: Dict[str, int] = field(default_factory=dict)

    def _add_rejection(self, reason: str):
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1


# ── Trade / Position ────────────────────────────────────────────────────

@dataclass
class Trade:
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
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
    tp1_hit: bool = False
    tp1_exit_price: float = 0.0
    original_sl: float = 0.0
    metadata: dict = field(default_factory=dict)


# ── Backtest ────────────────────────────────────────────────────────────

def run_backtest(
    symbol: str,
    df_1m: pd.DataFrame,
    engine: BreakoutEngine,
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

    for i in range(_MIN_WARMUP, len(df_full)):
        candle = df_full.iloc[i]

        # 1. Check exit
        if pos is not None:
            trade = _check_exit(pos, candle, i, diag)
            if trade is not None:
                trades.append(trade)
                pos = None

        # 2. Execute pending entry
        if pending_signal is not None and pos is None:
            entry_price = candle["open"]

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

                trade = _check_exit(pos, candle, i, diag)
                if trade is not None:
                    trades.append(trade)
                    pos = None

            pending_signal = None

        # 3. Trailing stop (after TP1 hit)
        if pos is not None and pos.tp1_hit:
            atr = candle.get("atr14", 0)
            if atr > 0:
                close = candle["close"]
                if pos.direction == "LONG":
                    pos.sl_price = max(pos.sl_price, close - 1.0 * atr)
                else:
                    pos.sl_price = min(pos.sl_price, close + 1.0 * atr)

        # 4. Scan for signals
        if pos is None and pending_signal is None:
            window_start = max(0, i - 50)
            visible = df_full.iloc[window_start:i + 1]
            signal = engine.analyze(symbol, visible)
            if signal is not None and signal.valid:
                diag.signals_detected += 1

                candle_time = candle.get("timestamp", candle.name)
                if not check_htf_alignment(htf_ema, candle_time, signal.direction.value):
                    diag.htf_filtered += 1
                    continue

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

    if pos is not None:
        last = df_full.iloc[-1]
        trade = _force_close(pos, last, len(df_full) - 1)
        trades.append(trade)

    return trades


def _check_exit(pos, candle, idx, diag):
    high, low = candle["high"], candle["low"]

    if pos.direction == "LONG":
        hit_sl = low <= pos.sl_price
        hit_tp1 = not pos.tp1_hit and high >= pos.tp1_price
        hit_tp2 = pos.tp1_hit and high >= pos.tp2_price
    else:
        hit_sl = high >= pos.sl_price
        hit_tp1 = not pos.tp1_hit and low <= pos.tp1_price
        hit_tp2 = pos.tp1_hit and low <= pos.tp2_price

    if hit_tp1 and not hit_sl:
        pos.tp1_hit = True
        pos.tp1_exit_price = pos.tp1_price
        pos.sl_price = pos.entry_price  # breakeven
        diag.tp1_hits += 1
        if hit_tp2:
            diag.tp2_hits += 1
            blended = 0.5 * pos.tp1_price + 0.5 * pos.tp2_price
            return _make_trade(pos, blended, "TP2", idx)
        return None

    if hit_tp1 and hit_sl:
        open_price = candle["open"]
        if abs(open_price - pos.tp1_price) <= abs(open_price - pos.sl_price):
            blended = 0.5 * pos.tp1_price + 0.5 * pos.sl_price
            diag.tp1_hits += 1
            diag.sl_hits += 1
            return _make_trade(pos, blended, "TP1+SL", idx)
        else:
            diag.sl_hits += 1
            return _make_trade(pos, pos.sl_price, "SL", idx)

    if hit_sl:
        if pos.tp1_hit:
            blended = 0.5 * pos.tp1_exit_price + 0.5 * pos.sl_price
            diag.trailing_sl_hits += 1
            return _make_trade(pos, blended, "TRAILING", idx)
        diag.sl_hits += 1
        return _make_trade(pos, pos.sl_price, "SL", idx)

    if hit_tp2:
        blended = 0.5 * pos.tp1_exit_price + 0.5 * pos.tp2_price
        diag.tp2_hits += 1
        return _make_trade(pos, blended, "TP2", idx)

    return None


def _force_close(pos, candle, idx):
    if pos.tp1_hit:
        blended = 0.5 * pos.tp1_exit_price + 0.5 * candle["close"]
        return _make_trade(pos, blended, "END_OF_DATA", idx)
    return _make_trade(pos, candle["close"], "END_OF_DATA", idx)


def _make_trade(pos, exit_price, exit_reason, idx):
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

def compute_metrics(trades):
    if not trades:
        return {"trades": 0, "win_rate": 0, "pf": 0, "pnl_usd": 0,
                "avg_win": 0, "avg_loss": 0, "max_dd": 0, "fees": 0, "avg_dur": 0}

    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    gp = sum(t.pnl_usd for t in wins)
    gl = abs(sum(t.pnl_usd for t in losses))
    pf = gp / gl if gl > 0 else (float("inf") if gp > 0 else 0)

    cum = peak = max_dd = 0.0
    for t in trades:
        cum += t.pnl_pct
        if cum > peak:
            peak = cum
        dd = peak - cum
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

    print(f"\nConfig: fee={CONFIG.fee_roundtrip_pct}% (maker), "
          f"min_rr={CONFIG.min_rr_net}, risk=${CONFIG.max_risk_per_trade_usd}")
    print(f"Symbols: {SYMBOLS}, Days: {DAYS}\n")

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

    engine = BreakoutEngine()
    all_trades = []
    all_diags = {}

    for symbol, df in data.items():
        diag = Diagnostics()
        logger.info("Running Breakout Engine on %s...", symbol)
        trades = run_backtest(symbol, df, engine, CONFIG, diag)
        logger.info("  → %d trades", len(trades))
        all_trades.extend(trades)
        all_diags[symbol] = diag

    # Aggregate diagnostics
    td = Diagnostics()
    for d in all_diags.values():
        td.signals_detected += d.signals_detected
        td.htf_filtered += d.htf_filtered
        td.viability_rejected_signal += d.viability_rejected_signal
        td.viability_rejected_entry += d.viability_rejected_entry
        td.trades_opened += d.trades_opened
        td.tp1_hits += d.tp1_hits
        td.tp2_hits += d.tp2_hits
        td.trailing_sl_hits += d.trailing_sl_hits
        td.sl_hits += d.sl_hits
        for r, c in d.rejection_reasons.items():
            td.rejection_reasons[r] = td.rejection_reasons.get(r, 0) + c

    m = compute_metrics(all_trades)

    # ── Results ─────────────────────────────────────────────────────────

    print("\n" + "=" * 80)
    print("FASE 3 FINAL: BREAKOUT ENGINE VALIDATION")
    print(f"Engine: BreakoutEngine v1 (stateless, consolidation breakout)")
    print(f"Config: maker fees {CONFIG.fee_roundtrip_pct}%, "
          f"min_rr={CONFIG.min_rr_net}, sl=[{CONFIG.min_sl_distance_pct}-{CONFIG.max_sl_distance_pct}%]")
    print(f"Data: {DAYS}d, Symbols: {', '.join(data.keys())}")
    print("=" * 80)

    print(f"\n{'Metric':<25} {'Value':>12}")
    print("-" * 40)
    print(f"{'Trades':<25} {m['trades']:>12d}")
    print(f"{'Win Rate':<25} {m['win_rate']:>11.1f}%")
    print(f"{'Profit Factor':<25} {m['pf']:>12.2f}")
    print(f"{'P&L (USD)':<25} {m['pnl_usd']:>+12.2f}")
    print(f"{'Avg Win':<25} {m['avg_win']:>+12.2f}")
    print(f"{'Avg Loss':<25} {m['avg_loss']:>+12.2f}")
    print(f"{'Max Drawdown':<25} {m['max_dd']:>11.2f}%")
    print(f"{'Fees Paid':<25} {m['fees']:>12.2f}")
    print(f"{'Avg Duration (candles)':<25} {m['avg_dur']:>12.1f}")

    # Diagnostics
    print("\n" + "=" * 80)
    print("DIAGNOSTICS: Signal Pipeline")
    print("=" * 80)
    print(f"  Breakout signals detected:   {td.signals_detected:>6d}")
    print(f"  HTF filtered out:            {td.htf_filtered:>6d}")
    print(f"  Viability rejected (signal): {td.viability_rejected_signal:>6d}")
    print(f"  Viability rejected (entry):  {td.viability_rejected_entry:>6d}")
    print(f"  Trades opened:               {td.trades_opened:>6d}")
    if td.signals_detected > 0:
        print(f"  Pass rate:                   {td.trades_opened / td.signals_detected * 100:>5.1f}%")

    print(f"\n  Exit breakdown:")
    print(f"    SL hits (full loss):       {td.sl_hits:>6d}")
    print(f"    TP1 hits (partial):        {td.tp1_hits:>6d}")
    print(f"    TP2 hits (full target):    {td.tp2_hits:>6d}")
    print(f"    Trailing SL (post-TP1):    {td.trailing_sl_hits:>6d}")

    if td.rejection_reasons:
        print(f"\n  Top rejection reasons:")
        cats = {}
        for reason, count in td.rejection_reasons.items():
            if "R:R liquido" in reason:
                cats["R:R too low"] = cats.get("R:R too low", 0) + count
            elif "Stop muito curto" in reason:
                cats["SL too tight"] = cats.get("SL too tight", 0) + count
            elif "Stop muito largo" in reason:
                cats["SL too wide"] = cats.get("SL too wide", 0) + count
            elif "Lucro esperado negativo" in reason:
                cats["Negative expected profit"] = cats.get("Negative expected profit", 0) + count
            elif "Fee impact" in reason:
                cats["Fee impact too high"] = cats.get("Fee impact too high", 0) + count
            else:
                cats[reason] = cats.get(reason, 0) + count
        for reason, count in sorted(cats.items(), key=lambda x: -x[1])[:8]:
            print(f"    {reason}: {count}")

    # Sample trades
    if all_trades:
        print("\n--- Sample trades (first 10) ---")
        for i, t in enumerate(all_trades[:10]):
            print(f"  [{i+1}] {t.direction} {t.symbol} "
                  f"entry={t.entry_price:.6f} exit={t.exit_price:.6f} "
                  f"SL={t.sl_price:.6f} TP1={t.tp1_price:.6f} "
                  f"→ {t.exit_reason} P&L=${t.pnl_usd:+.3f} ({t.duration_candles}c) "
                  f"range={t.metadata.get('range_pct','?')}% "
                  f"bb={t.metadata.get('bb_bandwidth','?')}%")

    # ── Verdict ─────────────────────────────────────────────────────────

    print("\n" + "=" * 80)
    print("VERDICT (DEFINITIVO)")
    print("=" * 80)

    n_trades = m["trades"]
    pf = m["pf"]

    if n_trades >= 10 and pf >= 1.2:
        print(f"GO: {n_trades} trades, PF={pf:.2f}")
        print("  Breakout tem edge no 1-min! Continuar desenvolvimento.")
    elif n_trades >= 5 and 1.0 <= pf < 1.2:
        print(f"INCONCLUSIVO: {n_trades} trades, PF={pf:.2f}")
        print("  Testar mais dias/pares antes de decidir.")
    else:
        if n_trades == 0:
            print(f"NO-GO: 0 trades gerados.")
        else:
            print(f"NO-GO: {n_trades} trades, PF={pf:.2f}")
        print()
        print("  CAPITULO 1-MIN FECHADO.")
        print("  3 padroes testados (Burst v1, Burst v2, Breakout),")
        print("  4 moedas (BTC, ETH, SOL, DOGE), 2 fee structures (taker, maker).")
        print("  Nenhum produziu edge.")
        print()
        print("  Proximo passo: pivotar infraestrutura pro 5-min.")
        print("  Momentum Pullback ja funciona la. Usar Risk Calculator,")
        print("  backtest engine e indicators como base pro segundo engine 5-min.")

    print()


if __name__ == "__main__":
    main()
