"""
Motor 3 -- Tendencia por EMA Crossover.

Cruzamentos de EMAs curtas capturam a transicao de micro-estrutura do mercado.
A entrada e feita no retest pos-cruzamento, nao no cruzamento em si.

Timeframes:
- Cruzamento/entrada: 3m
- Filtro de tendencia: 15m
- Retest e execucao fina: 1m

Condicoes de entrada LONG:
1. EMA9 cruza acima da EMA21 (confirmado no fechamento)
2. Preco recua ate zona EMA9-EMA21 (retest)
3. Candle de retest fecha acima da EMA9
4. EMA21 inclinando para cima (EMA21[0] > EMA21[3])
5. EMA50 no 15m abaixo do preco

Filtros:
- Gap EMA9-EMA21 > 0.3% no cruzamento
- Sem retest em 5 candles
- EMAs entrelaçadas no 15m (dist < 0.1%)
- > 3 cruzamentos em 15 candles

SL: abaixo da EMA21 - 0.2 x ATR14, max 0.7%
TP1 (50%): 1.5 x ATR14
TP2 (50%): high dos ultimos 20 candles ou 2.5 x ATR14
RR minimo >= 2.0
"""
import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from signal_types import Direction, Signal, ScalpingConfig
from scalping_data import fetch_candles, add_scalping_indicators

logger = logging.getLogger("scalping.ema_crossover")


def _find_recent_cross(df: pd.DataFrame, lookback: int = 15) -> Optional[dict]:
    """
    Encontra o cruzamento mais recente de EMA9/EMA21 nos ultimos N candles.

    Retorna dict com info do cruzamento ou None se nao encontrar.
    """
    start_idx = max(1, len(df) - lookback - 1)

    for i in range(len(df) - 2, start_idx, -1):
        curr_ema9 = df["ema9"].iloc[i]
        curr_ema21 = df["ema21"].iloc[i]
        prev_ema9 = df["ema9"].iloc[i - 1]
        prev_ema21 = df["ema21"].iloc[i - 1]

        if any(pd.isna(v) for v in [curr_ema9, curr_ema21, prev_ema9, prev_ema21]):
            continue

        # Cruzamento bullish: EMA9 cruza acima da EMA21
        if prev_ema9 <= prev_ema21 and curr_ema9 > curr_ema21:
            return {
                "direction": Direction.LONG,
                "index": i,
                "candles_ago": len(df) - 2 - i,
                "ema9_at_cross": curr_ema9,
                "ema21_at_cross": curr_ema21,
            }

        # Cruzamento bearish: EMA9 cruza abaixo da EMA21
        if prev_ema9 >= prev_ema21 and curr_ema9 < curr_ema21:
            return {
                "direction": Direction.SHORT,
                "index": i,
                "candles_ago": len(df) - 2 - i,
                "ema9_at_cross": curr_ema9,
                "ema21_at_cross": curr_ema21,
            }

    return None


def _count_crosses(df: pd.DataFrame, lookback: int = 15) -> int:
    """Conta o numero de cruzamentos EMA9/EMA21 nos ultimos N candles."""
    start_idx = max(1, len(df) - lookback - 1)
    count = 0

    for i in range(start_idx + 1, len(df) - 1):
        curr_ema9 = df["ema9"].iloc[i]
        curr_ema21 = df["ema21"].iloc[i]
        prev_ema9 = df["ema9"].iloc[i - 1]
        prev_ema21 = df["ema21"].iloc[i - 1]

        if any(pd.isna(v) for v in [curr_ema9, curr_ema21, prev_ema9, prev_ema21]):
            continue

        # Qualquer cruzamento
        if (prev_ema9 <= prev_ema21 and curr_ema9 > curr_ema21) or \
           (prev_ema9 >= prev_ema21 and curr_ema9 < curr_ema21):
            count += 1

    return count


