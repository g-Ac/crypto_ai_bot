"""Candle fetching, alignment by timestamp, and gap validation.

Fetching from Binance fapi is paginated per symbol. Alignment intersects
timestamps across symbols. Gap validation aborts before backtest if any
symbol has more missing candles than threshold permits.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd
import requests


_FAPI_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
_MAX_PER_REQUEST = 1000


class GapValidationError(Exception):
    """Raised when a symbol has too many missing candles."""


@dataclass(frozen=True)
class FetchResult:
    symbol: str
    candles: pd.DataFrame
    first_close_time_ms: int
    last_close_time_ms: int


def fetch_klines_paginated(
    symbol: str, interval: str, end_time_ms: int, total_needed: int,
    *, sleep_between: float = 0.1,
) -> pd.DataFrame:
    """Fetch backwards from end_time_ms in pages of 1000. Returns DataFrame oldest-first."""
    cursor = end_time_ms
    out_pages: list[list] = []
    remaining = total_needed
    while remaining > 0:
        limit = min(_MAX_PER_REQUEST, remaining)
        resp = requests.get(_FAPI_KLINES_URL, params={
            "symbol": symbol, "interval": interval, "limit": limit, "endTime": cursor,
        }, timeout=30)
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        out_pages.insert(0, page)
        cursor = page[0][0] - 1
        remaining -= len(page)
        time.sleep(sleep_between)
    rows = [r for page in out_pages for r in page]
    if not rows:
        return pd.DataFrame(columns=["close_time_ms", "open", "high", "low", "close", "volume"])
    return pd.DataFrame({
        "close_time_ms": [int(r[6]) for r in rows],
        "open": [float(r[1]) for r in rows],
        "high": [float(r[2]) for r in rows],
        "low": [float(r[3]) for r in rows],
        "close": [float(r[4]) for r in rows],
        "volume": [float(r[5]) for r in rows],
    })


def align_candles_by_timestamp(
    candles_by_symbol: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Intersect timestamps across all symbols and return aligned subsets."""
    if not candles_by_symbol:
        raise ValueError("candles_by_symbol must not be empty")

    common = None
    for sym, df in candles_by_symbol.items():
        ts_set = set(df["close_time_ms"].values.tolist())
        common = ts_set if common is None else (common & ts_set)
    common_sorted = sorted(common)

    aligned: dict[str, pd.DataFrame] = {}
    for sym, df in candles_by_symbol.items():
        mask = df["close_time_ms"].isin(common_sorted)
        aligned[sym] = df.loc[mask].reset_index(drop=True)
    return aligned


def validate_gap_threshold(
    *, symbol: str, expected: int, actual: int, threshold_pct: float,
) -> None:
    """Raise GapValidationError if gap exceeds threshold_pct of expected."""
    if expected <= 0:
        raise ValueError(f"expected must be positive, got {expected}")
    gap = expected - actual
    gap_pct = (gap / expected) * 100.0
    if gap_pct > threshold_pct:
        raise GapValidationError(
            f"{symbol}: expected_candles={expected}, actual_candles={actual}, "
            f"gap_pct={gap_pct:.2f}% > threshold {threshold_pct}%"
        )
