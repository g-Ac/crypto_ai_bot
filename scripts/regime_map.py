"""Mapa de regimes e timeframes — CARACTERIZACAO descritiva (nao testa estrategia).

Job 2026-06-01: foundation pra desenhar estrategia de swing/estrutura fresca.
100% descritivo: estatistica sobre o mercado. SEM P&L, SEM edge, SEM GO/NO-GO.

Responde com dado:
  (1) frequencia + duracao de cada regime
  (2) tamanho de movimento por regime e por timeframe (a pergunta do fee)
  (3) frequencia + duracao das estacoes de funding (gordo e negativo)
  (4) persistencia de regime (matriz de transicao)

Simbolos: BTC, ETH, SOL (spot + perp). TFs: 1h, 4h, 1d. ~2 anos.
Classificadores SIMPLES e padrao (ADX/vol), nao tunados. Nucleo testado em
tests/test_regime_map.py; I/O (download, ADX via ta) coberto por run real.
"""
from __future__ import annotations

import math
import sys
import time as _time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / "data" / "candles" / "regime"
REPORT_PATH = PROJECT_ROOT / "docs" / "REGIME_MAP_2026-06-01.md"

SPOT_URL = "https://api.binance.com/api/v3/klines"
PERP_URL = "https://fapi.binance.com/fapi/v1/klines"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = (("1h", 1), ("4h", 4), ("1d", 24))
ADX_THRESHOLD = 25.0          # padrao de mercado, NAO tunado
FUNDING_HI = 0.0003           # 0.03%/8h = "gordo" (anual ~33%)
FUNDING_NEG = -0.0001         # -0.01%/8h = "negativo" (capitulacao leve)
FEE_ROUNDTRIP_PCT = 0.08      # referencia: a licao do v1.1


# ═══════════════════════════════════════════════════════════════════════
# NUCLEO (testado)
# ═══════════════════════════════════════════════════════════════════════

def resample_ohlc(rows: Sequence[dict], factor: int) -> List[dict]:
    """Agrega `factor` barras em uma (open=first, high=max, low=min, close=last).
    Descarta a ultima barra incompleta. Preserva ts_ms do inicio do bloco."""
    out: List[dict] = []
    for i in range(0, len(rows) - factor + 1, factor):
        chunk = rows[i:i + factor]
        bar = {
            "open": chunk[0]["open"],
            "high": max(c["high"] for c in chunk),
            "low": min(c["low"] for c in chunk),
            "close": chunk[-1]["close"],
        }
        if "ts_ms" in chunk[0]:
            bar["ts_ms"] = chunk[0]["ts_ms"]
        out.append(bar)
    return out


def log_returns(closes: Sequence[float]) -> List[float]:
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]


def realized_vol(closes: Sequence[float], window: int) -> List[float]:
    """Std rolante dos log-returns (alinhado aos returns: len = len(closes)-1)."""
    rets = log_returns(closes)
    out: List[float] = []
    for i in range(len(rets)):
        w = rets[max(0, i - window + 1): i + 1]
        out.append(float(np.std(w)) if len(w) >= 2 else 0.0)
    return out


def classify_trend(adx: float, di_plus: float, di_minus: float,
                   threshold: float = ADX_THRESHOLD) -> str:
    if adx < threshold:
        return "range"
    return "up" if di_plus >= di_minus else "down"


def classify_vol(vol_val: float, vol_median: float) -> str:
    return "high" if vol_val >= vol_median else "low"


def run_lengths(labels: Sequence[str]) -> List[Tuple[str, int]]:
    if not labels:
        return []
    out: List[Tuple[str, int]] = []
    cur, n = labels[0], 1
    for x in labels[1:]:
        if x == cur:
            n += 1
        else:
            out.append((cur, n))
            cur, n = x, 1
    out.append((cur, n))
    return out


def transition_matrix(labels: Sequence[str]) -> Dict[str, Dict[str, float]]:
    counts: Dict[str, Dict[str, int]] = {}
    for a, b in zip(labels, labels[1:]):
        counts.setdefault(a, {}).setdefault(b, 0)
        counts[a][b] += 1
    return {a: {b: c / sum(row.values()) for b, c in row.items()}
            for a, row in counts.items()}


def funding_seasons(funding: Sequence[float], hi_thresh: float,
                    neg_thresh: float) -> List[Tuple[str, int]]:
    labels = ["gordo" if f >= hi_thresh else "negativo" if f <= neg_thresh else "neutro"
              for f in funding]
    return [(lbl, n) for lbl, n in run_lengths(labels) if lbl != "neutro"]


def pct_summary(values: Sequence[float]) -> Dict[str, float]:
    a = np.asarray(values, dtype=float)
    if a.size == 0:
        return {"n": 0, "mean": 0.0, "median": 0.0, "p25": 0.0, "p75": 0.0, "p90": 0.0}
    return {
        "n": int(a.size), "mean": float(np.mean(a)), "median": float(np.median(a)),
        "p25": float(np.percentile(a, 25)), "p75": float(np.percentile(a, 75)),
        "p90": float(np.percentile(a, 90)),
    }


