import pandas as pd
import ta

from config import INTERVAL_HTF, LIMIT, SMA_SHORT, SMA_LONG
from market import get_candles
from indicators import add_indicators

# Regime Gate v2 thresholds
ADX_SLOPE_THRESHOLD = 0.0    # slope <= 0 = trend weakening
DI_SPREAD_THRESHOLD = 10.0   # spread < 10 = no directional conviction


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
            return {"adx_1h": 0, "atr_1h_pct": 0, "bb_width_1h": 0, "regime_label": "UNKNOWN",
                    "adx_slope_3": 0.0, "di_spread": 0.0}

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        # ADX(14)
        adx_ind = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
        adx_series = adx_ind.adx()
        adx_raw = adx_series.iloc[-2]
        adx_val = 0.0 if pd.isna(adx_raw) else float(adx_raw)

        # ADX Slope (delta over 3 candles) — detects exhausting trends
        if len(adx_series) >= 5 and not pd.isna(adx_raw):
            slope_start = adx_series.iloc[-5]
            if not pd.isna(slope_start):
                adx_slope = float(adx_raw) - float(slope_start)
            else:
                adx_slope = None
        else:
            adx_slope = None

        # DI Spread — directional conviction
        di_plus = adx_ind.adx_pos().iloc[-2]
        di_minus = adx_ind.adx_neg().iloc[-2]
        if pd.isna(di_plus) or pd.isna(di_minus):
            di_spread = 0.0
        else:
            di_spread = abs(float(di_plus) - float(di_minus))

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
            bb_upper = bb.bollinger_hband().iloc[-2]
            bb_lower = bb.bollinger_lband().iloc[-2]
            bb_width_pct = ((bb_upper - bb_lower) / bb_mid) * 100
        else:
            bb_width_pct = 0.0

        # Regime classification (5 categories + v2 quality filters)
        if adx_val >= 25:
            if bb_width_pct > 1.5:
                adx_exhausting = adx_slope is not None and adx_slope <= ADX_SLOPE_THRESHOLD
                chop_bidirectional = di_spread < DI_SPREAD_THRESHOLD
                if adx_exhausting or chop_bidirectional:
                    regime = "WEAK_TREND"
                else:
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
            "adx_slope_3": round(float(adx_slope), 2) if adx_slope is not None else 0.0,
            "di_spread": round(float(di_spread), 1),
        }
    except Exception as e:
        import logging
        logging.getLogger("htf").warning("Erro ao calcular regime para %s: %s", symbol, e)
        return {"adx_1h": 0, "atr_1h_pct": 0, "bb_width_1h": 0, "regime_label": "UNKNOWN",
                "adx_slope_3": 0.0, "di_spread": 0.0}
