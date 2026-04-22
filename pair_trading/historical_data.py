"""Historical candle fetcher for pair trading.

Uses Binance Futures REST endpoint. Handles pagination for ranges > 1000.
"""
from __future__ import annotations

import time
from typing import List, Tuple

import numpy as np
import requests


_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
_MAX_PER_REQUEST = 1000


def fetch_klines(
    symbol: str,
    interval: str,
    limit: int,
    end_time_ms: int | None = None,
) -> List[list]:
    """Fetch `limit` klines ending at end_time_ms (or now).

    Returns raw list-of-lists from Binance. Handles pagination transparently
    by walking backward in time with end_time from previous batch.
    """
    out: List[list] = []
    remaining = limit
    cursor = end_time_ms

    while remaining > 0:
        page_size = min(remaining, _MAX_PER_REQUEST)
        params = {"symbol": symbol, "interval": interval, "limit": page_size}
        if cursor is not None:
            params["endTime"] = cursor
        r = requests.get(_KLINES_URL, params=params, timeout=15)
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        # Binance returns oldest → newest within a page; we walk backward, so
        # prepend pages to keep global chronological order.
        out = page + out
        remaining -= len(page)
        # Next page ends 1ms before the first candle of this page
        cursor = page[0][0] - 1
        if len(page) < page_size:
            break
        time.sleep(0.1)  # polite to the API
    return out


def klines_to_arrays(klines: List[list]) -> Tuple[np.ndarray, np.ndarray]:
    """Extract (close_prices, close_times_ms) as numpy arrays."""
    closes = np.array([float(k[4]) for k in klines], dtype=np.float64)
    close_times = np.array([int(k[6]) for k in klines], dtype=np.int64)
    return closes, close_times


def fetch_synced_pair(
    symbol_a: str,
    symbol_b: str,
    interval: str,
    limit: int,
    end_time_ms: int | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fetch both symbols and align by close_time.

    Returns (close_a, close_b, close_times) with only timestamps present in both.
    """
    a = fetch_klines(symbol_a, interval, limit, end_time_ms=end_time_ms)
    b = fetch_klines(symbol_b, interval, limit, end_time_ms=end_time_ms)

    a_close, a_ct = klines_to_arrays(a)
    b_close, b_ct = klines_to_arrays(b)

    common_ct, a_idx, b_idx = np.intersect1d(a_ct, b_ct, return_indices=True)
    return a_close[a_idx], b_close[b_idx], common_ct
