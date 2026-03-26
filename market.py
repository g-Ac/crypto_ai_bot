import requests
import pandas as pd
import time


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
                print(f"Erro HTTP {response.status_code} para {symbol}")
                time.sleep(2)

        except Exception as e:
            print(f"Tentativa {attempt + 1} falhou para {symbol}: {e}")
            time.sleep(2)

    raise Exception(f"Falha ao buscar dados para {symbol} após 3 tentativas.")