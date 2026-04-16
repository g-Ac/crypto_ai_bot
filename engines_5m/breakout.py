"""Breakout Engine 5m — detect consolidation breakouts on 5-min candles.

Stateless, 2-phase detection per candle:
  Phase 1: Identify consolidation (tight range + BB squeeze) in last N candles
  Phase 2: Detect breakout candle (close beyond range, volume + body confirmation)

Entry on next candle open. SL at mid-range. TP by range projection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import numpy as np
import pandas as pd

from engines_5m.base import Engine5m
from signal_types import Direction, Signal


class BreakoutEngine5m(Engine5m):
    """Consolidation breakout detector for 5-min candles."""

    name = "breakout_5m"
    version = "1.0.0"

    # Consolidation params (adjusted for 5-min)
    LOOKBACK_MIN = 8              # 40 min minimum consolidation
    LOOKBACK_MAX = 15             # 75 min maximum consolidation
    RANGE_THRESHOLD_PCT = 1.5     # max range for consolidation (vs 0.3% on 1m)
    BB_BANDWIDTH_MAX = 3.0        # BB squeeze threshold (vs 1.5% on 1m)

    # Breakout params
    VOLUME_MULTIPLE_MIN = 1.8     # volume spike (vs 2.0 on 1m)
    BODY_RATIO_MIN = 0.50         # body ratio (vs 0.55 on 1m)

    # Exit params — TP as range projection multiples
    TP1_PROJECTION = 1.0          # 1:1 range projection
    TP2_PROJECTION = 2.0          # 2:1 range projection (vs 1.5 on 1m)

    _MIN_CANDLES = 30             # LOOKBACK_MAX + warmup

    def analyze(
        self,
        symbol: str,
        df_5m: pd.DataFrame,
        market_data: dict | None = None,
    ) -> Optional[Signal]:
        n = len(df_5m)
        if n < self._MIN_CANDLES:
            return None

        # Pre-extract numpy arrays for performance
        highs = df_5m["high"].values
        lows = df_5m["low"].values
        closes = df_5m["close"].values
        opens = df_5m["open"].values
        idx = n - 1  # last candle

        # Last candle indicators
        vol_ratio = df_5m["vol_ratio"].values[idx]
        body_ratio = df_5m["body_ratio"].values[idx]
        bb_bw = df_5m["bb_bandwidth"].values[idx]
        atr = df_5m["atr14"].values[idx]

        if np.isnan(atr) or atr <= 0:
            return None
        if np.isnan(vol_ratio) or np.isnan(body_ratio) or np.isnan(bb_bw):
            return None

        # Phase 2 quick checks first (cheap, filters most candles)
        if vol_ratio < self.VOLUME_MULTIPLE_MIN:
            return None
        if body_ratio < self.BODY_RATIO_MIN:
            return None

        # Try consolidation windows from LOOKBACK_MAX down to LOOKBACK_MIN
        for lookback in range(self.LOOKBACK_MAX, self.LOOKBACK_MIN - 1, -1):
            if idx < lookback:
                continue

            # Phase 1: Check consolidation in the N candles BEFORE current
            cons_start = idx - lookback
            cons_end = idx  # exclusive — current candle is the breakout, not part of consolidation

            cons_highs = highs[cons_start:cons_end]
            cons_lows = lows[cons_start:cons_end]
            max_high = float(np.max(cons_highs))
            min_low = float(np.min(cons_lows))

            if min_low <= 0:
                continue

            range_pct = (max_high - min_low) / min_low * 100
            if range_pct >= self.RANGE_THRESHOLD_PCT:
                continue

            # BB bandwidth check (use bandwidth at candle before breakout)
            bb_bw_pre = df_5m["bb_bandwidth"].values[idx - 1]
            if np.isnan(bb_bw_pre) or bb_bw_pre >= self.BB_BANDWIDTH_MAX:
                continue

            # Phase 1 passed — consolidation confirmed

            # Phase 2: Check breakout direction
            close_now = float(closes[idx])
            is_green = closes[idx] > opens[idx]

            if close_now > max_high and is_green:
                direction = Direction.LONG
            elif close_now < min_low and not is_green:
                direction = Direction.SHORT
            else:
                continue

            # Build signal
            consolidation_range = max_high - min_low
            entry_price = close_now
            sl_price = (max_high + min_low) / 2  # mid-range

            if direction == Direction.LONG:
                tp1_price = entry_price + consolidation_range * self.TP1_PROJECTION
                tp2_price = entry_price + consolidation_range * self.TP2_PROJECTION
            else:
                tp1_price = entry_price - consolidation_range * self.TP1_PROJECTION
                tp2_price = entry_price - consolidation_range * self.TP2_PROJECTION

            sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100
            tp_distance_pct = abs(tp1_price - entry_price) / entry_price * 100
            rr_ratio = tp_distance_pct / sl_distance_pct if sl_distance_pct > 0 else 0

            if "timestamp" in df_5m.columns:
                timestamp = str(df_5m["timestamp"].iloc[-1])
            else:
                timestamp = datetime.now(timezone.utc).isoformat()

            return Signal(
                direction=direction,
                strength=min(1.0, vol_ratio / 4.0),
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
                reason="Consolidation breakout (5m)",
                metadata={
                    "lookback": lookback,
                    "range_pct": round(range_pct, 4),
                    "bb_bandwidth": round(float(bb_bw_pre), 4),
                    "vol_ratio": round(float(vol_ratio), 2),
                    "body_ratio": round(float(body_ratio), 3),
                    "max_high": round(max_high, 8),
                    "min_low": round(min_low, 8),
                    "consolidation_range": round(consolidation_range, 8),
                },
            )

        return None

    def required_indicators(self) -> List[str]:
        return [
            "atr14", "vol_ratio", "body_ratio",
            "bb_bandwidth", "is_green",
        ]
