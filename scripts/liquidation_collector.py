#!/usr/bin/env python3
"""
Coletor de liquidacoes reais — persiste evento-cru em k_liquidations.

Processo daemon ISOLADO: liga o feed de liquidacoes (WebSocket) e grava cada
liquidacao no bot.db. NAO toca v1.1, executor nem k_collector.

Fonte: Bybit (allLiquidation) — o WS de futuros da Binance e bloqueado neste Pi
(ver memoria binance_futures_ws_blocked).

Rodar:  python scripts/liquidation_collector.py
Parar:  SIGTERM/SIGINT (faz flush final automatico).
"""
from __future__ import annotations

import logging
import os
import signal
import sqlite3
import sys
import threading
import time

# raiz do projeto no path (este script vive em scripts/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import bybit_liquidation_feed as feed  # noqa: E402
from liquidation_store import ensure_schema, insert_liquidations  # noqa: E402

SOURCE = "bybit"
DB_PATH = os.environ.get("LIQUIDATION_DB", "/home/pi/crypto_ai_bot/runtime/baseline/bot.db")
FLUSH_SECONDS = int(os.environ.get("LIQUIDATION_FLUSH_SECONDS", "5"))
HEALTH_SECONDS = int(os.environ.get("LIQUIDATION_HEALTH_SECONDS", "300"))

# Mesmos 14 simbolos do k_collector (override via LIQUIDATION_SYMBOLS).
_DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "HYPEUSDT", "LINKUSDT", "AVAXUSDT",
    "LTCUSDT", "TRXUSDT", "SUIUSDT", "1000PEPEUSDT",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [liq-collector] %(message)s")
log = logging.getLogger("liquidation_collector")

_running = True


def _symbols() -> list[str]:
    env = os.environ.get("LIQUIDATION_SYMBOLS", "").strip()
    if env:
        return [s.strip().upper() for s in env.split(",") if s.strip()]
    return list(_DEFAULT_SYMBOLS)


class LiquidationBuffer:
    """Buffer thread-safe: o feed (thread WS) faz add(), o loop principal drain()."""

    def __init__(self) -> None:
        self._rows: list[tuple] = []
        self._lock = threading.Lock()

    def add(self, event_ms, symbol, side, qty, price, notional, collected_at) -> None:
        with self._lock:
            self._rows.append(
                (symbol, int(event_ms), side, float(qty), float(price),
                 float(notional), int(collected_at))
            )

    def drain(self) -> list[tuple]:
        with self._lock:
            rows, self._rows = self._rows, []
        return rows

    def __len__(self) -> int:
        with self._lock:
            return len(self._rows)


def _install_signal_handlers() -> None:
    def _stop(signum, _frame):
        global _running
        log.info("Sinal %s recebido — encerrando.", signum)
        _running = False
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)


def run(db_path: str = DB_PATH, symbols=None, flush_seconds: int = FLUSH_SECONDS) -> int:
    """Loop principal. Retorna total de linhas gravadas nesta sessao."""
    symbols = symbols or _symbols()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000")
    ensure_schema(conn)

    buf = LiquidationBuffer()
    feed.set_event_sink(lambda ems, s, sd, q, p, n: buf.add(ems, s, sd, q, p, n, int(time.time())))
    feed.init_feed(symbols)
    log.info("Iniciado: source=%s, %d simbolos, db=%s, flush=%ds", SOURCE, len(symbols), db_path, flush_seconds)

    total = 0
    last_health = time.time()
    try:
        while _running:
            time.sleep(flush_seconds)
            total += insert_liquidations(conn, buf.drain(), source=SOURCE)
            now = time.time()
            if now - last_health >= HEALTH_SECONDS:
                st = feed.feed_stats()
                log.info(
                    "saude: gravadas=%d conectado=%s recebidas=%d liq=%d",
                    total, st.get("connected"), st.get("total_received", 0),
                    st.get("total_liq", 0),
                )
                last_health = now
    finally:
        feed.set_event_sink(None)
        feed.stop_feed()
        total += insert_liquidations(conn, buf.drain(), source=SOURCE)  # flush final
        conn.close()
        log.info("Encerrado. Total gravadas nesta sessao: %d", total)
    return total


if __name__ == "__main__":
    _install_signal_handlers()
    run()
