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


def _nearest_expiry(chain, now_ts, min_days):
    """Menor expiry com >= min_days; fallback pra a mais próxima existente."""
    exps = sorted({c["expiry_ts"] for c in chain})
    floor = now_ts + min_days * 86400
    for e in exps:
        if e >= floor:
            return e
    return exps[-1] if exps else None


def compute_gex(chain, spot, now_ts):
    gex_signed = 0.0
    gex_abs = 0.0
    for c in chain:
        T = years_to_expiry(c["expiry_ts"], now_ts)
        g = bs_gamma(spot, c["strike"], c["iv"], T) * (c["oi"] or 0.0)
        sign = -1.0 if c["kind"] == "call" else 1.0   # CONGELADO: short calls / long puts
        gex_signed += g * sign
        gex_abs += g
    return gex_signed, gex_abs


def compute_gamma_flip(chain, spot, now_ts):
    """Spot onde GEX(spot) cruza zero. Grid ±15% em passos de 0.5%; None se não cruza."""
    if not chain:
        return None
    grid = [spot * (0.85 + 0.005 * i) for i in range(61)]   # 0.85..1.15
    prev_s = prev_g = None
    for s in grid:
        g = compute_gex(chain, s, now_ts)[0]
        if prev_g is not None and (prev_g <= 0 < g or prev_g >= 0 > g):
            # interpolação linear do cruzamento
            return prev_s + (s - prev_s) * (-prev_g) / (g - prev_g)
        prev_s, prev_g = s, g
    return None


def compute_iv_atm(chain, spot, now_ts, min_days=7):
    exp = _nearest_expiry(chain, now_ts, min_days)
    if exp is None:
        return None
    near = [c for c in chain if c["expiry_ts"] == exp and c["iv"] and c["iv"] > 0]
    if not near:
        return None
    best = min(near, key=lambda c: abs(c["strike"] - spot))
    return best["iv"]


def _iv_at_target_delta(legs, spot, now_ts, target_delta, kind):
    """IV interpolada no |delta|=target dentro de uma perna (call ou put)."""
    pts = []
    for c in legs:
        T = years_to_expiry(c["expiry_ts"], now_ts)
        d = bs_delta(spot, c["strike"], c["iv"], T, kind)
        pts.append((abs(d), c["iv"]))
    if len(pts) < 2:
        return None
    pts.sort()
    lo, hi = None, None
    for ad, iv in pts:
        if ad <= target_delta:
            lo = (ad, iv)
        if ad >= target_delta and hi is None:
            hi = (ad, iv)
    if lo and hi and hi[0] != lo[0]:
        w = (target_delta - lo[0]) / (hi[0] - lo[0])
        return lo[1] + w * (hi[1] - lo[1])
    return (lo or hi)[1] if (lo or hi) else None


def compute_skew_25d(chain, spot, now_ts, min_days=7):
    exp = _nearest_expiry(chain, now_ts, min_days)
    if exp is None:
        return None
    calls = [c for c in chain if c["expiry_ts"] == exp and c["kind"] == "call" and c["iv"]]
    puts = [c for c in chain if c["expiry_ts"] == exp and c["kind"] == "put" and c["iv"]]
    iv_call = _iv_at_target_delta(calls, spot, now_ts, 0.25, "call")
    iv_put = _iv_at_target_delta(puts, spot, now_ts, 0.25, "put")
    if iv_call is None or iv_put is None:
        return None
    return iv_put - iv_call   # CONGELADO: put - call (medo positivo)


def compute_term_slope(chain, spot, now_ts):
    exps = sorted({c["expiry_ts"] for c in chain})
    if len(exps) < 2:
        return None
    near = compute_iv_atm([c for c in chain if c["expiry_ts"] == exps[0]], spot, now_ts, min_days=0)
    far = compute_iv_atm([c for c in chain if c["expiry_ts"] == exps[-1]], spot, now_ts, min_days=0)
    if near is None or far is None:
        return None
    return near - far
