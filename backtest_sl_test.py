"""
Testa multiplos valores de Stop Loss para cada ativo
e mostra qual SL gera melhor resultado.
"""
import backtest as bt
from config import SYMBOLS, STOP_LOSS_MAP

SL_VALUES = [1.0, 1.5, 2.0, 2.5, 3.0]


def test_sl_for_symbol(symbol):
    print(f"\n  Buscando dados de {symbol}...")
    df = bt.fetch_historical(symbol, bt.INTERVAL, bt.BACKTEST_DAYS)
    df_htf = bt.fetch_historical(symbol, bt.INTERVAL_HTF, bt.BACKTEST_DAYS)
    df = bt.add_indicators(df)
    df_htf = bt.add_indicators(df_htf)
    df_htf = bt.compute_htf_trends(df_htf)

    print(f"  {len(df)} candles 5m | {len(df_htf)} candles 1h\n")

    warmup = max(bt.SMA_LONG, bt.BREAKOUT_WINDOW, bt.VOLUME_WINDOW, 14) + 5
    results = []

    for sl in SL_VALUES:
        trades = []
        position = None
        entry_price = 0.0
        entry_time = None
        entry_htf = False

        for i in range(warmup, len(df)):
            row = df.iloc[i]
            htf = bt.get_htf_at(row["time"], df_htf)
            sig = bt.signal_for_row(row, htf)
            if sig is None:
                continue

            price = sig["price"]
            low = row["low"]
            high = row["high"]

            if position == "LONG":
                sl_price = entry_price * (1 - sl / 100)
                if low <= sl_price:
                    trades.append({"pnl_pct": -sl, "exit_reason": "stop_loss"})
                    position = None
                    continue

            elif position == "SHORT":
                sl_price = entry_price * (1 + sl / 100)
                if high >= sl_price:
                    trades.append({"pnl_pct": -sl, "exit_reason": "stop_loss"})
                    position = None
                    continue

            if sig["decision"] == "BUY":
                if position == "SHORT":
                    pnl = ((entry_price - price) / entry_price) * 100
                    trades.append({"pnl_pct": pnl, "exit_reason": "signal"})
                    position = None
                if position is None:
                    position = "LONG"
                    entry_price = price
                    entry_time = row["time"]

            elif sig["decision"] == "SELL":
                if position == "LONG":
                    pnl = ((price - entry_price) / entry_price) * 100
                    trades.append({"pnl_pct": pnl, "exit_reason": "signal"})
                    position = None
                if position is None:
                    position = "SHORT"
                    entry_price = price
                    entry_time = row["time"]

        if position is not None:
            last_price = df.iloc[-1]["close"]
            if position == "LONG":
                pnl = ((last_price - entry_price) / entry_price) * 100
            else:
                pnl = ((entry_price - last_price) / entry_price) * 100
            trades.append({"pnl_pct": pnl, "exit_reason": "end_of_data"})

        if trades:
            wins = [t for t in trades if t["pnl_pct"] > 0]
            sl_hits = [t for t in trades if t["exit_reason"] == "stop_loss"]
            total_ret = sum(t["pnl_pct"] for t in trades)
            gp = sum(t["pnl_pct"] for t in wins) if wins else 0
            gl = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0))

            cum = peak = max_dd = 0.0
            for t in trades:
                cum += t["pnl_pct"]
                if cum > peak:
                    peak = cum
                dd = peak - cum
                if dd > max_dd:
                    max_dd = dd

            results.append({
                "sl": sl,
                "trades": len(trades),
                "wr": len(wins) / len(trades) * 100,
                "ret": total_ret,
                "max_dd": max_dd,
                "pf": gp / gl if gl > 0 else float("inf"),
                "sl_hits": len(sl_hits),
                "sl_pct": len(sl_hits) / len(trades) * 100,
            })

    return results


if __name__ == "__main__":
    print("=" * 70)
    print("  TESTE DE STOP LOSS OTIMO")
    print("=" * 70)

    for symbol in SYMBOLS:
        results = test_sl_for_symbol(symbol)

        print(f"  {symbol}")
        print(f"  {'SL':>5} | {'Trades':>6} | {'WR':>6} | {'Retorno':>8} | {'MaxDD':>6} | {'PF':>5} | {'SL Hits':>7}")
        print(f"  {'-'*60}")

        best = max(results, key=lambda r: r["ret"])

        for r in results:
            marker = " <-- melhor" if r["sl"] == best["sl"] else ""
            print(
                f"  {r['sl']:>4.1f}% | "
                f"{r['trades']:>6} | "
                f"{r['wr']:>5.1f}% | "
                f"{r['ret']:>+7.2f}% | "
                f"{r['max_dd']:>5.2f}% | "
                f"{r['pf']:>5.2f} | "
                f"{r['sl_hits']:>3} ({r['sl_pct']:.0f}%)"
                f"{marker}"
            )
        print()

    print("=" * 70)