def _is_in_retest_zone(row: pd.Series, direction: Direction) -> bool:
    """
    Verifica se o candle esta na zona de retest entre EMA9 e EMA21.
    """
    ema9 = row["ema9"]
    ema21 = row["ema21"]
    low = row["low"]
    high = row["high"]
    close = row["close"]

    if any(pd.isna(v) for v in [ema9, ema21]):
        return False

    if direction == Direction.LONG:
        # O preco deve ter recuado ate a zona EMA9-EMA21
        # O low do candle toca ou penetra a zona entre as EMAs
        zone_top = max(ema9, ema21)
        zone_bottom = min(ema9, ema21)
        return low <= zone_top and close >= ema9
    else:
        zone_top = max(ema9, ema21)
        zone_bottom = min(ema9, ema21)
        return high >= zone_bottom and close <= ema9


def analyze(
    symbol: str,
    config: ScalpingConfig,
    df_3m: Optional[pd.DataFrame] = None,
    df_15m: Optional[pd.DataFrame] = None,
) -> Signal:
    """
    Analisa condicoes de EMA Crossover com retest.

    Parametros:
        symbol: par de trading
        config: configuracao da estrategia
        df_3m: DataFrame 3m com indicadores
        df_15m: DataFrame 15m com indicadores (filtro de tendencia)

    Retorna:
        Signal com direcao, forca e niveis de SL/TP
    """
    now_str = datetime.now().isoformat()
    neutral = Signal(
        direction=Direction.NEUTRAL, strength=0.0, timestamp=now_str,
        source="ema_crossover", symbol=symbol, price=0.0,
        valid=False, reason="Sem sinal"
    )

    # Buscar dados se nao fornecidos
    if df_3m is None:
        df_3m = fetch_candles(symbol, "3m", 100)
        if df_3m is not None:
            df_3m = add_scalping_indicators(df_3m)

    if df_3m is None or len(df_3m) < 50:
        neutral.reason = "Dados 3m insuficientes"
        logger.warning("EMA %s: %s", symbol, neutral.reason)
        return neutral

    last = df_3m.iloc[-2]  # ultimo candle fechado
    price = last["close"]
    neutral.price = price

    # ============================================================
    # CONDICAO 1: Encontrar cruzamento recente de EMA9/EMA21
    # ============================================================
    cross = _find_recent_cross(df_3m, lookback=15)

    if cross is None:
        neutral.reason = "Nenhum cruzamento EMA9/EMA21 nos ultimos 15 candles"
        logger.info("EMA %s: %s", symbol, neutral.reason)
        return neutral

    direction = cross["direction"]
    candles_since_cross = cross["candles_ago"]

    logger.info(
        "EMA %s: Cruzamento %s encontrado ha %d candles",
        symbol, direction.value, candles_since_cross
    )

    # ============================================================
    # FILTRO: Sem retest em 5 candles (muito longe)
    # ============================================================
    if candles_since_cross > config.ema_max_retest_candles:
        neutral.reason = f"Cruzamento ha {candles_since_cross} candles > max {config.ema_max_retest_candles}"
        logger.info("EMA %s: %s", symbol, neutral.reason)
        return neutral

    # ============================================================
    # FILTRO: Gap EMA9-EMA21 > 0.3% no cruzamento (exaustao)
    # ============================================================
    ema9_cross = cross["ema9_at_cross"]
    ema21_cross = cross["ema21_at_cross"]
    gap_pct = 0.0
    if ema21_cross > 0:
        gap_pct = abs(ema9_cross - ema21_cross) / ema21_cross * 100
        if gap_pct > config.ema_max_gap_pct:
            neutral.reason = f"Gap no cruzamento {gap_pct:.2f}% > {config.ema_max_gap_pct}% (exaustao)"
            logger.info("EMA %s: %s", symbol, neutral.reason)
            return neutral

    # ============================================================
    # FILTRO: > 3 cruzamentos em 15 candles (choppy)
    # ============================================================
    total_crosses = _count_crosses(df_3m, lookback=15)
    if total_crosses > config.ema_max_crosses_15:
        neutral.reason = f"{total_crosses} cruzamentos em 15 candles > {config.ema_max_crosses_15} (choppy)"
        logger.warning("EMA %s: %s", symbol, neutral.reason)
        return neutral

    # ============================================================
    # CONDICAO 2+3: Preco recuou ate zona EMA9-EMA21 e fecha acima da EMA9
    # ============================================================
    if not _is_in_retest_zone(last, direction):
        neutral.reason = f"Nao esta em zona de retest (EMA9-EMA21)"
        logger.info("EMA %s: %s", symbol, neutral.reason)
        return neutral

    logger.info("EMA %s: Retest na zona EMA9-EMA21 confirmado", symbol)

    # ============================================================
    # CONDICAO 4: EMA21 inclinando na direcao certa
    # ============================================================
    slope_lookback = config.ema_slope_lookback
    if len(df_3m) > slope_lookback + 2:
        ema21_now = last["ema21"]
        ema21_back = df_3m["ema21"].iloc[-2 - slope_lookback]

        if pd.isna(ema21_now) or pd.isna(ema21_back):
            neutral.reason = "EMA21 slope indisponivel"
            return neutral

        if direction == Direction.LONG and ema21_now <= ema21_back:
            neutral.reason = f"EMA21 nao subindo: {ema21_now:.4f} <= {ema21_back:.4f} ({slope_lookback} candles atras)"
            logger.info("EMA %s: %s", symbol, neutral.reason)
            return neutral

        if direction == Direction.SHORT and ema21_now >= ema21_back:
            neutral.reason = f"EMA21 nao caindo: {ema21_now:.4f} >= {ema21_back:.4f} ({slope_lookback} candles atras)"
            logger.info("EMA %s: %s", symbol, neutral.reason)
            return neutral

    # ============================================================
    # CONDICAO 5: EMA50 no 15m alinhada
    # ============================================================
    if df_15m is not None and len(df_15m) > 50:
        ema50_15m = df_15m["ema50"].iloc[-2]
        price_15m = df_15m["close"].iloc[-2]

        if not pd.isna(ema50_15m):
            if direction == Direction.LONG and price_15m < ema50_15m:
                neutral.reason = f"LONG mas preco 15m {price_15m:.2f} abaixo da EMA50 {ema50_15m:.2f}"
                logger.info("EMA %s: %s", symbol, neutral.reason)
                return neutral

            if direction == Direction.SHORT and price_15m > ema50_15m:
                neutral.reason = f"SHORT mas preco 15m {price_15m:.2f} acima da EMA50 {ema50_15m:.2f}"
                logger.info("EMA %s: %s", symbol, neutral.reason)
                return neutral

        # FILTRO: EMAs entrelaçadas no 15m (distancia < 0.1%)
        ema9_15m = df_15m["ema9"].iloc[-2]
        ema21_15m = df_15m["ema21"].iloc[-2]
        if not pd.isna(ema9_15m) and not pd.isna(ema21_15m) and ema21_15m > 0:
            dist_15m = abs(ema9_15m - ema21_15m) / ema21_15m * 100
            if dist_15m < config.ema_htf_entangle_pct:
                neutral.reason = f"EMAs entrelaçadas no 15m: distancia {dist_15m:.3f}% < {config.ema_htf_entangle_pct}%"
                logger.warning("EMA %s: %s", symbol, neutral.reason)
                return neutral

    # ============================================================
    # CALCULAR NIVEIS DE SL / TP
    # ============================================================
    atr14 = last["atr14"]
    ema21 = last["ema21"]

    if pd.isna(atr14) or atr14 == 0 or pd.isna(ema21):
        neutral.reason = "ATR14 ou EMA21 indisponivel"
        return neutral

    entry_price = price

    # Buffer de slippage: alarga SL e reduz TP
    slip = entry_price * (config.slippage_pct / 100)

    if direction == Direction.LONG:
        # SL = abaixo da EMA21 - 0.2 x ATR14 - slippage
        sl_price = ema21 - (config.ema_sl_atr_mult * atr14) - slip
        tp1_price = entry_price + (config.ema_tp1_atr_mult * atr14) - slip

        # TP2: high dos ultimos 20 candles OU 2.5 x ATR14, o menor (- slippage)
        high_20 = last.get("high_20", None)
        tp2_atr = entry_price + (config.ema_tp2_atr_mult * atr14) - slip
        if high_20 is not None and not pd.isna(high_20) and high_20 > entry_price:
            tp2_price = min(high_20 - slip, tp2_atr)
        else:
            tp2_price = tp2_atr
    else:
        sl_price = ema21 + (config.ema_sl_atr_mult * atr14) + slip
        tp1_price = entry_price - (config.ema_tp1_atr_mult * atr14) + slip

        low_20 = last.get("low_20", None)
        tp2_atr = entry_price - (config.ema_tp2_atr_mult * atr14) + slip
        if low_20 is not None and not pd.isna(low_20) and low_20 < entry_price:
            tp2_price = max(low_20 + slip, tp2_atr)
        else:
            tp2_price = tp2_atr

    # Distancia do SL em %
    sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100

    # Verificar distancia maxima
    if sl_distance_pct > config.max_sl_ema_crossover:
        neutral.reason = f"SL muito distante: {sl_distance_pct:.2f}% > {config.max_sl_ema_crossover}%"
        logger.warning("EMA %s: %s", symbol, neutral.reason)
        return neutral

    # Calcular RR
    sl_distance = abs(entry_price - sl_price)
    tp2_distance = abs(tp2_price - entry_price)

    if sl_distance == 0:
        neutral.reason = "SL distance zero"
        return neutral

    rr_ratio = tp2_distance / sl_distance

    if rr_ratio < config.min_rr_ema_crossover:
        neutral.reason = f"RR insuficiente: {rr_ratio:.2f} < {config.min_rr_ema_crossover}"
        logger.info("EMA %s: %s", symbol, neutral.reason)
        return neutral

    # ============================================================
    # SINAL VALIDO
    # ============================================================
    # Strength: baseado na qualidade do retest e slope da EMA21
    ema21_slope = abs(last["ema21"] - df_3m["ema21"].iloc[-2 - slope_lookback])
    slope_normalized = min(ema21_slope / (price * 0.001), 1.0)  # normalizar vs 0.1% do preco

    strength = min(0.4 + slope_normalized * 0.3 + (1 - candles_since_cross / config.ema_max_retest_candles) * 0.3, 1.0)
    strength = max(0.3, strength)

    signal = Signal(
        direction=direction,
        strength=round(strength, 2),
        timestamp=now_str,
        source="ema_crossover",
        symbol=symbol,
        price=price,
        entry_price=round(entry_price, 8),
        sl_price=round(sl_price, 8),
        tp1_price=round(tp1_price, 8),
        tp2_price=round(tp2_price, 8),
        sl_distance_pct=round(sl_distance_pct, 4),
        rr_ratio=round(rr_ratio, 2),
        valid=True,
        reason=(
            f"EMA Crossover {direction.value}: retest {candles_since_cross}c ago, "
            f"crosses={total_crosses}, RR {rr_ratio:.1f}"
        ),
        metadata={
            "candles_since_cross": candles_since_cross,
            "total_crosses_15c": total_crosses,
            "ema9": round(last["ema9"], 8),
            "ema21": round(ema21, 8),
            "ema21_slope_up": direction == Direction.LONG,
            "cross_gap_pct": round(gap_pct, 4),
        },
    )

    logger.info(
        "EMA %s: SINAL %s | Forca: %.2f | Entry: %.4f | SL: %.4f (%.2f%%) | "
        "TP1: %.4f | TP2: %.4f | RR: %.2f | Cross %d candles atras",
        symbol, direction.value, strength, entry_price, sl_price,
        sl_distance_pct, tp1_price, tp2_price, rr_ratio, candles_since_cross
    )

    return signal
