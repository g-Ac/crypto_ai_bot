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
