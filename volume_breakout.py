"""
Motor 1 -- Breakout de Volume.

Detecta candles com volume anormalmente alto que rompem highs/lows recentes.
Volume acima da media indica participacao institucional ou liquidacao em massa.

Timeframes:
- Deteccao: 3m
- Contexto: 15m
- Gestao: 1m

Condicoes de entrada LONG:
1. Volume >= 2.5x media dos ultimos 20 candles
2. Candle fecha acima do high dos ultimos 5
3. Corpo >= 60% do range total
4. Preco acima da EMA20
5. Entrada no open do candle seguinte ao breakout

Filtros:
- 3o spike consecutivo na mesma direcao
- ATR(14) 5m < 0.15% do preco
- Wick > 40% do range (rejeicao)

SL: Low do candle breakout - 0.5 x ATR14, max 0.8%
TP1 (50%): entrada + 1.0 x ATR14
TP2 (50%): entrada + 2.2 x ATR14
RR minimo >= 1.8 (contra TP2)
"""
import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from signal_types import Direction, Signal, ScalpingConfig
from scalping_data import fetch_candles, add_scalping_indicators

logger = logging.getLogger("scalping.volume_breakout")


def _count_consecutive_spikes(
    df: pd.DataFrame, direction: Direction, vol_multiplier: float, vol_period: int
) -> int:
    """
    Conta quantos spikes consecutivos de volume ocorreram na mesma direcao
    nos ultimos candles (antes do candle atual).
    """
    count = 0
    for i in range(len(df) - 2, max(len(df) - 7, vol_period), -1):
        row = df.iloc[i]
        vol_avg = df["volume"].iloc[max(0, i - vol_period):i].mean()
        if vol_avg == 0:
            break

        is_spike = row["volume"] >= vol_multiplier * vol_avg

        if direction == Direction.LONG:
            is_same_dir = row["close"] > row["open"]
        else:
            is_same_dir = row["close"] < row["open"]

        if is_spike and is_same_dir:
            count += 1
        else:
            break

    return count


