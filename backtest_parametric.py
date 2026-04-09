"""
Backtest parametrico dos 3 motores de scalping ISOLADOS.

Testa cada motor com multiplas combinacoes de parametros para encontrar
se EXISTE alguma combinacao que gere expectativa positiva.

Exit strategy: trailing (melhor no backtest anterior).
Timeframe: 5m (principal), 3m/15m (auxiliares).
Dados: 180 dias, BTCUSDT + ETHUSDT via Binance Futures.

Uso: python backtest_parametric.py [--days 180] [--symbols BTCUSDT,ETHUSDT]
"""
import argparse
import csv
import itertools
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import pandas as pd
import ta

from config import BINANCE_KLINES_URL

# Reuse building blocks from backtest_scalping
from backtest_scalping import (
    fetch_historical_futures,
    SimulatedPosition,
    calculate_pnl,
    calc_metrics,
    FEE_PER_SIDE_PCT,
    ROUND_TRIP_FEE_PCT,
    EXTRA_SLIPPAGE_PCT,
    INITIAL_CAPITAL,
    WARMUP_CANDLES,
    ENGINE_WINDOW,
)
from signal_types import Direction

logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backtest_parametric")

# ============================================================
#  CONSTANTES
# ============================================================
DEFAULT_DAYS = 180
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
LEVERAGE = 3           # fixo para comparacao isolada
RISK_PCT = 2.0         # % do capital por trade
COOLDOWN_CANDLES = 3
SLIPPAGE_PCT = 0.05    # buffer de slippage nos motores

OUTPUT_DIR = os.path.join("reports", "parametric")

# ============================================================
#  PARAMETER GRIDS
# ============================================================
VB_GRID = {
    "volume_threshold": [1.2, 1.5, 1.8, 2.0, 2.5],
    "breakout_lookback": [10, 15, 20, 30],
    "atr_multiplier_sl": [1.0, 1.5, 2.0],
}

RSI_BB_GRID = {
    "rsi_levels": [(25, 75), (28, 72), (30, 70), (32, 68), (35, 65)],
    "bb_period": [14, 20, 30],
    "bb_std": [1.5, 2.0, 2.5],
}

EMA_GRID = {
    "ema_pair": [(5, 13), (8, 21), (9, 21), (12, 26), (5, 21)],
    "retest_zone_pct": [0.1, 0.2, 0.3, 0.5],
    "max_candles_since_cross": [5, 10, 15, 20],
}


def count_combos():
    vb = len(VB_GRID["volume_threshold"]) * len(VB_GRID["breakout_lookback"]) * len(VB_GRID["atr_multiplier_sl"])
    rsi = len(RSI_BB_GRID["rsi_levels"]) * len(RSI_BB_GRID["bb_period"]) * len(RSI_BB_GRID["bb_std"])
    ema = len(EMA_GRID["ema_pair"]) * len(EMA_GRID["retest_zone_pct"]) * len(EMA_GRID["max_candles_since_cross"])
    return vb, rsi, ema


# ============================================================
#  INDICATOR PRECOMPUTATION
# ============================================================

def add_base_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add standard indicators to any timeframe DataFrame."""
    if df is None or len(df) < 50:
        return df
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # EMAs (standard)
    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    # RSI(14)
    df["rsi"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()

    # BB standard (20, 2.0)
    bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_bandwidth"] = bb.bollinger_wband()

    # ATR(14)
    df["atr14"] = ta.volatility.AverageTrueRange(
        high=high, low=low, close=close, window=14
    ).average_true_range()

    # Volume average
    df["volume_avg20"] = volume.rolling(window=20).mean()

    # Body and wick ratios
    candle_range = high - low
    candle_range_safe = candle_range.replace(0, float("nan"))
    body = (close - df["open"]).abs()
    df["body_ratio"] = (body / candle_range_safe).fillna(0)
    df["upper_wick"] = ((high - close.where(close >= df["open"], df["open"])) / candle_range_safe).fillna(0).clip(0, 1)
    df["lower_wick"] = ((close.where(close < df["open"], df["open"]) - low) / candle_range_safe).fillna(0).clip(0, 1)

    # Recent highs/lows
    df["high_20"] = high.rolling(window=20).max().shift(1)
    df["low_20"] = low.rolling(window=20).min().shift(1)
    df["low_3"] = low.rolling(window=3).min()
    df["high_3"] = high.rolling(window=3).max()

    return df


def precompute_vb_variants(df_3m: pd.DataFrame, lookbacks: list) -> None:
    """Precompute high_N/low_N for each breakout lookback."""
    for lb in lookbacks:
        df_3m[f"high_{lb}"] = df_3m["high"].rolling(window=lb).max().shift(1)
        df_3m[f"low_{lb}"] = df_3m["low"].rolling(window=lb).min().shift(1)


def precompute_bb_variants(df_5m: pd.DataFrame, periods: list, stds: list) -> None:
    """Precompute BB for each (period, std) combo."""
    for period in periods:
        for std in stds:
            key = f"{period}_{std}"
            bb = ta.volatility.BollingerBands(
                close=df_5m["close"], window=period, window_dev=std
            )
            df_5m[f"bb_upper_{key}"] = bb.bollinger_hband()
            df_5m[f"bb_lower_{key}"] = bb.bollinger_lband()
            df_5m[f"bb_middle_{key}"] = bb.bollinger_mavg()
            df_5m[f"bb_bandwidth_{key}"] = bb.bollinger_wband()


def precompute_ema_variants(df_3m: pd.DataFrame, pairs: list) -> None:
    """Precompute EMA fast/slow for each pair."""
    for fast, slow in pairs:
        df_3m[f"ema_f{fast}"] = df_3m["close"].ewm(span=fast, adjust=False).mean()
        df_3m[f"ema_s{slow}"] = df_3m["close"].ewm(span=slow, adjust=False).mean()


# ============================================================
#  TIME ALIGNMENT
# ============================================================

def build_time_index(df_main: pd.DataFrame, df_other: pd.DataFrame) -> np.ndarray:
    """For each candle in df_main, find the index of the last candle in df_other
    with time <= that candle's time. Returns numpy array of indices."""
    times_main = df_main["time"].values.astype(np.int64)
    times_other = df_other["time"].values.astype(np.int64)
    indices = np.searchsorted(times_other, times_main, side="right") - 1
    return indices.clip(0)


# ============================================================
#  SIGNAL DETECTION: VOLUME BREAKOUT
# ============================================================

