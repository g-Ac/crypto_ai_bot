"""Backtest Breakout Engine 5m — 30d BTC/ETH/SOL with taker fees.

GO/NO-GO criteria:
  - PF >= 1.2 AND trades >= 10 → GO (proceed to paper trading)
  - Otherwise → NO-GO (close chapter, focus on Momentum Pullback)
"""
import sys
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, ".")

from engines_5m.breakout import BreakoutEngine5m
from indicators_5m import add_indicators_5m


FEE_ROUNDTRIP_PCT = 0.08
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DAYS = 30
TIMEOUT_CANDLES = 60  # 5 hours


def fetch_5m_candles(symbol: str, days: int) -> pd.DataFrame:
    """Fetch 5-min candles from Binance Spot Klines."""
    all_candles = []
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    limit = 1000

    current = start_time
    while current < end_time:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=5m&startTime={current}&limit={limit}"
        )
        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if not data:
                        current = end_time
                        break
                    all_candles.extend(data)
                    current = data[-1][0] + 1
                    break
                elif resp.status_code == 429:
                    time.sleep(5)
                else:
                    time.sleep(2)
            except Exception:
                time.sleep(2)
        else:
            break
        time.sleep(0.2)

    df = pd.DataFrame(all_candles, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbbav", "tbqav", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["timestamp"] = pd.to_datetime(df["time"], unit="ms")
    return df


def run_backtest(symbol: str):
    print(f"\n{'='*60}")
    print(f"  BACKTEST: {symbol} — Breakout 5m — {DAYS}d")
    print(f"{'='*60}")

    df_full = fetch_5m_candles(symbol, DAYS)
    print(f"  Candles: {len(df_full)}", flush=True)

    engine = BreakoutEngine5m()
    trades = []
    position = None
    signals_count = 0

    for i in range(engine._MIN_CANDLES, len(df_full)):
        visible = df_full.iloc[max(0, i - 120):i + 1].copy()
        visible = add_indicators_5m(visible)

        candle = df_full.iloc[i]
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        # Manage open position
        if position is not None:
            pos = position
            direction = pos["direction"]
            entry = pos["entry_price"]
            sl = pos["sl_price"]
            tp1 = pos["tp1_price"]
            tp2 = pos["tp2_price"]
            tp1_hit = pos.get("tp1_hit", False)
            pos["candles_elapsed"] += 1

            # MFE/MAE
            if direction == "LONG":
                pos["mfe_pct"] = max(pos["mfe_pct"], (high - entry) / entry * 100)
                pos["mae_pct"] = max(pos["mae_pct"], (entry - low) / entry * 100)
            else:
                pos["mfe_pct"] = max(pos["mfe_pct"], (entry - low) / entry * 100)
                pos["mae_pct"] = max(pos["mae_pct"], (high - entry) / entry * 100)

            exit_reason = None
            exit_price = close

            if direction == "LONG":
                if low <= sl:
                    exit_reason = "sl_hit" if not tp1_hit else "sl_breakeven"
                    exit_price = sl
                elif not tp1_hit and high >= tp1:
                    pos["tp1_hit"] = True
                    pos["tp1_exit_price"] = tp1
                    pos["sl_price"] = entry
                    if high >= tp2:
                        exit_reason = "tp2_hit"
                        exit_price = 0.5 * tp1 + 0.5 * tp2
                elif tp1_hit and high >= tp2:
                    exit_reason = "tp2_hit"
                    exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * tp2
                elif tp1_hit and low <= pos["sl_price"]:
                    exit_reason = "sl_breakeven"
                    exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * entry
            else:
                if high >= sl:
                    exit_reason = "sl_hit" if not tp1_hit else "sl_breakeven"
                    exit_price = sl
                elif not tp1_hit and low <= tp1:
                    pos["tp1_hit"] = True
                    pos["tp1_exit_price"] = tp1
                    pos["sl_price"] = entry
                    if low <= tp2:
                        exit_reason = "tp2_hit"
                        exit_price = 0.5 * tp1 + 0.5 * tp2
                elif tp1_hit and low <= tp2:
                    exit_reason = "tp2_hit"
                    exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * tp2
                elif tp1_hit and high >= pos["sl_price"]:
                    exit_reason = "sl_breakeven"
                    exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * entry

            if exit_reason is None and pos["candles_elapsed"] >= TIMEOUT_CANDLES:
                exit_reason = "timeout"
                exit_price = close

            if exit_reason:
                if direction == "LONG":
                    pnl_pct = (exit_price - entry) / entry * 100
                else:
                    pnl_pct = (entry - exit_price) / entry * 100
                pnl_pct -= FEE_ROUNDTRIP_PCT

                trades.append({
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry,
                    "exit_price": exit_price,
                    "pnl_pct": round(pnl_pct, 4),
                    "exit_reason": exit_reason,
                    "duration": pos["candles_elapsed"],
                    "mfe_pct": round(pos["mfe_pct"], 4),
                    "mae_pct": round(pos["mae_pct"], 4),
                })
                position = None

        # Generate new signal if no position
        if position is None:
            signal = engine.analyze(symbol, visible)
            if signal is not None and signal.valid:
                signals_count += 1
                position = {
                    "direction": signal.direction.value,
                    "entry_price": signal.entry_price,
                    "sl_price": signal.sl_price,
                    "tp1_price": signal.tp1_price,
                    "tp2_price": signal.tp2_price,
                    "candles_elapsed": 0,
                    "mfe_pct": 0.0,
                    "mae_pct": 0.0,
                    "tp1_hit": False,
                }

        # Progress indicator every 2000 candles
        if (i - engine._MIN_CANDLES) % 2000 == 0 and i > engine._MIN_CANDLES:
            pct = (i - engine._MIN_CANDLES) / (len(df_full) - engine._MIN_CANDLES) * 100
            print(f"  ... {pct:.0f}% ({i}/{len(df_full)}) signals={signals_count} trades={len(trades)}", flush=True)

    # Results
    print(f"\n  Signals: {signals_count}")
    print(f"  Trades: {len(trades)}")

    if not trades:
        print("  NO TRADES — skipping metrics")
        return trades

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    print(f"  Win Rate: {len(wins)}/{len(trades)} = {len(wins)/len(trades)*100:.1f}%")
    print(f"  Avg PnL: {np.mean(pnls):.4f}%")
    print(f"  Total PnL: {sum(pnls):.4f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Avg Duration: {np.mean([t['duration'] for t in trades]):.1f} candles ({np.mean([t['duration'] for t in trades])*5:.0f} min)")
    print(f"  Avg MFE: {np.mean([t['mfe_pct'] for t in trades]):.4f}%")
    print(f"  Avg MAE: {np.mean([t['mae_pct'] for t in trades]):.4f}%")

    # Exit reason distribution
    reasons = {}
    for t in trades:
        r = t["exit_reason"]
        reasons[r] = reasons.get(r, 0) + 1
    print(f"\n  Exit Reasons:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {r}: {c} ({c/len(trades)*100:.1f}%)")

    # Direction distribution
    longs = [t for t in trades if t["direction"] == "LONG"]
    shorts = [t for t in trades if t["direction"] == "SHORT"]
    print(f"\n  Direction: {len(longs)} LONG / {len(shorts)} SHORT")
    if longs:
        long_pnls = [t["pnl_pct"] for t in longs]
        print(f"    LONG avg PnL: {np.mean(long_pnls):.4f}%")
    if shorts:
        short_pnls = [t["pnl_pct"] for t in shorts]
        print(f"    SHORT avg PnL: {np.mean(short_pnls):.4f}%")

    return trades


if __name__ == "__main__":
    print(f"Breakout 5m Backtest — {DAYS}d — Fee {FEE_ROUNDTRIP_PCT}% roundtrip (taker)")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print(f"GO/NO-GO: PF >= 1.2 AND trades >= 10")

    all_trades = []
    for sym in SYMBOLS:
        trades = run_backtest(sym)
        all_trades.extend(trades)
        time.sleep(1)

    print(f"\n{'='*60}")
    print(f"  COMBINED RESULTS — {len(all_trades)} trades")
    print(f"{'='*60}")

    if all_trades:
        pnls = [t["pnl_pct"] for t in all_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gp = sum(wins) if wins else 0
        gl = abs(sum(losses)) if losses else 0
        pf = gp / gl if gl > 0 else float("inf")

        print(f"  Total Trades: {len(all_trades)}")
        print(f"  Win Rate: {len(wins)}/{len(all_trades)} = {len(wins)/len(all_trades)*100:.1f}%")
        print(f"  Avg PnL: {np.mean(pnls):.4f}%")
        print(f"  Total PnL: {sum(pnls):.4f}%")
        print(f"  Profit Factor: {pf:.2f}")

        # Per-symbol breakdown
        print(f"\n  Per-symbol:")
        for sym in SYMBOLS:
            sym_trades = [t for t in all_trades if t["symbol"] == sym]
            if sym_trades:
                sym_pnls = [t["pnl_pct"] for t in sym_trades]
                sym_wins = [p for p in sym_pnls if p > 0]
                sym_losses = [p for p in sym_pnls if p <= 0]
                sym_gp = sum(sym_wins) if sym_wins else 0
                sym_gl = abs(sum(sym_losses)) if sym_losses else 0
                sym_pf = sym_gp / sym_gl if sym_gl > 0 else float("inf")
                print(f"    {sym}: {len(sym_trades)}t WR={len(sym_wins)/len(sym_trades)*100:.0f}% PF={sym_pf:.2f} PnL={sum(sym_pnls):.2f}%")

        print(f"\n  ═══════════════════════════════════")
        print(f"  GO/NO-GO VERDICT:")
        print(f"  ═══════════════════════════════════")
        pf_pass = pf >= 1.2
        trades_pass = len(all_trades) >= 10
        go = pf_pass and trades_pass
        print(f"    PF >= 1.2:      {'PASS' if pf_pass else 'FAIL'} ({pf:.2f})")
        print(f"    Trades >= 10:   {'PASS' if trades_pass else 'FAIL'} ({len(all_trades)})")
        print(f"    ─────────────────────────────────")
        print(f"    Verdict:        {'>>> GO <<<' if go else '>>> NO-GO <<<'}")
        print(f"  ═══════════════════════════════════")
    else:
        print("  NO TRADES across all symbols")
        print(f"\n  GO/NO-GO: >>> NO-GO <<< (0 trades)")
