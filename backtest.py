import csv
import time
import requests
import pandas as pd
import ta
from datetime import datetime, timedelta
from config import (
    SYMBOLS, INTERVAL, INTERVAL_HTF,
    SMA_SHORT, SMA_LONG, BREAKOUT_WINDOW, VOLUME_WINDOW,
    BACKTEST_DAYS, ATR_SL_MULTIPLIER, ATR_SL_FLOOR_PCT,
    ATR_TP_MULTIPLIER, PAPER_REWARD_RATIO,
)
from indicators import add_indicators
from strategy import _score_row
from htf import classify_htf_trend

# Binance Futures fee: 0.04% per side (maker) = 0.08% round trip
ROUND_TRIP_FEE_PCT = 0.08


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
    """Assign HTF trend to each candle using shared classification logic.

    A4 FIX: Uses classify_htf_trend() from htf.py as single source of truth
    for trend classification, eliminating divergence with production code.
    """
    s_col = f"sma_{SMA_SHORT}"
    l_col = f"sma_{SMA_LONG}"
    df_htf = df_htf.copy()
    df_htf["htf_trend"] = df_htf.apply(
        lambda row: classify_htf_trend(row[s_col], row[l_col]), axis=1
    )
    return df_htf


def add_atr_to_htf(df_htf, period=14):
    """Calculate ATR on HTF (1h) data — mirrors production get_atr_1h().

    A6 FIX: backtest now uses dynamic ATR-based SL per candle instead of
    a fixed ATR_SL_FLOOR_PCT for all trades. This matches production behavior
    in paper_trader.py and trade_agents.py.
    """
    atr_indicator = ta.volatility.AverageTrueRange(
        high=df_htf["high"], low=df_htf["low"], close=df_htf["close"],
        window=period,
    )
    df_htf = df_htf.copy()
    df_htf["atr"] = atr_indicator.average_true_range()
    return df_htf


def get_htf_at(candle_time, df_htf):
    mask = df_htf["time"] <= candle_time
    if mask.any():
        return df_htf.loc[mask, "htf_trend"].iloc[-1]
    return "lateral"


def get_atr_at(candle_time, df_htf):
    """Get the most recent HTF ATR value at a given candle time.

    Returns None if ATR is not yet available (warmup period).
    """
    mask = df_htf["time"] <= candle_time
    if mask.any():
        val = df_htf.loc[mask, "atr"].iloc[-1]
        if pd.notna(val):
            return val
    return None


