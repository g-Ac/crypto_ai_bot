import pandas as pd
import ta

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


def get_htf_regime(symbol: str) -> dict:
    """Calculate ADX, ATR%, and BB Width on 1h data for regime classification.

    Returns dict with adx_1h, atr_1h_pct, bb_width_1h, regime_label.
    """
    try:
        df = get_candles(symbol, INTERVAL_HTF, LIMIT)
        if df is None or len(df) < 30:
            return {"adx_1h": 0, "atr_1h_pct": 0, "bb_width_1h": 0, "regime_label": "UNKNOWN"}

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        # ADX(14)
        adx_ind = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
        adx_val = adx_ind.adx().iloc[-2]
        if pd.isna(adx_val):
            adx_val = 0.0

        # ATR(14) as % of price
        atr_ind = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=14)
        atr_val = atr_ind.average_true_range().iloc[-2]
        price = close.iloc[-2]
        atr_pct = (atr_val / price * 100) if (price > 0 and not pd.isna(atr_val)) else 0.0

        # BB Width (20, 2.0) — ta library returns wband already as ratio * 100-ish scale
        bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
        bb_width_raw = bb.bollinger_wband().iloc[-2]
        bb_mid = bb.bollinger_mavg().iloc[-2]
        if not pd.isna(bb_width_raw) and not pd.isna(bb_mid) and bb_mid > 0:
            # Manual calculation for consistent % interpretation
            bb_upper = bb.bollinger_hband().iloc[-2]
            bb_lower = bb.bollinger_lband().iloc[-2]
            bb_width_pct = ((bb_upper - bb_lower) / bb_mid) * 100
        else:
            bb_width_pct = 0.0

        # Regime label (5 categories)
        # | ADX    | BB Width | Regime      | Motores permitidos  |
        # | >= 25  | > 1.5%   | TRENDING    | M1 + M2 + M3       |
        # | >= 25  | <= 1.5%  | WEAK_TREND  | M1 + M3            |
        # | < 25   | > 2.0%   | VOLATILE    | M2 apenas           |
        # | < 25   | 0.8-2.0% | RANGING     | M1 + M3            |
        # | < 25   | < 0.8%   | CHOPPY      | NENHUM              |
        if adx_val >= 25:
            if bb_width_pct > 1.5:
                regime = "TRENDING"
            else:
                regime = "WEAK_TREND"
        else:
            if bb_width_pct > 2.0:
                regime = "VOLATILE"
            elif bb_width_pct >= 0.8:
                regime = "RANGING"
            else:
                regime = "CHOPPY"

        return {
            "adx_1h": round(float(adx_val), 1),
            "atr_1h_pct": round(float(atr_pct), 2),
            "bb_width_1h": round(float(bb_width_pct), 2),
            "regime_label": regime,
        }
    except Exception as e:
        import logging
        logging.getLogger("htf").warning("Erro ao calcular regime para %s: %s", symbol, e)
        return {"adx_1h": 0, "atr_1h_pct": 0, "bb_width_1h": 0, "regime_label": "UNKNOWN"}