def detect_vb_signal(
    df_3m: pd.DataFrame,
    idx_3m: int,
    df_5m: pd.DataFrame,
    idx_5m: int,
    volume_threshold: float,
    breakout_lookback: int,
    atr_multiplier_sl: float,
) -> Optional[Dict]:
    """
    Detect Volume Breakout signal at df_3m[idx_3m] (last closed 3m candle).
    Returns signal dict or None.
    """
    if idx_3m < 50:
        return None

    last = df_3m.iloc[idx_3m]
    price = last["close"]

    # CONDITION 1: Volume >= threshold * avg20
    vol_avg = last.get("volume_avg20", 0)
    if pd.isna(vol_avg) or vol_avg == 0:
        return None
    volume_ratio = last["volume"] / vol_avg
    if volume_ratio < volume_threshold:
        return None

    # CONDITION 2: Close breaks high/low of last N candles
    high_n = df_3m[f"high_{breakout_lookback}"].iloc[idx_3m]
    low_n = df_3m[f"low_{breakout_lookback}"].iloc[idx_3m]
    if pd.isna(high_n) or pd.isna(low_n):
        return None

    is_long = price > high_n
    is_short = price < low_n
    if not is_long and not is_short:
        return None
    direction = Direction.LONG if is_long else Direction.SHORT

    # CONDITION 3: Body ratio >= 60%
    body_ratio = last.get("body_ratio", 0)
    if pd.isna(body_ratio) or body_ratio < 0.6:
        return None

    # CONDITION 4: Price vs EMA20
    ema20 = last.get("ema20", 0)
    if pd.isna(ema20):
        return None
    if direction == Direction.LONG and price <= ema20:
        return None
    if direction == Direction.SHORT and price >= ema20:
        return None

    # FILTER: Wick rejection > 40%
    if direction == Direction.LONG:
        wick = last.get("upper_wick", 0)
    else:
        wick = last.get("lower_wick", 0)
    if not pd.isna(wick) and wick > 0.4:
        return None

    # FILTER: ATR 5m too low (< 0.15%)
    if idx_5m >= 20 and "atr14" in df_5m.columns:
        atr_5m = df_5m["atr14"].iloc[idx_5m]
        price_5m = df_5m["close"].iloc[idx_5m]
        if not pd.isna(atr_5m) and price_5m > 0:
            atr_pct = (atr_5m / price_5m) * 100
            if atr_pct < 0.15:
                return None

    # FILTER: Consecutive spikes (max 2)
    consecutive = 0
    for j in range(idx_3m - 1, max(idx_3m - 6, 20), -1):
        row = df_3m.iloc[j]
        va = df_3m["volume_avg20"].iloc[j]
        if pd.isna(va) or va == 0:
            break
        is_spike = row["volume"] >= volume_threshold * va
        if direction == Direction.LONG:
            same_dir = row["close"] > row["open"]
        else:
            same_dir = row["close"] < row["open"]
        if is_spike and same_dir:
            consecutive += 1
        else:
            break
    if consecutive >= 2:
        return None

    # CALCULATE SL/TP
    atr14 = last.get("atr14", 0)
    if pd.isna(atr14) or atr14 == 0:
        return None

    entry_price = price
    slip = entry_price * (SLIPPAGE_PCT / 100)

    if direction == Direction.LONG:
        sl_price = last["low"] - (atr_multiplier_sl * atr14) - slip
        tp1_price = entry_price + (1.0 * atr14) - slip
        tp2_price = entry_price + (2.2 * atr14) - slip
    else:
        sl_price = last["high"] + (atr_multiplier_sl * atr14) + slip
        tp1_price = entry_price - (1.0 * atr14) + slip
        tp2_price = entry_price - (2.2 * atr14) + slip

    sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100
    if sl_distance_pct > 0.8:
        return None

    sl_distance = abs(entry_price - sl_price)
    tp2_distance = abs(tp2_price - entry_price)
    if sl_distance == 0:
        return None
    rr_ratio = tp2_distance / sl_distance
    if rr_ratio < 1.8:
        return None

    return {
        "direction": direction,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "atr": atr14,
    }


# ============================================================
#  SIGNAL DETECTION: RSI/BB REVERSAL
# ============================================================

