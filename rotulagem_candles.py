"""Busca CEGA de candles na Binance REST pra a tela de rotulagem.

So traz candles que fecharam ANTES do instante de entrada do trade — nada do
futuro vaza pro grafico. A fonte e a REST fapi (o WS desta maquina e bloqueado,
mas a REST entrega historico de qualquer epoca; validado a mao).
"""
from __future__ import annotations

import requests

_BINANCE_KLINES = "https://fapi.binance.com/fapi/v1/klines"


def _parse_klines(raw: list, entry_ms: int) -> list[dict]:
    """Formata klines (lightweight-charts) e corta os que fecham depois do entry."""
    out: list[dict] = []
    for k in raw:
        if int(k[6]) <= entry_ms:  # close_time_ms
            out.append({
                "time": int(k[0]) // 1000,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
            })
    return out


def blind_candles(symbol: str, entry_time_s: int, interval: str = "15m", n: int = 80) -> list[dict]:
    """~n candles que fecharam antes da entrada do trade. Lanca em erro de rede."""
    entry_ms = int(entry_time_s) * 1000
    resp = requests.get(
        _BINANCE_KLINES,
        params={"symbol": symbol, "interval": interval, "endTime": entry_ms, "limit": int(n)},
        timeout=12,
    )
    resp.raise_for_status()
    return _parse_klines(resp.json(), entry_ms)
