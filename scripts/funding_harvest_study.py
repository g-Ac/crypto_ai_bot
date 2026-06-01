"""Estudo contabil de funding harvest (cash-and-carry delta-neutro).

Pre-registro SELADO: docs/pre_registros/PREREG_funding_harvest.md
NAO preditivo: mede se colher funding (long spot + short perp) rende liquido de custos.

Constantes vem do pre-registro (fixas, nao otimizar in-sample):
  custo round-trip = 0.30% (taker spot+perp, ida e volta)
  holding assumido = 90 periodos 8h (30 dias)  ->  T break-even = custo/holding
  walk-forward = 3 sub-janelas cronologicas, exige lucro nas 3
  GO-economico = liquido anualizado > 8%

Uso:
    python scripts/funding_harvest_study.py            # relatorio completo
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")

# ── Parametros do pre-registro (FIXOS) ──────────────────────────────────
COST_ROUND_TRIP = 0.003          # 0.30% taker, ida+volta (spot 0.10 + perp 0.04, 2x)
HOLDING_PERIODS = 90             # periodos de 8h assumidos de holding (= 30 dias)
PERIODS_PER_YEAR = 1095          # 3 fundings/dia * 365
N_SUBWINDOWS = 3                 # walk-forward
GO_ECON_ANNUAL = 0.08            # 8% liquido anualizado = benchmark lending stablecoin
MIN_EPISODES = 3                 # minimo de episodios p/ nao ser sorte
LOOKBACK_DAYS = 90


# ── Nucleo aritmetico (testado) ─────────────────────────────────────────

def breakeven_threshold(cost_round_trip: float, holding_periods: int) -> float:
    """Funding 8h que, mantido por holding_periods, paga o round-trip."""
    return cost_round_trip / holding_periods


def find_episodes(funding_series: list[float], threshold: float) -> list[list[float]]:
    """Agrupa periodos 8h contiguos com funding >= threshold em episodios."""
    episodes: list[list[float]] = []
    current: list[float] = []
    for f in funding_series:
        if f >= threshold:
            current.append(f)
        elif current:
            episodes.append(current)
            current = []
    if current:
        episodes.append(current)
    return episodes


def episode_pnl(episode_fundings: list[float], cost_round_trip: float) -> float:
    """P&L liquido de UM episodio: funding acumulado - 1 round-trip."""
    return sum(episode_fundings) - cost_round_trip


def harvest_reactive(funding_series: list[float], threshold: float,
                     cost_round_trip: float) -> dict:
    """Cenario B: posicionado so nos episodios com funding >= threshold.
    1 round-trip de custo por episodio."""
    episodes = find_episodes(funding_series, threshold)
    gross = sum(sum(ep) for ep in episodes)
    total_cost = len(episodes) * cost_round_trip
    return {
        "n_episodes": len(episodes),
        "gross_funding": gross,
        "total_cost": total_cost,
        "net": gross - total_cost,
        "periods_in_market": sum(len(ep) for ep in episodes),
    }


def harvest_passive(funding_series: list[float], cost_round_trip: float) -> dict:
    """Cenario A: posicionado o periodo inteiro (1 round-trip)."""
    if not funding_series:
        return {"gross_funding": 0.0, "total_cost": 0.0, "net": 0.0, "periods_in_market": 0}
    gross = sum(funding_series)
    return {
        "gross_funding": gross,
        "total_cost": cost_round_trip,
        "net": gross - cost_round_trip,
        "periods_in_market": len(funding_series),
    }


def annualize(net_fraction: float, n_periods_8h: int) -> float:
    """Anualiza um retorno liquido medido sobre n_periods_8h periodos de 8h."""
    if n_periods_8h <= 0:
        return 0.0
    return net_fraction * PERIODS_PER_YEAR / n_periods_8h


def split_subwindows(series: list[float], k: int) -> list[list[float]]:
    """Divide a serie em k sub-janelas cronologicas (ultima leva o resto)."""
    n = len(series)
    if n < k:
        return [series]
    size = n // k
    return [series[i * size: (n if i == k - 1 else (i + 1) * size)] for i in range(k)]


# ── Orquestracao (I/O — coberta por run real, nao por unit test) ─────────

def load_funding(conn: sqlite3.Connection, symbol: str, since_ts: int) -> list[float]:
    rows = conn.execute(
        "SELECT funding_rate FROM k_funding_rates "
        "WHERE symbol=? AND funding_time>=? ORDER BY funding_time ASC",
        (symbol, since_ts),
    ).fetchall()
    return [float(r[0]) for r in rows]


def list_symbols(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT symbol FROM k_funding_rates ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


def study_symbol(series: list[float], threshold: float) -> dict:
    """Roda passivo + reativo + walk-forward por sub-janela para um simbolo."""
    n = len(series)
    passive = harvest_passive(series, COST_ROUND_TRIP)
    reactive = harvest_reactive(series, threshold, COST_ROUND_TRIP)

    subs = split_subwindows(series, N_SUBWINDOWS)
    sub_nets = [harvest_reactive(s, threshold, COST_ROUND_TRIP)["net"] for s in subs]
    all_positive = len(sub_nets) == N_SUBWINDOWS and all(x > 0 for x in sub_nets)

    go_pesquisa = all_positive and reactive["n_episodes"] >= MIN_EPISODES
    reactive_ann = annualize(reactive["net"], n)  # sobre o periodo total (capital dedicado)
    go_econ = go_pesquisa and reactive_ann > GO_ECON_ANNUAL

    return {
        "n_periods": n,
        "passive_net": passive["net"],
        "passive_ann": annualize(passive["net"], n),
        "reactive_net": reactive["net"],
        "reactive_ann": reactive_ann,
        "n_episodes": reactive["n_episodes"],
        "periods_in_market": reactive["periods_in_market"],
        "pct_in_market": (reactive["periods_in_market"] / n * 100) if n else 0.0,
        "sub_nets": sub_nets,
        "walk_forward_3of3": all_positive,
        "go_pesquisa": go_pesquisa,
        "go_econ": go_econ,
    }


def main() -> int:
    import time
    threshold = breakeven_threshold(COST_ROUND_TRIP, HOLDING_PERIODS)
    since = int(time.time()) - LOOKBACK_DAYS * 86400

    conn = sqlite3.connect(str(DB_PATH))
    try:
        symbols = list_symbols(conn)
        print(f"=== FUNDING HARVEST STUDY (pre-reg EXP-FH-01) ===")
        print(f"custo round-trip={COST_ROUND_TRIP:.3%}  T_breakeven={threshold:.5%}/8h  "
              f"lookback={LOOKBACK_DAYS}d  walk-forward={N_SUBWINDOWS}\n")
        header = f"{'symbol':<13} {'n':>4} {'passivo_a%':>10} {'reativo_a%':>10} {'eps':>4} {'%merc':>6} {'WF3/3':>6} {'GO':>10}"
        print(header)
        print("-" * len(header))

        results = {}
        for sym in symbols:
            series = load_funding(conn, sym, since)
            if not series:
                continue
            r = study_symbol(series, threshold)
            results[sym] = r
            go = "ECON" if r["go_econ"] else ("pesquisa" if r["go_pesquisa"] else "-")
            print(f"{sym:<13} {r['n_periods']:>4} {r['passive_ann']*100:>10.1f} "
                  f"{r['reactive_ann']*100:>10.1f} {r['n_episodes']:>4} "
                  f"{r['pct_in_market']:>6.0f} {'sim' if r['walk_forward_3of3'] else 'nao':>6} {go:>10}")

        go_pesq = [s for s, r in results.items() if r["go_pesquisa"]]
        go_econ = [s for s, r in results.items() if r["go_econ"]]
        print("\n=== VEREDITO (criterios selados) ===")
        print(f"GO-pesquisa (liquido>0 nas 3 sub-janelas + >={MIN_EPISODES} episodios): "
              f"{go_pesq if go_pesq else 'NENHUM'}")
        print(f"GO-economico (alem disso, anualizado > {GO_ECON_ANNUAL:.0%}): "
              f"{go_econ if go_econ else 'NENHUM'}")
        if not go_pesq:
            print("\n=> NO-GO neste regime. Infra fica pronta; T_breakeven calibrado acima.")
            print("   % do tempo com funding >= T por simbolo mostra quao 'seco' esta o regime.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