def detect_rsi_bb_signal(
    df_5m: pd.DataFrame,
    idx_5m: int,
    df_15m: pd.DataFrame,
    idx_15m: int,
    rsi_oversold: float,
    rsi_overbought: float,
    bb_period: int,
    bb_std: float,
) -> Optional[Dict]:
    """
    Detect RSI/BB Reversal signal at df_5m[idx_5m-1] (signal candle),
    confirmed by df_5m[idx_5m] (confirmation candle).
    """
    if idx_5m < 50:
        return None

    signal_candle = df_5m.iloc[idx_5m - 1]
    confirm_candle = df_5m.iloc[idx_5m]
    prev_candle = df_5m.iloc[idx_5m - 2]
    price = confirm_candle["close"]

    bb_key = f"{bb_period}_{bb_std}"

    # CONDITION 1: RSI in extreme zone
    rsi_signal = signal_candle.get("rsi", float("nan"))
    if pd.isna(rsi_signal):
        return None
    is_oversold = rsi_signal <= rsi_oversold
    is_overbought = rsi_signal >= rsi_overbought
    if not is_oversold and not is_overbought:
        return None
    direction = Direction.LONG if is_oversold else Direction.SHORT

    # CONDITION 2: Close beyond BB
    if direction == Direction.LONG:
        bb_band = signal_candle.get(f"bb_lower_{bb_key}", float("nan"))
        if pd.isna(bb_band) or signal_candle["close"] > bb_band:
            return None
    else:
        bb_band = signal_candle.get(f"bb_upper_{bb_key}", float("nan"))
        if pd.isna(bb_band) or signal_candle["close"] < bb_band:
            return None

    # CONDITION 3: Confirmation candle opens inside BB (pullback)
    if direction == Direction.LONG:
        bb_lower_confirm = confirm_candle.get(f"bb_lower_{bb_key}", float("nan"))
        if pd.isna(bb_lower_confirm) or confirm_candle["open"] < bb_lower_confirm:
            return None
    else:
        bb_upper_confirm = confirm_candle.get(f"bb_upper_{bb_key}", float("nan"))
        if pd.isna(bb_upper_confirm) or confirm_candle["open"] > bb_upper_confirm:
            return None

    # CONDITION 4: RSI turning
    rsi_confirm = confirm_candle.get("rsi", float("nan"))
    if pd.isna(rsi_confirm):
        return None
    if direction == Direction.LONG and rsi_confirm <= rsi_signal:
        return None
    if direction == Direction.SHORT and rsi_confirm >= rsi_signal:
        return None

    # CONDITION 5: Volume >= 1.5x avg
    vol_avg = df_5m["volume_avg20"].iloc[idx_5m - 1]
    if pd.isna(vol_avg) or vol_avg == 0:
        return None
    volume_ratio = confirm_candle["volume"] / vol_avg
    if volume_ratio < 1.5:
        return None

    # FILTER: Trend on 15m against direction
    if idx_15m >= 21 and df_15m is not None:
        ema9_15 = df_15m["ema9"].iloc[idx_15m]
        ema21_15 = df_15m["ema21"].iloc[idx_15m]
        if not pd.isna(ema9_15) and not pd.isna(ema21_15):
            if direction == Direction.LONG and ema9_15 < ema21_15:
                if rsi_signal > rsi_oversold - 5:
                    return None
            if direction == Direction.SHORT and ema9_15 > ema21_15:
                if rsi_signal < rsi_overbought + 5:
                    return None

    # FILTER: RSI extreme > 6 consecutive candles
    extreme_count = 0
    for j in range(idx_5m - 2, max(0, idx_5m - 22), -1):
        rsi_j = df_5m["rsi"].iloc[j]
        if pd.isna(rsi_j):
            break
        if direction == Direction.LONG and rsi_j <= rsi_oversold:
            extreme_count += 1
        elif direction == Direction.SHORT and rsi_j >= rsi_overbought:
            extreme_count += 1
        else:
            break
    if extreme_count > 6:
        return None

    # FILTER: BB bandwidth too low (< 0.8%)
    bw = signal_candle.get(f"bb_bandwidth_{bb_key}", float("nan"))
    bb_mid = signal_candle.get(f"bb_middle_{bb_key}", float("nan"))
    if not pd.isna(bw) and not pd.isna(bb_mid) and bb_mid > 0:
        bandwidth_pct = bw * 100
        if bandwidth_pct < 0.8:
            return None

    # FILTER: Band touches > 2
    band_touches = 0
    for j in range(idx_5m - 2, max(0, idx_5m - 12), -1):
        row = df_5m.iloc[j]
        bl = row.get(f"bb_lower_{bb_key}", float("nan"))
        bu = row.get(f"bb_upper_{bb_key}", float("nan"))
        if pd.isna(bl) or pd.isna(bu):
            continue
        if direction == Direction.LONG:
            if row["close"] <= bl or row["low"] <= bl:
                band_touches += 1
        else:
            if row["close"] >= bu or row["high"] >= bu:
                band_touches += 1
    if band_touches > 2:
        return None

    # FILTER: ATR too low (< 0.10%)
    atr14 = df_5m["atr14"].iloc[idx_5m - 1]
    if not pd.isna(atr14) and price > 0:
        atr_pct = (atr14 / price) * 100
        if atr_pct < 0.10:
            return None

    # CALCULATE SL/TP
    if pd.isna(atr14) or atr14 == 0:
        return None

    entry_price = price
    slip = entry_price * (SLIPPAGE_PCT / 100)

    if direction == Direction.LONG:
        low_3 = df_5m["low_3"].iloc[idx_5m - 1]
        if pd.isna(low_3):
            low_3 = df_5m["low"].iloc[max(0, idx_5m - 3):idx_5m].min()
        sl_price = low_3 - (0.3 * atr14) - slip
        tp1_price = confirm_candle.get(f"bb_middle_{bb_key}", float("nan"))
        tp2_price = confirm_candle.get(f"bb_upper_{bb_key}", float("nan"))
        if pd.isna(tp1_price) or pd.isna(tp2_price):
            return None
        tp1_price -= slip
        tp2_price -= slip
    else:
        high_3 = df_5m["high_3"].iloc[idx_5m - 1]
        if pd.isna(high_3):
            high_3 = df_5m["high"].iloc[max(0, idx_5m - 3):idx_5m].max()
        sl_price = high_3 + (0.3 * atr14) + slip
        tp1_price = confirm_candle.get(f"bb_middle_{bb_key}", float("nan"))
        tp2_price = confirm_candle.get(f"bb_lower_{bb_key}", float("nan"))
        if pd.isna(tp1_price) or pd.isna(tp2_price):
            return None
        tp1_price += slip
        tp2_price += slip

    sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100
    if sl_distance_pct > 0.6:
        return None

    sl_distance = abs(entry_price - sl_price)
    tp1_distance = abs(tp1_price - entry_price)
    if sl_distance == 0:
        return None
    rr_ratio = tp1_distance / sl_distance
    if rr_ratio < 1.5:
        return None

    return {
        "direction": direction,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "atr": atr14,
    }


# ============================================================
#  SIGNAL DETECTION: EMA CROSSOVER
# ============================================================

def _find_recent_cross_param(
    df: pd.DataFrame, idx: int, fast_col: str, slow_col: str, lookback: int
) -> Optional[Dict]:
    """Find most recent EMA cross within lookback candles before idx."""
    start = max(1, idx - lookback)
    for i in range(idx, start, -1):
        curr_f = df[fast_col].iloc[i]
        curr_s = df[slow_col].iloc[i]
        prev_f = df[fast_col].iloc[i - 1]
        prev_s = df[slow_col].iloc[i - 1]
        if any(pd.isna(v) for v in [curr_f, curr_s, prev_f, prev_s]):
            continue
        # Bullish cross
        if prev_f <= prev_s and curr_f > curr_s:
            return {
                "direction": Direction.LONG,
                "index": i,
                "candles_ago": idx - i,
                "ema_fast_at_cross": curr_f,
                "ema_slow_at_cross": curr_s,
            }
        # Bearish cross
        if prev_f >= prev_s and curr_f < curr_s:
            return {
                "direction": Direction.SHORT,
                "index": i,
                "candles_ago": idx - i,
                "ema_fast_at_cross": curr_f,
                "ema_slow_at_cross": curr_s,
            }
    return None


def _count_crosses_param(
    df: pd.DataFrame, idx: int, fast_col: str, slow_col: str, lookback: int
) -> int:
    """Count EMA crosses within lookback candles before idx."""
    start = max(1, idx - lookback)
    count = 0
    for i in range(start + 1, idx + 1):
        curr_f = df[fast_col].iloc[i]
        curr_s = df[slow_col].iloc[i]
        prev_f = df[fast_col].iloc[i - 1]
        prev_s = df[slow_col].iloc[i - 1]
        if any(pd.isna(v) for v in [curr_f, curr_s, prev_f, prev_s]):
            continue
        if (prev_f <= prev_s and curr_f > curr_s) or (prev_f >= prev_s and curr_f < curr_s):
            count += 1
    return count


