"""Estudo de validacao do sinal de entrada do v1.1 (exploratorio).

Pergunta (Gabriel, 2026-06-01): os ganhos do v1.1 tem fundamento estatistico
ou sao compativeis com sorte? Desdobrada em:
  1a TIMING   - entrar QUANDO o sinal entrou bate entrar em hora aleatoria?
  1b DIRECAO  - entrar PRA QUE LADO o sinal escolheu bate lado aleatorio?
  2  BOOTSTRAP- IC 95% do PF cruza 1.0?
  3  PERMUT.  - a separacao MAE/MFE win/loss e significante ou ruido?

Travas (do pre-registro): nao tunar/reabrir o v1.1; "nao ha edge" e veredito
legitimo; nao minerar feature nos 118 trades; parar em 1a/1b/2/3.

Fidelidade: a logica de SAIDA NAO e reimplementada. simulate_from_entry reusa
check_exit de momentum.research_runner -> saidas byte-a-byte iguais ao v1.1.
O PnL do banco e BRUTO (paper nao desconta fee); custo entra simetrico via
apply_cost. Nucleo testado em tests/test_entry_signal_study.py; I/O por run real.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from momentum.research_runner import check_exit  # noqa: E402

# Custo round-trip (taker Binance Futures ~0.04%/lado). Simetrico real/sintetico.
COST_ROUNDTRIP_PCT = 0.08


# ─── Metricas ───────────────────────────────────────────────────────────

def profit_factor(pnls: Sequence[float]) -> float:
    """Soma dos ganhos / |soma das perdas|. inf se nao ha perdas, 0 se nao ha ganhos."""
    gains = sum(p for p in pnls if p > 0)
    losses = sum(-p for p in pnls if p < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def apply_cost(pnl_pct: float, cost_roundtrip_pct: float = COST_ROUNDTRIP_PCT) -> float:
    """Desconta o custo round-trip de um PnL bruto (em pontos percentuais)."""
    return pnl_pct - cost_roundtrip_pct


# ─── Geometria de saida (o detalhe critico do 1b) ───────────────────────

def make_exit_prices(entry_price: float, direction: str, *,
                     sl_dist_pct: float, tp1_dist_pct: float,
                     tp2_dist_pct: float) -> Tuple[float, float, float]:
    """Reaplica DISTANCIAS no lado correto da direcao. Nunca usar preco absoluto
    do banco ao trocar a direcao (inverteria a geometria)."""
    if direction == "LONG":
        sl = entry_price * (1 - sl_dist_pct / 100)
        tp1 = entry_price * (1 + tp1_dist_pct / 100)
        tp2 = entry_price * (1 + tp2_dist_pct / 100)
    else:  # SHORT
        sl = entry_price * (1 + sl_dist_pct / 100)
        tp1 = entry_price * (1 - tp1_dist_pct / 100)
        tp2 = entry_price * (1 - tp2_dist_pct / 100)
    return sl, tp1, tp2


# ─── Simulador de saida (reusa check_exit, candle-by-candle) ────────────

def simulate_from_entry(candles: Sequence[Dict[str, float]], entry_idx: int,
                        direction: str, *, sl: float, tp1: float, tp2: float,
                        timeout_candles: int,
                        breakeven_trigger_pct: float = 0.0) -> Dict[str, Any]:
    """Entra no close de candles[entry_idx] e avanca de entry_idx+1 em diante
    (sem look-ahead: o proprio candle de entrada nunca decide a saida)."""
    entry_price = candles[entry_idx]["close"]
    mfe = 0.0
    mae = 0.0
    duration = 0
    for i in range(entry_idx + 1, len(candles)):
        duration += 1
        c = candles[i]
        res = check_exit(
            direction=direction,
            entry_price=entry_price,
            sl_price=sl,
            tp1_price=tp1,
            tp2_price=tp2,
            candle_high=c["high"],
            candle_low=c["low"],
            candle_close=c["close"],
            current_mfe=mfe,
            current_mae=mae,
            duration_candles=duration,
            timeout_candles=timeout_candles,
            breakeven_trigger_pct=breakeven_trigger_pct,
        )
        mfe, mae = res["mfe_pct"], res["mae_pct"]
        if res["closed"]:
            return {"exit_reason": res["exit_reason"], "pnl_pct": res["pnl_pct"],
                    "mfe_pct": mfe, "mae_pct": mae, "duration_candles": duration}
    # candles acabaram antes de fechar: marca como dado insuficiente (nao conta
    # como trade valido no estudo). PnL mark-to-market no ultimo close disponivel.
    last_close = candles[-1]["close"]
    pnl = (last_close - entry_price) / entry_price * 100
    if direction != "LONG":
        pnl = -pnl
    return {"exit_reason": "no_exit_data", "pnl_pct": pnl,
            "mfe_pct": mfe, "mae_pct": mae, "duration_candles": duration}


# ─── Estatistica de reamostragem ────────────────────────────────────────

def percentile_of(value: float, distribution: Sequence[float]) -> float:
    """Em que percentil (0-100) `value` cai em `distribution` (fracao abaixo dele)."""
    n = len(distribution)
    if n == 0:
        return float("nan")
    below = sum(1 for x in distribution if x < value)
    return 100.0 * below / n


def _safe_percentile(values: Sequence[float], q: float) -> float:
    """Percentil com interpolacao linear (igual ao numpy default) mas robusto a
    inf: quando os dois pontos vizinhos sao iguais (ex: inf == inf), evita o
    inf - inf = nan e devolve o proprio valor."""
    arr = np.sort(np.asarray(values, dtype=float))
    n = len(arr)
    if n == 1:
        return float(arr[0])
    pos = q / 100.0 * (n - 1)
    lo = int(np.floor(pos))
    hi = int(np.ceil(pos))
    if lo == hi or arr[lo] == arr[hi]:
        return float(arr[lo])
    return float(arr[lo] + (arr[hi] - arr[lo]) * (pos - lo))


def bootstrap_ci(pnls: Sequence[float], n_iter: int, rng: np.random.Generator,
                 ci: float = 95.0) -> Tuple[float, float]:
    """IC do PF por bootstrap (reamostragem com reposicao). Deterministico dado rng."""
    arr = np.asarray(pnls, dtype=float)
    n = len(arr)
    pfs = [profit_factor(arr[rng.integers(0, n, size=n)].tolist()) for _ in range(n_iter)]
    lo_pct = (100.0 - ci) / 2.0
    return _safe_percentile(pfs, lo_pct), _safe_percentile(pfs, 100.0 - lo_pct)


def permutation_pvalue(group_a: Sequence[float], group_b: Sequence[float],
                       n_iter: int, rng: np.random.Generator) -> float:
    """p-valor (two-sided) de a separacao das medias de dois grupos via permutacao
    de rotulos. Deterministico dado rng."""
    a = np.asarray(group_a, dtype=float)
    b = np.asarray(group_b, dtype=float)
    observed = abs(a.mean() - b.mean())
    pooled = np.concatenate([a, b])
    na = len(a)
    count = 0
    for _ in range(n_iter):
        perm = rng.permutation(pooled)
        if abs(perm[:na].mean() - perm[na:].mean()) >= observed:
            count += 1
    return count / n_iter


# ═══════════════════════════════════════════════════════════════════════
# I/O + orquestracao (NAO unit-testado — validado por run real + sanity)
# ═══════════════════════════════════════════════════════════════════════

import sqlite3  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

DB_PATH = PROJECT_ROOT / "runtime" / "baseline" / "bot.db"
CANDLE_DIR = PROJECT_ROOT / "data" / "candles"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TIMEOUT_CANDLES = 16
STUDY_START = datetime(2026, 4, 15, tzinfo=timezone.utc)


def load_candles(symbol: str, end_ms: int):
    """Candles 15m do periodo (cache CSV; baixa via fetch_candles do robustness)."""
    import pandas as pd
    path = CANDLE_DIR / f"{symbol}_15m_study.csv"
    if path.exists():
        df = pd.read_csv(path)
    else:
        from momentum.robustness_check import fetch_candles
        start_ms = int(STUDY_START.timestamp() * 1000)
        df = fetch_candles(symbol, "15m", start_ms, end_ms)
        df.to_csv(path, index=False)
    # forca resolucao de ms (read_csv pode inferir datetime64[us]/[ns] -> off by 1000x)
    open_ms = pd.to_datetime(df["time"]).values.astype("datetime64[ms]").astype("int64")
    candles = [{"high": h, "low": low, "close": c} for h, low, c in
               zip(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy())]
    return candles, open_ms


def load_trades(db_path):
    """118 trades com molde de saida (distancias %) e resultados reais (bruto)."""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT timestamp, symbol, direction, entry_price, sl_price, tp1_price, "
            "tp2_price, pnl_pct, mfe_pct, mae_pct, exit_reason "
            "FROM momentum_trades ORDER BY timestamp ASC"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for (ts, sym, d, entry, sl, tp1, tp2, pnl, mfe, mae, reason) in rows:
        out.append({
            "symbol": sym, "direction": d,
            "ts_ms": int(datetime.fromisoformat(ts).timestamp() * 1000),
            "sl_dist": abs(sl - entry) / entry * 100,
            "tp1_dist": abs(tp1 - entry) / entry * 100,
            "tp2_dist": abs(tp2 - entry) / entry * 100,
            "pnl_real": pnl, "mfe": mfe, "mae": mae, "is_win": pnl > 0,
        })
    return out


def _sim_gross(candles, idx, direction, t) -> float:
    """PnL bruto de uma entrada (idx) com a direcao e o molde de distancias de t."""
    sl, tp1, tp2 = make_exit_prices(candles[idx]["close"], direction,
                                    sl_dist_pct=t["sl_dist"], tp1_dist_pct=t["tp1_dist"],
                                    tp2_dist_pct=t["tp2_dist"])
    return simulate_from_entry(candles, idx, direction, sl=sl, tp1=tp1, tp2=tp2,
                               timeout_candles=TIMEOUT_CANDLES)["pnl_pct"]


def reconstruct(trades, candles_by, idx_by) -> List[float]:
    return [_sim_gross(candles_by[t["symbol"]], idx_by[i], t["direction"], t)
            for i, t in enumerate(trades)]


def mc_timing(trades, candles_by, n_iter, rng) -> List[List[float]]:
    """1a: randomiza so o timestamp (mesmo simbolo/direcao/molde). Brutos."""
    bound = {s: len(candles_by[s]) - TIMEOUT_CANDLES - 1 for s in candles_by}
    runs = []
    for _ in range(n_iter):
        runs.append([_sim_gross(candles_by[t["symbol"]],
                                int(rng.integers(0, bound[t["symbol"]])),
                                t["direction"], t) for t in trades])
    return runs


def mc_direction(trades, candles_by, idx_by, n_iter, rng) -> List[List[float]]:
    """1b: permuta so long/short (mesma composicao, timestamp/molde fixos). Brutos."""
    dirs = np.array([t["direction"] for t in trades])
    runs = []
    for _ in range(n_iter):
        perm = rng.permutation(dirs)
        runs.append([_sim_gross(candles_by[t["symbol"]], idx_by[i], perm[i], t)
                     for i, t in enumerate(trades)])
    return runs


def _pf_with_cost(pnls, cost):
    return profit_factor([p - cost for p in pnls])


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    n_iter = int(argv[0]) if argv else 3000
    rng = np.random.default_rng(20260601)

    trades_all = load_trades(DB_PATH)
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    candles_by, openms_by = {}, {}
    for s in SYMBOLS:
        candles_by[s], openms_by[s] = load_candles(s, end_ms)

    # entrada = ULTIMO candle fechado antes da decisao (close=open+15min), igual ao
    # paper (decide no fechamento, opera nos candles seguintes). Descarta sem 16 a frente.
    closems_by = {s: openms_by[s] + 900_000 for s in SYMBOLS}
    idx_all = [int(np.searchsorted(closems_by[t["symbol"]], t["ts_ms"], "right") - 1)
               for t in trades_all]
    valid = [(t, ix) for t, ix in zip(trades_all, idx_all)
             if 0 <= ix < len(candles_by[t["symbol"]]) - TIMEOUT_CANDLES - 1]
    trades = [t for t, _ in valid]
    idx_by = [ix for _, ix in valid]

    print(f"=== ESTUDO DO SINAL DE ENTRADA v1.1  (n_iter={n_iter}) ===")
    print(f"trades validos p/ simulacao: {len(trades)}/{len(trades_all)}  "
          f"L/S={sum(t['direction']=='LONG' for t in trades)}/"
          f"{sum(t['direction']=='SHORT' for t in trades)}")

    pf_bank = profit_factor([t["pnl_real"] for t in trades_all])
    gross_real = reconstruct(trades, candles_by, idx_by)
    print(f"PF banco(real,bruto)={pf_bank:.3f}  PF reconstruido(bruto)="
          f"{_pf_with_cost(gross_real,0.0):.3f}  <- sanity, devem bater\n")

    runs_1a = mc_timing(trades, candles_by, n_iter, rng)
    runs_1b = mc_direction(trades, candles_by, idx_by, n_iter, rng)

    for label, runs in (("1a TIMING ", runs_1a), ("1b DIRECAO", runs_1b)):
        for cost, tag in ((0.0, "bruto  "), (COST_ROUNDTRIP_PCT, "c/custo")):
            base = _pf_with_cost(gross_real, cost)
            null = [_pf_with_cost(r, cost) for r in runs]
            print(f"[{label} {tag}] PF_real={base:.3f}  null: "
                  f"med={_safe_percentile(null,50):.3f} p95={_safe_percentile(null,95):.3f}"
                  f"  -> percentil_real={percentile_of(base, null):.1f}%")
        print()

    pnls_real = [t["pnl_real"] for t in trades_all]
    for cost, tag in ((0.0, "bruto  "), (COST_ROUNDTRIP_PCT, "c/custo")):
        adj = [p - cost for p in pnls_real]
        lo, hi = bootstrap_ci(adj, n_iter, np.random.default_rng(7))
        cruza = "SIM (inconclusivo)" if lo <= 1.0 <= hi else (
            "nao, abaixo de 1" if hi < 1.0 else "nao, acima de 1")
        print(f"[2 BOOTSTRAP {tag}] PF={profit_factor(adj):.3f}  "
              f"IC95=[{lo:.3f},{hi:.3f}]  cruza 1.0? {cruza}")
    print()

    wins = [t for t in trades_all if t["is_win"]]
    loss = [t for t in trades_all if not t["is_win"]]
    for metric in ("mae", "mfe"):
        a = [t[metric] for t in wins]
        b = [t[metric] for t in loss]
        p = permutation_pvalue(a, b, n_iter, np.random.default_rng(13))
        print(f"[3 PERMUT {metric.upper()}] win_med={np.median(a):+.3f} "
              f"loss_med={np.median(b):+.3f}  p={p:.4f} "
              f"{'SIGNIFICANTE' if p < 0.05 else '(ruido)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
