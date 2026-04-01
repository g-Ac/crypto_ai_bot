"""
Backtest historico para a estrategia de scalping (3 motores + confluencia).

Requisitos:
- Baixa dados 3m, 5m e 15m da Binance Futures para pelo menos 90 dias
- Reutiliza a logica real dos motores (volume_breakout, rsi_bb_reversal, ema_crossover)
- Look-ahead fix: sinal gerado com dados ate candle i-1, entrada no open do candle i
- Simula gestao de posicao: SL, TP1 parcial (50%), TP2, breakeven apos TP1
- Fees: 0.04% por lado (0.08% round trip, Futures maker+taker medio)
- Metricas: win rate, profit factor, expectancy, max drawdown, Sharpe simplificado
- Resultados separados por confluencia 2/3 vs 3/3, motor principal, simbolo

Uso: python backtest_scalping.py [--days 90] [--symbols BTCUSDT,ETHUSDT]
"""
import argparse
import json
import logging
import math
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from config import BINANCE_KLINES_URL, BACKTEST_DAYS

# --- Importar logica real dos motores (padrao A4: single source of truth) ---
from scalping_data import add_scalping_indicators
from signal_types import Direction, Signal, ConfluenceResult, ScalpingConfig

import volume_breakout
import rsi_bb_reversal
import ema_crossover

# ============================================================
#  CONSTANTES
# ============================================================

# Futures fees: 0.02% maker + 0.04% taker ~ media 0.04% por lado
FEE_PER_SIDE_PCT = 0.04
ROUND_TRIP_FEE_PCT = FEE_PER_SIDE_PCT * 2  # 0.08%

# Slippage pessimista adicional (alem do que os motores ja incluem)
EXTRA_SLIPPAGE_PCT = 0.02  # 0.02% adicional por lado

# Capital inicial para simulacao
INITIAL_CAPITAL = 10000.0

# Symbols padrao
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

# Minimo de candles de warmup para indicadores
WARMUP_CANDLES = 60  # precisa de pelo menos 50 para add_scalping_indicators

# Janela de dados para alimentar os motores (quantos candles)
ENGINE_WINDOW = 100

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backtest_scalping")


# ============================================================
#  DOWNLOAD DE DADOS HISTORICOS
# ============================================================

