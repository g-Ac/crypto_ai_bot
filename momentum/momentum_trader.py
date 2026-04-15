"""Momentum Pullback signal evaluator.

Orchestrates: trend detection → pullback validation → confirmation → signal.
Uses swing_detector and pullback_detector — no duplicated logic.

Entry hypothesis: in a confirmed trend, a pullback of 30-70% that respects
structure (EMA slow) and then resumes (close back past EMA fast) tends to
continue in the trend direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from momentum.config import (
    MOMENTUM_PERMISSIVE_REGIMES,
    MomentumConfig,
    MomentumDirection,
    MomentumOutcome,
)
from momentum.pullback_detector import (
    PullbackRejection,
    PullbackResult,
    TrendDirection,
    detect_pullback,
)
from momentum.swing_detector import SwingPoint


@dataclass(frozen=True)
class MomentumSignal:
    """Result of evaluating a momentum pullback setup."""

    outcome: MomentumOutcome
    direction: MomentumDirection

    # Entry / exit prices (populated only when outcome == TRADE)
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0

    # Diagnostics
    ema_fast_value: float = 0.0
    ema_slow_value: float = 0.0
    ema_gap_pct: float = 0.0
    retracement_pct: float = 0.0
    impulse_start_price: float = 0.0
    impulse_end_price: float = 0.0

    # Pullback detail (for audit)
    pullback_rejection: Optional[PullbackRejection] = None

    # Context
    symbol: str = ""
    regime: str = ""
    timestamp: str = ""
    param_version: str = ""


# Minimum candles needed: EMA slow (50) + some buffer for swing detection
MIN_CANDLES = 60


def evaluate_momentum_pullback(
    candles: pd.DataFrame,
    regime: str,
    config: MomentumConfig,
    *,
    symbol: str = "",
    timestamp: str = "",
) -> MomentumSignal:
    """Evaluate whether current candle set has a valid momentum pullback signal.

    Rejection priority (deterministic — first failing check wins):
      1. INSUFFICIENT_DATA
      2. REGIME_BLOCKED
      3. NO_TREND
      4. TREND_TOO_YOUNG
      5. TREND_EXHAUSTION
      6. NO_VALID_PULLBACK
      7. NO_CONFIRMATION

    Args:
        candles: DataFrame with high, low, close columns. Uses only rows
                 up to and including the last row (no lookahead).
        regime: Current market regime string (from HTF).
        config: Frozen v1 parameters.
        symbol: Trading symbol for audit trail.
        timestamp: Current timestamp for audit trail.

    Returns:
        MomentumSignal with outcome and, if TRADE, entry/SL/TP prices.
    """
    base = dict(symbol=symbol, regime=regime, timestamp=timestamp,
                param_version=config.param_version)

    # --- 1. INSUFFICIENT_DATA ---
    if len(candles) < MIN_CANDLES:
        return MomentumSignal(
            outcome=MomentumOutcome.INSUFFICIENT_DATA,
            direction=MomentumDirection.NEUTRAL,
            **base,
        )

    # --- Compute EMAs (uses only data up to current candle) ---
    closes = candles["close"].values.astype(float)
    ema_fast_arr = _ema(closes, config.ema_fast)
    ema_slow_arr = _ema(closes, config.ema_slow)

    ema_fast_now = ema_fast_arr[-1]
    ema_slow_now = ema_slow_arr[-1]
    current_close = closes[-1]

    ema_gap_pct = (ema_fast_now - ema_slow_now) / ema_slow_now * 100 if ema_slow_now != 0 else 0.0

    diag = dict(
        ema_fast_value=ema_fast_now,
        ema_slow_value=ema_slow_now,
        ema_gap_pct=ema_gap_pct,
    )

    # --- 2. REGIME_BLOCKED ---
    if regime not in MOMENTUM_PERMISSIVE_REGIMES:
        return MomentumSignal(
            outcome=MomentumOutcome.REGIME_BLOCKED,
            direction=MomentumDirection.NEUTRAL,
            **base, **diag,
        )

    # --- 3. NO_TREND ---
    if ema_fast_now > ema_slow_now:
        direction = MomentumDirection.LONG
    elif ema_fast_now < ema_slow_now:
        direction = MomentumDirection.SHORT
    else:
        return MomentumSignal(
            outcome=MomentumOutcome.NO_TREND,
            direction=MomentumDirection.NEUTRAL,
            **base, **diag,
        )

    # --- 4. TREND_TOO_YOUNG ---
    crossover_age = _crossover_age(ema_fast_arr, ema_slow_arr)
    if crossover_age < config.trend_age_min:
        return MomentumSignal(
            outcome=MomentumOutcome.TREND_TOO_YOUNG,
            direction=direction,
            **base, **diag,
        )

    # --- 5. TREND_EXHAUSTION ---
    if _emas_converging(ema_fast_arr, ema_slow_arr, config.ema_convergence_lookback):
        return MomentumSignal(
            outcome=MomentumOutcome.TREND_EXHAUSTION,
            direction=direction,
            **base, **diag,
        )

    # --- 6. NO_VALID_PULLBACK ---
    pb_direction = TrendDirection.LONG if direction == MomentumDirection.LONG else TrendDirection.SHORT

    pb_result = detect_pullback(
        candles,
        direction=pb_direction,
        ema_slow_value=ema_slow_now,
        swing_lookback=config.swing_lookback,
        min_retracement_pct=config.pullback_min_pct,
        max_retracement_pct=config.pullback_max_pct,
    )

    pb_diag = dict(
        retracement_pct=pb_result.retracement_pct,
        impulse_start_price=pb_result.impulse_start.price if pb_result.impulse_start else 0.0,
        impulse_end_price=pb_result.impulse_end.price if pb_result.impulse_end else 0.0,
        pullback_rejection=pb_result.rejection,
    )

    if not pb_result.valid:
        return MomentumSignal(
            outcome=MomentumOutcome.NO_VALID_PULLBACK,
            direction=direction,
            **base, **diag, **pb_diag,
        )

    # --- 7. NO_CONFIRMATION ---
    confirmed = _check_confirmation(direction, current_close, ema_fast_now)
    if not confirmed:
        return MomentumSignal(
            outcome=MomentumOutcome.NO_CONFIRMATION,
            direction=direction,
            **base, **diag, **pb_diag,
        )

    # --- ALL CHECKS PASSED: compute entry, SL, TP1, TP2 ---
    entry_price = current_close

    sl_price = _compute_sl(direction, pb_result, entry_price, config.sl_floor_pct)
    tp1_price = _compute_tp1(direction, pb_result, entry_price, config.tp1_factor)
    tp2_price = _compute_tp2(direction, entry_price, sl_price, config.tp2_rr_mult)

    return MomentumSignal(
        outcome=MomentumOutcome.TRADE,
        direction=direction,
        entry_price=entry_price,
        sl_price=sl_price,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
        **base, **diag, **pb_diag,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Compute EMA using pandas (no lookahead — standard causal EMA)."""
    s = pd.Series(values)
    return s.ewm(span=period, adjust=False).mean().values


