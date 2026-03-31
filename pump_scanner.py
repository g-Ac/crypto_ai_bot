"""
Pump Scanner - detecta volume anormal e movimentos explosivos.
Roda independente do bot principal.
"""
import time
import json
import os
import tempfile
import requests
import pandas as pd
import database as db
from datetime import datetime
from config import (
    PUMP_VOLUME_MULTIPLIER, PUMP_PRICE_CHANGE_MIN,
    PUMP_SCAN_INTERVAL, PUMP_TOP_COINS,
)
from telegram_notifier import send_telegram_message, send_pump_alert
from pump_trader import open_position, check_positions, get_status
from daily_report import is_circuit_broken
from telegram_commands import is_paused

ALERT_COOLDOWN_FILE = "pump_cooldown.json"
COOLDOWN_MINUTES = 30


def load_cooldown():
    if not os.path.exists(ALERT_COOLDOWN_FILE):
        return {}
    with open(ALERT_COOLDOWN_FILE, "r") as f:
        return json.load(f)


def save_cooldown(data):
    content = json.dumps(data, indent=2)
    dir_name = os.path.dirname(os.path.abspath(ALERT_COOLDOWN_FILE))
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as f:
        f.write(content)
        tmp_path = f.name
    os.replace(tmp_path, ALERT_COOLDOWN_FILE)


def is_on_cooldown(symbol):
    cd = load_cooldown()
    if symbol not in cd:
        return False
    last = datetime.fromisoformat(cd[symbol])
    diff = (datetime.now() - last).total_seconds() / 60
    return diff < COOLDOWN_MINUTES


def set_cooldown(symbol):
    cd = load_cooldown()
    cd[symbol] = datetime.now().isoformat()
    save_cooldown(cd)


def get_top_symbols():
    """Get top USDT pairs by 24h volume from Binance."""
    for attempt in range(3):
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/ticker/24hr", timeout=10
            )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                print(f"Rate limit (429) ao buscar tickers, aguardando {retry_after}s...")
                time.sleep(min(retry_after, 30))
                continue
            if resp.status_code != 200:
                print(f"Erro ao buscar tickers: {resp.status_code}")
                return []

            tickers = resp.json()

            usdt_pairs = [
                t for t in tickers
                if t["symbol"].endswith("USDT")
                and float(t["quoteVolume"]) > 0
                and "UP" not in t["symbol"]
                and "DOWN" not in t["symbol"]
                and "BEAR" not in t["symbol"]
                and "BULL" not in t["symbol"]
            ]

            usdt_pairs.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
            return [t["symbol"] for t in usdt_pairs[:PUMP_TOP_COINS]]

        except Exception as e:
            print(f"Tentativa {attempt + 1} falhou ao buscar tickers: {e}")
            time.sleep(min(2 ** attempt, 10))
    return []


def analyze_symbol(symbol):
    """Check if a symbol has abnormal volume and price movement."""
    try:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=5m&limit=25"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json()
        if len(data) < 25:
            return None

        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # Current candle (last completed)
        current = df.iloc[-2]
        # Average volume of previous 20 candles
        avg_volume = df.iloc[-22:-2]["volume"].mean()

        if avg_volume == 0:
            return None

        volume_ratio = current["volume"] / avg_volume
        price_change = ((current["close"] - current["open"]) / current["open"]) * 100

        # Also check last 3 candles combined for sustained move
        last_3_close = df.iloc[-2]["close"]
        last_3_open = df.iloc[-4]["open"]
        price_change_3 = ((last_3_close - last_3_open) / last_3_open) * 100

        return {
            "symbol": symbol,
            "price": current["close"],
            "volume_ratio": round(volume_ratio, 2),
            "price_change_1": round(price_change, 2),
            "price_change_3": round(price_change_3, 2),
            "avg_volume": avg_volume,
            "current_volume": current["volume"],
        }

    except Exception:
        return None