def run_backtest(symbol):
    print(f"\n  Buscando {symbol} 5m... (SL: ATR-dynamic, floor={ATR_SL_FLOOR_PCT}%)")
    df = fetch_historical(symbol, INTERVAL, BACKTEST_DAYS)
    print(f"  Buscando {symbol} 1h...")
    df_htf = fetch_historical(symbol, INTERVAL_HTF, BACKTEST_DAYS)

    df = add_indicators(df)
    df_htf = add_indicators(df_htf)
    df_htf = compute_htf_trends(df_htf)
    df_htf = add_atr_to_htf(df_htf)  # A6 FIX: ATR for dynamic SL

    print(f"  {len(df)} candles 5m | {len(df_htf)} candles 1h")

    warmup = max(SMA_LONG, BREAKOUT_WINDOW, VOLUME_WINDOW, 14) + 5

    trades = []
    position = None
    entry_price = 0.0
    entry_time = None
    entry_htf = False
    entry_sl_pct = ATR_SL_FLOOR_PCT  # SL for current position (dynamic per trade)
    entry_tp_pct = ATR_SL_FLOOR_PCT * PAPER_REWARD_RATIO  # TP for current position
    signals = {"BUY": 0, "SELL": 0, "HOLD": 0}

    # C5 FIX: Signal generated on candle i-1 (closed), entry on open of candle i.
    # Loop starts at warmup+1 so that candle i-1 = warmup has valid indicators.
    for i in range(warmup + 1, len(df)):
        row = df.iloc[i]          # current candle (execution candle)
        prev_row = df.iloc[i - 1] # previous candle (signal candle, already closed)

        # --- Generate signal from the PREVIOUS (closed) candle ---
        # Uses _score_row from strategy.py (A4 FIX: single source of truth)
        htf = get_htf_at(prev_row["time"], df_htf)
        sig = _score_row(prev_row, htf)
        if sig is not None:
            signals[sig["decision"]] += 1

        # --- Use the OPEN of current candle as execution price ---
        exec_price = row["open"]
        low = row["low"]
        high = row["high"]

        # Check stop loss and take profit using candle extremes (more realistic)
        if position == "LONG":
            sl_price = entry_price * (1 - entry_sl_pct / 100)
            tp_price = entry_price * (1 + entry_tp_pct / 100)
            if low <= sl_price:
                raw_pnl = -entry_sl_pct
                trades.append({
                    "type": "LONG", "entry_time": entry_time,
                    "entry_price": entry_price, "exit_time": row["time"],
                    "exit_price": round(sl_price, 6),
                    "pnl_pct": round(raw_pnl - ROUND_TRIP_FEE_PCT, 6),
                    "exit_reason": "stop_loss",
                    "htf_aligned": entry_htf,
                    "sl_pct": round(entry_sl_pct, 4),
                })
                position = None
                continue
            if high >= tp_price:
                raw_pnl = entry_tp_pct
                trades.append({
                    "type": "LONG", "entry_time": entry_time,
                    "entry_price": entry_price, "exit_time": row["time"],
                    "exit_price": round(tp_price, 6),
                    "pnl_pct": round(raw_pnl - ROUND_TRIP_FEE_PCT, 6),
                    "exit_reason": "take_profit",
                    "htf_aligned": entry_htf,
                    "sl_pct": round(entry_sl_pct, 4),
                })
                position = None
                continue

        elif position == "SHORT":
            sl_price = entry_price * (1 + entry_sl_pct / 100)
            tp_price = entry_price * (1 - entry_tp_pct / 100)
            if high >= sl_price:
                raw_pnl = -entry_sl_pct
                trades.append({
                    "type": "SHORT", "entry_time": entry_time,
                    "entry_price": entry_price, "exit_time": row["time"],
                    "exit_price": round(sl_price, 6),
                    "pnl_pct": round(raw_pnl - ROUND_TRIP_FEE_PCT, 6),
                    "exit_reason": "stop_loss",
                    "htf_aligned": entry_htf,
                    "sl_pct": round(entry_sl_pct, 4),
                })
                position = None
                continue
            if low <= tp_price:
                raw_pnl = entry_tp_pct
                trades.append({
                    "type": "SHORT", "entry_time": entry_time,
                    "entry_price": entry_price, "exit_time": row["time"],
                    "exit_price": round(tp_price, 6),
                    "pnl_pct": round(raw_pnl - ROUND_TRIP_FEE_PCT, 6),
                    "exit_reason": "take_profit",
                    "htf_aligned": entry_htf,
                    "sl_pct": round(entry_sl_pct, 4),
                })
                position = None
                continue

        if sig is None:
            continue

        # Entry / exit logic - executes at open of current candle
        if sig["decision"] == "BUY":
            if position == "SHORT":
                raw_pnl = ((entry_price - exec_price) / entry_price) * 100
                trades.append({
                    "type": "SHORT", "entry_time": entry_time,
                    "entry_price": entry_price, "exit_time": row["time"],
                    "exit_price": exec_price,
                    "pnl_pct": round(raw_pnl - ROUND_TRIP_FEE_PCT, 6),
                    "exit_reason": "signal", "htf_aligned": entry_htf,
                    "sl_pct": round(entry_sl_pct, 4),
                })
                position = None
            if position is None:
                position = "LONG"
                entry_price = exec_price
                entry_time = row["time"]
                entry_htf = sig["htf_aligned"]
                # A6 FIX: Dynamic ATR-based SL/TP — mirrors paper_trader.py logic
                atr = get_atr_at(prev_row["time"], df_htf)
                if atr and entry_price > 0:
                    entry_sl_pct = max(
                        (atr * ATR_SL_MULTIPLIER / entry_price) * 100,
                        ATR_SL_FLOOR_PCT,
                    )
                    entry_tp_pct = (atr * ATR_TP_MULTIPLIER / entry_price) * 100
                else:
                    entry_sl_pct = ATR_SL_FLOOR_PCT
                    entry_tp_pct = entry_sl_pct * PAPER_REWARD_RATIO

        elif sig["decision"] == "SELL":
            if position == "LONG":
                raw_pnl = ((exec_price - entry_price) / entry_price) * 100
                trades.append({
                    "type": "LONG", "entry_time": entry_time,
                    "entry_price": entry_price, "exit_time": row["time"],
                    "exit_price": exec_price,
                    "pnl_pct": round(raw_pnl - ROUND_TRIP_FEE_PCT, 6),
                    "exit_reason": "signal", "htf_aligned": entry_htf,
                    "sl_pct": round(entry_sl_pct, 4),
                })
                position = None
            if position is None:
                position = "SHORT"
                entry_price = exec_price
                entry_time = row["time"]
                entry_htf = sig["htf_aligned"]
                # A6 FIX: Dynamic ATR-based SL/TP — mirrors paper_trader.py logic
                atr = get_atr_at(prev_row["time"], df_htf)
                if atr and entry_price > 0:
                    entry_sl_pct = max(
                        (atr * ATR_SL_MULTIPLIER / entry_price) * 100,
                        ATR_SL_FLOOR_PCT,
                    )
                    entry_tp_pct = (atr * ATR_TP_MULTIPLIER / entry_price) * 100
                else:
                    entry_sl_pct = ATR_SL_FLOOR_PCT
                    entry_tp_pct = entry_sl_pct * PAPER_REWARD_RATIO

    # Close open position at end
    if position is not None:
        last = df.iloc[-1]
        lp = last["close"]
        if position == "LONG":
            raw_pnl = ((lp - entry_price) / entry_price) * 100
        else:
            raw_pnl = ((entry_price - lp) / entry_price) * 100
        trades.append({
            "type": position, "entry_time": entry_time,
            "entry_price": entry_price, "exit_time": last["time"],
            "exit_price": lp,
            "pnl_pct": round(raw_pnl - ROUND_TRIP_FEE_PCT, 6),
            "exit_reason": "end_of_data", "htf_aligned": entry_htf,
            "sl_pct": round(entry_sl_pct, 4),
        })

    return trades, signals