def _crossover_age(ema_fast: np.ndarray, ema_slow: np.ndarray) -> int:
    """Count candles since the last EMA crossover.

    Walks backwards from the current candle. Returns the number of
    consecutive candles where the current side relationship held.
    """
    n = len(ema_fast)
    if n < 2:
        return 0

    current_above = ema_fast[-1] > ema_slow[-1]

    age = 0
    for i in range(n - 1, -1, -1):
        was_above = ema_fast[i] > ema_slow[i]
        if was_above != current_above:
            break
        age += 1

    return age


def _emas_converging(
    ema_fast: np.ndarray,
    ema_slow: np.ndarray,
    lookback: int,
) -> bool:
    """Check if the trend is exhausting by looking at EMA slow momentum.

    During a healthy pullback, the slow EMA continues moving in the trend
    direction (it's too slow to react to a short pullback). During true
    exhaustion, the slow EMA flattens or reverses.

    Compares the slow EMA's rate of change over the last `lookback`
    candles against its prior rate. If it has slowed to < 30% of its
    previous pace, the trend is dying.

    This avoids false positives during normal pullbacks where the fast
    EMA temporarily converges toward the slow EMA.
    """
    n = len(ema_slow)
    if n < 2 * lookback + 1:
        return False

    # Slow EMA slope over the last `lookback` candles
    slope_now = abs(float(ema_slow[-1] - ema_slow[-1 - lookback]))
    # Slow EMA slope over the prior `lookback` candles
    slope_before = abs(float(ema_slow[-1 - lookback] - ema_slow[-1 - 2 * lookback]))

    if slope_before < 1e-10:
        return False  # No prior movement to compare against

    # Trend is exhausting if slow EMA has slowed to < 30% of prior pace
    return (slope_now / slope_before) < 0.3


