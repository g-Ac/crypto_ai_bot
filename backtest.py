import csv
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from config import (
    SYMBOLS, INTERVAL, INTERVAL_HTF,
    SMA_SHORT, SMA_LONG, BREAKOUT_WINDOW, VOLUME_WINDOW,
    RSI_OVERSOLD, RSI_OVERBOUGHT, RSI_BUY_ZONE, RSI_SELL_ZONE,
    SIGNAL_SCORE_MIN, PRE_SIGNAL_SCORE_MIN, PRE_SIGNAL_DIFF_MIN, OBSERVATION_SCORE_MIN,
    BODY_RATIO_MIN, BACKTEST_DAYS, STOP_LOSS_PCT, STOP_LOSS_MAP,
)
from indicators import add_indicators


def fetch_historical(symbol, interval, days):
    all_data = []
    start_ms = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
    end_ms = int(datetime.now().timestamp() * 1000)
    cursor = start_ms

    while cursor < end_ms:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={interval}&startTime={cursor}&limit=1000"
        )
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                print(f"  Erro HTTP {resp.status_code} para {symbol} {interval}")
                break
            data = resp.json()
            if not data:
                break
            all_data.extend(data)
            cursor = data[-1][0] + 1
            time.sleep(0.2)
        except Exception as e:
            print(f"  Erro: {e}")
            break

    df = pd.DataFrame(all_data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df


def compute_htf_trends(df_htf):
    s_col = f"sma_{SMA_SHORT}"
    l_col = f"sma_{SMA_LONG}"
    trends = []
    for _, row in df_htf.iterrows():
        if pd.isna(row[s_col]) or pd.isna(row[l_col]):
            trends.append("lateral")
        elif row[s_col] > row[l_col]:
            trends.append("alta")
        elif row[s_col] < row[l_col]:
            trends.append("baixa")
        else:
            trends.append("lateral")
    df_htf = df_htf.copy()
    df_htf["htf_trend"] = trends
    return df_htf


def get_htf_at(candle_time, df_htf):
    mask = df_htf["time"] <= candle_time
    if mask.any():
        return df_htf.loc[mask, "htf_trend"].iloc[-1]
    return "lateral"


def signal_for_row(row, htf_trend):
    s_col = f"sma_{SMA_SHORT}"
    l_col = f"sma_{SMA_LONG}"
    sp_col = f"sma_{SMA_SHORT}_prev"
    lp_col = f"sma_{SMA_LONG}_prev"
    rh_col = f"recent_high_{BREAKOUT_WINDOW}"
    rl_col = f"recent_low_{BREAKOUT_WINDOW}"

    price = row["close"]
    sma_s = row[s_col]
    sma_l = row[l_col]
    sma_sp = row[sp_col]
    sma_lp = row[lp_col]
    rsi = row["rsi"]
    r_high = row[rh_col]
    r_low = row[rl_col]
    vol = row["volume"]
    vol_avg = row["volume_avg"]
    body_r = row["body_ratio"]

    vals = [sma_s, sma_l, sma_sp, sma_lp, rsi, r_high, r_low, vol_avg]
    if any(pd.isna(v) for v in vals):
        return None

    vol_above = vol > vol_avg

    trend = "alta" if sma_s > sma_l else ("baixa" if sma_s < sma_l else "lateral")

    rsi_status = "sobrevendido" if rsi < RSI_OVERSOLD else (
        "sobrecomprado" if rsi > RSI_OVERBOUGHT else "neutro"
    )

    sma_s_dir = "subindo" if sma_s > sma_sp else ("caindo" if sma_s < sma_sp else "reta")
    sma_l_dir = "subindo" if sma_l > sma_lp else ("caindo" if sma_l < sma_lp else "reta")

    breakout = "rompeu maxima" if price > r_high else (
        "rompeu minima" if price < r_low else "dentro"
    )

    buy = 0
    sell = 0

    if trend == "alta":
        buy += 1
    elif trend == "baixa":
        sell += 1

    if price > sma_s and price > sma_l:
        buy += 1
    elif price < sma_s and price < sma_l:
        sell += 1

    if sma_s_dir == "subindo" and sma_l_dir == "subindo":
        buy += 1
    elif sma_s_dir == "caindo" and sma_l_dir == "caindo":
        sell += 1

    if RSI_BUY_ZONE[0] <= rsi <= RSI_BUY_ZONE[1]:
        buy += 1
    elif RSI_SELL_ZONE[0] <= rsi <= RSI_SELL_ZONE[1]:
        sell += 1

    if breakout == "rompeu maxima":
        buy += 1
    elif breakout == "rompeu minima":
        sell += 1

    if vol_above and breakout == "rompeu maxima":
        buy += 1
    elif vol_above and breakout == "rompeu minima":
        sell += 1

    if body_r >= BODY_RATIO_MIN:
        buy += 1
    elif body_r <= -BODY_RATIO_MIN:
        sell += 1

    decision = "HOLD"

    if buy >= SIGNAL_SCORE_MIN and buy > sell:
        if rsi_status != "sobrecomprado":
            decision = "BUY"
    elif sell >= SIGNAL_SCORE_MIN and sell > buy:
        if rsi_status != "sobrevendido":
            decision = "SELL"

    if htf_trend == "alta" and decision == "SELL":
        decision = "HOLD"
    elif htf_trend == "baixa" and decision == "BUY":
        decision = "HOLD"

    htf_aligned = (
        (decision == "BUY" and htf_trend == "alta")
        or (decision == "SELL" and htf_trend == "baixa")
        or htf_trend == "lateral"
    )

    return {
        "decision": decision,
        "price": price,
        "buy_score": buy,
        "sell_score": sell,
        "htf_aligned": htf_aligned,
    }


def run_backtest(symbol):
    sl = STOP_LOSS_MAP.get(symbol, STOP_LOSS_PCT)
    print(f"\n  Buscando {symbol} 5m... (SL: {sl}%)")
    df = fetch_historical(symbol, INTERVAL, BACKTEST_DAYS)
    print(f"  Buscando {symbol} 1h...")
    df_htf = fetch_historical(symbol, INTERVAL_HTF, BACKTEST_DAYS)

    df = add_indicators(df)
    df_htf = add_indicators(df_htf)
    df_htf = compute_htf_trends(df_htf)

    print(f"  {len(df)} candles 5m | {len(df_htf)} candles 1h")

    warmup = max(SMA_LONG, BREAKOUT_WINDOW, VOLUME_WINDOW, 14) + 5

    trades = []
    position = None
    entry_price = 0.0
    entry_time = None
    entry_htf = False
    signals = {"BUY": 0, "SELL": 0, "HOLD": 0}

    for i in range(warmup, len(df)):
        row = df.iloc[i]
        htf = get_htf_at(row["time"], df_htf)
        sig = signal_for_row(row, htf)
        if sig is None:
            continue

        signals[sig["decision"]] += 1
        price = sig["price"]
        low = row["low"]
        high = row["high"]

        # Check stop loss using candle extremes (more realistic)
        if position == "LONG":
            sl_price = entry_price * (1 - sl / 100)
            if low <= sl_price:
                trades.append({
                    "type": "LONG", "entry_time": entry_time,
                    "entry_price": entry_price, "exit_time": row["time"],
                    "exit_price": round(sl_price, 6),
                    "pnl_pct": -sl, "exit_reason": "stop_loss",
                    "htf_aligned": entry_htf,
                })
                position = None
                continue

        elif position == "SHORT":
            sl_price = entry_price * (1 + sl / 100)
            if high >= sl_price:
                trades.append({
                    "type": "SHORT", "entry_time": entry_time,
                    "entry_price": entry_price, "exit_time": row["time"],
                    "exit_price": round(sl_price, 6),
                    "pnl_pct": -sl, "exit_reason": "stop_loss",
                    "htf_aligned": entry_htf,
                })
                position = None
                continue

        # Entry / exit logic
        if sig["decision"] == "BUY":
            if position == "SHORT":
                pnl = ((entry_price - price) / entry_price) * 100
                trades.append({
                    "type": "SHORT", "entry_time": entry_time,
                    "entry_price": entry_price, "exit_time": row["time"],
                    "exit_price": price, "pnl_pct": pnl,
                    "exit_reason": "signal", "htf_aligned": entry_htf,
                })
                position = None
            if position is None:
                position = "LONG"
                entry_price = price
                entry_time = row["time"]
                entry_htf = sig["htf_aligned"]

        elif sig["decision"] == "SELL":
            if position == "LONG":
                pnl = ((price - entry_price) / entry_price) * 100
                trades.append({
                    "type": "LONG", "entry_time": entry_time,
                    "entry_price": entry_price, "exit_time": row["time"],
                    "exit_price": price, "pnl_pct": pnl,
                    "exit_reason": "signal", "htf_aligned": entry_htf,
                })
                position = None
            if position is None:
                position = "SHORT"
                entry_price = price
                entry_time = row["time"]
                entry_htf = sig["htf_aligned"]

    # Close open position at end
    if position is not None:
        last = df.iloc[-1]
        lp = last["close"]
        if position == "LONG":
            pnl = ((lp - entry_price) / entry_price) * 100
        else:
            pnl = ((entry_price - lp) / entry_price) * 100
        trades.append({
            "type": position, "entry_time": entry_time,
            "entry_price": entry_price, "exit_time": last["time"],
            "exit_price": lp, "pnl_pct": pnl,
            "exit_reason": "end_of_data", "htf_aligned": entry_htf,
        })

    return trades, signals


def calc_metrics(trades):
    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_return": 0, "avg_win": 0, "avg_loss": 0,
                "max_dd": 0, "profit_factor": 0, "best": 0, "worst": 0}

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    total_ret = sum(t["pnl_pct"] for t in trades)

    cum = peak = max_dd = 0.0
    for t in trades:
        cum += t["pnl_pct"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    gp = sum(t["pnl_pct"] for t in wins) if wins else 0
    gl = abs(sum(t["pnl_pct"] for t in losses)) if losses else 0

    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades)) * 100,
        "total_return": total_ret,
        "avg_win": gp / len(wins) if wins else 0,
        "avg_loss": -(gl / len(losses)) if losses else 0,
        "max_dd": max_dd,
        "profit_factor": gp / gl if gl > 0 else float("inf"),
        "best": max(t["pnl_pct"] for t in trades),
        "worst": min(t["pnl_pct"] for t in trades),
    }