def calc_metrics(trades, initial_capital=10000):
    """Calcula metricas do backtest usando retorno composto e equity curve real.

    M12 FIX: Antes usava soma aritmetica de pnl_pct, o que subestimava perdas
    e superestimava ganhos em series longas. Agora simula capital real.

    Args:
        trades: lista de dicts com pelo menos 'pnl_pct'
        initial_capital: capital inicial simulado (default 10000 USD)
    """
    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_return": 0, "avg_win": 0, "avg_loss": 0,
                "max_dd": 0, "profit_factor": 0, "best": 0, "worst": 0,
                "final_capital": initial_capital}

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]

    # --- Retorno composto via equity curve ---
    capital = float(initial_capital)
    peak = capital
    max_dd_pct = 0.0

    for t in trades:
        capital *= (1 + t["pnl_pct"] / 100)
        if capital > peak:
            peak = capital
        if peak > 0:
            dd_pct = ((peak - capital) / peak) * 100
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

    total_return_pct = ((capital - initial_capital) / initial_capital) * 100

    # --- Profit factor em USD (soma de ganhos / soma de perdas) ---
    gains_usd = sum(
        initial_capital * (t["pnl_pct"] / 100) for t in wins
    ) if wins else 0.0
    losses_usd = abs(sum(
        initial_capital * (t["pnl_pct"] / 100) for t in losses
    )) if losses else 0.0

    # --- Medias por trade (mantidas em % para compatibilidade) ---
    avg_win = (sum(t["pnl_pct"] for t in wins) / len(wins)) if wins else 0
    avg_loss = -(abs(sum(t["pnl_pct"] for t in losses)) / len(losses)) if losses else 0

    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades)) * 100,
        "total_return": round(total_return_pct, 4),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_dd": round(max_dd_pct, 4),
        "profit_factor": round(gains_usd / losses_usd, 4) if losses_usd > 0 else float("inf"),
        "best": max(t["pnl_pct"] for t in trades),
        "worst": min(t["pnl_pct"] for t in trades),
        "final_capital": round(capital, 2),
    }


