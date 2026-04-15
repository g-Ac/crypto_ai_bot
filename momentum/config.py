"""Configuration for Momentum Pullback strategy.

All v1.1 parameters are frozen — do not change without explicit approval.
v1.0 → v1.1: sl_floor raised from 0.3% to 0.5% (B1 tuning result).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class MomentumOutcome(str, Enum):
    """Outcome of a momentum pullback evaluation.

    Values are ordered by rejection priority (checked top-to-bottom).
    When multiple conditions fail simultaneously, the first match wins.
    """

    # --- Rejections (priority order) ---
    INSUFFICIENT_DATA = "insufficient_data"  # 1st: not enough candles
    REGIME_BLOCKED = "regime_blocked"         # 2nd: wrong regime
    NO_TREND = "no_trend"                     # 3rd: EMAs not aligned
    TREND_TOO_YOUNG = "trend_too_young"       # 4th: crossover too recent
    TREND_EXHAUSTION = "trend_exhaustion"     # 5th: EMAs converging
    NO_VALID_PULLBACK = "no_valid_pullback"   # 6th: pullback check failed
    NO_CONFIRMATION = "no_confirmation"       # 7th: price not back above/below EMA fast

    # --- Approved ---
    TRADE = "trade"


class MomentumDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


# Regimes that allow momentum pullback trading
MOMENTUM_PERMISSIVE_REGIMES = frozenset({"TRENDING", "WEAK_TREND"})


@dataclass
class MomentumConfig:
    """Frozen v1 parameters for Momentum Pullback.

    Do not change these without explicit approval from Gabriel.
    """

    # Trend detection
    ema_fast: int = 20
    ema_slow: int = 50
    trend_age_min: int = 5  # candles since EMA crossover

    # Pullback validation
    pullback_min_pct: float = 30.0
    pullback_max_pct: float = 70.0
    swing_lookback: int = 5

    # Exit structure
    tp2_rr_mult: float = 1.5   # TP2 = entry + 1.5 * SL distance
    timeout_candles: int = 16   # 4h in 15m candles
    sl_floor_pct: float = 0.5   # Minimum SL as % of price (v1.0=0.3, v1.1=0.5)

    # Convergence detection
    ema_convergence_lookback: int = 3  # candles to check if gap is shrinking

    # Exit tuning (v1.1 — entry logic unchanged)
    tp1_factor: float = 1.0  # TP1 = entry + factor * (impulse_end - entry). 1.0 = v1
    breakeven_trigger_pct: float = 0.0  # 0 = disabled. 0.5 = move SL to entry
                                        # after MFE reaches 50% of TP1 distance

    # Versioning
    param_version: str = "momentum-pullback-v1.1"