def print_report(symbol, trades, signals, m):
    sl = STOP_LOSS_MAP.get(symbol, STOP_LOSS_PCT)
    print(f"\n{'='*60}")
    print(f"  BACKTEST: {symbol} | {BACKTEST_DAYS} dias | {INTERVAL} + HTF {INTERVAL_HTF}")
    print(f"  Stop Loss: {sl}%")
    print(f"{'='*60}")

    print(f"\n  Sinais: BUY={signals['BUY']} | SELL={signals['SELL']} | HOLD={signals['HOLD']}")
    print(f"\n  Trades: {m['total']} | Wins: {m['wins']} | Losses: {m['losses']}")
    print(f"  Win rate: {m['win_rate']:.1f}%")
    print(f"\n  Retorno total: {m['total_return']:+.2f}%")
    print(f"  Max drawdown: {m['max_dd']:.2f}%")
    print(f"  Profit factor: {m['profit_factor']:.2f}")
    print(f"\n  Media win: +{m['avg_win']:.2f}% | Media loss: {m['avg_loss']:.2f}%")
    print(f"  Melhor trade: +{m['best']:.2f}% | Pior trade: {m['worst']:.2f}%")

    # HTF analysis
    aligned = [t for t in trades if t["htf_aligned"]]
    not_aligned = [t for t in trades if not t["htf_aligned"]]

    if aligned:
        wr = len([t for t in aligned if t["pnl_pct"] > 0]) / len(aligned) * 100
        ret = sum(t["pnl_pct"] for t in aligned)
        print(f"\n  Alinhados c/ HTF: {len(aligned)} trades | WR: {wr:.1f}% | Ret: {ret:+.2f}%")
    if not_aligned:
        wr = len([t for t in not_aligned if t["pnl_pct"] > 0]) / len(not_aligned) * 100
        ret = sum(t["pnl_pct"] for t in not_aligned)
        print(f"  Contra HTF:       {len(not_aligned)} trades | WR: {wr:.1f}% | Ret: {ret:+.2f}%")

    # Stop loss stats
    sl = [t for t in trades if t["exit_reason"] == "stop_loss"]
    if sl:
        print(f"\n  Stop losses: {len(sl)} ({len(sl)/len(trades)*100:.0f}% dos trades)")

    # Trade log
    print(f"\n  {'-'*56}")
    print(f"  # | TIPO  | ENTRADA     | SAIDA       | P&L      | MOTIVO")
    print(f"  {'-'*56}")
    for i, t in enumerate(trades, 1):
        print(
            f"  {i:>2} | {t['type']:5s} | "
            f"{t['entry_price']:>11.4f} | "
            f"{t['exit_price']:>11.4f} | "
            f"{t['pnl_pct']:>+7.2f}% | "
            f"{t['exit_reason']}"
        )