def scan():
    """Run one scan cycle."""
    if is_circuit_broken("pump"):
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Circuit breaker ativo - pump trading pausado")
        # Still check existing positions even when circuit breaker is active
        pos_msgs = check_positions()
        for msg in pos_msgs:
            print(f"  {msg}")
            send_telegram_message(f"\U0001f680 <b>[PUMP]</b> {msg}")
        print(f"  {get_status()}")
        return

    symbols = get_top_symbols()
    if not symbols:
        print("Nenhum simbolo encontrado.")
        return

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Escaneando {len(symbols)} moedas...")

    alerts = []

    for symbol in symbols:
        result = analyze_symbol(symbol)
        if result is None:
            continue

        vol_r = result["volume_ratio"]
        pc1 = result["price_change_1"]
        pc3 = result["price_change_3"]

        # Detection criteria:
        # 1. Volume spike + price move (single candle)
        # 2. Sustained move over 3 candles with volume
        is_pump = (
            (vol_r >= PUMP_VOLUME_MULTIPLIER and abs(pc1) >= PUMP_PRICE_CHANGE_MIN)
            or (vol_r >= PUMP_VOLUME_MULTIPLIER * 0.6 and abs(pc3) >= PUMP_PRICE_CHANGE_MIN * 2)
        )

        if is_pump and not is_on_cooldown(symbol):
            direction = "PUMP" if pc1 > 0 or pc3 > 0 else "DUMP"
            result["direction"] = direction
            alerts.append(result)
            set_cooldown(symbol)

        time.sleep(0.1)  # Rate limiting

    # Check existing positions (trailing stop, timeout)
    pos_msgs = check_positions()
    for msg in pos_msgs:
        print(f"  {msg}")
        send_telegram_message(f"\U0001f680 <b>[PUMP]</b> {msg}")

    if is_paused():
        print("  Bot pausado - novas posicoes suspensas.")
        print(f"  {get_status()}")
        return

    if alerts:
        alerts.sort(key=lambda x: x["volume_ratio"], reverse=True)
        print(f"  {len(alerts)} alertas detectados!")

        for a in alerts:
            try:
                direction = "LONG" if a["direction"] == "PUMP" else "SHORT"

                # Open trade
                trade_msg = open_position(a["symbol"], direction, a["price"], a["volume_ratio"])

                print(f"  {a['symbol']}: {a['direction']} | Vol: {a['volume_ratio']}x | {a['price_change_1']:+.2f}%")
                send_pump_alert(
                    symbol=a["symbol"],
                    direction=a["direction"],
                    price=a["price"],
                    volume_ratio=a["volume_ratio"],
                    change_1=a["price_change_1"],
                    change_3=a["price_change_3"],
                )

                if trade_msg:
                    print(f"  {trade_msg}")
                    send_telegram_message(f"\U0001f680 <b>[PUMP]</b> {trade_msg}")
            except Exception as e:
                print(f"  [ERRO] Falha ao processar alerta {a['symbol']}: {e}")
    else:
        print("  Nenhuma anomalia detectada.")

    # Print status
    print(f"  {get_status()}")


if __name__ == "__main__":
    db.init_db()
    print("=" * 50)
    print("  PUMP SCANNER")
    print(f"  Top {PUMP_TOP_COINS} moedas | Vol >= {PUMP_VOLUME_MULTIPLIER}x | Price >= {PUMP_PRICE_CHANGE_MIN}%")
    print(f"  Scan a cada {PUMP_SCAN_INTERVAL}s | Cooldown: {COOLDOWN_MINUTES}min")
    print("=" * 50)

    while True:
        try:
            scan()
            print(f"  Proximo scan em {PUMP_SCAN_INTERVAL}s...")
            time.sleep(PUMP_SCAN_INTERVAL)
        except Exception as e:
            print(f"Erro: {e}")
            time.sleep(PUMP_SCAN_INTERVAL)