def detect_ema_signal(
    df_3m: pd.DataFrame,
    idx_3m: int,
    df_15m: pd.DataFrame,
    idx_15m: int,
    ema_fast: int,
    ema_slow: int,
    retest_zone_pct: float,
    max_candles_since_cross: int,
) -> Optional[Dict]:
    """
    Detect EMA Crossover signal at df_3m[idx_3m] (last closed 3m candle).
    """
    if idx_3m < 50:
        return None

    fast_col = f"ema_f{ema_fast}"
    slow_col = f"ema_s{ema_slow}"
    last = df_3m.iloc[idx_3m]
    price = last["close"]

    # CONDITION 1: Find recent cross
    cross = _find_recent_cross_param(df_3m, idx_3m, fast_col, slow_col, lookback=15)
    if cross is None:
        return None

    direction = cross["direction"]
    candles_since = cross["candles_ago"]

    # FILTER: Too many candles since cross
    if candles_since > max_candles_since_cross:
        return None

    # FILTER: Gap at cross > 0.3% (exhaustion)
    ema_f_cross = cross["ema_fast_at_cross"]
    ema_s_cross = cross["ema_slow_at_cross"]
    if ema_s_cross > 0:
        gap_pct = abs(ema_f_cross - ema_s_cross) / ema_s_cross * 100
        if gap_pct > 0.3:
            return None

    # FILTER: > 3 crosses in 15 candles (choppy)
    total_crosses = _count_crosses_param(df_3m, idx_3m, fast_col, slow_col, lookback=15)
    if total_crosses > 3:
        return None

    # CONDITION 2+3: Retest zone (parameterized width)
    ema_f = last[fast_col]
    ema_s = last[slow_col]
    if pd.isna(ema_f) or pd.isna(ema_s):
        return None

    zone_top = max(ema_f, ema_s)
    zone_bottom = min(ema_f, ema_s)
    zone_buffer = price * (retest_zone_pct / 100)

    if direction == Direction.LONG:
        in_zone = last["low"] <= (zone_top + zone_buffer) and last["close"] >= ema_f
    else:
        in_zone = last["high"] >= (zone_bottom - zone_buffer) and last["close"] <= ema_f

    if not in_zone:
        return None

    # CONDITION 4: EMA slow sloping correctly
    slope_lookback = 3
    if idx_3m > slope_lookback + 2:
        ema_s_now = ema_s
        ema_s_back = df_3m[slow_col].iloc[idx_3m - slope_lookback]
        if pd.isna(ema_s_now) or pd.isna(ema_s_back):
            return None
        if direction == Direction.LONG and ema_s_now <= ema_s_back:
            return None
        if direction == Direction.SHORT and ema_s_now >= ema_s_back:
            return None

    # CONDITION 5: 15m trend alignment (EMA50)
    if df_15m is not None and idx_15m >= 50:
        ema50_15 = df_15m["ema50"].iloc[idx_15m]
        price_15 = df_15m["close"].iloc[idx_15m]
        if not pd.isna(ema50_15):
            if direction == Direction.LONG and price_15 < ema50_15:
                return None
            if direction == Direction.SHORT and price_15 > ema50_15:
                return None

        # FILTER: Entangled 15m EMAs (distance < 0.1%)
        ema9_15 = df_15m["ema9"].iloc[idx_15m]
        ema21_15 = df_15m["ema21"].iloc[idx_15m]
        if not pd.isna(ema9_15) and not pd.isna(ema21_15) and ema21_15 > 0:
            dist_15 = abs(ema9_15 - ema21_15) / ema21_15 * 100
            if dist_15 < 0.1:
                return None

    # CALCULATE SL/TP
    atr14 = last.get("atr14", 0)
    if pd.isna(atr14) or atr14 == 0:
        return None

    entry_price = price
    slip = entry_price * (SLIPPAGE_PCT / 100)

    if direction == Direction.LONG:
        sl_price = ema_s - (0.2 * atr14) - slip
        tp1_price = entry_price + (1.5 * atr14) - slip
        high_20 = last.get("high_20", float("nan"))
        tp2_atr = entry_price + (2.5 * atr14) - slip
        if not pd.isna(high_20) and high_20 > entry_price:
            tp2_price = min(high_20 - slip, tp2_atr)
        else:
            tp2_price = tp2_atr
    else:
        sl_price = ema_s + (0.2 * atr14) + slip
        tp1_price = entry_price - (1.5 * atr14) + slip
        low_20 = last.get("low_20", float("nan"))
        tp2_atr = entry_price - (2.5 * atr14) + slip
        if not pd.isna(low_20) and low_20 < entry_price:
            tp2_price = max(low_20 + slip, tp2_atr)
        else:
            tp2_price = tp2_atr

    sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100
    if sl_distance_pct > 0.7:
        return None

    sl_distance = abs(entry_price - sl_price)
    tp2_distance = abs(tp2_price - entry_price)
    if sl_distance == 0:
        return None
    rr_ratio = tp2_distance / sl_distance
    if rr_ratio < 2.0:
        return None

    return {
        "direction": direction,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "atr": atr14,
    }


# ============================================================
#  TRADE SIMULATION (single engine, single symbol)
# ============================================================