def export_trades(symbol, trades):
    fname = f"backtest_{symbol}.csv"
    with open(fname, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#", "type", "entry_time", "entry_price",
                     "exit_time", "exit_price", "pnl_pct", "exit_reason", "htf_aligned"])
        for i, t in enumerate(trades, 1):
            w.writerow([
                i, t["type"], t["entry_time"], round(t["entry_price"], 6),
                t["exit_time"], round(t["exit_price"], 6),
                round(t["pnl_pct"], 4), t["exit_reason"], t["htf_aligned"]
            ])
    print(f"  Exportado: {fname}")


if __name__ == "__main__":
    print("=" * 60)
    print("  BACKTESTER - crypto_ai_bot")
    print(f"  {BACKTEST_DAYS} dias | {len(SYMBOLS)} ativos | SL: {STOP_LOSS_PCT}%")
    print("=" * 60)

    all_trades = []

    for symbol in SYMBOLS:
        trades, signals = run_backtest(symbol)
        m = calc_metrics(trades)
        print_report(symbol, trades, signals, m)
        export_trades(symbol, trades)
        all_trades.extend(trades)

    # Overall
    om = calc_metrics(all_trades)
    print(f"\n{'='*60}")
    print(f"  RESUMO GERAL | {len(SYMBOLS)} ativos | {BACKTEST_DAYS} dias")
    print(f"{'='*60}")
    print(f"  Total trades: {om['total']}")
    print(f"  Win rate: {om['win_rate']:.1f}%")
    print(f"  Retorno total: {om['total_return']:+.2f}%")
    print(f"  Max drawdown: {om['max_dd']:.2f}%")
    print(f"  Profit factor: {om['profit_factor']:.2f}")
    print(f"{'='*60}")
