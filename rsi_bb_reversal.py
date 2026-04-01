"""
Motor 2 -- Reversao por RSI + Bollinger Bands.

Quando o preco toca/perfura a banda externa de Bollinger com RSI em zona
extrema, ha alta probabilidade de reversao para a media.

Timeframes:
- Entrada: 5m
- Contexto: 15m
- Gestao: 1m

Condicoes de entrada LONG (reversao de sobrevenda):
1. RSI(14) <= 32
2. Candle fecha abaixo da BB inferior (20, 2.0)
3. Candle seguinte abre acima da BB inferior (pullback confirmado)
4. RSI subindo vs candle anterior
5. Volume >= 1.5x media 20

Filtros:
- Tendencia forte no 15m contra direcao (EMA9 vs EMA21)
- RSI em extremo > 6 candles consecutivos
- BB bandwidth < 0.8%
- 3o toque na banda sem bounce
- ATR(14) 5m < 0.10%

SL: Min dos ultimos 3 candles - 0.3 x ATR14, max 0.6%
TP1 (50%): SMA20 (media BB)
TP2 (50%): Banda oposta
RR minimo >= 1.5 (contra TP1)
"""
import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from signal_types import Direction, Signal, ScalpingConfig
from scalping_data import fetch_candles, add_scalping_indicators

logger = logging.getLogger("scalping.rsi_bb")


def _count_extreme_rsi_candles(df: pd.DataFrame, threshold: float, above: bool) -> int:
    """
    Conta quantos candles consecutivos (antes do atual) tem RSI em zona extrema.

    Se above=True, conta RSI >= threshold (sobrecompra).
    Se above=False, conta RSI <= threshold (sobrevenda).
    """
    count = 0
    for i in range(len(df) - 2, max(0, len(df) - 20), -1):
        rsi = df["rsi"].iloc[i]
        if pd.isna(rsi):
            break
        if above and rsi >= threshold:
            count += 1
        elif not above and rsi <= threshold:
            count += 1
        else:
            break
    return count


def _count_band_touches(df: pd.DataFrame, direction: Direction, lookback: int = 10) -> int:
    """
    Conta quantos toques na banda de Bollinger ocorreram sem bounce nos ultimos N candles.
    """
    count = 0
    for i in range(len(df) - 2, max(0, len(df) - lookback - 2), -1):
        row = df.iloc[i]
        if pd.isna(row["bb_lower"]) or pd.isna(row["bb_upper"]):
            continue

        if direction == Direction.LONG:
            # Toque na banda inferior
            if row["close"] <= row["bb_lower"] or row["low"] <= row["bb_lower"]:
                count += 1
        else:
            # Toque na banda superior
            if row["close"] >= row["bb_upper"] or row["high"] >= row["bb_upper"]:
                count += 1
    return count