def _check_confirmation(
    direction: MomentumDirection,
    current_close: float,
    ema_fast_now: float,
) -> bool:
    """Check if price has confirmed the pullback is over.

    LONG: close >= EMA fast (price back above the fast moving average).
    SHORT: close <= EMA fast (price back below the fast moving average).
    """
    if direction == MomentumDirection.LONG:
        return current_close >= ema_fast_now
    else:
        return current_close <= ema_fast_now


def _compute_sl(
    direction: MomentumDirection,
    pb_result: PullbackResult,
    entry_price: float,
    sl_floor_pct: float,
) -> float:
    """Compute stop loss at the extreme of the pullback.

    LONG: SL below the lowest low during the pullback.
    SHORT: SL above the highest high during the pullback.

    Uses the impulse start as proxy for pullback extreme (the swing
    that defines where the retracement is measured from).

    Enforces a minimum SL distance (floor) to avoid stop on noise.
    """
    if pb_result.impulse_end is None:
        # Should not happen if pullback is valid, but defensive
        floor = entry_price * sl_floor_pct / 100
        if direction == MomentumDirection.LONG:
            return entry_price - floor
        return entry_price + floor

    # The pullback extreme is approximated by the current price
    # (which is between impulse start and end, at the retracement level).
    # But the structural SL should be at/beyond the impulse start
    # (the swing that started the impulse — if price goes past it,
    # the trend structure is broken).
    impulse_start_price = pb_result.impulse_start.price

    floor = entry_price * sl_floor_pct / 100

    if direction == MomentumDirection.LONG:
        # SL just below the swing low that started the impulse
        sl = impulse_start_price
        # Enforce floor
        max_sl = entry_price - floor
        return min(sl, max_sl)
    else:
        # SL just above the swing high that started the impulse
        sl = impulse_start_price
        min_sl = entry_price + floor
        return max(sl, min_sl)


def _compute_tp1(
    direction: MomentumDirection,
    pb_result: PullbackResult,
    entry_price: float = 0.0,
    tp1_factor: float = 1.0,
) -> float:
    """TP1 = entry + factor * (impulse_end - entry).

    factor=1.0 → full impulse end (v1 default).
    factor=0.5 → halfway between entry and impulse end.
    """
    impulse_end = pb_result.impulse_end.price
    if tp1_factor >= 1.0 or entry_price == 0.0:
        return impulse_end

    if direction == MomentumDirection.LONG:
        return entry_price + tp1_factor * (impulse_end - entry_price)
    else:
        return entry_price - tp1_factor * (entry_price - impulse_end)


def _compute_tp2(
    direction: MomentumDirection,
    entry_price: float,
    sl_price: float,
    rr_mult: float,
) -> float:
    """TP2 = entry + rr_mult * SL distance."""
    sl_distance = abs(entry_price - sl_price)

    if direction == MomentumDirection.LONG:
        return entry_price + rr_mult * sl_distance
    else:
        return entry_price - rr_mult * sl_distance
