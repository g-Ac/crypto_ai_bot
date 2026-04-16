#!/usr/bin/env python3
"""Fase 3 Validation: Test fee friction hypothesis.

Question: Does Momentum Burst work on volatile coins (SOL, DOGE)
with maker fees (0.04% roundtrip)?

Uses spec thresholds (NOT relaxed). If trades appear with PF > 1.0,
the problem was fee + volatility, not the strategy.

Usage:
    cd ~/crypto_ai_bot && source .venv/bin/activate
    python scripts/fase3_validation.py
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from config_1m import Config1m
from engines_1m.momentum_burst import MomentumBurst1m
from indicators_1m import add_indicators_1m
from market_1m import fetch_1m_historical
from risk_calculator_1m import calculate_viability
from signal_types import Direction

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────

SYMBOLS = ["SOLUSDT", "DOGEUSDT"]
DAYS = 30

# Maker fees: 0.02% per side = 0.04% roundtrip
CONFIG_MAKER = Config1m(
    max_risk_per_trade_usd=2.0,
    use_maker_orders=True,  # triggers 0.04% roundtrip via __post_init__
)

# Taker fees for comparison: 0.04% per side = 0.08% roundtrip
CONFIG_TAKER = Config1m(
    max_risk_per_trade_usd=2.0,
    use_maker_orders=False,  # 0.08% roundtrip
)

# Also test BTC/ETH with maker fees to isolate the variable
SYMBOLS_BTC = ["BTCUSDT", "ETHUSDT"]


# ── Diagnostics ─────────────────────────────────────────────────────────

@dataclass
class Diagnostics:
    signals_detected: int = 0
    viability_rejected_signal: int = 0
    viability_rejected_entry: int = 0
    trades_opened: int = 0
    rejection_reasons: Dict[str, int] = field(default_factory=dict)


# ── Trade / Position ────────────────────────────────────────────────────

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
    tp_price: float
    entry_idx: int
    notional_usd: float
    fee_roundtrip_pct: float


# ── Backtest ────────────────────────────────────────────────────────────

_MIN_WARMUP = 25


def run_backtest(
    symbol: str,
    df_1m: pd.DataFrame,
    engine: MomentumBurst1m,
    config: Config1m,
    diag: Diagnostics,
) -> List[Trade]:
    """Candle-by-candle backtest with spec thresholds."""
    if "time" in df_1m.columns and "timestamp" not in df_1m.columns:
        df_1m = df_1m.rename(columns={"time": "timestamp"})

    df_full = add_indicators_1m(df_1m.copy())

    trades: List[Trade] = []
    pos: Optional[Position] = None
    pending_signal = None

    for i in range(_MIN_WARMUP, len(df_full)):
        candle = df_full.iloc[i]

        # 1. Check exit
        if pos is not None:
            trade = _check_exit(pos, candle, i)
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
                reason = viability.reason
                diag.rejection_reasons[reason] = diag.rejection_reasons.get(reason, 0) + 1
            else:
                diag.trades_opened += 1
                pos = Position(
                    symbol=symbol,
                    direction=pending_signal.direction.value,
                    entry_price=entry_price,
                    sl_price=pending_signal.sl_price,
                    tp_price=pending_signal.tp1_price,
                    entry_idx=i,
                    notional_usd=viability.notional_usd,
                    fee_roundtrip_pct=config.fee_roundtrip_pct,
                )

                # B3: Check exit on entry candle
                trade = _check_exit(pos, candle, i)
                if trade is not None:
                    trades.append(trade)
                    pos = None

            pending_signal = None

        # 3. Scan for signals
        if pos is None and pending_signal is None:
            visible = df_full.iloc[:i + 1]
            signal = engine.analyze(symbol, visible)
            if signal is not None and signal.valid:
                diag.signals_detected += 1

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

    # Force close remaining
    if pos is not None:
        last = df_full.iloc[-1]
        trades.append(_force_close(pos, last, len(df_full) - 1))

    return trades


def _check_exit(pos: Position, candle: pd.Series, idx: int) -> Optional[Trade]:
    high, low = candle["high"], candle["low"]

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

    # Fetch all data upfront
    all_data = {}
    for symbol in set(SYMBOLS + SYMBOLS_BTC):
        logger.info("Fetching %dd 1m data for %s...", DAYS, symbol)
        df = fetch_1m_historical(symbol, days=DAYS)
        if df.empty:
            logger.warning("No data for %s — skipping", symbol)
            continue
        logger.info("  %s: %d candles", symbol, len(df))
        all_data[symbol] = df

    engine = MomentumBurst1m()

    # Define test scenarios
    scenarios = {
        "SOL+DOGE maker (0.04%)": {
            "symbols": SYMBOLS,
            "config": CONFIG_MAKER,
        },
        "SOL+DOGE taker (0.08%)": {
            "symbols": SYMBOLS,
            "config": CONFIG_TAKER,
        },
        "BTC+ETH maker (0.04%)": {
            "symbols": SYMBOLS_BTC,
            "config": CONFIG_MAKER,
        },
        "BTC+ETH taker (0.08%)": {
            "symbols": SYMBOLS_BTC,
            "config": CONFIG_TAKER,
        },
    }

    all_results = {}
    all_diags = {}
    all_scenario_trades = {}

    for scenario_name, scenario in scenarios.items():
        diag = Diagnostics()
        scenario_trades = []
        per_symbol = {}

        for symbol in scenario["symbols"]:
            if symbol not in all_data:
                continue
            logger.info("Running %-28s on %s...", scenario_name, symbol)
            trades = run_backtest(
                symbol=symbol, df_1m=all_data[symbol],
                engine=engine, config=scenario["config"],
                diag=diag,
            )
            logger.info("  → %d trades", len(trades))
            per_symbol[symbol] = trades
            scenario_trades.extend(trades)

        all_results[scenario_name] = compute_metrics(scenario_trades)
        all_diags[scenario_name] = diag
        all_scenario_trades[scenario_name] = per_symbol

    # ── Print Results ───────────────────────────────────────────────────

    print("\n" + "=" * 95)
    print("FASE 3 VALIDATION: Fee Friction Hypothesis Test")
    print(f"Engine: MomentumBurst v1 (spec thresholds, NOT relaxed)")
    print(f"Data: {DAYS}d | Spec: min_rr=1.5, max_fee_impact=30%, sl=[0.05%-1.0%]")
    print("=" * 95)

    header = (
        f"{'Scenario':<30} {'Trades':>6} {'WR%':>6} {'PF':>6} {'P&L $':>8} "
        f"{'AvgWin':>8} {'AvgLoss':>8} {'MaxDD%':>7} {'Fees$':>7} {'AvgDur':>6}"
    )
    print(header)
    print("-" * 95)

    for name, m in all_results.items():
        print(
            f"{name:<30} "
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

    # ── Diagnostics ─────────────────────────────────────────────────────

    print("\n" + "=" * 95)
    print("DIAGNOSTICS: Signal → Trade Pipeline")
    print("=" * 95)
    print(
        f"{'Scenario':<30} {'Signals':>8} {'Viab Rej':>9} "
        f"{'Entry Rej':>10} {'Opened':>8} {'Pass%':>6}"
    )
    print("-" * 95)
    for name, d in all_diags.items():
        pass_rate = (d.trades_opened / d.signals_detected * 100) if d.signals_detected > 0 else 0
        print(
            f"{name:<30} "
            f"{d.signals_detected:>8d} "
            f"{d.viability_rejected_signal:>9d} "
            f"{d.viability_rejected_entry:>10d} "
            f"{d.trades_opened:>8d} "
            f"{pass_rate:>5.1f}%"
        )

    # ── Top Rejection Reasons (condensed) ───────────────────────────────

    print("\n--- Top Rejection Reasons (top 5 per scenario) ---")
    for name, d in all_diags.items():
        if not d.rejection_reasons:
            print(f"\n{name}: (no rejections)")
            continue
        # Aggregate by category
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
            else:
                categories[reason] = categories.get(reason, 0) + count

        print(f"\n{name}:")
        for reason, count in sorted(categories.items(), key=lambda x: -x[1])[:5]:
            print(f"  {reason}: {count}")

    # ── Per-symbol breakdown ────────────────────────────────────────────

    print("\n--- Per-symbol breakdown ---")
    for name, per_symbol in all_scenario_trades.items():
        has_trades = any(len(t) > 0 for t in per_symbol.values())
        if not has_trades:
            continue
        print(f"\n{name}:")
        for symbol, trades in per_symbol.items():
            m = compute_metrics(trades)
            if m["trades"] > 0:
                wins = sum(1 for t in trades if t.pnl_usd > 0)
                losses = sum(1 for t in trades if t.pnl_usd <= 0)
                exits = {}
                for t in trades:
                    exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1
                exits_str = ", ".join(f"{k}:{v}" for k, v in sorted(exits.items()))
                print(
                    f"  {symbol}: {m['trades']} trades (W:{wins} L:{losses}), "
                    f"WR={m['win_rate']:.0f}%, PF={m['pf']:.2f}, "
                    f"P&L=${m['pnl_usd']:+.2f} [{exits_str}]"
                )

    # ── Verdict ─────────────────────────────────────────────────────────

    print("\n" + "=" * 95)
    print("VERDICT")
    print("=" * 95)

    sol_maker = all_results.get("SOL+DOGE maker (0.04%)", {})
    btc_taker = all_results.get("BTC+ETH taker (0.08%)", {})

    if sol_maker.get("trades", 0) > 0 and sol_maker.get("pf", 0) > 1.0:
        print("HIPOTESE CONFIRMADA: Moedas volateis + maker fees viabilizam o 1-min.")
        print(f"  SOL+DOGE maker: {sol_maker['trades']} trades, PF={sol_maker['pf']:.2f}")
        print("  → Proximo passo: Engine 2 (Breakout) em SOL/DOGE com maker fees")
    elif sol_maker.get("trades", 0) > 0:
        print("PARCIAL: Moedas volateis + maker fees geram trades, mas sem edge (PF < 1.0).")
        print(f"  SOL+DOGE maker: {sol_maker['trades']} trades, PF={sol_maker['pf']:.2f}")
        print("  → Momentum Burst nao tem edge mesmo com condicoes favoraveis")
    elif all_diags.get("SOL+DOGE maker (0.04%)", Diagnostics()).signals_detected > 0:
        print("HIPOTESE REFUTADA: Mesmo com moedas volateis + maker fees, Guardiao rejeita tudo.")
        print("  → 1-min inteiro e inviavel com spec thresholds atuais")
    else:
        print("SEM DADOS: Nenhum sinal detectado em SOL/DOGE.")
        print("  → Verificar se os dados foram carregados corretamente")

    print()


if __name__ == "__main__":
    main()