def analyze(
    symbol: str,
    config: ScalpingConfig,
    df_5m: Optional[pd.DataFrame] = None,
    df_15m: Optional[pd.DataFrame] = None,
) -> Signal:
    """
    Analisa condicoes de RSI + Bollinger Bands Reversal.

    Parametros:
        symbol: par de trading
        config: configuracao da estrategia
        df_5m: DataFrame 5m com indicadores (se None, busca da API)
        df_15m: DataFrame 15m com indicadores (para filtro de tendencia)

    Retorna:
        Signal com direcao, forca e niveis de SL/TP
    """
    now_str = datetime.now().isoformat()
    neutral = Signal(
        direction=Direction.NEUTRAL, strength=0.0, timestamp=now_str,
        source="rsi_bb_reversal", symbol=symbol, price=0.0,
        valid=False, reason="Sem sinal"
    )

    # Buscar dados se nao fornecidos
    if df_5m is None:
        df_5m = fetch_candles(symbol, "5m", 100)
        if df_5m is not None:
            df_5m = add_scalping_indicators(df_5m)

    if df_5m is None or len(df_5m) < 50:
        neutral.reason = "Dados 5m insuficientes"
        logger.warning("RSI_BB %s: %s", symbol, neutral.reason)
        return neutral

    # Candle de sinal (ultimo fechado) e candle de confirmacao
    signal_candle = df_5m.iloc[-2]   # candle que tocou a banda (ultimo fechado)
    confirm_candle = df_5m.iloc[-1]  # candle atual (confirmacao)
    prev_candle = df_5m.iloc[-3]     # candle anterior ao sinal (para comparar RSI)

    price = confirm_candle["close"]
    neutral.price = price

    # ============================================================
    # CONDICAO 1: RSI(14) em zona extrema
    # ============================================================
    rsi_signal = signal_candle["rsi"]
    if pd.isna(rsi_signal):
        neutral.reason = "RSI indisponivel"
        return neutral

    is_oversold = rsi_signal <= config.rsi_oversold
    is_overbought = rsi_signal >= config.rsi_overbought

    if not is_oversold and not is_overbought:
        neutral.reason = f"RSI {rsi_signal:.1f} nao em extremo (sobrevenda <= {config.rsi_oversold}, sobrecompra >= {config.rsi_overbought})"
        logger.info("RSI_BB %s: %s", symbol, neutral.reason)
        return neutral

    direction = Direction.LONG if is_oversold else Direction.SHORT
    logger.info("RSI_BB %s: RSI %.1f em zona extrema (%s)", symbol, rsi_signal, direction.value)

    # ============================================================
    # CONDICAO 2: Candle fecha abaixo da BB inferior (LONG) / acima BB superior (SHORT)
    # ============================================================
    if direction == Direction.LONG:
        bb_band = signal_candle["bb_lower"]
        if pd.isna(bb_band) or signal_candle["close"] > bb_band:
            neutral.reason = f"LONG: close {signal_candle['close']:.4f} acima da BB inferior {bb_band:.4f}"
            logger.info("RSI_BB %s: %s", symbol, neutral.reason)
            return neutral
    else:
        bb_band = signal_candle["bb_upper"]
        if pd.isna(bb_band) or signal_candle["close"] < bb_band:
            neutral.reason = f"SHORT: close {signal_candle['close']:.4f} abaixo da BB superior {bb_band:.4f}"
            logger.info("RSI_BB %s: %s", symbol, neutral.reason)
            return neutral

    logger.info("RSI_BB %s: Toque na banda confirmado", symbol)

    # ============================================================
    # CONDICAO 3: Candle seguinte abre acima da banda (pullback confirmado)
    # ============================================================
    if direction == Direction.LONG:
        bb_lower_confirm = confirm_candle["bb_lower"]
        if pd.isna(bb_lower_confirm) or confirm_candle["open"] < bb_lower_confirm:
            neutral.reason = "Pullback nao confirmado: candle de confirmacao abriu abaixo da BB inferior"
            logger.info("RSI_BB %s: %s", symbol, neutral.reason)
            return neutral
    else:
        bb_upper_confirm = confirm_candle["bb_upper"]
        if pd.isna(bb_upper_confirm) or confirm_candle["open"] > bb_upper_confirm:
            neutral.reason = "Pullback nao confirmado: candle de confirmacao abriu acima da BB superior"
            logger.info("RSI_BB %s: %s", symbol, neutral.reason)
            return neutral

    logger.info("RSI_BB %s: Pullback confirmado", symbol)

    # ============================================================
    # CONDICAO 4: RSI subindo vs candle anterior (LONG) / caindo (SHORT)
    # ============================================================
    rsi_confirm = confirm_candle["rsi"]
    rsi_prev = prev_candle["rsi"]

    if pd.isna(rsi_confirm) or pd.isna(rsi_prev):
        neutral.reason = "RSI de confirmacao indisponivel"
        return neutral

    if direction == Direction.LONG and rsi_confirm <= rsi_signal:
        neutral.reason = f"RSI nao subindo: confirm {rsi_confirm:.1f} <= signal {rsi_signal:.1f}"
        logger.info("RSI_BB %s: %s", symbol, neutral.reason)
        return neutral

    if direction == Direction.SHORT and rsi_confirm >= rsi_signal:
        neutral.reason = f"RSI nao caindo: confirm {rsi_confirm:.1f} >= signal {rsi_signal:.1f}"
        logger.info("RSI_BB %s: %s", symbol, neutral.reason)
        return neutral

    # ============================================================
    # CONDICAO 5: Volume >= 1.5x media 20
    # ============================================================
    vol_avg = df_5m["volume_avg20"].iloc[-2]
    if vol_avg is None or vol_avg == 0 or pd.isna(vol_avg):
        neutral.reason = "Volume medio indisponivel"
        return neutral

    volume_ratio = confirm_candle["volume"] / vol_avg
    if volume_ratio < config.rsi_bb_vol_multiplier:
        neutral.reason = f"Volume ratio {volume_ratio:.2f}x < {config.rsi_bb_vol_multiplier}x"
        logger.info("RSI_BB %s: %s", symbol, neutral.reason)
        return neutral

    logger.info("RSI_BB %s: Volume de reversao confirmado: %.2fx", symbol, volume_ratio)

    # ============================================================
    # FILTROS
    # ============================================================

    # Filtro: Tendencia forte no 15m contra direcao
    if df_15m is not None and len(df_15m) > 21:
        ema9_15m = df_15m["ema9"].iloc[-2]
        ema21_15m = df_15m["ema21"].iloc[-2]
        if not pd.isna(ema9_15m) and not pd.isna(ema21_15m):
            if direction == Direction.LONG and ema9_15m < ema21_15m:
                # Tendencia de baixa no 15m, LONG e contra tendencia
                # Mas permitimos se o RSI estiver MUITO extremo
                if rsi_signal > config.rsi_oversold - 5:  # nao tao extremo
                    neutral.reason = "Contra tendencia 15m (baixa) e RSI nao suficientemente extremo"
                    logger.warning("RSI_BB %s: %s", symbol, neutral.reason)
                    return neutral

            if direction == Direction.SHORT and ema9_15m > ema21_15m:
                if rsi_signal < config.rsi_overbought + 5:
                    neutral.reason = "Contra tendencia 15m (alta) e RSI nao suficientemente extremo"
                    logger.warning("RSI_BB %s: %s", symbol, neutral.reason)
                    return neutral

    # Filtro: RSI em extremo > 6 candles consecutivos (tendencia, nao excesso)
    if direction == Direction.LONG:
        extreme_count = _count_extreme_rsi_candles(df_5m, config.rsi_oversold, above=False)
    else:
        extreme_count = _count_extreme_rsi_candles(df_5m, config.rsi_overbought, above=True)

    if extreme_count > config.rsi_max_extreme_candles:
        neutral.reason = f"RSI em extremo por {extreme_count} candles > {config.rsi_max_extreme_candles} (tendencia)"
        logger.warning("RSI_BB %s: %s", symbol, neutral.reason)
        return neutral

    # Filtro: BB bandwidth < 0.8% (bandas comprimidas)
    bb_bandwidth = df_5m["bb_bandwidth"].iloc[-2]
    bb_middle = df_5m["bb_middle"].iloc[-2]
    bandwidth_pct = 0.0
    if not pd.isna(bb_bandwidth) and not pd.isna(bb_middle) and bb_middle > 0:
        bandwidth_pct = bb_bandwidth * 100
        if bandwidth_pct < config.rsi_bb_bandwidth_min:
            neutral.reason = f"BB bandwidth {bandwidth_pct:.2f}% < {config.rsi_bb_bandwidth_min}%"
            logger.warning("RSI_BB %s: %s", symbol, neutral.reason)
            return neutral

    # Filtro: 3o toque na banda sem bounce
    band_touches = _count_band_touches(df_5m, direction, lookback=10)
    if band_touches > config.rsi_bb_max_touches:
        neutral.reason = f"Toque #{band_touches} na banda (> {config.rsi_bb_max_touches}) - surfando a banda"
        logger.warning("RSI_BB %s: %s", symbol, neutral.reason)
        return neutral

    # Filtro: ATR(14) 5m < 0.10%
    atr14 = df_5m["atr14"].iloc[-2]
    if not pd.isna(atr14) and price > 0:
        atr_pct = (atr14 / price) * 100
        if atr_pct < config.rsi_bb_atr_min_pct:
            neutral.reason = f"ATR 5m muito baixo: {atr_pct:.3f}% < {config.rsi_bb_atr_min_pct}%"
            logger.warning("RSI_BB %s: %s", symbol, neutral.reason)
            return neutral

    # ============================================================
    # CALCULAR NIVEIS DE SL / TP
    # ============================================================
    if pd.isna(atr14) or atr14 == 0:
        neutral.reason = "ATR14 indisponivel para calcular SL/TP"
        return neutral

    entry_price = price

    # Buffer de slippage: alarga SL e reduz TP
    slip = entry_price * (config.slippage_pct / 100)

    if direction == Direction.LONG:
        # SL = Min dos ultimos 3 candles - 0.3 x ATR14 - slippage
        low_3 = df_5m["low_3"].iloc[-2]
        if pd.isna(low_3):
            low_3 = min(df_5m["low"].iloc[-4:-1])
        sl_price = low_3 - (config.rsi_bb_sl_atr_mult * atr14) - slip
        tp1_price = confirm_candle["bb_middle"] - slip   # SMA20 = media BB
        tp2_price = confirm_candle["bb_upper"] - slip     # Banda oposta
    else:
        # SL = Max dos ultimos 3 candles + 0.3 x ATR14 + slippage
        high_3 = df_5m["high_3"].iloc[-2]
        if pd.isna(high_3):
            high_3 = max(df_5m["high"].iloc[-4:-1])
        sl_price = high_3 + (config.rsi_bb_sl_atr_mult * atr14) + slip
        tp1_price = confirm_candle["bb_middle"] + slip    # SMA20
        tp2_price = confirm_candle["bb_lower"] + slip      # Banda oposta

    if pd.isna(tp1_price) or pd.isna(tp2_price):
        neutral.reason = "TP (BB middle/banda oposta) indisponivel"
        return neutral

    # Distancia do SL em %
    sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100

    # Verificar distancia maxima
    if sl_distance_pct > config.max_sl_rsi_bb:
        neutral.reason = f"SL muito distante: {sl_distance_pct:.2f}% > {config.max_sl_rsi_bb}%"
        logger.warning("RSI_BB %s: %s", symbol, neutral.reason)
        return neutral

    # Calcular RR contra TP1
    sl_distance = abs(entry_price - sl_price)
    tp1_distance = abs(tp1_price - entry_price)

    if sl_distance == 0:
        neutral.reason = "SL distance zero"
        return neutral

    rr_ratio = tp1_distance / sl_distance

    if rr_ratio < config.min_rr_rsi_bb:
        neutral.reason = f"RR insuficiente (vs TP1): {rr_ratio:.2f} < {config.min_rr_rsi_bb}"
        logger.info("RSI_BB %s: %s", symbol, neutral.reason)
        return neutral

    # ============================================================
    # SINAL VALIDO
    # ============================================================
    # Strength: baseado na distancia do RSI ao extremo e volume
    rsi_extreme_score = 0.0
    if direction == Direction.LONG:
        rsi_extreme_score = max(0, (config.rsi_oversold - rsi_signal) / config.rsi_oversold)
    else:
        rsi_extreme_score = max(0, (rsi_signal - config.rsi_overbought) / (100 - config.rsi_overbought))

    vol_score = min((volume_ratio - config.rsi_bb_vol_multiplier) / config.rsi_bb_vol_multiplier, 0.5)
    strength = min(0.4 + rsi_extreme_score * 0.3 + vol_score * 0.3, 1.0)
    strength = max(0.3, strength)

    signal = Signal(
        direction=direction,
        strength=round(strength, 2),
        timestamp=now_str,
        source="rsi_bb_reversal",
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
            f"RSI/BB Reversal {direction.value}: RSI {rsi_signal:.0f}, "
            f"vol {volume_ratio:.1f}x, RR {rr_ratio:.1f}"
        ),
        metadata={
            "rsi_signal": round(rsi_signal, 2),
            "rsi_confirm": round(rsi_confirm, 2),
            "volume_ratio": round(volume_ratio, 2),
            "bb_bandwidth_pct": round(bandwidth_pct, 2) if not pd.isna(bb_bandwidth) else 0,
            "band_touches": band_touches,
            "extreme_candles": extreme_count,
        },
    )

    logger.info(
        "RSI_BB %s: SINAL %s | RSI: %.1f | Forca: %.2f | Entry: %.4f | "
        "SL: %.4f (%.2f%%) | TP1: %.4f | TP2: %.4f | RR: %.2f",
        symbol, direction.value, rsi_signal, strength, entry_price,
        sl_price, sl_distance_pct, tp1_price, tp2_price, rr_ratio
    )

    return signal