# ═══════════════════════════════════════════════════════════════════════
# I/O (run real)
# ═══════════════════════════════════════════════════════════════════════

def _get(url: str, params: dict) -> list:
    import requests
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 3:
                raise
            _time.sleep(2 ** attempt)
    return []


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int, url: str) -> List[dict]:
    rows: List[dict] = []
    cursor = start_ms
    while cursor < end_ms:
        data = _get(url, {"symbol": symbol, "interval": interval,
                          "startTime": cursor, "endTime": end_ms, "limit": 1000})
        if not data:
            break
        for k in data:
            rows.append({"ts_ms": int(k[0]), "open": float(k[1]), "high": float(k[2]),
                         "low": float(k[3]), "close": float(k[4])})
        cursor = data[-1][6] + 1
        if len(data) < 1000:
            break
        _time.sleep(0.25)
    return rows


def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> List[dict]:
    rows: List[dict] = []
    cursor = start_ms
    while cursor < end_ms:
        data = _get(FUNDING_URL, {"symbol": symbol, "startTime": cursor,
                                  "endTime": end_ms, "limit": 1000})
        if not data:
            break
        for f in data:
            rows.append({"ts_ms": int(f["fundingTime"]), "rate": float(f["fundingRate"])})
        cursor = data[-1]["fundingTime"] + 1
        if len(data) < 1000:
            break
        _time.sleep(0.25)
    return rows


def _cache(name: str, fetch_fn) -> List[dict]:
    import csv
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{name}.csv"
    if path.exists():
        with path.open() as fh:
            return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(fh)]
    rows = fetch_fn()
    if rows:
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return rows


def compute_adx(rows: List[dict], period: int = 14):
    """ADX + DI via ta lib. Retorna (adx, di_plus, di_minus) como np arrays."""
    import pandas as pd
    import ta
    df = pd.DataFrame(rows)
    ind = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=period)
    return (ind.adx().fillna(0).to_numpy(),
            ind.adx_pos().fillna(0).to_numpy(),
            ind.adx_neg().fillna(0).to_numpy())


# ═══════════════════════════════════════════════════════════════════════
# Orquestracao + relatorio
# ═══════════════════════════════════════════════════════════════════════

def analyze_timeframe(rows: List[dict], tf_name: str, out: List[str]) -> None:
    if len(rows) < 60:
        out.append(f"  [{tf_name}] dados insuficientes ({len(rows)} barras)")
        return
    closes = [r["close"] for r in rows]
    adx, dip, dim = compute_adx(rows)
    vol = realized_vol(closes, window=20)
    vol_med = float(np.median([v for v in vol if v > 0])) if any(vol) else 0.0

    trend = [classify_trend(adx[i], dip[i], dim[i]) for i in range(len(rows))]
    # alinha vol (len rows-1) ao trend pegando o indice deslocado
    vol_lab = ["high"] + [classify_vol(vol[i - 1], vol_med) for i in range(1, len(rows))]

    n = len(trend)
    freq = {r: 100.0 * trend.count(r) / n for r in ("up", "down", "range")}
    durs = run_lengths(trend)
    trend_durs = [d for lbl, d in durs if lbl in ("up", "down")]
    range_durs = [d for lbl, d in durs if lbl == "range"]

    # tamanho de movimento por barra (corpo %) por regime de trend
    body = {}
    for r in ("up", "down", "range"):
        vals = [abs(rows[i]["close"] - rows[i]["open"]) / rows[i]["open"] * 100
                for i in range(n) if trend[i] == r]
        body[r] = pct_summary(vals)
    # movimento acumulado por RUN de tendencia (a joia: swing capturavel)
    swing_moves = []
    idx = 0
    for lbl, d in durs:
        if lbl in ("up", "down"):
            c0, c1 = rows[idx]["close"], rows[min(idx + d - 1, n - 1)]["close"]
            swing_moves.append(abs(c1 - c0) / c0 * 100)
        idx += d
    swing = pct_summary(swing_moves)
    tmat = transition_matrix(trend)

    out.append(f"  **[{tf_name}]** trend up/down/range = "
               f"{freq['up']:.0f}%/{freq['down']:.0f}%/{freq['range']:.0f}%  "
               f"| vol_alta = {100.0*vol_lab.count('high')/n:.0f}%")
    if trend_durs:
        td = pct_summary(trend_durs)
        out.append(f"     duracao estacao tendencia: mediana {td['median']:.0f} barras "
                   f"(p90 {td['p90']:.0f}); range: mediana "
                   f"{pct_summary(range_durs)['median']:.0f} barras")
    out.append(f"     corpo/barra em tendencia: mediana {body['up']['median']:.2f}% / "
               f"{body['down']['median']:.2f}% (up/down) vs fee {FEE_ROUNDTRIP_PCT}% "
               f"-> fee = {FEE_ROUNDTRIP_PCT/max(body['up']['median'],0.01)*100:.0f}% do corpo up")
    if swing["n"]:
        out.append(f"     **swing por estacao de tendencia: mediana {swing['median']:.2f}% "
                   f"(p25 {swing['p25']:.2f} / p75 {swing['p75']:.2f} / p90 {swing['p90']:.2f}), "
                   f"n={swing['n']}**")
    persist = tmat.get("up", {}).get("up", 0) * 100, tmat.get("down", {}).get("down", 0) * 100, \
        tmat.get("range", {}).get("range", 0) * 100
    out.append(f"     persistencia (P[mesmo regime no proximo bar]): "
               f"up {persist[0]:.0f}% / down {persist[1]:.0f}% / range {persist[2]:.0f}%")