def simulate_trades(
    df_5m: pd.DataFrame,
    signals: List[Tuple[int, Dict]],
) -> List[Dict]:
    """
    Given pre-detected signals (list of (5m_candle_index, signal_dict)),
    simulate trades using trailing exit on 5m candles.
    Returns list of trade dicts.
    """
    trades = []
    position: Optional[SimulatedPosition] = None
    cooldown_remaining = 0
    signal_idx = 0
    signals_sorted = sorted(signals, key=lambda x: x[0])

    for i in range(WARMUP_CANDLES + 1, len(df_5m)):
        current_candle = df_5m.iloc[i]

        # --- MANAGE OPEN POSITION ---
        if position is not None:
            exit_events = position.check_exit(current_candle)
            if exit_events and position.remaining_size_pct <= 0:
                total_net_pnl_pct = 0.0
                total_pnl_usd = 0.0
                exit_details = []
                for ev in exit_events:
                    pnl = calculate_pnl(
                        direction=position.direction,
                        entry_price=position.entry_price,
                        exit_price=ev["price"],
                        size_pct=ev["size_pct"],
                        position_size_usd=position.position_size_usd,
                        leverage=position.leverage,
                    )
                    total_net_pnl_pct += pnl["net_pnl_pct"] * pnl["fraction"]
                    total_pnl_usd += pnl["pnl_usd"]
                    exit_details.append({"reason": ev["reason"], **pnl})

                entry_idx = position._entry_idx
                duration = i - entry_idx

                trades.append({
                    "total_net_pnl_pct": round(total_net_pnl_pct, 6),
                    "total_pnl_usd": round(total_pnl_usd, 4),
                    "direction": position.direction.value,
                    "entry_price": position.entry_price,
                    "exit_reason": exit_details[-1]["reason"] if exit_details else "unknown",
                    "duration_candles": int(duration),
                })
                cooldown_remaining = COOLDOWN_CANDLES
                position = None

        # Decrement cooldown
        if cooldown_remaining > 0:
            cooldown_remaining -= 1

        # --- CHECK FOR NEW SIGNAL ---
        if position is not None or cooldown_remaining > 0:
            continue

        # Find signal for this candle index
        while signal_idx < len(signals_sorted) and signals_sorted[signal_idx][0] < i:
            signal_idx += 1
        if signal_idx >= len(signals_sorted) or signals_sorted[signal_idx][0] != i:
            continue

        sig = signals_sorted[signal_idx][1]
        signal_idx += 1

        # Entry on open of current candle
        entry_price = current_candle["open"]
        slip = entry_price * (EXTRA_SLIPPAGE_PCT / 100)
        if sig["direction"] == Direction.LONG:
            entry_price += slip
        else:
            entry_price -= slip

        # Position sizing: 2% risk
        sl_distance_pct = abs(entry_price - sig["sl_price"]) / entry_price
        if sl_distance_pct <= 0:
            continue
        risk_amount = INITIAL_CAPITAL * (RISK_PCT / 100)
        position_size_usd = risk_amount / sl_distance_pct
        max_margin = INITIAL_CAPITAL * 0.5
        margin = position_size_usd / LEVERAGE
        if margin > max_margin:
            position_size_usd = max_margin * LEVERAGE

        position = SimulatedPosition(
            symbol="",
            direction=sig["direction"],
            entry_price=entry_price,
            entry_time=current_candle["time"],
            sl_price=sig["sl_price"],
            tp1_price=sig["tp1_price"],
            tp2_price=sig["tp2_price"],
            position_size_usd=position_size_usd,
            leverage=LEVERAGE,
            confluence_score=1,
            primary_engine="",
            engines_active=[],
            exit_mode="trailing",
            atr_at_entry=sig["atr"],
        )
        position._entry_idx = i

        # Check if SL/TP hit on entry candle
        exit_events = position.check_exit(current_candle)
        if exit_events and position.remaining_size_pct <= 0:
            total_net_pnl_pct = 0.0
            total_pnl_usd = 0.0
            for ev in exit_events:
                pnl = calculate_pnl(
                    direction=position.direction,
                    entry_price=position.entry_price,
                    exit_price=ev["price"],
                    size_pct=ev["size_pct"],
                    position_size_usd=position.position_size_usd,
                    leverage=position.leverage,
                )
                total_net_pnl_pct += pnl["net_pnl_pct"] * pnl["fraction"]
                total_pnl_usd += pnl["pnl_usd"]
            trades.append({
                "total_net_pnl_pct": round(total_net_pnl_pct, 6),
                "total_pnl_usd": round(total_pnl_usd, 4),
                "direction": position.direction.value,
                "entry_price": position.entry_price,
                "exit_reason": exit_events[-1]["reason"],
                "duration_candles": 0,
            })
            cooldown_remaining = COOLDOWN_CANDLES
            position = None

    # Close open position at end of data
    if position is not None:
        last = df_5m.iloc[-1]
        pnl = calculate_pnl(
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=last["close"],
            size_pct=position.remaining_size_pct,
            position_size_usd=position.position_size_usd,
            leverage=position.leverage,
        )
        trades.append({
            "total_net_pnl_pct": round(pnl["net_pnl_pct"] * pnl["fraction"], 6),
            "total_pnl_usd": round(pnl["pnl_usd"], 4),
            "direction": position.direction.value,
            "entry_price": position.entry_price,
            "exit_reason": "end_of_data",
            "duration_candles": len(df_5m) - 1 - position._entry_idx,
        })

    return trades


# ============================================================
#  ENGINE RUNNERS
# ============================================================

def run_vb_combo(
    symbol: str,
    df_3m: pd.DataFrame,
    df_5m: pd.DataFrame,
    idx_3m_for_5m: np.ndarray,
    idx_5m_for_5m: np.ndarray,
    volume_threshold: float,
    breakout_lookback: int,
    atr_multiplier_sl: float,
) -> Dict:
    """Run a single VB parameter combination and return results."""
    signals = []
    for i in range(WARMUP_CANDLES + 1, len(df_5m)):
        # Signal candle = 5m[i-1], use corresponding 3m index
        i3 = idx_3m_for_5m[i - 1]
        i5 = i - 1
        sig = detect_vb_signal(
            df_3m, i3, df_5m, i5,
            volume_threshold, breakout_lookback, atr_multiplier_sl,
        )
        if sig is not None:
            signals.append((i, sig))

    trades = simulate_trades(df_5m, signals)
    metrics = calc_metrics(trades)
    return {
        "engine": "volume_breakout",
        "symbol": symbol,
        "params": f"vol={volume_threshold},lb={breakout_lookback},atr_sl={atr_multiplier_sl}",
        "volume_threshold": volume_threshold,
        "breakout_lookback": breakout_lookback,
        "atr_multiplier_sl": atr_multiplier_sl,
        "total_signals": len(signals),
        **metrics,
    }


def run_rsi_bb_combo(
    symbol: str,
    df_5m: pd.DataFrame,
    df_15m: pd.DataFrame,
    idx_15m_for_5m: np.ndarray,
    rsi_oversold: float,
    rsi_overbought: float,
    bb_period: int,
    bb_std: float,
) -> Dict:
    """Run a single RSI/BB parameter combination."""
    signals = []
    for i in range(WARMUP_CANDLES + 1, len(df_5m)):
        i15 = idx_15m_for_5m[i - 1]
        sig = detect_rsi_bb_signal(
            df_5m, i, df_15m, i15,
            rsi_oversold, rsi_overbought, bb_period, bb_std,
        )
        if sig is not None:
            signals.append((i, sig))

    trades = simulate_trades(df_5m, signals)
    metrics = calc_metrics(trades)
    return {
        "engine": "rsi_bb_reversal",
        "symbol": symbol,
        "params": f"rsi=({rsi_oversold},{rsi_overbought}),bb={bb_period}/{bb_std}",
        "rsi_oversold": rsi_oversold,
        "rsi_overbought": rsi_overbought,
        "bb_period": bb_period,
        "bb_std": bb_std,
        "total_signals": len(signals),
        **metrics,
    }


