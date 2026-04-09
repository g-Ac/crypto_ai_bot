"""
Execution Layer — calcula niveis de entrada/SL/TP para motores V2.

Os motores de microestrutura (funding, liquidation, basis) geram direcao e score
mas NAO geram niveis de preco. Esta camada recebe o sinal da confluence e calcula
entry, SL, TP1, TP2 usando ATR dos candles 5m.

Regras:
  - Entry: close do ultimo candle fechado (entrada no proximo open)
  - SL: entry -/+ ATR14 * ATR_SL_MULTIPLIER (floor: ATR_SL_FLOOR_PCT)
  - TP1: entry +/- ATR14 * 1.5 (parcial 50%)
  - TP2: entry +/- ATR14 * tp_mult (ajustado pelo score do sinal)
  - Score >= 80: tp_mult = 2.5 (sinal forte)
  - Score 60-79: tp_mult = 2.0 (normal)
  - Score < 60: tp_mult = 1.5 (conservador)
"""
import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import ta

from signal_types import Direction, Signal
from config import ATR_SL_MULTIPLIER, ATR_TP_MULTIPLIER, ATR_SL_FLOOR_PCT

logger = logging.getLogger("scalping.execution")


@dataclass
class ExecutionPlan:
    """Niveis de execucao calculados para um trade."""
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    sl_distance_pct: float
    rr_ratio: float
    rr_valid: bool
    atr_value: float
    tp_multiplier: float


def _compute_atr14(candles: pd.DataFrame) -> Optional[float]:
    """Calcula ATR(14) a partir de candles OHLCV. Retorna None se insuficiente."""
    if candles is None or len(candles) < 16:
        return None
    high = candles["high"].astype(float)
    low = candles["low"].astype(float)
    close = candles["close"].astype(float)
    atr_series = ta.volatility.AverageTrueRange(
        high=high, low=low, close=close, window=14,
    ).average_true_range()
    val = atr_series.iloc[-2]  # ultimo candle fechado
    if pd.isna(val) or val <= 0:
        return None
    return float(val)


def _tp_multiplier_for_score(score: int) -> float:
    """Ajusta multiplicador de TP2 pelo score do sinal.

    O RR minimo aceitavel e 1.5. Com ATR_SL_MULTIPLIER=1.5:
      - Score >= 80: TP2 = ATR * 3.75 -> RR = 2.5
      - Score 60-79: TP2 = ATR * 3.0  -> RR = 2.0
      - Score < 60:  TP2 = ATR * 2.25 -> RR = 1.5
    """
    if score >= 80:
        return ATR_SL_MULTIPLIER * 2.5   # RR = 2.5
    elif score >= 60:
        return ATR_SL_MULTIPLIER * 2.0   # RR = 2.0
    else:
        return ATR_SL_MULTIPLIER * 1.5   # RR = 1.5


def calculate_levels(
    signal: Signal,
    candles_5m: Optional[pd.DataFrame],
    direction: Direction,
    score: int,
) -> Optional[ExecutionPlan]:
    """Calcula niveis de execucao (entry/SL/TP) via ATR.

    Args:
        signal: melhor sinal da confluence (usado para source/metadata)
        candles_5m: DataFrame OHLCV 5m para calculo de ATR e preco
        direction: direcao do trade (LONG/SHORT)
        score: score total do sinal (0-100) para ajustar TP

    Returns:
        ExecutionPlan com todos os niveis, ou None se dados insuficientes.
    """
    if direction == Direction.NEUTRAL:
        return None

    if candles_5m is None or len(candles_5m) < 2:
        logger.warning("EXEC %s: candles_5m insuficientes", signal.symbol)
        return None

    entry_price = float(candles_5m["close"].iloc[-2])  # ultimo candle fechado
    if entry_price <= 0:
        logger.warning("EXEC %s: entry_price invalido (%.4f)", signal.symbol, entry_price)
        return None

    # ATR14 com fallback para floor
    atr = _compute_atr14(candles_5m)
    floor_distance = entry_price * (ATR_SL_FLOOR_PCT / 100)

    if atr is None:
        logger.info("EXEC %s: ATR indisponivel, usando floor %.2f%%", signal.symbol, ATR_SL_FLOOR_PCT)
        atr = floor_distance / ATR_SL_MULTIPLIER

    # SL distance: ATR * multiplier, com floor minimo
    sl_distance = atr * ATR_SL_MULTIPLIER
    if sl_distance < floor_distance:
        logger.info(
            "EXEC %s: SL distance %.4f < floor %.4f (%.2f%%), usando floor",
            signal.symbol, sl_distance, floor_distance, ATR_SL_FLOOR_PCT,
        )
        sl_distance = floor_distance

    # TP multiplier ajustado pelo score
    tp_mult = _tp_multiplier_for_score(score)
    tp2_distance = atr * tp_mult
    tp1_distance = tp2_distance * 0.5  # parcial 50% no meio do caminho

    # Calcular niveis
    if direction == Direction.LONG:
        sl_price = entry_price - sl_distance
        tp1_price = entry_price + tp1_distance
        tp2_price = entry_price + tp2_distance
    else:  # SHORT
        sl_price = entry_price + sl_distance
        tp1_price = entry_price - tp1_distance
        tp2_price = entry_price - tp2_distance

    sl_distance_pct = (sl_distance / entry_price) * 100
    rr_ratio = tp2_distance / sl_distance if sl_distance > 0 else 0.0
    rr_valid = rr_ratio >= 1.5

    logger.info(
        "EXEC %s %s: entry=%.4f sl=%.4f (%.2f%%) tp1=%.4f tp2=%.4f "
        "RR=%.2f atr=%.4f tp_mult=%.1f",
        signal.symbol, direction.value, entry_price, sl_price,
        sl_distance_pct, tp1_price, tp2_price, rr_ratio, atr, tp_mult,
    )

    return ExecutionPlan(
        entry_price=entry_price,
        sl_price=sl_price,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
        sl_distance_pct=round(sl_distance_pct, 4),
        rr_ratio=round(rr_ratio, 2),
        rr_valid=rr_valid,
        atr_value=round(atr, 6),
        tp_multiplier=tp_mult,
    )


def apply_to_signal(signal: Signal, plan: ExecutionPlan) -> Signal:
    """Preenche os campos de execucao no Signal existente (mutacao in-place + retorno)."""
    signal.entry_price = plan.entry_price
    signal.sl_price = plan.sl_price
    signal.tp1_price = plan.tp1_price
    signal.tp2_price = plan.tp2_price
    signal.sl_distance_pct = plan.sl_distance_pct
    signal.rr_ratio = plan.rr_ratio
    signal.price = plan.entry_price
    return signal