def analyze(
    symbol: str,
    config: ScalpingConfig,
    df_3m: Optional[pd.DataFrame] = None,
    df_5m: Optional[pd.DataFrame] = None,
) -> Signal:
    """
    Analisa condicoes de Volume Breakout para um par.

    Parametros:
        symbol: par de trading (ex: BTCUSDT)
        config: configuracao da estrategia
        df_3m: DataFrame de 3m com indicadores (se None, busca da API)
        df_5m: DataFrame de 5m com indicadores (para filtro ATR)

    Retorna:
        Signal com direcao, forca e niveis de SL/TP
    """
    now_str = datetime.now().isoformat()
    neutral = Signal(
        direction=Direction.NEUTRAL, strength=0.0, timestamp=now_str,
        source="volume_breakout", symbol=symbol, price=0.0,
        valid=False, reason="Sem sinal"
    )

    # Buscar dados se nao fornecidos
    if df_3m is None:
        df_3m = fetch_candles(symbol, "3m", 100)
        if df_3m is not None:
            df_3m = add_scalping_indicators(df_3m)

    if df_3m is None or len(df_3m) < 50:
        neutral.reason = "Dados 3m insuficientes"
        logger.warning("VB %s: %s", symbol, neutral.reason)
        return neutral

    # Ultimo candle fechado (penultimo do df, o ultimo pode estar incompleto)
    last = df_3m.iloc[-2]
    prev = df_3m.iloc[-3]
    price = last["close"]
    neutral.price = price

    # ============================================================
    # CONDICAO 1: Volume >= 2.5x media dos ultimos 20
    # ============================================================
    vol_avg = df_3m["volume_avg20"].iloc[-2]
    if vol_avg is None or vol_avg == 0 or pd.isna(vol_avg):
        neutral.reason = "Volume medio indisponivel"
        logger.info("VB %s: %s", symbol, neutral.reason)
        return neutral

    volume_ratio = last["volume"] / vol_avg
    if volume_ratio < config.vb_volume_multiplier:
        neutral.reason = f"Volume ratio {volume_ratio:.2f}x < {config.vb_volume_multiplier}x"
        logger.info("VB %s: %s", symbol, neutral.reason)
        return neutral

    logger.info("VB %s: Volume spike detectado: %.2fx", symbol, volume_ratio)

    # ============================================================
    # CONDICAO 2: Fecha acima do high_5 (LONG) ou abaixo do low_5 (SHORT)
    # ============================================================
    high_5 = last["high_5"]
    low_5 = last["low_5"]

    if pd.isna(high_5) or pd.isna(low_5):
        neutral.reason = "High/Low 5 periodos indisponivel"
        return neutral

    is_long_breakout = last["close"] > high_5
    is_short_breakout = last["close"] < low_5

    if not is_long_breakout and not is_short_breakout:
        neutral.reason = f"Sem breakout: close {price:.2f} entre low_5 {low_5:.2f} e high_5 {high_5:.2f}"
        logger.info("VB %s: %s", symbol, neutral.reason)
        return neutral

    direction = Direction.LONG if is_long_breakout else Direction.SHORT
    logger.info("VB %s: Breakout %s detectado", symbol, direction.value)

    # ============================================================
    # CONDICAO 3: Corpo >= 60% do range
    # ============================================================
    body_ratio = last["body_ratio"]
    if body_ratio < config.vb_body_ratio_min:
        neutral.reason = f"Body ratio {body_ratio:.2f} < {config.vb_body_ratio_min}"
        logger.info("VB %s: %s", symbol, neutral.reason)
        return neutral

    # ============================================================
    # CONDICAO 4: Preco acima da EMA20 (LONG) / abaixo (SHORT)
    # ============================================================
    ema20 = last["ema20"]
    if pd.isna(ema20):
        neutral.reason = "EMA20 indisponivel"
        return neutral

    if direction == Direction.LONG and price <= ema20:
        neutral.reason = f"LONG mas preco {price:.2f} abaixo da EMA20 {ema20:.2f}"
        logger.info("VB %s: %s", symbol, neutral.reason)
        return neutral

    if direction == Direction.SHORT and price >= ema20:
        neutral.reason = f"SHORT mas preco {price:.2f} acima da EMA20 {ema20:.2f}"
        logger.info("VB %s: %s", symbol, neutral.reason)
        return neutral

    # ============================================================
    # FILTROS
    # ============================================================

    # Filtro: 3o spike consecutivo
    consecutive = _count_consecutive_spikes(
        df_3m, direction, config.vb_volume_multiplier, config.vb_volume_period
    )
    if consecutive >= config.vb_max_consecutive_spikes:
        neutral.reason = f"Spike #{consecutive + 1} consecutivo - movimento exausto"
        logger.warning("VB %s: %s", symbol, neutral.reason)
        return neutral

    # Filtro: ATR(14) 5m < 0.15% do preco (mercado sem volatilidade)
    if df_5m is not None and len(df_5m) > 20 and "atr14" in df_5m.columns:
        atr_5m = df_5m["atr14"].iloc[-2]
        price_5m = df_5m["close"].iloc[-2]
        if price_5m > 0 and not pd.isna(atr_5m):
            atr_pct = (atr_5m / price_5m) * 100
            if atr_pct < config.vb_atr_min_pct:
                neutral.reason = f"ATR 5m muito baixo: {atr_pct:.3f}% < {config.vb_atr_min_pct}%"
                logger.warning("VB %s: %s", symbol, neutral.reason)
                return neutral

    # Filtro: Wick > 40% do range (rejeicao)
    if direction == Direction.LONG:
        wick_pct = last["upper_wick"]
    else:
        wick_pct = last["lower_wick"]

    if wick_pct > config.vb_wick_max_pct:
        neutral.reason = f"Wick de rejeicao: {wick_pct:.2f} > {config.vb_wick_max_pct}"
        logger.warning("VB %s: %s", symbol, neutral.reason)
        return neutral

    # ============================================================
    # CALCULAR NIVEIS DE SL / TP
    # ============================================================
    atr14 = last["atr14"]
    if pd.isna(atr14) or atr14 == 0:
        neutral.reason = "ATR14 indisponivel"
        return neutral

    # Entrada no open do candle seguinte (estimamos como close do breakout)
    entry_price = price

    # Buffer de slippage: alarga SL e reduz TP
    slip = entry_price * (config.slippage_pct / 100)

    if direction == Direction.LONG:
        # SL = Low do candle breakout - 0.5 x ATR14 - slippage
        sl_price = last["low"] - (config.vb_sl_atr_mult * atr14) - slip
        tp1_price = entry_price + (config.vb_tp1_atr_mult * atr14) - slip
        tp2_price = entry_price + (config.vb_tp2_atr_mult * atr14) - slip
    else:
        # SL = High do candle breakout + 0.5 x ATR14 + slippage
        sl_price = last["high"] + (config.vb_sl_atr_mult * atr14) + slip
        tp1_price = entry_price - (config.vb_tp1_atr_mult * atr14) + slip
        tp2_price = entry_price - (config.vb_tp2_atr_mult * atr14) + slip

    # Distancia do SL em %
    sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100

    # Verificar distancia maxima do SL
    if sl_distance_pct > config.max_sl_volume_breakout:
        neutral.reason = (
            f"SL muito distante: {sl_distance_pct:.2f}% > {config.max_sl_volume_breakout}%"
        )
        logger.warning("VB %s: %s", symbol, neutral.reason)
        return neutral

    # Calcular RR contra TP2
    sl_distance = abs(entry_price - sl_price)
    tp2_distance = abs(tp2_price - entry_price)

    if sl_distance == 0:
        neutral.reason = "SL distance zero"
        return neutral

    rr_ratio = tp2_distance / sl_distance

    if rr_ratio < config.min_rr_volume_breakout:
        neutral.reason = f"RR insuficiente: {rr_ratio:.2f} < {config.min_rr_volume_breakout}"
        logger.info("VB %s: %s", symbol, neutral.reason)
        return neutral

    # ============================================================
    # SINAL VALIDO
    # ============================================================
    # Strength: baseado no volume ratio normalizado (2.5x = 0.5, 5x+ = 1.0)
    strength = min((volume_ratio - config.vb_volume_multiplier) / config.vb_volume_multiplier + 0.5, 1.0)
    strength = max(0.3, strength)

    signal = Signal(
        direction=direction,
        strength=round(strength, 2),
        timestamp=now_str,
        source="volume_breakout",
        symbol=symbol,
        price=price,
        entry_price=round(entry_price, 8),
        sl_price=round(sl_price, 8),
        tp1_price=round(tp1_price, 8),
        tp2_price=round(tp2_price, 8),
        sl_distance_pct=round(sl_distance_pct, 4),
        rr_ratio=round(rr_ratio, 2),
        valid=True,
        reason=f"Volume Breakout {direction.value}: vol {volume_ratio:.1f}x, body {body_ratio:.0%}, RR {rr_ratio:.1f}",
        metadata={
            "volume_ratio": round(volume_ratio, 2),
            "body_ratio": round(body_ratio, 4),
            "ema20": round(ema20, 8),
            "atr14": round(atr14, 8),
            "consecutive_spikes": consecutive,
            "breakout_candle_high": round(last["high"], 8),
            "breakout_candle_low": round(last["low"], 8),
        },
    )

    logger.info(
        "VB %s: SINAL %s | Forca: %.2f | Entry: %.4f | SL: %.4f (%.2f%%) | "
        "TP1: %.4f | TP2: %.4f | RR: %.2f",
        symbol, direction.value, strength, entry_price, sl_price,
        sl_distance_pct, tp1_price, tp2_price, rr_ratio
    )

    return signal
