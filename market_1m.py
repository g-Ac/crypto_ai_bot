"""Market data fetching for 1-minute trading system.

Two modes:
  - Live: fetch latest N candles from Binance Futures API
  - Historical: use backtest/data_fetcher.py for bulk download + caching
"""
import time
import pandas as pd
import requests
from config import BINANCE_FUTURES_KLINES_URL
from backtest.data_fetcher import fetch_and_cache


def fetch_1m_candles_live(symbol: str, limit: int = 200) -> pd.DataFrame:
    """Fetch latest 1-min candles from Binance Futures.

    Args:
        symbol: e.g. "BTCUSDT"
        limit: number of candles (max 1500)

    Returns:
        DataFrame with columns: time, open, high, low, close, volume
    """
    url = BINANCE_FUTURES_KLINES_URL
    params = {"symbol": symbol, "interval": "1m", "limit": limit}

    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                df = pd.DataFrame(data, columns=[
                    "time", "open", "high", "low", "close", "volume",
                    "close_time", "qav", "trades", "tbbav", "tbqav", "ignore",
                ])
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = df[col].astype(float)
                df["time"] = pd.to_datetime(df["time"], unit="ms")
                return df[["time", "open", "high", "low", "close", "volume"]].copy()
            delay = min(2 ** (attempt + 1), 30)
            time.sleep(delay)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(min(2 ** attempt, 10))

    raise Exception(f"Falha ao buscar 1m candles para {symbol} apos 3 tentativas")


def fetch_1m_historical(
    symbol: str, days: int = 30, force: bool = False,
) -> pd.DataFrame:
    """Fetch historical 1-min candles via data_fetcher (cached to disk).

    Args:
        symbol: e.g. "BTCUSDT"
        days: how many days of history
        force: force re-download even if cache exists

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    return fetch_and_cache(symbol, "1m", days=days, force=force)
