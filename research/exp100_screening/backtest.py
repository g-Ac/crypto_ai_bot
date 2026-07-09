"""EXP-100 — engine de avaliação (measurement-critical).

Calcula retorno LÍQUIDO de fee por trade, faz split temporal IS/OOS sem leak,
e resume (expectancy, PF, win-rate, p-bootstrap). Erro aqui = conclusão falsa,
então é a parte mais testada. Regras congeladas na mini-moldura 2026-06-17:
  - entry no close do bucket do sinal; exit no close de entry + horizonte;
  - exit estritamente no futuro (sem look-ahead);
  - fee 10 bps round-trip (taker 0.05%/lado, ver project_momentum_fee_net);
  - trades sobrepostos no mesmo símbolo são deduplicados (cooldown=horizonte)
    para não inflar N com observações autocorrelacionadas (p otimista).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEE_BPS_ROUNDTRIP = 10.0
HOUR = 3600


def dedupe_overlap(entries, horizon_h):
    """Remove entradas sobrepostas por símbolo: depois de abrir em t, ignora
    novas entradas no mesmo símbolo até t + horizonte. Mantém quase-independência
    entre trades (premissa do bootstrap). entries: iterável de (sym, ts, dir)."""
    last_exit = {}
    out = []
    span = horizon_h * HOUR
    for sym, ts, d in sorted(entries, key=lambda e: (e[0], e[1])):
        if sym in last_exit and ts < last_exit[sym]:
            continue
        out.append((sym, ts, d))
        last_exit[sym] = ts + span
    return out


def trade_returns(entries, panels, horizon_h, fee_bps=FEE_BPS_ROUNDTRIP):
    """entries: iterável de (symbol, entry_ts, direction[+1/-1]).
    Retorna DataFrame: symbol, entry_ts, direction, ret_net_bps.
    Descarta trades sem barra de saída (fim da série) — não extrapola."""
    rows = []
    for sym, ets, d in entries:
        df = panels.get(sym)
        if df is None or ets not in df.index:
            continue
        exit_ts = ets + horizon_h * HOUR
        if exit_ts not in df.index:
            continue
        entry_px = df.at[ets, "close"]
        exit_px = df.at[exit_ts, "close"]
        if not (entry_px > 0) or not (exit_px > 0):
            continue
        gross = d * (exit_px / entry_px - 1.0) * 1e4  # bps
        rows.append((sym, ets, d, gross - fee_bps))
    return pd.DataFrame(rows, columns=["symbol", "entry_ts", "direction", "ret_net_bps"])


def split_is_oos(trades, boundary_ts):
    """IS = entradas antes do boundary; OOS = boundary em diante."""
    is_ = trades[trades["entry_ts"] < boundary_ts]
    oos = trades[trades["entry_ts"] >= boundary_ts]
    return is_, oos


def bootstrap_p(rets, n_boot=2000, seed=0):
    """p-value bicaudal para H0: média=0, via bootstrap não-paramétrico.
    Robusto a caudas gordas (melhor que t-test para retornos de trading)."""
    rets = np.asarray(rets, dtype=float)
    n = len(rets)
    if n < 2:
        return 1.0
    obs = rets.mean()
    if obs == 0.0:
        return 1.0
    rng = np.random.default_rng(seed)
    centered = rets - obs  # impõe H0 (média 0)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = centered[idx].mean(axis=1)
    return float(np.mean(np.abs(boot_means) >= np.abs(obs)))


def summarize(trades, n_boot=2000, seed=0):
    """Resumo de um conjunto de trades. PF = soma ganhos / soma |perdas|."""
    r = np.asarray(trades["ret_net_bps"], dtype=float) if len(trades) else np.array([])
    n = len(r)
    if n == 0:
        return {"n": 0, "expectancy_bps": float("nan"), "pf": float("nan"),
                "win_rate": float("nan"), "p_value": 1.0}
    wins = r[r > 0].sum()
    losses = -r[r < 0].sum()
    if losses > 0:
        pf = float(wins / losses)
    elif wins > 0:
        pf = float("inf")
    else:
        pf = float("nan")
    return {"n": int(n),
            "expectancy_bps": float(r.mean()),
            "pf": pf,
            "win_rate": float((r > 0).mean()),
            "p_value": bootstrap_p(r, n_boot=n_boot, seed=seed)}
