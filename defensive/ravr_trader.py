"""RAVR (Regime-Aware Value Reversion) — primary V1 strategy.

Mean reversion filtered by regime: enter when price deviates significantly
from rolling VWAP (z-score >= threshold) in permissive regime.
Exit targets based on return-to-value (VWAP), not generic ATR multiples.

Edge hypothesis: in calm markets, price tends to revert to VWAP when
displaced by >= 2 standard deviations. The exit aligns with the thesis.
"""
from __future__ import annotations

import pandas as pd

from defensive.config import DefensiveConfig
from defensive.enums import PERMISSIVE_REGIMES, Direction, Outcome, Regime, Session, Strategy
from defensive.models import TradeDecision
from defensive.value_reference import compute_value_metrics


def evaluate_ravr(
    candles_15m: pd.DataFrame,
    regime: Regime,
    session: Session,
    config: DefensiveConfig,
    *,
    symbol: str = "",
    cycle_id: str = "",
    timestamp: str = "",
) -> TradeDecision:
    """Evaluate RAVR signal on current candle set.

    Pipeline:
      1. Regime gate (must be permissive)
      2. Compute z-score from VWAP
      3. If |z-score| >= threshold -> entry in reversion direction
      4. TP1 = VWAP (return to value), TP2 = extension beyond VWAP
      5. SL = structural via ATR

    Returns:
        TradeDecision with outcome TRADE or rejection reason.
    """
    decision = TradeDecision(
        strategy=Strategy.RAVR,
        symbol=symbol,
        cycle_id=cycle_id,
        timestamp=timestamp,
        regime=regime,
        session=session,
    )

    # --- Gate 1: Regime ---
    if regime not in PERMISSIVE_REGIMES:
        decision.outcome = Outcome.REGIME_BLOCKED
        return decision

    # --- Gate 2: Sufficient data ---
    if len(candles_15m) < 100:
        decision.outcome = Outcome.ERROR
        return decision

    # --- Compute value metrics ---
    vm = compute_value_metrics(candles_15m, vwap_period=config.ravr_vwap_period)

    decision.z_score = vm.z_score
    decision.vwap_distance_pct = (
        abs(vm.vwap - float(candles_15m["close"].iloc[-1])) / vm.vwap * 100
        if vm.vwap > 0 else 0.0
    )

    # --- Gate 3: Z-score threshold ---
    if abs(vm.z_score) < config.ravr_zscore_threshold:
        decision.outcome = Outcome.ZSCORE_INSUFFICIENT
        return decision

    # --- Direction: revert toward VWAP ---
    last_close = float(candles_15m["close"].iloc[-1])
    vwap = vm.vwap

    if vm.z_score > 0:
        # Price above VWAP -> expect reversion down -> SHORT
        direction = Direction.SHORT
    else:
        # Price below VWAP -> expect reversion up -> LONG
        direction = Direction.LONG

    decision.direction = direction
    decision.outcome = Outcome.TRADE

    # --- SL: structural via ATR ---
    atr = vm.atr if vm.atr > 0 else last_close * 0.005
    sl_distance = max(
        atr * config.atr_sl_multiplier,
        last_close * config.atr_sl_floor_pct / 100,
    )

    # --- TP: configurable via ravr_tp1_mode ---
    vwap_distance = abs(last_close - vwap)

    if config.ravr_tp1_mode == "rr":
        # TP1 = multiple of SL distance (e.g. 1R)
        tp1_distance = sl_distance * config.ravr_tp1_rr_mult
    else:
        # TP1 = fraction of VWAP distance (1.0=full VWAP, 0.4=40%)
        tp1_distance = vwap_distance * config.ravr_tp1_vwap_frac
        # Floor: at least sl_distance to avoid tiny targets
        tp1_distance = max(tp1_distance, sl_distance)

    # TP2 = fraction of VWAP distance
    tp2_distance = vwap_distance * config.ravr_tp2_vwap_frac
    tp2_distance = max(tp2_distance, tp1_distance * 1.1)  # TP2 always beyond TP1

    if direction == Direction.LONG:
        decision.entry_price = last_close
        decision.sl_price = last_close - sl_distance
        decision.tp1_price = last_close + tp1_distance
        decision.tp2_price = last_close + tp2_distance
    else:  # SHORT
        decision.entry_price = last_close
        decision.sl_price = last_close + sl_distance
        decision.tp1_price = last_close - tp1_distance
        decision.tp2_price = last_close - tp2_distance

    return decision