def print_report(symbol, trades, signals, m):
    # A6 FIX: Show dynamic SL stats instead of fixed value
    sl_values = [t.get("sl_pct", ATR_SL_FLOOR_PCT) for t in trades] if trades else [ATR_SL_FLOOR_PCT]
    avg_sl = sum(sl_values) / len(sl_values)
    min_sl = min(sl_values)
    max_sl = max(sl_values)
    print(f"\n{'='*60}")
    print(f"  BACKTEST: {symbol} | {BACKTEST_DAYS} dias | {INTERVAL} + HTF {INTERVAL_HTF}")
    print(f"  Stop Loss: ATR-dynamic (avg={avg_sl:.2f}% | min={min_sl:.2f}% | max={max_sl:.2f}% | floor={ATR_SL_FLOOR_PCT}%)")
    print(f"{'='*60}")

    print(f"\n  Sinais: BUY={signals['BUY']} | SELL={signals['SELL']} | HOLD={signals['HOLD']}")
    print(f"\n  Trades: {m['total']} | Wins: {m['wins']} | Losses: {m['losses']}")
    print(f"  Win rate: {m['win_rate']:.1f}%")
    print(f"\n  Retorno total (composto): {m['total_return']:+.2f}%")
    print(f"  Capital final: ${m.get('final_capital', 'N/A'):,.2f}")
    print(f"  Max drawdown (do pico): {m['max_dd']:.2f}%")
    print(f"  Profit factor (USD): {m['profit_factor']:.2f}")
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

    # Stop loss / take profit stats
    sl = [t for t in trades if t["exit_reason"] == "stop_loss"]
    tp = [t for t in trades if t["exit_reason"] == "take_profit"]
    if sl:
        print(f"\n  Stop losses:  {len(sl)} ({len(sl)/len(trades)*100:.0f}% dos trades)")
    if tp:
        print(f"  Take profits: {len(tp)} ({len(tp)/len(trades)*100:.0f}% dos trades)")

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
                     "exit_time", "exit_price", "pnl_pct", "exit_reason",
                     "htf_aligned", "sl_pct"])
        for i, t in enumerate(trades, 1):
            w.writerow([
                i, t["type"], t["entry_time"], round(t["entry_price"], 6),
                t["exit_time"], round(t["exit_price"], 6),
                round(t["pnl_pct"], 4), t["exit_reason"], t["htf_aligned"],
                t.get("sl_pct", ATR_SL_FLOOR_PCT),
            ])
    print(f"  Exportado: {fname}")


if __name__ == "__main__":
    print("=" * 60)
    print("  BACKTESTER - crypto_ai_bot")
    print(f"  {BACKTEST_DAYS} dias | {len(SYMBOLS)} ativos | SL: ATR-dynamic (floor={ATR_SL_FLOOR_PCT}%)")
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
    print(f"  Retorno total (composto): {om['total_return']:+.2f}%")
    print(f"  Capital final: ${om.get('final_capital', 'N/A'):,.2f}")
    print(f"  Max drawdown (do pico): {om['max_dd']:.2f}%")
    print(f"  Profit factor (USD): {om['profit_factor']:.2f}")
    print(f"{'='*60}")