def run_ema_combo(
    symbol: str,
    df_3m: pd.DataFrame,
    df_5m: pd.DataFrame,
    df_15m: pd.DataFrame,
    idx_3m_for_5m: np.ndarray,
    idx_15m_for_5m: np.ndarray,
    ema_fast: int,
    ema_slow: int,
    retest_zone_pct: float,
    max_candles_since_cross: int,
) -> Dict:
    """Run a single EMA Crossover parameter combination."""
    signals = []
    for i in range(WARMUP_CANDLES + 1, len(df_5m)):
        i3 = idx_3m_for_5m[i - 1]
        i15 = idx_15m_for_5m[i - 1]
        sig = detect_ema_signal(
            df_3m, i3, df_15m, i15,
            ema_fast, ema_slow, retest_zone_pct, max_candles_since_cross,
        )
        if sig is not None:
            signals.append((i, sig))

    trades = simulate_trades(df_5m, signals)
    metrics = calc_metrics(trades)
    return {
        "engine": "ema_crossover",
        "symbol": symbol,
        "params": f"ema=({ema_fast},{ema_slow}),zone={retest_zone_pct},maxc={max_candles_since_cross}",
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "retest_zone_pct": retest_zone_pct,
        "max_candles_since_cross": max_candles_since_cross,
        "total_signals": len(signals),
        **metrics,
    }


# ============================================================
#  CSV OUTPUT
# ============================================================

CSV_COLUMNS = [
    "engine", "symbol", "params",
    "total_signals", "total_trades", "wins", "losses", "win_rate",
    "avg_win_usd", "avg_loss_usd", "expectancy_usd",
    "total_pnl_usd", "total_return_pct",
    "profit_factor", "max_drawdown_pct", "max_drawdown_usd",
    "sharpe_simplified", "rr_effective",
    "expectancy_pct", "avg_win_pct", "avg_loss_pct",
    "best_trade_pct", "worst_trade_pct", "avg_duration_candles",
]


def save_results_csv(results: List[Dict], filepath: str) -> None:
    """Save results to CSV."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"  CSV salvo: {filepath} ({len(results)} linhas)")


def save_progress(results: List[Dict], engine_name: str) -> None:
    """Save partial results for a completed engine."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"partial_{engine_name}.csv")
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"  Progresso salvo: {filepath}")


# ============================================================
#  MARKDOWN SUMMARY
# ============================================================

def generate_summary(results: List[Dict], days: int, symbols: List[str]) -> str:
    """Generate markdown summary of parametric backtest results."""
    lines = []
    lines.append("# Backtest Parametrico - Resultados")
    lines.append("")
    lines.append(f"- **Periodo**: {days} dias")
    lines.append(f"- **Symbols**: {', '.join(symbols)}")
    lines.append(f"- **Timeframe**: 5m (principal)")
    lines.append(f"- **Exit**: Trailing stop (0.5x ATR activation, 0.8x ATR trail)")
    lines.append(f"- **Fees**: {ROUND_TRIP_FEE_PCT}% round-trip + {EXTRA_SLIPPAGE_PCT*2}% slippage")
    lines.append(f"- **Capital**: ${INITIAL_CAPITAL:,.0f} | Leverage: {LEVERAGE}x | Risk: {RISK_PCT}%/trade")
    lines.append(f"- **Total combinacoes testadas**: {len(results)}")
    lines.append("")

    # Sort by expectancy descending
    sorted_results = sorted(results, key=lambda r: r.get("expectancy_usd", 0), reverse=True)

    # Check if ANY combination has positive expectancy
    positive = [r for r in sorted_results if r.get("expectancy_usd", 0) > 0]
    negative_all = len(positive) == 0
    has_trades = [r for r in sorted_results if r.get("total_trades", 0) > 0]

    lines.append("## Veredicto")
    lines.append("")
    if negative_all:
        lines.append("**NENHUMA combinacao de parametros gerou expectativa positiva.**")
        lines.append("")
        lines.append("Isso confirma que o problema e estrutural nos motores de entrada,")
        lines.append("nao apenas uma questao de parametros.")
    else:
        lines.append(f"**{len(positive)} de {len(has_trades)} combinacoes com trades tem expectativa positiva.**")
        pct = len(positive) / max(1, len(has_trades)) * 100
        lines.append(f"({pct:.1f}% das combinacoes com trades)")
    lines.append("")

    # Top 10 by expectancy
    lines.append("## Top 10 Combinacoes (por expectativa USD/trade)")
    lines.append("")
    lines.append("| # | Motor | Symbol | Params | Trades | WR% | Exp$/trade | PnL$ | PF | Sharpe | MaxDD% |")
    lines.append("|---|-------|--------|--------|--------|-----|------------|------|----|----|--------|")
    for i, r in enumerate(sorted_results[:10], 1):
        if r.get("total_trades", 0) == 0:
            continue
        lines.append(
            f"| {i} | {r['engine']} | {r['symbol']} | {r['params']} | "
            f"{r['total_trades']} | {r['win_rate']:.1f} | "
            f"{r.get('expectancy_usd', 0):+.2f} | {r['total_pnl_usd']:+.2f} | "
            f"{r['profit_factor']:.2f} | {r['sharpe_simplified']:.2f} | "
            f"{r['max_drawdown_pct']:.2f} |"
        )
    lines.append("")

    # Bottom 10
    lines.append("## Bottom 10 Combinacoes (piores)")
    lines.append("")
    lines.append("| # | Motor | Symbol | Params | Trades | WR% | Exp$/trade | PnL$ |")
    lines.append("|---|-------|--------|--------|--------|-----|------------|------|")
    for i, r in enumerate(sorted_results[-10:], 1):
        if r.get("total_trades", 0) == 0:
            continue
        lines.append(
            f"| {i} | {r['engine']} | {r['symbol']} | {r['params']} | "
            f"{r['total_trades']} | {r['win_rate']:.1f} | "
            f"{r.get('expectancy_usd', 0):+.2f} | {r['total_pnl_usd']:+.2f} |"
        )
    lines.append("")

    # Per-engine summary
    for engine_name in ["volume_breakout", "rsi_bb_reversal", "ema_crossover"]:
        engine_results = [r for r in sorted_results if r["engine"] == engine_name and r.get("total_trades", 0) > 0]
        if not engine_results:
            lines.append(f"## {engine_name}")
            lines.append("")
            lines.append("Nenhuma combinacao gerou trades.")
            lines.append("")
            continue

        lines.append(f"## {engine_name}")
        lines.append("")

        exp_values = [r.get("expectancy_usd", 0) for r in engine_results]
        wr_values = [r.get("win_rate", 0) for r in engine_results]
        trade_counts = [r.get("total_trades", 0) for r in engine_results]
        pf_values = [r.get("profit_factor", 0) for r in engine_results]

        lines.append(f"- **Combinacoes com trades**: {len(engine_results)}")
        lines.append(f"- **Expectativa media**: ${sum(exp_values)/len(exp_values):+.2f}/trade")
        lines.append(f"- **Melhor expectativa**: ${max(exp_values):+.2f}/trade")
        lines.append(f"- **Pior expectativa**: ${min(exp_values):+.2f}/trade")
        lines.append(f"- **Win rate range**: {min(wr_values):.1f}% - {max(wr_values):.1f}%")
        lines.append(f"- **Trades range**: {min(trade_counts)} - {max(trade_counts)}")
        lines.append(f"- **PF range**: {min(pf_values):.2f} - {max(pf_values):.2f}")

        pos_exp = [r for r in engine_results if r.get("expectancy_usd", 0) > 0]
        lines.append(f"- **Com expectativa positiva**: {len(pos_exp)} / {len(engine_results)}")
        lines.append("")

        # Best 3 for this engine
        engine_sorted = sorted(engine_results, key=lambda r: r.get("expectancy_usd", 0), reverse=True)
        lines.append(f"### Top 3 {engine_name}")
        lines.append("")
        for j, r in enumerate(engine_sorted[:3], 1):
            lines.append(
                f"{j}. **{r['params']}** ({r['symbol']}) - "
                f"Trades: {r['total_trades']}, WR: {r['win_rate']:.1f}%, "
                f"Exp: ${r.get('expectancy_usd', 0):+.2f}/trade, "
                f"PnL: ${r['total_pnl_usd']:+.2f}, "
                f"PF: {r['profit_factor']:.2f}, "
                f"Sharpe: {r['sharpe_simplified']:.2f}"
            )
        lines.append("")

    # Sensitivity analysis: which parameters matter most
    lines.append("## Analise de Sensibilidade")
    lines.append("")
    lines.append("Parametros que mais afetam a expectativa (range de expectativa por valor):")
    lines.append("")

    # VB sensitivity
    vb_results = [r for r in results if r["engine"] == "volume_breakout" and r.get("total_trades", 0) > 0]
    if vb_results:
        lines.append("### Volume Breakout")
        lines.append("")
        for param_name in ["volume_threshold", "breakout_lookback", "atr_multiplier_sl"]:
            by_val = {}
            for r in vb_results:
                v = r.get(param_name, "?")
                by_val.setdefault(v, []).append(r.get("expectancy_usd", 0))
            lines.append(f"**{param_name}**:")
            for v in sorted(by_val.keys()):
                exps = by_val[v]
                lines.append(f"  - {v}: avg ${sum(exps)/len(exps):+.2f}, range [{min(exps):+.2f}, {max(exps):+.2f}] (n={len(exps)})")
            lines.append("")

    # RSI/BB sensitivity
    rsi_results = [r for r in results if r["engine"] == "rsi_bb_reversal" and r.get("total_trades", 0) > 0]
    if rsi_results:
        lines.append("### RSI/BB Reversal")
        lines.append("")
        for param_name in ["rsi_oversold", "bb_period", "bb_std"]:
            by_val = {}
            for r in rsi_results:
                v = r.get(param_name, "?")
                by_val.setdefault(v, []).append(r.get("expectancy_usd", 0))
            lines.append(f"**{param_name}**:")
            for v in sorted(by_val.keys()):
                exps = by_val[v]
                lines.append(f"  - {v}: avg ${sum(exps)/len(exps):+.2f}, range [{min(exps):+.2f}, {max(exps):+.2f}] (n={len(exps)})")
            lines.append("")

    # EMA sensitivity
    ema_results = [r for r in results if r["engine"] == "ema_crossover" and r.get("total_trades", 0) > 0]
    if ema_results:
        lines.append("### EMA Crossover")
        lines.append("")
        for param_name in ["ema_fast", "retest_zone_pct", "max_candles_since_cross"]:
            by_val = {}
            for r in ema_results:
                v = r.get(param_name, "?")
                by_val.setdefault(v, []).append(r.get("expectancy_usd", 0))
            lines.append(f"**{param_name}**:")
            for v in sorted(by_val.keys()):
                exps = by_val[v]
                lines.append(f"  - {v}: avg ${sum(exps)/len(exps):+.2f}, range [{min(exps):+.2f}, {max(exps):+.2f}] (n={len(exps)})")
            lines.append("")

    # Zero-signal combos
    zero_signal = [r for r in results if r.get("total_signals", 0) == 0]
    if zero_signal:
        lines.append("## Combinacoes sem sinais")
        lines.append("")
        lines.append(f"{len(zero_signal)} combinacoes nao geraram nenhum sinal.")
        lines.append("Isso indica filtros muito restritivos para esses parametros.")
        lines.append("")

    return "\n".join(lines)


