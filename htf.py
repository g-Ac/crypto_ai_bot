import pandas as pd

from config import INTERVAL_HTF, LIMIT, SMA_SHORT, SMA_LONG
from market import get_candles
from indicators import add_indicators


def classify_htf_trend(sma_short_val, sma_long_val):
    """Classify HTF trend from SMA values.

    Single source of truth for HTF trend classification, used by both
    the live bot (get_htf_trend) and the backtester (compute_htf_trends).

    Returns 'alta', 'baixa', or 'lateral'.
    """
    if pd.isna(sma_short_val) or pd.isna(sma_long_val):
        return "lateral"
    if sma_short_val > sma_long_val:
        return "alta"
    elif sma_short_val < sma_long_val:
        return "baixa"
    else:
        return "lateral"


def get_htf_trend(symbol: str) -> str:
    df = get_candles(symbol, INTERVAL_HTF, LIMIT)
    df = add_indicators(df)
    last = df.iloc[-2]

    return classify_htf_trend(
        last[f"sma_{SMA_SHORT}"],
        last[f"sma_{SMA_LONG}"],
    )