def analyze_symbol(symbol: str, start_ms: int, end_ms: int, out: List[str]) -> None:
    out.append(f"\n## {symbol}")
    spot = _cache(f"{symbol}_spot_1h", lambda: fetch_klines(symbol, "1h", start_ms, end_ms, SPOT_URL))
    perp = _cache(f"{symbol}_perp_1h", lambda: fetch_klines(symbol, "1h", start_ms, end_ms, PERP_URL))
    funding = _cache(f"{symbol}_funding", lambda: fetch_funding(symbol, start_ms, end_ms))
    out.append(f"_spot {len(spot)} barras 1h, perp {len(perp)}, funding {len(funding)} pts_")

    # (1)(2)(4) regime + movimento + persistencia, por TF
    for tf_name, factor in TIMEFRAMES:
        rows = spot if factor == 1 else resample_ohlc(spot, factor)
        analyze_timeframe(rows, tf_name, out)

    # (3) estacoes de funding + basis
    rates = [f["rate"] for f in funding]
    if rates:
        fs = funding_seasons(rates, FUNDING_HI, FUNDING_NEG)
        gordos = [d for lbl, d in fs if lbl == "gordo"]
        negs = [d for lbl, d in fs if lbl == "negativo"]
        pos_pct = 100.0 * sum(1 for r in rates if r > 0) / len(rates)
        out.append(f"  **funding:** mediana {np.median(rates)*100:.4f}%/8h "
                   f"(anual ~{np.median(rates)*3*365*100:.1f}%), {pos_pct:.0f}% dos 8h positivo")
        out.append(f"     estacoes GORDAS (>={FUNDING_HI*100:.2f}%/8h): {len(gordos)} episodios, "
                   f"duracao mediana {np.median(gordos) if gordos else 0:.0f}x8h "
                   f"({sum(gordos)} de {len(rates)} pts = {100*sum(gordos)/len(rates):.0f}% do tempo)")
        out.append(f"     estacoes NEGATIVAS (<={FUNDING_NEG*100:.2f}%/8h): {len(negs)} episodios, "
                   f"{100*sum(negs)/len(rates):.0f}% do tempo")
    # basis spot vs perp (alinha por ts_ms no 1h)
    perp_by_ts = {p["ts_ms"]: p["close"] for p in perp}
    basis = [(perp_by_ts[s["ts_ms"]] - s["close"]) / s["close"] * 100
             for s in spot if s["ts_ms"] in perp_by_ts]
    if basis:
        bs = pct_summary(basis)
        out.append(f"  **basis (perp-spot):** mediana {bs['median']:.4f}% "
                   f"(p25 {bs['p25']:.4f} / p75 {bs['p75']:.4f}), "
                   f"{100*sum(1 for b in basis if b>0)/len(basis):.0f}% do tempo em premio")


def main() -> int:
    from datetime import datetime, timezone
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - 2 * 365 * 86400 * 1000
    out: List[str] = []
    out.append("# Mapa de regimes e timeframes — CARACTERIZACAO (descritivo)")
    out.append(f"\nGerado: {datetime.now(timezone.utc).isoformat()} | janela ~2 anos | "
               f"classificadores SIMPLES (ADX>{ADX_THRESHOLD:.0f}, vol realizada) NAO tunados.")
    out.append("**Caveat:** ~2 anos = ~1 ciclo parcial. Frequencias sao desta amostra, "
               "nao leis eternas. Taxonomia de regime e uma lente, nao verdade absoluta. "
               "Sem P&L, sem recomendacao de estrategia — so o terreno.\n")

    for symbol in SYMBOLS:
        print(f"[{symbol}] baixando + analisando...", flush=True)
        try:
            analyze_symbol(symbol, start_ms, end_ms, out)
        except Exception as exc:  # noqa: BLE001 - run real, registra e segue
            out.append(f"\n## {symbol}\n  ERRO: {exc!r}")
            print(f"  ERRO em {symbol}: {exc!r}", flush=True)

    out.append("\n---\n## Leitura rapida (em que TF o sinal estrutural parece mais limpo)")
    out.append("Ver, por simbolo/TF: swing por estacao de tendencia vs fee, e persistencia. "
               "TF onde swing mediano >> fee E persistencia alta = candidato a desenhar swing.")
    report = "\n".join(out)
    REPORT_PATH.write_text(report + "\n")
    print(f"\nRelatorio salvo em {REPORT_PATH}")
    print("\n".join(out[-40:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