# ============================================================
#  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Backtest parametrico dos 3 motores isolados")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--symbols", type=str, default=",".join(DEFAULT_SYMBOLS))
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    days = args.days

    vb_n, rsi_n, ema_n = count_combos()
    total_combos = (vb_n + rsi_n + ema_n) * len(symbols)

    print("=" * 70)
    print("  BACKTEST PARAMETRICO - 3 MOTORES ISOLADOS")
    print(f"  Periodo: {days} dias | Symbols: {', '.join(symbols)}")
    print(f"  VB: {vb_n} combos | RSI/BB: {rsi_n} combos | EMA: {ema_n} combos")
    print(f"  Total: {total_combos} combinacoes ({len(symbols)} symbols)")
    print(f"  Exit: Trailing | Capital: ${INITIAL_CAPITAL:,.0f} | Leverage: {LEVERAGE}x")
    print("=" * 70)

    all_results = []
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for symbol in symbols:
        print(f"\n{'='*50}")
        print(f"  Baixando dados para {symbol}...")
        print(f"{'='*50}")

        t0 = time.time()
        df_3m = fetch_historical_futures(symbol, "3m", days)
        df_5m = fetch_historical_futures(symbol, "5m", days)
        df_15m = fetch_historical_futures(symbol, "15m", days)
        dl_time = time.time() - t0
        print(f"  Download: {dl_time:.1f}s | 3m: {len(df_3m) if df_3m is not None else 0} | "
              f"5m: {len(df_5m) if df_5m is not None else 0} | 15m: {len(df_15m) if df_15m is not None else 0}")

        if df_3m is None or df_5m is None or df_15m is None:
            print(f"  ERRO: Dados insuficientes para {symbol}, pulando...")
            continue
        if len(df_5m) < WARMUP_CANDLES + 100:
            print(f"  ERRO: Menos de {WARMUP_CANDLES + 100} candles 5m, pulando...")
            continue

        # --- ADD BASE INDICATORS ---
        print("  Calculando indicadores base...")
        t0 = time.time()
        df_3m = add_base_indicators(df_3m)
        df_5m = add_base_indicators(df_5m)
        df_15m = add_base_indicators(df_15m)

        # --- PRECOMPUTE VARIANTS ---
        precompute_vb_variants(df_3m, VB_GRID["breakout_lookback"])
        precompute_bb_variants(df_5m, RSI_BB_GRID["bb_period"], RSI_BB_GRID["bb_std"])
        precompute_ema_variants(df_3m, EMA_GRID["ema_pair"])
        ind_time = time.time() - t0
        print(f"  Indicadores prontos em {ind_time:.1f}s")

        # --- TIME ALIGNMENT ---
        idx_3m_for_5m = build_time_index(df_5m, df_3m)
        idx_15m_for_5m = build_time_index(df_5m, df_15m)
        # Identity index for 5m->5m
        idx_5m_for_5m = np.arange(len(df_5m))

        # ============================================================
        # ENGINE 1: VOLUME BREAKOUT
        # ============================================================
        print(f"\n  --- Volume Breakout ({vb_n} combos) ---")
        vb_results = []
        done = 0
        t0 = time.time()

        for vol_th in VB_GRID["volume_threshold"]:
            for lb in VB_GRID["breakout_lookback"]:
                for atr_sl in VB_GRID["atr_multiplier_sl"]:
                    result = run_vb_combo(
                        symbol, df_3m, df_5m,
                        idx_3m_for_5m, idx_5m_for_5m,
                        vol_th, lb, atr_sl,
                    )
                    vb_results.append(result)
                    done += 1
                    if done % 10 == 0:
                        elapsed = time.time() - t0
                        print(f"    {done}/{vb_n} ({elapsed:.0f}s) "
                              f"- ultimo: {result['total_signals']} sinais, "
                              f"{result['total_trades']} trades, "
                              f"exp=${result.get('expectancy_usd', 0):+.2f}")

        vb_time = time.time() - t0
        print(f"  VB completo: {vb_time:.0f}s ({len(vb_results)} resultados)")
        all_results.extend(vb_results)
        save_progress(vb_results, f"vb_{symbol}")

        # ============================================================
        # ENGINE 2: RSI/BB REVERSAL
        # ============================================================
        print(f"\n  --- RSI/BB Reversal ({rsi_n} combos) ---")
        rsi_results = []
        done = 0
        t0 = time.time()

        for rsi_os, rsi_ob in RSI_BB_GRID["rsi_levels"]:
            for bb_p in RSI_BB_GRID["bb_period"]:
                for bb_s in RSI_BB_GRID["bb_std"]:
                    result = run_rsi_bb_combo(
                        symbol, df_5m, df_15m,
                        idx_15m_for_5m,
                        rsi_os, rsi_ob, bb_p, bb_s,
                    )
                    rsi_results.append(result)
                    done += 1
                    if done % 10 == 0:
                        elapsed = time.time() - t0
                        print(f"    {done}/{rsi_n} ({elapsed:.0f}s) "
                              f"- ultimo: {result['total_signals']} sinais, "
                              f"{result['total_trades']} trades, "
                              f"exp=${result.get('expectancy_usd', 0):+.2f}")

        rsi_time = time.time() - t0
        print(f"  RSI/BB completo: {rsi_time:.0f}s ({len(rsi_results)} resultados)")
        all_results.extend(rsi_results)
        save_progress(rsi_results, f"rsi_bb_{symbol}")

        # ============================================================
        # ENGINE 3: EMA CROSSOVER
        # ============================================================
        print(f"\n  --- EMA Crossover ({ema_n} combos) ---")
        ema_results_list = []
        done = 0
        t0 = time.time()

        for ema_f, ema_s in EMA_GRID["ema_pair"]:
            for zone in EMA_GRID["retest_zone_pct"]:
                for maxc in EMA_GRID["max_candles_since_cross"]:
                    result = run_ema_combo(
                        symbol, df_3m, df_5m, df_15m,
                        idx_3m_for_5m, idx_15m_for_5m,
                        ema_f, ema_s, zone, maxc,
                    )
                    ema_results_list.append(result)
                    done += 1
                    if done % 10 == 0:
                        elapsed = time.time() - t0
                        print(f"    {done}/{ema_n} ({elapsed:.0f}s) "
                              f"- ultimo: {result['total_signals']} sinais, "
                              f"{result['total_trades']} trades, "
                              f"exp=${result.get('expectancy_usd', 0):+.2f}")

        ema_time = time.time() - t0
        print(f"  EMA completo: {ema_time:.0f}s ({len(ema_results_list)} resultados)")
        all_results.extend(ema_results_list)
        save_progress(ema_results_list, f"ema_{symbol}")

    # ============================================================
    # FINAL OUTPUT
    # ============================================================
    print(f"\n{'='*70}")
    print(f"  GERANDO RESULTADOS FINAIS")
    print(f"{'='*70}")

    # Sort all results by expectancy
    all_results.sort(key=lambda r: r.get("expectancy_usd", 0), reverse=True)

    # Save CSV
    csv_path = os.path.join(OUTPUT_DIR, "parametric_results.csv")
    save_results_csv(all_results, csv_path)

    # Save markdown summary
    summary = generate_summary(all_results, days, symbols)
    md_path = os.path.join(OUTPUT_DIR, "parametric_summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"  Summary salvo: {md_path}")

    # Quick terminal summary
    positive = [r for r in all_results if r.get("expectancy_usd", 0) > 0 and r.get("total_trades", 0) > 0]
    with_trades = [r for r in all_results if r.get("total_trades", 0) > 0]

    print(f"\n  RESUMO RAPIDO:")
    print(f"  - Total combinacoes: {len(all_results)}")
    print(f"  - Com trades: {len(with_trades)}")
    print(f"  - Expectativa positiva: {len(positive)}")

    if positive:
        best = positive[0]
        print(f"\n  MELHOR COMBINACAO:")
        print(f"  Motor: {best['engine']}")
        print(f"  Symbol: {best['symbol']}")
        print(f"  Params: {best['params']}")
        print(f"  Trades: {best['total_trades']} | WR: {best['win_rate']:.1f}%")
        print(f"  Expectativa: ${best.get('expectancy_usd', 0):+.2f}/trade")
        print(f"  PnL total: ${best['total_pnl_usd']:+.2f}")
        print(f"  Profit Factor: {best['profit_factor']:.2f}")
        print(f"  Sharpe: {best['sharpe_simplified']:.2f}")
    else:
        print(f"\n  NENHUMA combinacao com expectativa positiva.")
        print(f"  O problema e estrutural nos motores de entrada.")
        if with_trades:
            least_bad = with_trades[0]
            print(f"\n  Menos pior:")
            print(f"  Motor: {least_bad['engine']} | {least_bad['symbol']}")
            print(f"  Params: {least_bad['params']}")
            print(f"  Exp: ${least_bad.get('expectancy_usd', 0):+.2f}/trade")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
