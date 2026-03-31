import requests
import pandas as pd
import time


def _backoff_delay(attempt, response=None):
    """Calculate retry delay: respect Retry-After header or use exponential backoff."""
    if response is not None and response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(int(retry_after), 60)
            except ValueError:
                pass
        return min(2 ** (attempt + 1), 30)
    return min(2 ** attempt, 10)


def get_candles(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"

    for attempt in range(3):
        try:
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()

                df = pd.DataFrame(data, columns=[
                    "time", "open", "high", "low", "close", "volume",
                    "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
                ])

                numeric_cols = ["open", "high", "low", "close", "volume"]
                for col in numeric_cols:
                    df[col] = df[col].astype(float)

                df["time"] = pd.to_datetime(df["time"], unit="ms")

                return df

            else:
                delay = _backoff_delay(attempt, response)
                print(f"Erro HTTP {response.status_code} para {symbol} (retry em {delay}s)")
                time.sleep(delay)

        except Exception as e:
            delay = _backoff_delay(attempt)
            print(f"Tentativa {attempt + 1} falhou para {symbol}: {e} (retry em {delay}s)")
            time.sleep(delay)

    raise Exception(f"Falha ao buscar dados para {symbol} após 3 tentativas.")