import ta
from config import SMA_SHORT, SMA_LONG, RSI_WINDOW, BREAKOUT_WINDOW, VOLUME_WINDOW


def add_indicators(df):
    df[f"sma_{SMA_SHORT}"] = df["close"].rolling(window=SMA_SHORT).mean()
    df[f"sma_{SMA_LONG}"] = df["close"].rolling(window=SMA_LONG).mean()
    df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=RSI_WINDOW).rsi()

    df[f"sma_{SMA_SHORT}_prev"] = df[f"sma_{SMA_SHORT}"].shift(1)
    df[f"sma_{SMA_LONG}_prev"] = df[f"sma_{SMA_LONG}"].shift(1)

    df[f"recent_high_{BREAKOUT_WINDOW}"] = df["high"].rolling(window=BREAKOUT_WINDOW).max().shift(1)
    df[f"recent_low_{BREAKOUT_WINDOW}"] = df["low"].rolling(window=BREAKOUT_WINDOW).min().shift(1)

    df["volume_avg"] = df["volume"].rolling(window=VOLUME_WINDOW).mean()

    candle_range = df["high"] - df["low"]
    df["body_ratio"] = (df["close"] - df["open"]) / candle_range.replace(0, float("nan"))
    df["body_ratio"] = df["body_ratio"].fillna(0)

    df["atr14"] = ta.volatility.AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()

    return df