def fetch_historical_futures(
    symbol: str, interval: str, days: int
) -> Optional[pd.DataFrame]:
    """
    Baixa candles historicos da Binance Futures (fapi).
    Pagina automaticamente em blocos de 1500.
    """
    all_data = []
    start_ms = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    end_ms = int(datetime.utcnow().timestamp() * 1000)
    cursor = start_ms

    while cursor < end_ms:
        url = (
            f"{BINANCE_KLINES_URL}"
            f"?symbol={symbol}&interval={interval}"
            f"&startTime={cursor}&limit=1500"
        )
        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    print(f"    Rate limited, aguardando {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                if resp.status_code != 200:
                    print(f"    HTTP {resp.status_code} para {symbol}/{interval}")
                    time.sleep(2)
                    continue
                data = resp.json()
                if not data:
                    cursor = end_ms  # fim dos dados
                    break
                all_data.extend(data)
                cursor = data[-1][0] + 1
                break
            except Exception as e:
                print(f"    Erro (tentativa {attempt+1}): {e}")
                time.sleep(2 ** attempt)
        else:
            print(f"    Falha apos 3 tentativas para {symbol}/{interval}")
            break
        time.sleep(0.15)  # rate limit friendly

    if not all_data:
        return None

    df = pd.DataFrame(all_data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    df = df[["time", "open", "high", "low", "close", "volume"]].copy()

    # Remover duplicatas por timestamp
    df = df.drop_duplicates(subset=["time"]).reset_index(drop=True)
    return df


# ============================================================
#  ALINHAMENTO DE TIMEFRAMES
# ============================================================

def align_timeframes(
    df_3m: pd.DataFrame,
    df_5m: pd.DataFrame,
    df_15m: pd.DataFrame,
) -> list:
    """
    Retorna lista de indices do df_5m onde temos dados suficientes
    nos 3 timeframes para rodar os motores.

    Para cada candle 5m[i], encontramos os candles 3m e 15m
    que estavam disponiveis ATE aquele momento (sem look-ahead).
    """
    # O loop principal itera sobre candles 5m
    # Para cada candle 5m com timestamp T:
    #   - df_3m disponivel: todos candles com time < T (fechados)
    #   - df_15m disponivel: todos candles com time < T (fechados)
    # O sinal e gerado no candle 5m[i-1] (fechado), entrada no open de 5m[i]
    return list(range(WARMUP_CANDLES + 1, len(df_5m)))


def get_window_up_to(df: pd.DataFrame, end_time: pd.Timestamp, n: int) -> pd.DataFrame:
    """
    Retorna os ultimos `n` candles do DataFrame com time <= end_time.
    Simula os dados que estariam disponiveis naquele ponto no tempo.
    """
    mask = df["time"] <= end_time
    subset = df.loc[mask]
    if len(subset) > n:
        subset = subset.iloc[-n:]
    return subset.copy()


# ============================================================
#  CONFLUENCIA LOCAL (sem fetch de API)
# ============================================================

def run_confluence_local(
    symbol: str,
    config: ScalpingConfig,
    df_3m_window: pd.DataFrame,
    df_5m_window: pd.DataFrame,
    df_15m_window: pd.DataFrame,
) -> ConfluenceResult:
    """
    Replica a logica de confluence.analyze() mas usando DataFrames locais
    (sem buscar dados da API). Importa e usa os motores reais.
    """
    no_trade = ConfluenceResult(
        direction=Direction.NEUTRAL,
        score=0,
        meets_threshold=False,
        reason="Confluencia insuficiente"
    )

    if df_3m_window is None or len(df_3m_window) < 50:
        no_trade.reason = "Dados 3m insuficientes"
        return no_trade
    if df_5m_window is None or len(df_5m_window) < 50:
        no_trade.reason = "Dados 5m insuficientes"
        return no_trade

    # Adicionar indicadores nas janelas
    df_3m_ind = add_scalping_indicators(df_3m_window.copy())
    df_5m_ind = add_scalping_indicators(df_5m_window.copy())
    df_15m_ind = None
    if df_15m_window is not None and len(df_15m_window) >= 50:
        df_15m_ind = add_scalping_indicators(df_15m_window.copy())

    # Executar os 3 motores com dados locais (A4: single source of truth)
    sig_vb = volume_breakout.analyze(symbol, config, df_3m=df_3m_ind, df_5m=df_5m_ind)
    sig_rsi = rsi_bb_reversal.analyze(symbol, config, df_5m=df_5m_ind, df_15m=df_15m_ind)
    sig_ema = ema_crossover.analyze(symbol, config, df_3m=df_3m_ind, df_15m=df_15m_ind)

    all_signals = [sig_vb, sig_rsi, sig_ema]
    valid_signals = [s for s in all_signals if s.valid]

    if not valid_signals:
        no_trade.signals = all_signals
        no_trade.reason = "Nenhum motor gerou sinal valido"
        return no_trade

    # Contar sinais por direcao
    long_count = sum(1 for s in valid_signals if s.direction == Direction.LONG)
    short_count = sum(1 for s in valid_signals if s.direction == Direction.SHORT)

    # Sinais opostos
    if long_count > 0 and short_count > 0:
        no_trade.signals = all_signals
        no_trade.reason = "Sinais opostos"
        return no_trade

    # Direcao dominante
    if long_count > short_count:
        direction = Direction.LONG
        score = long_count
    elif short_count > long_count:
        direction = Direction.SHORT
        score = short_count
    else:
        no_trade.signals = all_signals
        no_trade.reason = "Sem direcao dominante"
        return no_trade

    # Avaliar confluencia
    same_dir_signals = [s for s in valid_signals if s.direction == direction]

    # Selecionar melhor sinal (maior RR, depois maior forca)
    same_dir_signals.sort(key=lambda s: (s.rr_ratio, s.strength), reverse=True)
    best_signal = same_dir_signals[0]

    if score >= 3:
        position_size_pct = 100.0
        leverage = 5
    elif score >= 2:
        position_size_pct = 50.0
        leverage = 3
    else:
        no_trade.signals = all_signals
        no_trade.score = score
        no_trade.reason = f"Confluencia {score}/3 insuficiente"
        return no_trade

    meets_threshold = score >= config.min_confluence_score

    return ConfluenceResult(
        direction=direction,
        score=score,
        meets_threshold=meets_threshold,
        signals=all_signals,
        position_size_pct=position_size_pct,
        leverage=leverage,
        reason=f"Confluencia {score}/3 {direction.value}",
        best_signal=best_signal,
    )


# ============================================================
#  POSICAO SIMULADA
# ============================================================

class SimulatedPosition:
    """Rastreia uma posicao aberta no backtest."""

    def __init__(
        self,
        symbol: str,
        direction: Direction,
        entry_price: float,
        entry_time: pd.Timestamp,
        sl_price: float,
        tp1_price: float,
        tp2_price: float,
        position_size_usd: float,
        leverage: int,
        confluence_score: int,
        primary_engine: str,
        engines_active: list,
    ):
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.sl_price = sl_price
        self.tp1_price = tp1_price
        self.tp2_price = tp2_price
        self.position_size_usd = position_size_usd
        self.remaining_size_pct = 100.0  # % da posicao ainda aberta
        self.leverage = leverage
        self.confluence_score = confluence_score
        self.primary_engine = primary_engine
        self.engines_active = engines_active
        self.tp1_hit = False
        self.breakeven_active = False
        self.original_sl = sl_price

    def check_exit(self, candle: pd.Series) -> list:
        """
        Verifica se o candle atual aciona SL, TP1 ou TP2.

        Retorna lista de eventos de saida:
        [{"reason": str, "price": float, "size_pct": float}, ...]

        Ordem de verificacao (pessimista):
        1. SL primeiro (se a direcao tiver ido contra)
        2. TP1 (fecha 50%)
        3. TP2 (fecha restante)

        Assume pior caso: se tanto SL quanto TP poderiam ser atingidos
        no mesmo candle, SL e acionado primeiro.
        """
        exits = []
        high = candle["high"]
        low = candle["low"]

        if self.remaining_size_pct <= 0:
            return exits

        # --- STOP LOSS ---
        sl_hit = False
        if self.direction == Direction.LONG:
            if low <= self.sl_price:
                sl_hit = True
        else:  # SHORT
            if high >= self.sl_price:
                sl_hit = True

        if sl_hit:
            exits.append({
                "reason": "stop_loss",
                "price": self.sl_price,
                "size_pct": self.remaining_size_pct,
            })
            self.remaining_size_pct = 0
            return exits  # posicao inteira fechada

        # --- TP1 (50% da posicao) ---
        if not self.tp1_hit:
            tp1_hit = False
            if self.direction == Direction.LONG:
                if high >= self.tp1_price:
                    tp1_hit = True
            else:
                if low <= self.tp1_price:
                    tp1_hit = True

            if tp1_hit:
                close_pct = min(50.0, self.remaining_size_pct)
                exits.append({
                    "reason": "tp1",
                    "price": self.tp1_price,
                    "size_pct": close_pct,
                })
                self.remaining_size_pct -= close_pct
                self.tp1_hit = True

                # Ativar breakeven: mover SL para entry
                self.breakeven_active = True
                self.sl_price = self.entry_price

        # --- TP2 (restante) ---
        if self.tp1_hit and self.remaining_size_pct > 0:
            tp2_hit = False
            if self.direction == Direction.LONG:
                if high >= self.tp2_price:
                    tp2_hit = True
            else:
                if low <= self.tp2_price:
                    tp2_hit = True

            if tp2_hit:
                exits.append({
                    "reason": "tp2",
                    "price": self.tp2_price,
                    "size_pct": self.remaining_size_pct,
                })
                self.remaining_size_pct = 0

        return exits


# ============================================================
#  CALCULO DE PNL
# ============================================================

def calculate_pnl(
    direction: Direction,
    entry_price: float,
    exit_price: float,
    size_pct: float,
    position_size_usd: float,
    leverage: int,
) -> dict:
    """
    Calcula PnL para uma saida parcial ou total.

    Aplica fees (0.04% por lado) e slippage extra.
    """
    # PnL bruto em %
    if direction == Direction.LONG:
        raw_pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    else:
        raw_pnl_pct = ((entry_price - exit_price) / entry_price) * 100

    # Fees: 0.04% entrada + 0.04% saida = 0.08% total
    fee_pct = ROUND_TRIP_FEE_PCT

    # Slippage adicional pessimista
    slippage_pct = EXTRA_SLIPPAGE_PCT * 2  # entrada + saida

    # PnL liquido em % (alavancado)
    net_pnl_pct = (raw_pnl_pct * leverage) - fee_pct - slippage_pct

    # PnL em USD (proporcional a % da posicao fechada)
    fraction = size_pct / 100.0
    pnl_usd = (net_pnl_pct / 100) * position_size_usd * fraction

    return {
        "raw_pnl_pct": round(raw_pnl_pct, 6),
        "net_pnl_pct": round(net_pnl_pct, 6),
        "fee_pct": round(fee_pct, 4),
        "slippage_pct": round(slippage_pct, 4),
        "pnl_usd": round(pnl_usd, 4),
        "fraction": round(fraction, 4),
    }


# ============================================================
#  METRICAS
# ============================================================

def calc_metrics(trades: list) -> dict:
    """Calcula metricas de performance."""
    if not trades:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "total_return_pct": 0, "total_pnl_usd": 0,
            "avg_win_pct": 0, "avg_loss_pct": 0,
            "max_drawdown_pct": 0, "max_drawdown_usd": 0,
            "profit_factor": 0, "expectancy_pct": 0,
            "sharpe_simplified": 0, "best_trade_pct": 0, "worst_trade_pct": 0,
            "avg_duration_candles": 0,
        }

    wins = [t for t in trades if t["total_net_pnl_pct"] > 0]
    losses = [t for t in trades if t["total_net_pnl_pct"] <= 0]

    total_return_pct = sum(t["total_net_pnl_pct"] for t in trades)
    total_pnl_usd = sum(t["total_pnl_usd"] for t in trades)

    # Max drawdown (baseado em PnL acumulado em %)
    cum = 0.0
    peak = 0.0
    max_dd_pct = 0.0
    for t in trades:
        cum += t["total_net_pnl_pct"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd_pct:
            max_dd_pct = dd

    # Max drawdown em USD
    cum_usd = 0.0
    peak_usd = 0.0
    max_dd_usd = 0.0
    for t in trades:
        cum_usd += t["total_pnl_usd"]
        if cum_usd > peak_usd:
            peak_usd = cum_usd
        dd_usd = peak_usd - cum_usd
        if dd_usd > max_dd_usd:
            max_dd_usd = dd_usd

    # Profit factor
    gross_profit = sum(t["total_net_pnl_pct"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["total_net_pnl_pct"] for t in losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Expectancy
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = -(gross_loss / len(losses)) if losses else 0
    win_rate = (len(wins) / len(trades)) * 100 if trades else 0
    expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

    # Sharpe simplificado (retorno medio / desvio padrao dos retornos)
    returns = [t["total_net_pnl_pct"] for t in trades]
    avg_return = sum(returns) / len(returns) if returns else 0
    if len(returns) > 1:
        variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
        std_return = math.sqrt(variance) if variance > 0 else 0
        sharpe = avg_return / std_return if std_return > 0 else 0
    else:
        sharpe = 0

    # Duracao media dos trades
    durations = [t.get("duration_candles", 0) for t in trades]
    avg_duration = sum(durations) / len(durations) if durations else 0

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 2),
        "total_return_pct": round(total_return_pct, 4),
        "total_pnl_usd": round(total_pnl_usd, 2),
        "avg_win_pct": round(avg_win, 4),
        "avg_loss_pct": round(avg_loss, 4),
        "max_drawdown_pct": round(max_dd_pct, 4),
        "max_drawdown_usd": round(max_dd_usd, 2),
        "profit_factor": round(pf, 4) if pf != float("inf") else 999.99,
        "expectancy_pct": round(expectancy, 4),
        "sharpe_simplified": round(sharpe, 4),
        "best_trade_pct": round(max(t["total_net_pnl_pct"] for t in trades), 4),
        "worst_trade_pct": round(min(t["total_net_pnl_pct"] for t in trades), 4),
        "avg_duration_candles": round(avg_duration, 1),
    }


# ============================================================
#  LOOP PRINCIPAL DO BACKTEST
# ============================================================

def run_backtest_symbol(
    symbol: str,
    df_3m: pd.DataFrame,
    df_5m: pd.DataFrame,
    df_15m: pd.DataFrame,
    config: ScalpingConfig,
) -> list:
    """
    Executa backtest para um simbolo.

    Loop principal sobre candles 5m (timeframe principal).
    Para cada candle 5m[i]:
    1. Olhamos dados ate 5m[i-1] (candle fechado) para gerar sinal
    2. Se ha sinal, entrada no open do 5m[i]
    3. Gerencia posicao aberta com high/low de 5m[i]
    """
    trades = []
    position: Optional[SimulatedPosition] = None
    cooldown_remaining = 0  # candles de cooldown

    # Indices validos para o loop
    start_idx = WARMUP_CANDLES + 1

    total_candles = len(df_5m)
    signals_generated = 0

    for i in range(start_idx, total_candles):
        current_candle = df_5m.iloc[i]
        signal_candle = df_5m.iloc[i - 1]  # candle fechado para gerar sinal

        # Timestamp do candle de sinal (tudo ate esse ponto e "conhecido")
        signal_time = signal_candle["time"]

        # --- GERENCIAR POSICAO ABERTA ---
        if position is not None:
            exit_events = position.check_exit(current_candle)

            if exit_events:
                total_net_pnl_pct = 0.0
                total_pnl_usd = 0.0
                exit_details = []

                for ev in exit_events:
                    pnl = calculate_pnl(
                        direction=position.direction,
                        entry_price=position.entry_price,
                        exit_price=ev["price"],
                        size_pct=ev["size_pct"],
                        position_size_usd=position.position_size_usd,
                        leverage=position.leverage,
                    )
                    total_net_pnl_pct += pnl["net_pnl_pct"] * pnl["fraction"]
                    total_pnl_usd += pnl["pnl_usd"]
                    exit_details.append({
                        "reason": ev["reason"],
                        "price": round(ev["price"], 8),
                        "size_pct": ev["size_pct"],
                        **pnl,
                    })

                # Se posicao totalmente fechada
                if position.remaining_size_pct <= 0:
                    # Calcular duracao em candles
                    entry_idx = df_5m.index[df_5m["time"] == position.entry_time]
                    duration = i - (entry_idx[0] if len(entry_idx) > 0 else i)

                    trade = {
                        "symbol": symbol,
                        "direction": position.direction.value,
                        "entry_price": round(position.entry_price, 8),
                        "entry_time": str(position.entry_time),
                        "exit_time": str(current_candle["time"]),
                        "sl_price": round(position.original_sl, 8),
                        "tp1_price": round(position.tp1_price, 8),
                        "tp2_price": round(position.tp2_price, 8),
                        "confluence_score": position.confluence_score,
                        "primary_engine": position.primary_engine,
                        "engines_active": position.engines_active,
                        "leverage": position.leverage,
                        "position_size_usd": round(position.position_size_usd, 2),
                        "exit_details": exit_details,
                        "total_net_pnl_pct": round(total_net_pnl_pct, 6),
                        "total_pnl_usd": round(total_pnl_usd, 4),
                        "tp1_hit": position.tp1_hit,
                        "duration_candles": int(duration),
                    }
                    trades.append(trade)

                    # Ativar cooldown
                    cooldown_remaining = config.cooldown_candles
                    position = None

        # Decrementar cooldown
        if cooldown_remaining > 0:
            cooldown_remaining -= 1

        # --- GERAR SINAL (se nao tem posicao aberta e cooldown expirou) ---
        if position is not None or cooldown_remaining > 0:
            continue

        # Construir janelas de dados ATE signal_time (sem look-ahead)
        df_3m_window = get_window_up_to(df_3m, signal_time, ENGINE_WINDOW)
        df_5m_window = get_window_up_to(df_5m, signal_time, ENGINE_WINDOW)
        df_15m_window = get_window_up_to(df_15m, signal_time, ENGINE_WINDOW)

        # Verificar janelas minimas
        if len(df_3m_window) < 50 or len(df_5m_window) < 50:
            continue

        # Rodar confluencia local
        confluence = run_confluence_local(
            symbol, config,
            df_3m_window, df_5m_window, df_15m_window
        )

        # Verificar se temos sinal operavel
        if not confluence.meets_threshold or confluence.score < 2:
            continue
        if confluence.direction == Direction.NEUTRAL:
            continue
        if confluence.best_signal is None:
            continue

        signals_generated += 1
        best = confluence.best_signal

        # --- ENTRADA no open do candle atual (i) ---
        entry_price = current_candle["open"]

        # Aplicar slippage pessimista na entrada
        slip = entry_price * (EXTRA_SLIPPAGE_PCT / 100)
        if confluence.direction == Direction.LONG:
            entry_price += slip  # compra mais caro
        else:
            entry_price -= slip  # vende mais barato

        # Position sizing: 2% do capital por trade
        sl_distance_pct = abs(entry_price - best.sl_price) / entry_price
        if sl_distance_pct <= 0:
            continue

        risk_amount = INITIAL_CAPITAL * (config.max_risk_pct / 100)
        position_size_usd = risk_amount / sl_distance_pct

        # Ajustar pelo % de confluencia
        position_size_usd = position_size_usd * (confluence.position_size_pct / 100)

        # Cap no maximo 50% do capital em margem
        max_margin = INITIAL_CAPITAL * 0.5
        margin = position_size_usd / confluence.leverage
        if margin > max_margin:
            position_size_usd = max_margin * confluence.leverage

        # Identificar motores ativos
        engines_active = [
            s.source for s in confluence.signals
            if s.valid and s.direction == confluence.direction
        ]

        # Abrir posicao
        position = SimulatedPosition(
            symbol=symbol,
            direction=confluence.direction,
            entry_price=entry_price,
            entry_time=current_candle["time"],
            sl_price=best.sl_price,
            tp1_price=best.tp1_price,
            tp2_price=best.tp2_price,
            position_size_usd=position_size_usd,
            leverage=confluence.leverage,
            confluence_score=confluence.score,
            primary_engine=best.source,
            engines_active=engines_active,
        )

        # Verificar se SL/TP ja atingido no candle de entrada
        exit_events = position.check_exit(current_candle)
        if exit_events and position.remaining_size_pct <= 0:
            total_net_pnl_pct = 0.0
            total_pnl_usd = 0.0
            exit_details = []
            for ev in exit_events:
                pnl = calculate_pnl(
                    direction=position.direction,
                    entry_price=position.entry_price,
                    exit_price=ev["price"],
                    size_pct=ev["size_pct"],
                    position_size_usd=position.position_size_usd,
                    leverage=position.leverage,
                )
                total_net_pnl_pct += pnl["net_pnl_pct"] * pnl["fraction"]
                total_pnl_usd += pnl["pnl_usd"]
                exit_details.append({
                    "reason": ev["reason"],
                    "price": round(ev["price"], 8),
                    "size_pct": ev["size_pct"],
                    **pnl,
                })

            trade = {
                "symbol": symbol,
                "direction": position.direction.value,
                "entry_price": round(position.entry_price, 8),
                "entry_time": str(position.entry_time),
                "exit_time": str(current_candle["time"]),
                "sl_price": round(position.original_sl, 8),
                "tp1_price": round(position.tp1_price, 8),
                "tp2_price": round(position.tp2_price, 8),
                "confluence_score": position.confluence_score,
                "primary_engine": position.primary_engine,
                "engines_active": engines_active,
                "leverage": position.leverage,
                "position_size_usd": round(position.position_size_usd, 2),
                "exit_details": exit_details,
                "total_net_pnl_pct": round(total_net_pnl_pct, 6),
                "total_pnl_usd": round(total_pnl_usd, 4),
                "tp1_hit": position.tp1_hit,
                "duration_candles": 0,
            }
            trades.append(trade)
            cooldown_remaining = config.cooldown_candles
            position = None

    # Fechar posicao aberta no fim dos dados
    if position is not None:
        last = df_5m.iloc[-1]
        close_price = last["close"]
        pnl = calculate_pnl(
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=close_price,
            size_pct=position.remaining_size_pct,
            position_size_usd=position.position_size_usd,
            leverage=position.leverage,
        )
        entry_idx = df_5m.index[df_5m["time"] == position.entry_time]
        duration = (total_candles - 1) - (entry_idx[0] if len(entry_idx) > 0 else total_candles - 1)

        trade = {
            "symbol": symbol,
            "direction": position.direction.value,
            "entry_price": round(position.entry_price, 8),
            "entry_time": str(position.entry_time),
            "exit_time": str(last["time"]),
            "sl_price": round(position.original_sl, 8),
            "tp1_price": round(position.tp1_price, 8),
            "tp2_price": round(position.tp2_price, 8),
            "confluence_score": position.confluence_score,
            "primary_engine": position.primary_engine,
            "engines_active": position.engines_active,
            "leverage": position.leverage,
            "position_size_usd": round(position.position_size_usd, 2),
            "exit_details": [{
                "reason": "end_of_data",
                "price": round(close_price, 8),
                "size_pct": position.remaining_size_pct,
                **pnl,
            }],
            "total_net_pnl_pct": round(pnl["net_pnl_pct"] * pnl["fraction"], 6),
            "total_pnl_usd": round(pnl["pnl_usd"], 4),
            "tp1_hit": position.tp1_hit,
            "duration_candles": int(duration),
        }
        trades.append(trade)

    print(f"    {symbol}: {signals_generated} sinais gerados, {len(trades)} trades executados")
    return trades


# ============================================================
#  RELATORIO FORMATADO
# ============================================================

def print_separator(char="=", width=70):
    print(char * width)


def print_report(all_trades: list, by_symbol: dict, days: int):
    """Imprime relatorio completo no terminal."""

    print_separator()
    print(f"  BACKTEST SCALPING | {days} dias | {len(by_symbol)} ativos")
    print(f"  Fees: {ROUND_TRIP_FEE_PCT}% round-trip | Slippage extra: {EXTRA_SLIPPAGE_PCT * 2}%")
    print(f"  Capital: ${INITIAL_CAPITAL:,.0f}")
    print_separator()

    # --- METRICAS GLOBAIS ---
    m = calc_metrics(all_trades)
    print(f"\n  RESULTADO GLOBAL")
    print(f"  {'-'*50}")
    print(f"  Trades: {m['total_trades']} | Wins: {m['wins']} | Losses: {m['losses']}")
    print(f"  Win Rate: {m['win_rate']:.1f}%")
    print(f"  Retorno total: {m['total_return_pct']:+.2f}% (${m['total_pnl_usd']:+,.2f})")
    print(f"  Max Drawdown: {m['max_drawdown_pct']:.2f}% (${m['max_drawdown_usd']:,.2f})")
    print(f"  Profit Factor: {m['profit_factor']:.2f}")
    print(f"  Expectancy: {m['expectancy_pct']:+.4f}%")
    print(f"  Sharpe (simplificado): {m['sharpe_simplified']:.2f}")
    print(f"  Media win: +{m['avg_win_pct']:.2f}% | Media loss: {m['avg_loss_pct']:.2f}%")
    print(f"  Melhor: +{m['best_trade_pct']:.2f}% | Pior: {m['worst_trade_pct']:.2f}%")
    print(f"  Duracao media: {m['avg_duration_candles']:.0f} candles")

    # --- POR SIMBOLO ---
    print(f"\n  POR SIMBOLO")
    print(f"  {'-'*50}")
    print(f"  {'Simbolo':<12} {'Trades':>6} {'WR':>6} {'Return':>10} {'PF':>6} {'MaxDD':>8}")
    for sym, sym_trades in sorted(by_symbol.items()):
        sm = calc_metrics(sym_trades)
        print(
            f"  {sym:<12} {sm['total_trades']:>6} "
            f"{sm['win_rate']:>5.1f}% "
            f"{sm['total_return_pct']:>+9.2f}% "
            f"{sm['profit_factor']:>6.2f} "
            f"{sm['max_drawdown_pct']:>7.2f}%"
        )

    # --- POR CONFLUENCIA ---
    score_2 = [t for t in all_trades if t["confluence_score"] == 2]
    score_3 = [t for t in all_trades if t["confluence_score"] == 3]

    print(f"\n  POR CONFLUENCIA")
    print(f"  {'-'*50}")
    for label, subset in [("2/3", score_2), ("3/3", score_3)]:
        sm = calc_metrics(subset)
        if sm["total_trades"] > 0:
            print(
                f"  Score {label}: {sm['total_trades']} trades | "
                f"WR: {sm['win_rate']:.1f}% | "
                f"Ret: {sm['total_return_pct']:+.2f}% | "
                f"PF: {sm['profit_factor']:.2f} | "
                f"DD: {sm['max_drawdown_pct']:.2f}%"
            )
        else:
            print(f"  Score {label}: 0 trades")

    # --- POR MOTOR PRINCIPAL ---
    engines = {}
    for t in all_trades:
        eng = t["primary_engine"]
        engines.setdefault(eng, []).append(t)

    print(f"\n  POR MOTOR PRINCIPAL")
    print(f"  {'-'*50}")
    for eng_name, eng_trades in sorted(engines.items()):
        em = calc_metrics(eng_trades)
        if em["total_trades"] > 0:
            print(
                f"  {eng_name:<20} {em['total_trades']:>4} trades | "
                f"WR: {em['win_rate']:.1f}% | "
                f"Ret: {em['total_return_pct']:+.2f}% | "
                f"PF: {em['profit_factor']:.2f}"
            )

    # --- POR DIRECAO ---
    longs = [t for t in all_trades if t["direction"] == "LONG"]
    shorts = [t for t in all_trades if t["direction"] == "SHORT"]

    print(f"\n  POR DIRECAO")
    print(f"  {'-'*50}")
    for label, subset in [("LONG", longs), ("SHORT", shorts)]:
        sm = calc_metrics(subset)
        if sm["total_trades"] > 0:
            print(
                f"  {label:<8} {sm['total_trades']:>4} trades | "
                f"WR: {sm['win_rate']:.1f}% | "
                f"Ret: {sm['total_return_pct']:+.2f}% | "
                f"PF: {sm['profit_factor']:.2f}"
            )

    # --- EXIT REASONS ---
    exit_reasons = {}
    for t in all_trades:
        for ed in t.get("exit_details", []):
            r = ed["reason"]
            exit_reasons[r] = exit_reasons.get(r, 0) + 1

    print(f"\n  MOTIVOS DE SAIDA")
    print(f"  {'-'*50}")
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        pct = count / max(1, sum(exit_reasons.values())) * 100
        print(f"  {reason:<20} {count:>4} ({pct:.0f}%)")

    # --- TRADE LOG (ultimos 20) ---
    print(f"\n  ULTIMOS 20 TRADES")
    print(f"  {'-'*66}")
    print(f"  {'#':>3} {'Dir':>5} {'Sym':<10} {'Entry':>10} {'PnL%':>8} {'Score':>5} {'Exit':>12}")
    print(f"  {'-'*66}")
    for idx, t in enumerate(all_trades[-20:], max(1, len(all_trades) - 19)):
        exit_reason = t["exit_details"][-1]["reason"] if t["exit_details"] else "?"
        print(
            f"  {idx:>3} {t['direction']:>5} {t['symbol']:<10} "
            f"{t['entry_price']:>10.2f} "
            f"{t['total_net_pnl_pct']:>+7.2f}% "
            f"  {t['confluence_score']}/3 "
            f"{exit_reason:>12}"
        )

    # --- ANALISE DE ROBUSTEZ ---
    print(f"\n  NOTAS DE ROBUSTEZ")
    print(f"  {'-'*50}")

    if m["total_trades"] < 30:
        print(f"  [ALERTA] Amostra pequena: {m['total_trades']} trades. Minimo recomendado: 30+")
    if m["total_trades"] < 100:
        print(f"  [AVISO] Amostra moderada: {m['total_trades']} trades. Ideal: 100+")

    if m["profit_factor"] > 3.0 and m["total_trades"] > 10:
        print(f"  [SUSPEITO] PF muito alto ({m['profit_factor']:.2f}). Verificar overfitting.")

    if m["win_rate"] > 80:
        print(f"  [SUSPEITO] Win rate muito alto ({m['win_rate']:.1f}%). Verificar look-ahead.")

    if days < 90:
        print(f"  [ALERTA] Periodo curto ({days} dias). Minimo recomendado: 90+ dias.")

    # Verificar concentracao de PnL
    if all_trades:
        pnls = sorted([t["total_net_pnl_pct"] for t in all_trades], reverse=True)
        if len(pnls) >= 5:
            top5_pnl = sum(pnls[:5])
            total_positive = sum(p for p in pnls if p > 0)
            if total_positive > 0 and top5_pnl / total_positive > 0.5:
                print(
                    f"  [AVISO] Top 5 trades representam {top5_pnl/total_positive*100:.0f}% "
                    f"do lucro total. Resultado pode ser fragil."
                )

    print_separator()


# ============================================================
#  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Backtest Scalping Strategy")
    parser.add_argument("--days", type=int, default=BACKTEST_DAYS, help=f"Dias de historico (default: {BACKTEST_DAYS})")
    parser.add_argument(
        "--symbols", type=str, default=None,
        help="Simbolos separados por virgula (default: BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT)"
    )
    parser.add_argument("--output", type=str, default="backtest_scalping_results.json",
                        help="Arquivo JSON de saida")
    args = parser.parse_args()

    symbols = args.symbols.split(",") if args.symbols else DEFAULT_SYMBOLS
    days = args.days

    print_separator()
    print(f"  BACKTEST SCALPING")
    print(f"  Periodo: {days} dias | Ativos: {', '.join(symbols)}")
    print(f"  Timeframes: 3m + 5m (principal) + 15m")
    print(f"  Fees: {ROUND_TRIP_FEE_PCT}% round-trip | Slippage: {EXTRA_SLIPPAGE_PCT * 2}%")
    print_separator()

    config = ScalpingConfig()

    all_trades = []
    by_symbol = {}

    for symbol in symbols:
        print(f"\n  [{symbol}] Baixando dados historicos...")

        # Baixar dados dos 3 timeframes
        # Adicionar margem extra para warmup
        fetch_days = days + 5

        print(f"    Baixando 3m...")
        df_3m = fetch_historical_futures(symbol, "3m", fetch_days)
        print(f"    Baixando 5m...")
        df_5m = fetch_historical_futures(symbol, "5m", fetch_days)
        print(f"    Baixando 15m...")
        df_15m = fetch_historical_futures(symbol, "15m", fetch_days)

        if df_3m is None or df_5m is None:
            print(f"    ERRO: Dados insuficientes para {symbol}, pulando.")
            continue

        if df_15m is None:
            print(f"    AVISO: Dados 15m indisponiveis, usando apenas 3m e 5m")
            df_15m = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        print(
            f"    Candles: 3m={len(df_3m)} | 5m={len(df_5m)} | 15m={len(df_15m)}"
        )
        print(
            f"    Periodo: {df_5m['time'].iloc[0]} a {df_5m['time'].iloc[-1]}"
        )

        # Rodar backtest
        print(f"    Executando backtest...")
        sym_trades = run_backtest_symbol(symbol, df_3m, df_5m, df_15m, config)

        all_trades.extend(sym_trades)
        by_symbol[symbol] = sym_trades

    # Imprimir relatorio
    print_report(all_trades, by_symbol, days)

    # Exportar JSON
    results = {
        "metadata": {
            "run_date": datetime.utcnow().isoformat(),
            "days": days,
            "symbols": symbols,
            "fee_round_trip_pct": ROUND_TRIP_FEE_PCT,
            "extra_slippage_pct": EXTRA_SLIPPAGE_PCT,
            "initial_capital": INITIAL_CAPITAL,
            "config": {
                "max_risk_pct": config.max_risk_pct,
                "cooldown_candles": config.cooldown_candles,
                "min_confluence_score": config.min_confluence_score,
                "slippage_pct": config.slippage_pct,
                "max_sl_volume_breakout": config.max_sl_volume_breakout,
                "max_sl_rsi_bb": config.max_sl_rsi_bb,
                "max_sl_ema_crossover": config.max_sl_ema_crossover,
                "min_rr_volume_breakout": config.min_rr_volume_breakout,
                "min_rr_rsi_bb": config.min_rr_rsi_bb,
                "min_rr_ema_crossover": config.min_rr_ema_crossover,
                "vb_volume_multiplier": config.vb_volume_multiplier,
                "rsi_oversold": config.rsi_oversold,
                "rsi_overbought": config.rsi_overbought,
            },
        },
        "global_metrics": calc_metrics(all_trades),
        "by_symbol": {
            sym: calc_metrics(trades) for sym, trades in by_symbol.items()
        },
        "by_confluence": {
            "score_2": calc_metrics([t for t in all_trades if t["confluence_score"] == 2]),
            "score_3": calc_metrics([t for t in all_trades if t["confluence_score"] == 3]),
        },
        "by_engine": {},
        "by_direction": {
            "LONG": calc_metrics([t for t in all_trades if t["direction"] == "LONG"]),
            "SHORT": calc_metrics([t for t in all_trades if t["direction"] == "SHORT"]),
        },
        "trades": all_trades,
    }

    # Por motor
    engines = {}
    for t in all_trades:
        eng = t["primary_engine"]
        engines.setdefault(eng, []).append(t)
    results["by_engine"] = {
        eng: calc_metrics(trades) for eng, trades in engines.items()
    }

    # Salvar JSON
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  Resultados exportados para: {args.output}")


if __name__ == "__main__":
    main()
