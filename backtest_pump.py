"""
Backtest para Pump Scanner — verifica se a deteccao de pumps
e o trailing-stop geram edge real com dados historicos.

Uso: python backtest_pump.py

Logica:
  1. Baixa dados 5m de Binance Futures (fapi) para top coins
  2. Simula deteccao de pump (volume_ratio + price_change)
  3. Entra LONG/SHORT no open do candle seguinte (sem look-ahead)
  4. Gerencia com trailing stop e timeout, candle a candle
  5. Aplica fees de 0.08% round trip (Futures taker)
  6. Reporta metricas de robustez, segmentadas por simbolo/hora/direcao
"""

import json
import time
import sys
import requests
import pandas as pd
from datetime import datetime, timedelta
from config import (
    SYMBOLS,
    BACKTEST_DAYS,
    PUMP_VOLUME_MULTIPLIER,
    PUMP_PRICE_CHANGE_MIN,
    PUMP_TRAILING_STOP,
    PUMP_MAX_POSITION_TIME,
    PUMP_MAX_POSITIONS,
    PUMP_CAPITAL,
    PUMP_POSITION_SIZE_PCT,
)

# ── Config do backtest ──────────────────────────────────────────
ROUND_TRIP_FEE_PCT = 0.08          # Futures taker: 0.04% * 2
COOLDOWN_CANDLES = 6               # 30min / 5min = 6 candles de cooldown
VOLUME_AVG_WINDOW = 20             # janela para media de volume
PRICE_CHANGE_LOOKBACK = 3          # candles para price change sustentado

# Simbolos extras alem do config.SYMBOLS
EXTRA_SYMBOLS = ["AVAXUSDT", "ADAUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT"]

# Mescla sem duplicatas
BACKTEST_SYMBOLS = list(dict.fromkeys(SYMBOLS + EXTRA_SYMBOLS))

# Binance Futures klines endpoint
FUTURES_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"


# ── Coleta de dados ─────────────────────────────────────────────

