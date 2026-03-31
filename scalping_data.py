"""
Modulo de dados OHLCV para a estrategia de scalping.

Busca candles da Binance via REST API (spot/futures) e calcula
indicadores tecnicos necessarios para os 3 motores.
Implementa cache simples para evitar chamadas duplicadas no mesmo ciclo.
"""
import time
import logging
import requests
import pandas as pd
import ta
from typing import Optional, Dict, Tuple

logger = logging.getLogger("scalping.data")

# Cache de candles por (symbol, interval) — limpo a cada ciclo
_candle_cache: Dict[Tuple[str, str], Tuple[float, pd.DataFrame]] = {}
_CACHE_TTL_SECONDS = 30  # candles validos por 30s


def clear_cache() -> None:
    """Limpa o cache de candles. Chamar no inicio de cada ciclo."""
    _candle_cache.clear()


def _backoff_delay(attempt: int, response: Optional[requests.Response] = None) -> float:
    """Calcula delay de retry com backoff exponencial."""
    if response is not None and response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(int(retry_after), 60)
            except ValueError:
                pass
        return min(2 ** (attempt + 1), 30)
    return min(2 ** attempt, 10)


def fetch_candles(symbol: str, interval: str, limit: int = 100) -> Optional[pd.DataFrame]:
    """
    Busca candles OHLCV da Binance Spot API.

    Usa cache para evitar chamadas duplicadas no mesmo ciclo.
    Retorna DataFrame com colunas: time, open, high, low, close, volume.
    Retorna None em caso de falha.
    """
    cache_key = (symbol, interval)
    now = time.time()

    # Verificar cache
    if cache_key in _candle_cache:
        cached_time, cached_df = _candle_cache[cache_key]
        if now - cached_time < _CACHE_TTL_SECONDS:
            return cached_df.copy()

    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}&interval={interval}&limit={limit}"
    )

    for attempt in range(3):
        try:
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                df = pd.DataFrame(data, columns=[
                    "time", "open", "high", "low", "close", "volume",
                    "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
                ])

                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = df[col].astype(float)

                df["time"] = pd.to_datetime(df["time"], unit="ms")

                # Manter apenas colunas necessarias
                df = df[["time", "open", "high", "low", "close", "volume"]].copy()

                # Salvar no cache
                _candle_cache[cache_key] = (now, df)
                return df.copy()

            else:
                delay = _backoff_delay(attempt, response)
                logger.warning(
                    "HTTP %d para %s/%s (retry %d em %.1fs)",
                    response.status_code, symbol, interval, attempt + 1, delay
                )
                time.sleep(delay)

        except Exception as e:
            delay = _backoff_delay(attempt)
            logger.warning(
                "Erro ao buscar %s/%s (tentativa %d): %s",
                symbol, interval, attempt + 1, e
            )
            time.sleep(delay)

    logger.error("Falha ao buscar candles %s/%s apos 3 tentativas", symbol, interval)
    return None


def get_funding_rate(symbol: str) -> Optional[float]:
    """
    Busca o funding rate atual de um par de futuros na Binance.

    Retorna o funding rate como percentual (ex: 0.01 = 0.01%).
    Retorna None em caso de falha.
    """
    # Converter symbol para formato futures se necessario
    url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data:
                rate = float(data[0]["fundingRate"]) * 100  # converter para %
                logger.info("Funding rate %s: %.4f%%", symbol, rate)
                return rate
    except Exception as e:
        logger.warning("Erro ao buscar funding rate %s: %s", symbol, e)

    return None


def add_scalping_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adiciona todos os indicadores necessarios para os 3 motores de scalping.

    Indicadores calculados:
    - EMA 9, 21, 20, 50
    - RSI(14)
    - Bollinger Bands (20, 2.0)
    - ATR(14)
    - Volume media 20 periodos
    - Body ratio e wick ratio
    """
    if df is None or len(df) < 50:
        return df

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # EMAs
    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    # RSI
    df["rsi"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_bandwidth"] = bb.bollinger_wband()

    # ATR
    df["atr14"] = ta.volatility.AverageTrueRange(
        high=high, low=low, close=close, window=14
    ).average_true_range()

    # Volume media
    df["volume_avg20"] = volume.rolling(window=20).mean()

    # Body e wick ratio
    candle_range = high - low
    candle_range_safe = candle_range.replace(0, float("nan"))
    body = (close - df["open"]).abs()
    df["body_ratio"] = body / candle_range_safe
    df["body_ratio"] = df["body_ratio"].fillna(0)

    # Wick superior e inferior como % do range
    df["upper_wick"] = (high - close.where(close >= df["open"], df["open"])) / candle_range_safe
    df["lower_wick"] = (close.where(close < df["open"], df["open"]) - low) / candle_range_safe
    df["upper_wick"] = df["upper_wick"].fillna(0).clip(0, 1)
    df["lower_wick"] = df["lower_wick"].fillna(0).clip(0, 1)

    # Highs e lows recentes (para breakout)
    df["high_5"] = high.rolling(window=5).max().shift(1)
    df["low_5"] = low.rolling(window=5).min().shift(1)
    df["high_20"] = high.rolling(window=20).max().shift(1)
    df["low_20"] = low.rolling(window=20).min().shift(1)

    # Low/high dos ultimos 3 candles (para SL do RSI/BB)
    df["low_3"] = low.rolling(window=3).min()
    df["high_3"] = high.rolling(window=3).max()

    return df
