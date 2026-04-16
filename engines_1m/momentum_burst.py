"""Momentum Burst Engine for 1-minute timeframe.

Detects explosive momentum candles (range > 2x ATR, volume > 2.5x avg,
strong body) aligned with short-term trend, and enters in the direction
of the burst.

Entry: open of next candle (backtest) or current close (live)
SL: candle low - 0.3 * ATR14 (LONG) / candle high + 0.3 * ATR14 (SHORT)
TP: trailing stop based on ATR, initial target 1.5x ATR, max 3.0x ATR
"""
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd

from engines_1m.base import Engine1m
from signal_types import Direction, Signal


class MomentumBurst1m(Engine1m):

    name = "momentum_burst_1m"
    version = "1.0.0"

    # Detection thresholds
    ATR_MULTIPLE_MIN = 2.0
    VOLUME_MULTIPLE_MIN = 2.5
    BODY_RATIO_MIN = 0.65
    RSI_LOW = 30.0
    RSI_HIGH = 70.0

    # SL/TP parameters
    SL_ATR_MULT = 0.3
    TP_INITIAL_ATR_MULT = 1.5
    TP_MAX_ATR_MULT = 3.0

    def analyze(
        self,
        symbol: str,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame | None = None,
        market_data: dict | None = None,
    ) -> Optional[Signal]:
        if len(df_1m) < 25:
            return None

        last = df_1m.iloc[-1]

        # Check for NaN in required indicators
        required_vals = [last.get("atr14"), last.get("ema8"), last.get("ema21"),
                         last.get("rsi14"), last.get("vol_ratio"), last.get("body_ratio")]
        if any(v is None or pd.isna(v) for v in required_vals):
            return None

        atr = last["atr14"]
        if atr <= 0:
            return None

        candle_range = last["range"]
        atr_multiple = candle_range / atr if atr > 0 else 0

        # Condition 1: range > 2.0x ATR
        if atr_multiple < self.ATR_MULTIPLE_MIN:
            return None

        # Condition 2: volume > 2.5x average
        vol_ratio = last["vol_ratio"]
        if pd.isna(vol_ratio) or vol_ratio < self.VOLUME_MULTIPLE_MIN:
            return None

        # Condition 3: body ratio >= 65%
        body_ratio = last["body_ratio"]
        if pd.isna(body_ratio) or body_ratio < self.BODY_RATIO_MIN:
            return None

        # Condition 4: EMA alignment determines direction
        ema8 = last["ema8"]
        ema21 = last["ema21"]
        is_green = last["is_green"]

        if ema8 > ema21 and is_green:
            direction = Direction.LONG
        elif ema8 < ema21 and not is_green:
            direction = Direction.SHORT
        else:
            return None  # No alignment

        # Condition 5: RSI not extreme
        rsi = last["rsi14"]
        if rsi < self.RSI_LOW or rsi > self.RSI_HIGH:
            return None

        # Calculate entry, SL, TP
        entry_price = last["close"]

        if direction == Direction.LONG:
            sl_price = last["low"] - self.SL_ATR_MULT * atr
            tp1_price = entry_price + self.TP_INITIAL_ATR_MULT * atr
            tp2_price = entry_price + self.TP_MAX_ATR_MULT * atr
        else:
            sl_price = last["high"] + self.SL_ATR_MULT * atr
            tp1_price = entry_price - self.TP_INITIAL_ATR_MULT * atr
            tp2_price = entry_price - self.TP_MAX_ATR_MULT * atr

        sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100
        tp_distance_pct = abs(tp1_price - entry_price) / entry_price * 100
        rr_ratio = tp_distance_pct / sl_distance_pct if sl_distance_pct > 0 else 0

        # Strength: scale 0-1 based on how far above thresholds
        strength = min(1.0, (
            min(atr_multiple / 4.0, 0.4) +
            min(vol_ratio / 5.0, 0.3) +
            min(body_ratio, 0.3)
        ))

        timestamp = str(last.get("timestamp", datetime.now(timezone.utc).isoformat()))

        return Signal(
            direction=direction,
            strength=strength,
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
            reason="Momentum burst detected",
            metadata={
                "engine": self.name,
                "atr_multiple": round(atr_multiple, 2),
                "volume_multiple": round(vol_ratio, 2),
                "body_ratio": round(body_ratio, 3),
                "ema_alignment": "ALIGNED",
                "rsi": round(rsi, 1),
                "atr": round(atr, 6),
            },
        )

    def required_indicators(self) -> List[str]:
        return [
            "atr14", "ema8", "ema21", "rsi14",
            "vol_ratio", "body_ratio", "range", "is_green",
        ]
