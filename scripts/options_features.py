"""Núcleo de features de opções (EXP-019) — Black-Scholes puro, sem rede nem DB.

CONGELADO após início da coleta (selo research/exp019_options_structure/PREREGISTRO.md).
Convenções: IV em fração (0.42, não 42); T em anos; r=0 (cripto); expiry Deribit às 08:00 UTC.
"""
from __future__ import annotations

import datetime as dt
import math

SECONDS_PER_YEAR = 365.25 * 24 * 3600
_MONTHS = {m: i for i, m in enumerate(
    ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"], start=1)}


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def parse_instrument_name(name: str) -> dict | None:
    """'BTC-26MAR27-105000-C' -> dict; None se não for opção bem-formada."""
    parts = name.strip().upper().split("-")
    if len(parts) != 4:
        return None
    currency, date_str, strike_str, kind_ch = parts
    if kind_ch not in ("C", "P"):
        return None
    try:
        day = int(date_str[:-5]); mon = _MONTHS[date_str[-5:-2]]; yr = 2000 + int(date_str[-2:])
        expiry = dt.datetime(yr, mon, day, 8, 0, tzinfo=dt.timezone.utc)
        strike = float(strike_str)
    except (KeyError, ValueError, IndexError):
        return None
    return {
        "currency": currency,
        "expiry_ts": int(expiry.timestamp()),
        "strike": strike,
        "kind": "call" if kind_ch == "C" else "put",
    }


def years_to_expiry(expiry_ts: int, now_ts: int) -> float:
    return max(0.0, (expiry_ts - now_ts) / SECONDS_PER_YEAR)


def _d1(S: float, K: float, sigma: float, T: float) -> float | None:
    if S <= 0 or K <= 0 or sigma <= 0 or T <= 0:
        return None
    return (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))


def bs_gamma(S: float, K: float, sigma: float, T: float) -> float:
    d1 = _d1(S, K, sigma, T)
    if d1 is None:
        return 0.0
    return norm_pdf(d1) / (S * sigma * math.sqrt(T))


def bs_delta(S: float, K: float, sigma: float, T: float, kind: str) -> float:
    d1 = _d1(S, K, sigma, T)
    if d1 is None:
        return 0.0
    return norm_cdf(d1) if kind == "call" else norm_cdf(d1) - 1.0
