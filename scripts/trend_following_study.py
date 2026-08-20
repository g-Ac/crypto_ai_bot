"""EXP-014 — Trend-following diario (BTC/ETH/SOL): edge selecionavel ou drift+saida?

TESTE FINAL da linha "edge nesses ativos" (Gabriel, 2026-06-02). O mapa fechou
intraday (fee) e funding (basis); sobrou trend-following no 1d (unico TF onde o
fee vira ruido). Pre-compromissos SELADOS antes de ver o resultado:
  - ULTIMA candidata. NO-GO fecha a linha (sem #5, sem altcoin, sem "mais dado").
  - inconclusivo (IC largo) = NO-GO explicito.
  - GO so se as 4: (a) liquido+margem, (b) bate entrada aleatoria (cauda direita),
    (c) bate buy-and-hold, (d) nao carregado por 1-2 trades.

Parametros CONGELADOS a priori (defaults de manual, sem varredura):
  ADX>25 define tendencia | ATR(14) | stop inicial 2*ATR | trailing chandelier 3*ATR
  entra na virada de tendencia, sai no trailing OU quando ADX cai < 25.

Reusa: entry_signal_study (profit_factor/percentile_of/bootstrap_ci/apply_cost),
regime_map (resample_ohlc/classify_trend/compute_adx). Nucleo testado; I/O run real.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from entry_signal_study import (  # noqa: E402
    apply_cost, bootstrap_ci, percentile_of, profit_factor,
)
from regime_map import classify_trend, compute_adx, resample_ohlc  # noqa: E402

REGIME_CACHE = PROJECT_ROOT / "data" / "candles" / "regime"
REPORT_PATH = PROJECT_ROOT / "docs" / "TREND_FOLLOWING_2026-06-02.md"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

STOP_MULT = 2.0          # stop inicial = 2*ATR (corta rapido quem nao engrena)
TRAIL_MULT = 3.0         # trailing chandelier = 3*ATR (deixa a vencedora correr)
ADX_TREND = 25.0
COST_ROUNDTRIP = 0.10    # 0.08% fee + 0.02% slippage (round-trip, no diario)
N_ITER = 5000


# ═══════════════════════════════════════════════════════════════════════
# NUCLEO (testado)
# ═══════════════════════════════════════════════════════════════════════

def simulate_trend_exit(candles: Sequence[dict], idx_entry: int, direction: str,
                        entry_price: float, atr: float, adx_after: Sequence[float],
                        stop_mult: float = STOP_MULT, trail_mult: float = TRAIL_MULT,
                        adx_exit: float = ADX_TREND) -> Dict:
    """Entra no close de idx_entry; avanca de idx_entry+1. Stop inicial e trailing
    chandelier por ATR (ratchet: nunca afrouxa). Sai no stop OU quando ADX < adx_exit.
    adx_after[k] = ADX da barra idx_entry+1+k. Worst-case: checa stop antes do extremo."""
    is_long = direction == "LONG"
    if is_long:
        stop = entry_price - stop_mult * atr
        peak = entry_price
    else:
        stop = entry_price + stop_mult * atr
        peak = entry_price

    for j, i in enumerate(range(idx_entry + 1, len(candles))):
        c = candles[i]
        if is_long:
            if c["low"] <= stop:
                return _exit(stop, entry_price, True, "trail_stop", j + 1)
            peak = max(peak, c["high"])
            stop = max(stop, peak - trail_mult * atr)
        else:
            if c["high"] >= stop:
                return _exit(stop, entry_price, False, "trail_stop", j + 1)
            peak = min(peak, c["low"])
            stop = min(stop, peak + trail_mult * atr)
        if j < len(adx_after) and adx_after[j] < adx_exit:
            return _exit(c["close"], entry_price, is_long, "regime_end", j + 1)

    return _exit(candles[-1]["close"], entry_price, is_long, "data_end",
                 len(candles) - 1 - idx_entry)


def _exit(px: float, entry: float, is_long: bool, reason: str, bars: int) -> Dict:
    pnl = (px - entry) / entry * 100 if is_long else (entry - px) / entry * 100
    return {"pnl_pct": pnl, "exit_reason": reason, "bars": bars}


def find_entries(trend_labels: Sequence[str]) -> List:
    """Inicio de cada estacao de tendencia (virada para up/down). 1 trade por estacao."""
    entries: List = []
    prev = None
    for i, t in enumerate(trend_labels):
        if t in ("up", "down") and t != prev:
            entries.append((i, "LONG" if t == "up" else "SHORT"))
        prev = t
    return entries


def concentration_top_k(pnls: Sequence[float], k: int) -> float:
    """Fracao do lucro bruto que vem dos top-k trades vencedores."""
    gains = sorted([p for p in pnls if p > 0], reverse=True)
    total = sum(gains)
    return sum(gains[:k]) / total if total > 0 else 0.0


def buy_and_hold_return(closes: Sequence[float]) -> float:
    return (closes[-1] - closes[0]) / closes[0] * 100 if closes else 0.0


# ═══════════════════════════════════════════════════════════════════════
# I/O + orquestracao (run real)
# ═══════════════════════════════════════════════════════════════════════

def load_1d(symbol: str) -> List[dict]:
    import csv
    path = REGIME_CACHE / f"{symbol}_spot_1h.csv"
    with path.open() as fh:
        rows1h = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(fh)]
    return resample_ohlc(rows1h, 24)


def compute_atr(rows: List[dict], period: int = 14) -> np.ndarray:
    import pandas as pd
    import ta
    df = pd.DataFrame(rows)
    atr = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=period)
    return atr.average_true_range().bfill().fillna(0.0).to_numpy()


def run_strategy(rows: List[dict]):
    """Roda a estrategia real: classifica trend, entra na virada, sai no trailing."""
    adx, dip, dim = compute_adx(rows)
    atr = compute_atr(rows)
    trend = [classify_trend(adx[i], dip[i], dim[i]) for i in range(len(rows))]
    trades = []
    for idx, direction in find_entries(trend):
        if idx + 1 >= len(rows) or atr[idx] <= 0:
            continue
        r = simulate_trend_exit(rows, idx, direction, rows[idx]["close"], atr[idx],
                                list(adx[idx + 1:]))
        trades.append({**r, "idx": idx, "direction": direction})
    return trades, adx, atr


def mc_random_entry(rows: List[dict], adx: np.ndarray, atr: np.ndarray,
                    directions: List[str], n_iter: int, rng) -> List[float]:
    """A2: mesmas saidas (trailing), entrada em timing aleatorio, composicao casada."""
    hi = len(rows) - 2
    pfs = []
    for _ in range(n_iter):
        pnls = []
        for d in directions:
            idx = int(rng.integers(14, hi))  # >=14 p/ ATR valido
            if atr[idx] <= 0:
                continue
            r = simulate_trend_exit(rows, idx, d, rows[idx]["close"], atr[idx],
                                    list(adx[idx + 1:]))
            pnls.append(r["pnl_pct"])
        pfs.append(profit_factor(pnls))
    return pfs


def main() -> int:
    rng = np.random.default_rng(20260602)
    out: List[str] = ["# EXP-014 — Trend-following diario (BTC/ETH/SOL)",
                      "\n_Teste final. Parametros congelados: ADX>25, ATR14, stop 2*ATR, "
                      "trailing 3*ATR. Custo 0.10% round-trip. Inconclusivo = NO-GO._\n"]
    pooled_net: List[float] = []
    crit = {}

    for sym in SYMBOLS:
        rows = load_1d(sym)
        closes = [r["close"] for r in rows]
        trades, adx, atr = run_strategy(rows)
        pnls = [t["pnl_pct"] for t in trades]
        net = [apply_cost(p, COST_ROUNDTRIP) for p in pnls]
        pooled_net.extend(net)
        n = len(trades)
        dirs = [t["direction"] for t in trades]

        # A1 liquido
        ret_gross, ret_net = sum(pnls), sum(net)
        pf_net = profit_factor(net)
        wins = sum(1 for p in net if p > 0)
        # A2 vs aleatorio
        dist = mc_random_entry(rows, adx, atr, dirs, N_ITER, rng)
        pctile = percentile_of(pf_net, dist)
        # A3 vs buy-and-hold
        bnh = buy_and_hold_return(closes)
        # A4 concentracao
        c1 = concentration_top_k(net, 1)
        c2 = concentration_top_k(net, 2)
        # A5 bootstrap (se amostra permitir)
        lo, hi = bootstrap_ci(net, N_ITER, np.random.default_rng(7)) if n >= 5 else (float("nan"), float("nan"))

        out.append(f"\n## {sym}  (n={n} estacoes, {dirs.count('LONG')}L/{dirs.count('SHORT')}S)")
        out.append(f"- **A1 liquido:** ret bruto {ret_gross:+.1f}% / liquido {ret_net:+.1f}% "
                   f"| PF {pf_net:.2f} | win {wins}/{n}")
        out.append(f"- **A2 vs aleatorio:** PF real percentil **{pctile:.0f}%** do null "
                   f"(med {np.median(dist):.2f}) {'BATE' if pctile>=90 else 'NAO bate (>=90 exigido)'}")
        out.append(f"- **A3 vs buy-and-hold:** estrategia {ret_net:+.1f}% vs B&H {bnh:+.1f}% "
                   f"-> {'BATE' if ret_net>bnh else 'NAO bate'}")
        out.append(f"- **A4 concentracao:** top-1 = {c1*100:.0f}% do lucro, top-2 = {c2*100:.0f}% "
                   f"{'(FRAGIL: 1-2 trades carregam)' if c2>0.6 else ''}")
        out.append(f"- **A5 bootstrap IC95 do PF:** [{lo:.2f}, {hi:.2f}] "
                   f"{'cruza 1.0 (inconclusivo)' if lo<=1.0<=hi else ('todo <1' if hi<1 else 'todo >1')}")
        crit[sym] = {"a": ret_net > 0, "b": pctile >= 90, "c": ret_net > bnh,
                     "d": c2 <= 0.6, "ic_cross1": lo <= 1.0 <= hi}

    # Veredito pooled + por simbolo
    out.append("\n---\n## Veredito (GO so se as 4: liquido+, bate-aleatorio, bate-B&H, nao-concentrado)")
    any_go = False
    for sym, c in crit.items():
        # SELADO: GO exige os 4 criterios E IC conclusivo (nao cruza 1.0).
        # IC largo cruzando 1.0 = inconclusivo = NO-GO, mesmo com criterios pontuais +.
        conclusive = not c["ic_cross1"]
        passed = c["a"] and c["b"] and c["c"] and c["d"] and conclusive
        any_go = any_go or passed
        flags = f"liq{'+' if c['a'] else '-'} alea{'+' if c['b'] else '-'} " \
                f"bnh{'+' if c['c'] else '-'} conc{'+' if c['d'] else '-'} " \
                f"IC{'-conclusivo' if conclusive else '-cruza1(inconclusivo)'}"
        verdict = "GO" if passed else ("NO-GO (inconclusivo)" if c["ic_cross1"] else "NO-GO")
        out.append(f"- {sym}: {flags}  ->  **{verdict}**")
    pf_pool = profit_factor(pooled_net)
    lo_p, hi_p = bootstrap_ci(pooled_net, N_ITER, np.random.default_rng(7))
    out.append(f"\n**Pooled** (n={len(pooled_net)}, correlacionado): PF {pf_pool:.2f}, "
               f"IC95 [{lo_p:.2f}, {hi_p:.2f}] {'cruza 1.0' if lo_p<=1.0<=hi_p else ''}")
    out.append(f"\n## LINHA BTC/ETH/SOL: **{'GO (revisar)' if any_go else 'NO-GO — FECHADA'}**")
    out.append("Inconclusivo/morno foi pre-selado como NO-GO. ~25 estacoes/simbolo "
               "(correlacionadas) nao distinguem edge de drift+saida com confianca.")

    report = "\n".join(out)
    REPORT_PATH.write_text(report + "\n")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
