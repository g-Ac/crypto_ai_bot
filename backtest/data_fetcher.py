"""Fetch historical candle data from Binance public API.

Downloads OHLCV data and saves as CSV for backtesting.
No API key needed — uses public klines endpoint.

Usage:
    python -m backtest.data_fetcher --symbol BTCUSDT --interval 15m --days 180
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
DATA_DIR = Path("data/candles")
MAX_LIMIT = 1000  # Binance max per request
RATE_LIMIT_SLEEP = 0.3  # seconds between requests


def fetch_klines(
    symbol: str,
    interval: str,
    start_time: datetime,
    end_time: datetime,
) -> pd.DataFrame:
    """Fetch klines from Binance in batches.

    Args:
        symbol: e.g. "BTCUSDT"
        interval: e.g. "15m", "1h", "5m"
        start_time: UTC start (inclusive)
        end_time: UTC end (inclusive)

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    all_rows: List[list] = []
    current_start = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    interval_ms = _interval_to_ms(interval)
    total_expected = (end_ms - current_start) // interval_ms
    fetched = 0

    logger.info(
        "Fetching %s %s from %s to %s (~%d candles)",
        symbol, interval, start_time.date(), end_time.date(), total_expected,
    )

    while current_start < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_ms,
            "limit": MAX_LIMIT,
        }

        try:
            resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("API error: %s — retrying in 5s", e)
            time.sleep(5)
            continue

        if not data:
            break

        all_rows.extend(data)
        fetched += len(data)

        # Move start to after last candle
        last_open_time = data[-1][0]
        current_start = last_open_time + interval_ms

        if fetched % 5000 == 0 or len(data) < MAX_LIMIT:
            logger.info("  ... %d candles fetched", fetched)

        if len(data) < MAX_LIMIT:
            break

        time.sleep(RATE_LIMIT_SLEEP)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ])

    # Keep only OHLCV
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()

    # Convert types
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("timestamp").reset_index(drop=True)

    # Remove duplicates
    df = df.drop_duplicates(subset=["timestamp"]).reset_index(drop=True)

    logger.info("Fetched %d candles for %s %s", len(df), symbol, interval)
    return df


def save_candles(df: pd.DataFrame, symbol: str, interval: str) -> Path:
    """Save candles to CSV in data/candles/<symbol>_<interval>.csv."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{symbol}_{interval}.csv"
    df.to_csv(path, index=False)
    logger.info("Saved %d candles to %s", len(df), path)
    return path


def load_cached_candles(symbol: str, interval: str) -> Optional[pd.DataFrame]:
    """Load candles from cache if available."""
    path = DATA_DIR / f"{symbol}_{interval}.csv"
    if not path.exists():
        return None

    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fetch_and_cache(
    symbol: str,
    interval: str,
    days: int = 180,
    force: bool = False,
) -> pd.DataFrame:
    """Fetch candles and cache to disk. Use cache if fresh enough.

    Args:
        symbol: e.g. "BTCUSDT"
        interval: e.g. "15m"
        days: How many days of history.
        force: Force re-download even if cache exists.

    Returns:
        DataFrame with candles.
    """
    if not force:
        cached = load_cached_candles(symbol, interval)
        if cached is not None and len(cached) > 0:
            # Check if cache covers enough
            cache_days = (cached["timestamp"].iloc[-1] - cached["timestamp"].iloc[0]).days
            if cache_days >= days * 0.9:
                logger.info("Using cached %s %s (%d candles, %d days)", symbol, interval, len(cached), cache_days)
                return cached

    end_time = datetime.now(timezone.utc) - timedelta(days=1)
    start_time = end_time - timedelta(days=days)

    df = fetch_klines(symbol, interval, start_time, end_time)
    if len(df) > 0:
        save_candles(df, symbol, interval)
    return df


def _interval_to_ms(interval: str) -> int:
    """Convert Binance interval string to milliseconds."""
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    for suffix, ms in units.items():
        if interval.endswith(suffix):
            return int(interval[:-1]) * ms
    raise ValueError(f"Unknown interval: {interval}")


def fetch_all_required(days: int = 180, force: bool = False) -> dict:
    """Fetch all data needed for backtest matrix.

    Downloads:
      BTC+ETH x (15m, 1h, 5m)
    """
    symbols = ["BTCUSDT", "ETHUSDT"]
    intervals = ["15m", "1h", "5m"]
    results = {}

    for symbol in symbols:
        for interval in intervals:
            key = f"{symbol}_{interval}"
            logger.info("--- Fetching %s ---", key)
            df = fetch_and_cache(symbol, interval, days=days, force=force)
            results[key] = {
                "candles": len(df),
                "start": str(df["timestamp"].iloc[0]) if len(df) > 0 else "",
                "end": str(df["timestamp"].iloc[-1]) if len(df) > 0 else "",
            }
            logger.info("  %s: %d candles", key, len(df))

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="Fetch Binance historical candles")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--all", action="store_true", help="Fetch all required data")
    parser.add_argument("--force", action="store_true", help="Force re-download")
    args = parser.parse_args()

    if args.all:
        results = fetch_all_required(days=args.days, force=args.force)
        for k, v in results.items():
            print(f"  {k}: {v['candles']} candles ({v['start']} → {v['end']})")
    else:
        df = fetch_and_cache(args.symbol, args.interval, days=args.days, force=args.force)
        print(f"Fetched {len(df)} candles")
