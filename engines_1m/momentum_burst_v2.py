"""Momentum Burst v2 — Break & Retest engine.

3-phase stateful detection:
  Phase 1 (SCANNING): Find support/resistance zones from swing lows/highs
  Phase 2 (BURST):    Detect momentum burst leaving the zone (no signal yet)
  Phase 3 (RETEST):   Wait for price to retest the zone with rejection candle

Entry is on the retest (near support/resistance), not on the burst.
This gives structurally favorable R:R vs v1 which enters at burst extremes.

State machine:
  SCANNING → burst detected → WAITING_RETEST → retest confirmed → Signal + reset
                                              → timeout (30 candles) → reset
                                              → invalidation (new low) → reset
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engines_1m.base import Engine1m
from signal_types import Direction, Signal


class _Phase(Enum):
    SCANNING = "scanning"
    WAITING_RETEST = "waiting_retest"


@dataclass
class _BurstState:
    phase: _Phase = _Phase.SCANNING
    direction: str = ""
    zone_low: float = 0.0
    zone_high: float = 0.0
    zone_touches: int = 0
    burst_extreme: float = 0.0  # burst_high (LONG) or burst_low (SHORT)
    candles_since_burst: int = 0

    def reset(self):
        self.phase = _Phase.SCANNING
        self.direction = ""
        self.zone_low = 0.0
        self.zone_high = 0.0
        self.zone_touches = 0
        self.burst_extreme = 0.0
        self.candles_since_burst = 0


class MomentumBurstV2(Engine1m):
    """Break & Retest: enter on retest of support/resistance after burst."""

    name = "momentum_burst_v2"
    version = "2.0.0"

    # ── Scanning params ──
    SWING_NEIGHBORS = 3          # candles each side to confirm swing
    SCAN_WINDOW = 50             # how far back to look for swings
    ZONE_CLUSTER_PCT = 0.1       # group swings within 0.1%
    MIN_TOUCHES = 2              # minimum touches to form a zone
    MAX_TOUCH_AGE = 20           # last touch must be within 20 candles

    # ── Burst params ──
    ATR_MULTIPLE_MIN = 2.0
    VOLUME_MULTIPLE_MIN = 2.0
    BODY_RATIO_MIN = 0.60
    BURST_DISTANCE_ATR = 1.5     # price must move 1.5×ATR from zone

    # ── Retest params ──
    RETEST_TOLERANCE_PCT = 0.15  # how close price must get to zone
    INVALIDATION_PCT = 0.05      # new low below this = setup dead
    REJECTION_SHADOW_RATIO = 1.5 # lower_shadow > 1.5× body
    RETEST_TIMEOUT = 30          # candles to wait for retest

    # ── Exit params ──
    SL_ATR_MULT = 0.1            # SL = swing_low - 0.1×ATR
    FIBO_TP1 = 1.272
    FIBO_TP2 = 1.618
    TP_MIN_DISTANCE_PCT = 0.2    # fallback if Fibo TP too close
    TP_FALLBACK_ATR = 2.0        # fallback TP = entry ± 2×ATR

    _MIN_CANDLES = 70            # SCAN_WINDOW + SWING_NEIGHBORS + margin

    def __init__(self):
        self._states: Dict[str, _BurstState] = {}

    def analyze(
        self,
        symbol: str,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame | None = None,
        market_data: dict | None = None,
    ) -> Optional[Signal]:
        if len(df_1m) < self._MIN_CANDLES:
            return None

        state = self._states.setdefault(symbol, _BurstState())

        # Pre-extract numpy arrays for fast access (avoid iloc in loops)
        arrays = {
            "high": df_1m["high"].values,
            "low": df_1m["low"].values,
            "open": df_1m["open"].values,
            "close": df_1m["close"].values,
            "atr14": df_1m["atr14"].values,
            "vol_ratio": df_1m["vol_ratio"].values,
            "body_ratio": df_1m["body_ratio"].values,
            "is_green": df_1m["is_green"].values,
            "lower_shadow": df_1m["lower_shadow"].values,
            "upper_shadow": df_1m["upper_shadow"].values,
        }
        n = len(df_1m)
        idx = n - 1  # last candle index

        atr = arrays["atr14"][idx]
        if np.isnan(atr) or atr <= 0:
            return None

        if state.phase == _Phase.SCANNING:
            return self._scan(symbol, df_1m, arrays, n, state)
        else:
            return self._check_retest(symbol, df_1m, arrays, n, state)

    def required_indicators(self) -> List[str]:
        return [
            "atr14", "vol_ratio", "body_ratio", "is_green",
            "lower_shadow", "upper_shadow",
        ]

    def reset_state(self, symbol: str | None = None):
        """Reset engine state. Call between backtest runs."""
        if symbol:
            if symbol in self._states:
                self._states[symbol].reset()
        else:
            self._states.clear()

    # ── Phase 1+2: Scan for zones and burst ────────────────────────────

    def _scan(self, symbol, df_1m, arrays, n, state):
        idx = n - 1

        # Try LONG: support zones + upward burst
        for zone in self._find_zones(arrays, n, "support"):
            if self._is_burst(arrays, idx, zone, "LONG"):
                state.phase = _Phase.WAITING_RETEST
                state.direction = "LONG"
                state.zone_low = zone["low"]
                state.zone_high = zone["high"]
                state.zone_touches = zone["touches"]
                state.burst_extreme = arrays["high"][idx]
                state.candles_since_burst = 0
                return None

        # Try SHORT: resistance zones + downward burst
        for zone in self._find_zones(arrays, n, "resistance"):
            if self._is_burst(arrays, idx, zone, "SHORT"):
                state.phase = _Phase.WAITING_RETEST
                state.direction = "SHORT"
                state.zone_low = zone["low"]
                state.zone_high = zone["high"]
                state.zone_touches = zone["touches"]
                state.burst_extreme = arrays["low"][idx]
                state.candles_since_burst = 0
                return None

        return None

    def _find_zones(self, arrays, n, zone_type: str):
        """Find support (swing lows) or resistance (swing highs) zones.

        Uses pre-extracted numpy arrays for fast access.
        """
        nb = self.SWING_NEIGHBORS
        prices = arrays["low"] if zone_type == "support" else arrays["high"]

        start = max(nb, n - self.SCAN_WINDOW - nb)
        end = n - nb

        swings = []
        for j in range(start, end):
            pj = prices[j]
            is_swing = True
            for k in range(1, nb + 1):
                if zone_type == "support":
                    if pj >= prices[j - k] or pj >= prices[j + k]:
                        is_swing = False
                        break
                else:
                    if pj <= prices[j - k] or pj <= prices[j + k]:
                        is_swing = False
                        break
            if is_swing:
                swings.append((j, float(pj)))

        if len(swings) < self.MIN_TOUCHES:
            return []

        # Group swings within ZONE_CLUSTER_PCT
        zones = []
        used = set()
        for i, (idx_i, price_i) in enumerate(swings):
            if i in used:
                continue
            group = [(idx_i, price_i)]
            used.add(i)
            for j, (idx_j, price_j) in enumerate(swings):
                if j in used:
                    continue
                if abs(price_j - price_i) / price_i * 100 < self.ZONE_CLUSTER_PCT:
                    group.append((idx_j, price_j))
                    used.add(j)

            if len(group) >= self.MIN_TOUCHES:
                group_prices = [g[1] for g in group]
                indices = [g[0] for g in group]
                last_touch_age = (n - 1) - max(indices)
                if last_touch_age <= self.MAX_TOUCH_AGE:
                    zones.append({
                        "low": min(group_prices),
                        "high": max(group_prices),
                        "touches": len(group),
                        "last_touch_idx": max(indices),
                    })

        zones.sort(key=lambda z: -z["touches"])
        return zones

    def _is_burst(self, arrays, idx, zone, direction: str) -> bool:
        """Check if candle at idx is a burst leaving the zone."""
        atr = arrays["atr14"][idx]
        if np.isnan(atr) or atr <= 0:
            return False

        candle_range = arrays["high"][idx] - arrays["low"][idx]
        if candle_range < self.ATR_MULTIPLE_MIN * atr:
            return False

        vol_ratio = arrays["vol_ratio"][idx]
        if np.isnan(vol_ratio) or vol_ratio < self.VOLUME_MULTIPLE_MIN:
            return False

        body_ratio = arrays["body_ratio"][idx]
        if np.isnan(body_ratio) or body_ratio < self.BODY_RATIO_MIN:
            return False

        if direction == "LONG":
            if not arrays["is_green"][idx]:
                return False
            if arrays["close"][idx] < zone["high"] + self.BURST_DISTANCE_ATR * atr:
                return False
        else:
            if arrays["is_green"][idx]:
                return False
            if arrays["close"][idx] > zone["low"] - self.BURST_DISTANCE_ATR * atr:
                return False

        return True

    # ── Phase 3: Wait for retest ───────────────────────────────────────

    def _check_retest(self, symbol, df_1m, arrays, n, state):
        state.candles_since_burst += 1
        idx = n - 1
        atr = arrays["atr14"][idx]

        # Timeout
        if state.candles_since_burst > self.RETEST_TIMEOUT:
            state.reset()
            return None

        # Track burst extreme extending on subsequent candles
        if state.direction == "LONG" and arrays["high"][idx] > state.burst_extreme:
            state.burst_extreme = float(arrays["high"][idx])
        elif state.direction == "SHORT" and arrays["low"][idx] < state.burst_extreme:
            state.burst_extreme = float(arrays["low"][idx])

        # Invalidation: new extreme beyond zone
        if state.direction == "LONG":
            if arrays["low"][idx] < state.zone_low * (1 - self.INVALIDATION_PCT / 100):
                state.reset()
                return None
        else:
            if arrays["high"][idx] > state.zone_high * (1 + self.INVALIDATION_PCT / 100):
                state.reset()
                return None

        # Check retest conditions
        if not self._is_valid_retest(arrays, idx, state):
            return None

        # Retest confirmed → generate signal and reset
        signal = self._build_signal(symbol, df_1m, arrays, n, state, atr)
        state.reset()
        return signal

    def _is_valid_retest(self, arrays, idx, state) -> bool:
        """Check if candle at idx retests zone with rejection."""
        if state.direction == "LONG":
            zone_ref = (state.zone_low + state.zone_high) / 2
            tolerance = zone_ref * self.RETEST_TOLERANCE_PCT / 100

            # Low must touch zone (within tolerance)
            if arrays["low"][idx] > state.zone_high + tolerance:
                return False

            # Rejection: lower shadow > 1.5× body
            body = abs(arrays["close"][idx] - arrays["open"][idx])
            lower_shadow = arrays["lower_shadow"][idx]
            if body > 0 and lower_shadow < self.REJECTION_SHADOW_RATIO * body:
                return False
            if body == 0 and lower_shadow == 0:
                return False

            # Close above zone
            if arrays["close"][idx] <= state.zone_high:
                return False

            return True
        else:
            zone_ref = (state.zone_low + state.zone_high) / 2
            tolerance = zone_ref * self.RETEST_TOLERANCE_PCT / 100

            # High must touch zone (within tolerance)
            if arrays["high"][idx] < state.zone_low - tolerance:
                return False

            # Rejection: upper shadow > 1.5× body
            body = abs(arrays["close"][idx] - arrays["open"][idx])
            upper_shadow = arrays["upper_shadow"][idx]
            if body > 0 and upper_shadow < self.REJECTION_SHADOW_RATIO * body:
                return False
            if body == 0 and upper_shadow == 0:
                return False

            # Close below zone
            if arrays["close"][idx] >= state.zone_low:
                return False

            return True

    # ── Signal construction ────────────────────────────────────────────

    def _build_signal(self, symbol, df_1m, arrays, n, state, atr):
        idx = n - 1
        entry_price = float(arrays["close"][idx])

        if state.direction == "LONG":
            sl_price = state.zone_low - self.SL_ATR_MULT * atr
            swing_range = state.burst_extreme - state.zone_low
            tp1_price = state.zone_low + swing_range * self.FIBO_TP1
            tp2_price = state.zone_low + swing_range * self.FIBO_TP2
        else:
            sl_price = state.zone_high + self.SL_ATR_MULT * atr
            swing_range = state.zone_high - state.burst_extreme
            tp1_price = state.zone_high - swing_range * self.FIBO_TP1
            tp2_price = state.zone_high - swing_range * self.FIBO_TP2

        # Fallback if TP1 too close to entry
        tp1_dist_pct = abs(tp1_price - entry_price) / entry_price * 100
        if tp1_dist_pct < self.TP_MIN_DISTANCE_PCT:
            if state.direction == "LONG":
                tp1_price = entry_price + self.TP_FALLBACK_ATR * atr
                tp2_price = entry_price + self.TP_FALLBACK_ATR * 1.5 * atr
            else:
                tp1_price = entry_price - self.TP_FALLBACK_ATR * atr
                tp2_price = entry_price - self.TP_FALLBACK_ATR * 1.5 * atr

        direction = Direction.LONG if state.direction == "LONG" else Direction.SHORT
        sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100
        tp_distance_pct = abs(tp1_price - entry_price) / entry_price * 100
        rr_ratio = tp_distance_pct / sl_distance_pct if sl_distance_pct > 0 else 0

        from datetime import datetime, timezone
        if "timestamp" in df_1m.columns:
            timestamp = str(df_1m["timestamp"].iloc[-1])
        else:
            timestamp = datetime.now(timezone.utc).isoformat()

        return Signal(
            direction=direction,
            strength=0.7,
            timestamp=timestamp,
            source=self.name,
            symbol=symbol,
            price=entry_price,
            entry_price=entry_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            sl_distance_pct=sl_distance_pct,
            rr_ratio=rr_ratio,
            valid=True,
            reason="Break & Retest confirmed",
            metadata={
                "zone_low": round(state.zone_low, 8),
                "zone_high": round(state.zone_high, 8),
                "zone_touches": state.zone_touches,
                "burst_extreme": round(state.burst_extreme, 8),
                "swing_range_pct": round(swing_range / entry_price * 100, 4),
                "candles_since_burst": state.candles_since_burst,
            },
        )
