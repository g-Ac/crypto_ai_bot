import math
from config import INTERVAL_HTF, LIMIT, SMA_SHORT, SMA_LONG
from market import get_candles
from indicators import add_indicators


def get_htf_trend(symbol: str) -> str:
    df = get_candles(symbol, INTERVAL_HTF, LIMIT)
    df = add_indicators(df)
    last = df.iloc[-2]

    sma_short = last[f"sma_{SMA_SHORT}"]
    sma_long = last[f"sma_{SMA_LONG}"]

    if sma_short > sma_long:
        return "alta"
    elif sma_short < sma_long:
        return "baixa"
    else:
        return "lateral"


def get_htf_data(symbol: str) -> dict:
    """Retorna dados completos do timeframe 1h para o Agent V2."""
    df = get_candles(symbol, INTERVAL_HTF, LIMIT)
    df = add_indicators(df)
    last = df.iloc[-2]

    sma_short = float(last[f"sma_{SMA_SHORT}"])
    sma_long = float(last[f"sma_{SMA_LONG}"])

    if sma_short > sma_long:
        trend = "alta"
    elif sma_short < sma_long:
        trend = "baixa"
    else:
        trend = "lateral"

    atr14 = float(last["atr14"])
    if math.isnan(atr14):
        atr14 = 0.0

    return {
        "trend": trend,
        "sma9": round(sma_short, 6),
        "sma21": round(sma_long, 6),
        "rsi": round(float(last["rsi"]), 2),
        "atr14": round(atr14, 6),
    }