def fetch_futures_klines(symbol, interval="5m", days=BACKTEST_DAYS):
    """Baixa klines de Binance Futures com paginacao."""
    all_data = []
    start_ms = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    end_ms = int(datetime.utcnow().timestamp() * 1000)
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "limit": 1500,
        }
        for attempt in range(3):
            try:
                resp = requests.get(FUTURES_KLINES_URL, params=params, timeout=15)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 5))
                    print(f"    Rate limit 429, aguardando {wait}s...")
                    time.sleep(min(wait, 30))
                    continue
                if resp.status_code != 200:
                    print(f"    HTTP {resp.status_code} para {symbol}")
                    return pd.DataFrame()
                data = resp.json()
                break
            except Exception as e:
                print(f"    Tentativa {attempt+1} falhou: {e}")
                time.sleep(2 ** attempt)
        else:
            break

        if not data:
            break
        all_data.extend(data)
        cursor = data[-1][0] + 1
        time.sleep(0.15)

    if not all_data:
        return pd.DataFrame()

    df = pd.DataFrame(all_data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbbav", "tbqav", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    df.drop_duplicates(subset=["time"], inplace=True)
    df.sort_values("time", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ── Deteccao de pump (mesma logica do pump_scanner.py) ──────────

def detect_pumps(df):
    """
    Para cada candle, calcula volume_ratio e price_change.
    Marca candle como pump/dump se criteria atingidos.
    Retorna DataFrame com colunas extras: vol_ratio, pc1, pc3, signal, direction.

    IMPORTANTE: o sinal e gerado com dados do candle FECHADO (iloc[i]).
    A entrada acontecera no open do candle i+1 (tratado no simulador).
    """
    n = len(df)
    vol_ratios = [0.0] * n
    pc1s = [0.0] * n
    pc3s = [0.0] * n
    signals = [False] * n
    directions = [""] * n

    for i in range(VOLUME_AVG_WINDOW + PRICE_CHANGE_LOOKBACK, n):
        # Volume ratio: candle atual vs media das 20 anteriores
        avg_vol = df["volume"].iloc[i - VOLUME_AVG_WINDOW:i].mean()
        if avg_vol <= 0:
            continue
        current_vol = df["volume"].iloc[i]
        vol_ratio = current_vol / avg_vol

        # Price change single candle
        o = df["open"].iloc[i]
        c = df["close"].iloc[i]
        if o <= 0:
            continue
        pc1 = ((c - o) / o) * 100

        # Price change 3 candles (sustentado)
        o3 = df["open"].iloc[i - PRICE_CHANGE_LOOKBACK + 1]
        if o3 <= 0:
            continue
        pc3 = ((c - o3) / o3) * 100

        vol_ratios[i] = round(vol_ratio, 4)
        pc1s[i] = round(pc1, 4)
        pc3s[i] = round(pc3, 4)

        # Criterio dual (identico ao pump_scanner.py linhas 177-183)
        is_pump = (
            (vol_ratio >= PUMP_VOLUME_MULTIPLIER and abs(pc1) >= PUMP_PRICE_CHANGE_MIN)
            or (vol_ratio >= PUMP_VOLUME_MULTIPLIER * 0.6 and abs(pc3) >= PUMP_PRICE_CHANGE_MIN * 2)
        )

        if is_pump:
            signals[i] = True
            directions[i] = "LONG" if (pc1 > 0 or pc3 > 0) else "SHORT"

    df = df.copy()
    df["vol_ratio"] = vol_ratios
    df["pc1"] = pc1s
    df["pc3"] = pc3s
    df["signal"] = signals
    df["direction"] = directions
    return df


# ── Simulador de posicoes ───────────────────────────────────────

class Position:
    __slots__ = [
        "symbol", "direction", "entry_price", "entry_idx", "entry_time",
        "peak", "trough", "allocation", "volume_ratio",
    ]

    def __init__(self, symbol, direction, entry_price, entry_idx, entry_time,
                 allocation, volume_ratio):
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.entry_idx = entry_idx
        self.entry_time = entry_time
        self.peak = entry_price
        self.trough = entry_price
        self.allocation = allocation
        self.volume_ratio = volume_ratio


def simulate_trades(symbol, df):
    """
    Simula trades para um simbolo.
    - Sinal no candle i (signal==True), entrada no open do candle i+1
    - Trailing stop e timeout candle a candle
    - Cooldown de 6 candles (30min) entre trades no mesmo ativo
    - Retorna lista de trades completados
    """
    trades = []
    positions = {}          # symbol -> Position (aqui so 1 por simbolo)
    cooldown_until = 0      # indice ate o qual o cooldown esta ativo
    capital = PUMP_CAPITAL
    n = len(df)

    for i in range(1, n):
        prev = i - 1  # candle onde o sinal foi gerado

        # ── Gerenciar posicoes abertas ──
        to_close = []
        for sym, pos in list(positions.items()):
            candle_high = df["high"].iloc[i]
            candle_low = df["low"].iloc[i]
            candle_time = df["time"].iloc[i]
            duration_min = (candle_time - pos.entry_time).total_seconds() / 60

            # Atualizar peak/trough com extremos do candle
            if pos.direction == "LONG":
                if candle_high > pos.peak:
                    pos.peak = candle_high
                drop_from_peak = ((pos.peak - candle_low) / pos.peak) * 100
                trailing_hit = drop_from_peak >= PUMP_TRAILING_STOP
                # PnL no pior caso: se trailing hit, saida e no preco do trailing
                if trailing_hit:
                    exit_price = pos.peak * (1 - PUMP_TRAILING_STOP / 100)
                    # Garante que exit_price esta dentro do range do candle
                    exit_price = max(exit_price, candle_low)
                else:
                    exit_price = df["close"].iloc[i]
            else:  # SHORT
                if candle_low < pos.trough:
                    pos.trough = candle_low
                rise_from_trough = ((candle_high - pos.trough) / pos.trough) * 100
                trailing_hit = rise_from_trough >= PUMP_TRAILING_STOP
                if trailing_hit:
                    exit_price = pos.trough * (1 + PUMP_TRAILING_STOP / 100)
                    exit_price = min(exit_price, candle_high)
                else:
                    exit_price = df["close"].iloc[i]

            timeout_hit = duration_min >= PUMP_MAX_POSITION_TIME

            if trailing_hit or timeout_hit:
                if pos.direction == "LONG":
                    pnl_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100
                else:
                    pnl_pct = ((pos.entry_price - exit_price) / pos.entry_price) * 100

                pnl_pct -= ROUND_TRIP_FEE_PCT  # fees
                pnl_usd = pos.allocation * (pnl_pct / 100)
                capital += pnl_usd

                trades.append({
                    "symbol": symbol,
                    "direction": pos.direction,
                    "entry_price": pos.entry_price,
                    "exit_price": round(exit_price, 8),
                    "entry_time": str(pos.entry_time),
                    "exit_time": str(candle_time),
                    "entry_idx": pos.entry_idx,
                    "exit_idx": i,
                    "pnl_pct": round(pnl_pct, 4),
                    "pnl_usd": round(pnl_usd, 4),
                    "exit_reason": "trailing_stop" if trailing_hit else "timeout",
                    "duration_min": round(duration_min, 1),
                    "peak": round(pos.peak, 8),
                    "trough": round(pos.trough, 8),
                    "volume_ratio": pos.volume_ratio,
                    "entry_hour": pos.entry_time.hour,
                    "capital_after": round(capital, 2),
                })
                to_close.append(sym)
                cooldown_until = i + COOLDOWN_CANDLES

        for sym in to_close:
            del positions[sym]

        # ── Verificar novo sinal ──
        if (
            df["signal"].iloc[prev]
            and symbol not in positions
            and len(positions) < PUMP_MAX_POSITIONS
            and i > cooldown_until
        ):
            entry_price = df["open"].iloc[i]  # entrada no open do candle seguinte
            allocation = capital * (PUMP_POSITION_SIZE_PCT / 100)
            if allocation <= 0 or capital <= 0:
                continue

            direction = df["direction"].iloc[prev]
            positions[symbol] = Position(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                entry_idx=i,
                entry_time=df["time"].iloc[i],
                allocation=allocation,
                volume_ratio=df["vol_ratio"].iloc[prev],
            )

    # Fechar posicoes abertas no final dos dados
    for sym, pos in positions.items():
        last_close = df["close"].iloc[-1]
        last_time = df["time"].iloc[-1]
        duration_min = (last_time - pos.entry_time).total_seconds() / 60

        if pos.direction == "LONG":
            pnl_pct = ((last_close - pos.entry_price) / pos.entry_price) * 100
        else:
            pnl_pct = ((pos.entry_price - last_close) / pos.entry_price) * 100
        pnl_pct -= ROUND_TRIP_FEE_PCT

        pnl_usd = pos.allocation * (pnl_pct / 100)
        capital += pnl_usd

        trades.append({
            "symbol": symbol,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": round(last_close, 8),
            "entry_time": str(pos.entry_time),
            "exit_time": str(last_time),
            "entry_idx": pos.entry_idx,
            "exit_idx": len(df) - 1,
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usd": round(pnl_usd, 4),
            "exit_reason": "end_of_data",
            "duration_min": round(duration_min, 1),
            "peak": round(pos.peak, 8),
            "trough": round(pos.trough, 8),
            "volume_ratio": pos.volume_ratio,
            "entry_hour": pos.entry_time.hour,
            "capital_after": round(capital, 2),
        })

    return trades, capital


# ── Metricas ────────────────────────────────────────────────────

def calc_metrics(trades):
    """Calcula metricas padrao de performance."""
    if not trades:
        return {
            "total": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "total_return_pct": 0, "total_return_usd": 0,
            "avg_pnl": 0, "avg_win": 0, "avg_loss": 0,
            "profit_factor": 0, "max_dd_pct": 0,
            "avg_duration_min": 0, "best": 0, "worst": 0,
            "by_exit_reason": {},
        }

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]

    total_usd = sum(t["pnl_usd"] for t in trades)
    gross_profit = sum(t["pnl_usd"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl_usd"] for t in losses)) if losses else 0

    # Max drawdown sobre equity curve (USD)
    equity = PUMP_CAPITAL
    peak_equity = equity
    max_dd_usd = 0
    for t in sorted(trades, key=lambda x: x["entry_time"]):
        equity += t["pnl_usd"]
        if equity > peak_equity:
            peak_equity = equity
        dd = peak_equity - equity
        if dd > max_dd_usd:
            max_dd_usd = dd
    max_dd_pct = (max_dd_usd / PUMP_CAPITAL) * 100 if PUMP_CAPITAL > 0 else 0

    # Por motivo de saida
    reasons = {}
    for t in trades:
        r = t["exit_reason"]
        if r not in reasons:
            reasons[r] = {"count": 0, "pnl_sum": 0, "wins": 0}
        reasons[r]["count"] += 1
        reasons[r]["pnl_sum"] += t["pnl_pct"]
        if t["pnl_pct"] > 0:
            reasons[r]["wins"] += 1

    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round((len(wins) / len(trades)) * 100, 2),
        "total_return_pct": round(sum(t["pnl_pct"] for t in trades), 4),
        "total_return_usd": round(total_usd, 2),
        "avg_pnl": round(sum(t["pnl_pct"] for t in trades) / len(trades), 4),
        "avg_win": round(sum(t["pnl_pct"] for t in wins) / len(wins), 4) if wins else 0,
        "avg_loss": round(sum(t["pnl_pct"] for t in losses) / len(losses), 4) if losses else 0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else float("inf"),
        "max_dd_pct": round(max_dd_pct, 4),
        "avg_duration_min": round(sum(t["duration_min"] for t in trades) / len(trades), 1),
        "best": round(max(t["pnl_pct"] for t in trades), 4),
        "worst": round(min(t["pnl_pct"] for t in trades), 4),
        "by_exit_reason": reasons,
    }


def calc_segmented(trades, key):
    """Agrupa trades por uma chave e calcula metricas por grupo."""
    groups = {}
    for t in trades:
        k = t.get(key, "unknown")
        if k not in groups:
            groups[k] = []
        groups[k].append(t)

    result = {}
    for k, group_trades in sorted(groups.items()):
        m = calc_metrics(group_trades)
        result[k] = {
            "trades": m["total"],
            "win_rate": m["win_rate"],
            "avg_pnl": m["avg_pnl"],
            "total_return_pct": m["total_return_pct"],
            "profit_factor": m["profit_factor"],
        }
    return result


def calc_monthly(trades):
    """Agrupa trades por mes para ver estabilidade temporal."""
    groups = {}
    for t in trades:
        # entry_time e string, extrair YYYY-MM
        month = t["entry_time"][:7]
        if month not in groups:
            groups[month] = []
        groups[month].append(t)

    result = {}
    for month, group_trades in sorted(groups.items()):
        m = calc_metrics(group_trades)
        result[month] = {
            "trades": m["total"],
            "win_rate": m["win_rate"],
            "avg_pnl": m["avg_pnl"],
            "total_return_pct": m["total_return_pct"],
            "profit_factor": m["profit_factor"],
            "max_dd_pct": m["max_dd_pct"],
        }
    return result


# ── Report ──────────────────────────────────────────────────────

def print_report(all_trades, metrics, by_symbol, by_hour, by_direction, by_month):
    """Imprime relatorio formatado no terminal."""
    w = 70
    print(f"\n{'='*w}")
    print(f"  BACKTEST PUMP SCANNER")
    print(f"  {BACKTEST_DAYS} dias | {len(BACKTEST_SYMBOLS)} ativos | Fees: {ROUND_TRIP_FEE_PCT}%")
    print(f"  Vol >= {PUMP_VOLUME_MULTIPLIER}x | Price >= {PUMP_PRICE_CHANGE_MIN}%")
    print(f"  Trailing stop: {PUMP_TRAILING_STOP}% | Timeout: {PUMP_MAX_POSITION_TIME}min")
    print(f"  Capital inicial: ${PUMP_CAPITAL:.2f}")
    print(f"{'='*w}")

    m = metrics
    print(f"\n  RESULTADO GERAL")
    print(f"  {'-'*50}")
    print(f"  Trades:          {m['total']}")
    print(f"  Wins / Losses:   {m['wins']} / {m['losses']}")
    print(f"  Win rate:        {m['win_rate']:.1f}%")
    print(f"  Retorno total:   {m['total_return_pct']:+.2f}% (${m['total_return_usd']:+.2f})")
    print(f"  P&L medio:       {m['avg_pnl']:+.4f}%")
    print(f"  Media win:       {m['avg_win']:+.4f}%")
    print(f"  Media loss:      {m['avg_loss']:.4f}%")
    print(f"  Profit factor:   {m['profit_factor']:.2f}")
    print(f"  Max drawdown:    {m['max_dd_pct']:.2f}%")
    print(f"  Duracao media:   {m['avg_duration_min']:.1f} min")
    print(f"  Melhor trade:    {m['best']:+.4f}%")
    print(f"  Pior trade:      {m['worst']:.4f}%")

    # Por motivo de saida
    if m["by_exit_reason"]:
        print(f"\n  POR MOTIVO DE SAIDA")
        print(f"  {'-'*50}")
        for reason, stats in m["by_exit_reason"].items():
            wr = (stats["wins"] / stats["count"]) * 100 if stats["count"] > 0 else 0
            avg = stats["pnl_sum"] / stats["count"] if stats["count"] > 0 else 0
            print(f"  {reason:20s}: {stats['count']:4d} trades | WR: {wr:5.1f}% | Avg: {avg:+.3f}%")

    # Por simbolo
    print(f"\n  POR SIMBOLO")
    print(f"  {'-'*50}")
    print(f"  {'Simbolo':12s} {'Trades':>7s} {'WR':>7s} {'AvgPnL':>9s} {'TotRet':>9s} {'PF':>7s}")
    for sym, s in by_symbol.items():
        if s["trades"] > 0:
            print(f"  {sym:12s} {s['trades']:7d} {s['win_rate']:6.1f}% {s['avg_pnl']:+8.3f}% {s['total_return_pct']:+8.2f}% {s['profit_factor']:6.2f}")

    # Por direcao
    print(f"\n  POR DIRECAO")
    print(f"  {'-'*50}")
    for d, s in by_direction.items():
        if s["trades"] > 0:
            print(f"  {d:12s} {s['trades']:7d} trades | WR: {s['win_rate']:5.1f}% | Avg: {s['avg_pnl']:+.3f}% | PF: {s['profit_factor']:.2f}")

    # Por hora do dia
    print(f"\n  POR HORA DO DIA (UTC)")
    print(f"  {'-'*50}")
    print(f"  {'Hora':>6s} {'Trades':>7s} {'WR':>7s} {'AvgPnL':>9s} {'TotRet':>9s}")
    for h, s in by_hour.items():
        if s["trades"] > 0:
            print(f"  {h:>4s}:00 {s['trades']:7d} {s['win_rate']:6.1f}% {s['avg_pnl']:+8.3f}% {s['total_return_pct']:+8.2f}%")

    # Por mes
    print(f"\n  POR MES (estabilidade temporal)")
    print(f"  {'-'*50}")
    print(f"  {'Mes':10s} {'Trades':>7s} {'WR':>7s} {'AvgPnL':>9s} {'TotRet':>9s} {'MaxDD':>8s} {'PF':>7s}")
    for month, s in by_month.items():
        print(
            f"  {month:10s} {s['trades']:7d} {s['win_rate']:6.1f}% "
            f"{s['avg_pnl']:+8.3f}% {s['total_return_pct']:+8.2f}% "
            f"{s['max_dd_pct']:7.2f}% {s['profit_factor']:6.2f}"
        )

    # Alertas de robustez
    print(f"\n  ALERTAS DE ROBUSTEZ")
    print(f"  {'-'*50}")
    alerts = []
    if m["total"] < 30:
        alerts.append("[CRITICO] Amostra < 30 trades — resultado estatisticamente insignificante")
    elif m["total"] < 100:
        alerts.append("[AVISO] Amostra < 100 trades — confianca moderada apenas")
    if m["max_dd_pct"] > 20:
        alerts.append(f"[CRITICO] Max drawdown de {m['max_dd_pct']:.1f}% — risco excessivo")
    if m["profit_factor"] < 1.0:
        alerts.append("[CRITICO] Profit factor < 1.0 — estrategia perde dinheiro")
    elif m["profit_factor"] < 1.3:
        alerts.append("[AVISO] Profit factor < 1.3 — edge muito fino, fragil apos slippage real")

    # Verificar concentracao em poucos simbolos
    if by_symbol:
        active_symbols = [s for s, v in by_symbol.items() if v["trades"] > 0]
        if len(active_symbols) <= 2 and m["total"] > 10:
            alerts.append(f"[AVISO] Trades concentrados em {len(active_symbols)} ativos — risco de overfitting")

    # Verificar consistencia mensal
    if by_month:
        month_rets = [v["total_return_pct"] for v in by_month.values() if v["trades"] > 0]
        if month_rets:
            positive_months = sum(1 for r in month_rets if r > 0)
            total_months = len(month_rets)
            if total_months >= 2 and positive_months / total_months < 0.5:
                alerts.append(f"[AVISO] Apenas {positive_months}/{total_months} meses lucrativos — instabilidade temporal")

    # Verificar se timeout domina
    if m["by_exit_reason"]:
        timeout_info = m["by_exit_reason"].get("timeout", {})
        total_timeout = timeout_info.get("count", 0)
        if m["total"] > 0 and total_timeout / m["total"] > 0.5:
            alerts.append(f"[AVISO] {total_timeout}/{m['total']} trades por timeout — trailing stop pode ser apertado demais ou pump nao se sustenta")

    if not alerts:
        alerts.append("[OK] Nenhum alerta critico detectado")
    for a in alerts:
        print(f"  {a}")

    print(f"\n{'='*w}")


# ── Exportar JSON ───────────────────────────────────────────────

def export_results(all_trades, metrics, by_symbol, by_hour, by_direction, by_month):
    """Salva resultados em JSON para analise posterior."""
    output = {
        "config": {
            "backtest_days": BACKTEST_DAYS,
            "symbols": BACKTEST_SYMBOLS,
            "pump_volume_multiplier": PUMP_VOLUME_MULTIPLIER,
            "pump_price_change_min": PUMP_PRICE_CHANGE_MIN,
            "pump_trailing_stop": PUMP_TRAILING_STOP,
            "pump_max_position_time": PUMP_MAX_POSITION_TIME,
            "pump_max_positions": PUMP_MAX_POSITIONS,
            "pump_capital": PUMP_CAPITAL,
            "pump_position_size_pct": PUMP_POSITION_SIZE_PCT,
            "round_trip_fee_pct": ROUND_TRIP_FEE_PCT,
            "cooldown_candles": COOLDOWN_CANDLES,
            "generated_at": datetime.utcnow().isoformat(),
        },
        "metrics": metrics,
        "by_symbol": by_symbol,
        "by_hour": {str(k): v for k, v in by_hour.items()},
        "by_direction": by_direction,
        "by_month": by_month,
        "trades": all_trades,
    }

    fname = "backtest_pump_results.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Resultados salvos em: {fname}")
    return fname


# ── Main ────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  BACKTEST PUMP SCANNER")
    print(f"  {BACKTEST_DAYS} dias | {len(BACKTEST_SYMBOLS)} ativos")
    print(f"  Parametros: Vol >= {PUMP_VOLUME_MULTIPLIER}x | Price >= {PUMP_PRICE_CHANGE_MIN}%")
    print(f"  Trailing: {PUMP_TRAILING_STOP}% | Timeout: {PUMP_MAX_POSITION_TIME}min")
    print(f"  Fees: {ROUND_TRIP_FEE_PCT}% round trip | Capital: ${PUMP_CAPITAL:.2f}")
    print("=" * 70)

    all_trades = []
    symbols_ok = 0
    symbols_fail = 0

    for idx, symbol in enumerate(BACKTEST_SYMBOLS, 1):
        print(f"\n  [{idx}/{len(BACKTEST_SYMBOLS)}] Baixando {symbol}...")
        df = fetch_futures_klines(symbol, "5m", BACKTEST_DAYS)

        if df.empty or len(df) < VOLUME_AVG_WINDOW + PRICE_CHANGE_LOOKBACK + 10:
            print(f"    Dados insuficientes para {symbol} ({len(df) if not df.empty else 0} candles), pulando.")
            symbols_fail += 1
            continue

        print(f"    {len(df)} candles carregados ({df['time'].iloc[0]} a {df['time'].iloc[-1]})")

        # Detectar pumps
        df = detect_pumps(df)
        pump_count = df["signal"].sum()
        print(f"    {pump_count} sinais de pump detectados")

        if pump_count == 0:
            symbols_ok += 1
            continue

        # Simular trades
        trades, final_capital = simulate_trades(symbol, df)
        print(f"    {len(trades)} trades executados")

        all_trades.extend(trades)
        symbols_ok += 1

    print(f"\n  Dados carregados: {symbols_ok} OK, {symbols_fail} falhas")
    print(f"  Total de trades: {len(all_trades)}")

    if not all_trades:
        print("\n  NENHUM TRADE GERADO — nenhum pump detectado nos dados historicos.")
        print("  Possíveis causas:")
        print(f"    - PUMP_VOLUME_MULTIPLIER ({PUMP_VOLUME_MULTIPLIER}x) muito alto")
        print(f"    - PUMP_PRICE_CHANGE_MIN ({PUMP_PRICE_CHANGE_MIN}%) muito alto")
        print(f"    - Periodo de {BACKTEST_DAYS} dias sem eventos de volume extremo")
        print("  Considere testar com parametros mais relaxados.")
        return

    # Calcular metricas
    metrics = calc_metrics(all_trades)
    by_symbol = calc_segmented(all_trades, "symbol")
    by_direction = calc_segmented(all_trades, "direction")

    # Converter hora para string para segmentacao
    for t in all_trades:
        t["entry_hour_str"] = str(t["entry_hour"]).zfill(2)
    by_hour = calc_segmented(all_trades, "entry_hour_str")

    by_month = calc_monthly(all_trades)

    # Report
    print_report(all_trades, metrics, by_symbol, by_hour, by_direction, by_month)

    # Exportar
    export_results(all_trades, metrics, by_symbol, by_hour, by_direction, by_month)


if __name__ == "__main__":
    main()
