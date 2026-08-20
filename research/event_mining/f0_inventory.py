#!/usr/bin/env python3
"""F0 — Inventario do EXP-016 Event Mining (BRIEFING.md Secao 6/F0).

Conta eventos candidatos por familia/simbolo (threshold p95/p5, pos-cooldown),
episodios no pooled, tercos temporais e viabilidade BTC. NAO le nem calcula
nenhum retorno forward: as unicas consultas a k_prices usam bucket_ts (EXISTS
de referencia/alvo), nunca colunas de preco.

Definicoes congeladas no CP0 (Anexo A + propostas desta fase):
- p95/p5 = percentil empirico com interpolacao linear, por simbolo, sobre a
  janela inteira disponivel da fonte (Anexo A.1).
- BASIS usa basis_rate (relativa) — proposta CP0.
- OI-SHOCK usa delta relativo 1h: (OI_t - OI_{t-1h}) / OI_{t-1h} — proposta CP0.
- LSR-*: delta absoluto 1h do ratio (como escrito na grade).
- Elegibilidade: threshold atingido E bucket de referencia T+1h existe em
  k_prices (invariante iv). Cooldown roda DEPOIS da elegibilidade.
- Cooldown: rolante first-event-then-skip, 24h, por simbolo+familia (A.9).
- Episodio: single-linkage, gap < 24h (= max(24h, horizonte) para 1h/4h/24h),
  sobre eventos pos-cooldown da familia (pooled; BTC separado).
- Borda por horizonte h: evento conta na celula se bucket T+1h E bucket
  T+(1+h)h existem em k_prices (A.3) — checagem de existencia, sem preco.
"""

import json
import sqlite3
from pathlib import Path

import numpy as np

DB = "/home/pi/crypto_ai_bot/runtime/baseline/bot.db"
OUTDIR = Path(__file__).resolve().parent
HOUR = 3600
COOLDOWN = 24 * HOUR
GAP = 24 * HOUR
HORIZONS = (1, 4, 24)
N_MIN_EVENTS = 30
N_MIN_EPISODES = 10
BTC = "BTCUSDT"


def pctl(vals, q):
    return float(np.percentile(np.asarray(vals, dtype=float), q, method="linear"))


def cooldown_filter(ts_sorted):
    out, next_ok = [], None
    for t in ts_sorted:
        if next_ok is None or t >= next_ok:
            out.append(t)
            next_ok = t + COOLDOWN
    return out


def episodes(ts_list):
    """Single-linkage temporal: gap < GAP une eventos no mesmo episodio."""
    ts = sorted(ts_list)
    if not ts:
        return []
    clusters = [[ts[0]]]
    for t in ts[1:]:
        if t - clusters[-1][-1] < GAP:
            clusters[-1].append(t)
        else:
            clusters.append([t])
    return clusters


def episodes_anchored(ts_list):
    """Variante anti-chaining p/ decisao CP0: janela de 24h ancorada no
    primeiro evento do episodio (first-event-anchored, mesma semantica do
    cooldown). Evento a >= 24h da ancora abre episodio novo."""
    ts = sorted(ts_list)
    if not ts:
        return []
    clusters, anchor = [], None
    for t in ts:
        if anchor is None or t - anchor >= GAP:
            clusters.append([t])
            anchor = t
        else:
            clusters[-1].append(t)
    return clusters


def iso(ts):
    import datetime as dt

    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    # --- k_prices: apenas bucket_ts (nenhuma coluna de preco e lida) ---
    price_buckets = {}
    for sym, ts in conn.execute("SELECT symbol, bucket_ts FROM k_prices"):
        price_buckets.setdefault(sym, set()).add(ts)
    symbols = sorted(price_buckets)
    first_price = {s: min(b) for s, b in price_buckets.items()}
    last_price = {s: max(b) for s, b in price_buckets.items()}
    gap_check = {
        s: (last_price[s] - first_price[s]) // HOUR + 1 - len(price_buckets[s])
        for s in symbols
    }

    def load(query):
        d = {}
        for sym, ts, v in conn.execute(query):
            if v is not None:
                d.setdefault(sym, []).append((int(ts), float(v)))
        for sym in d:
            d[sym].sort()
        return d

    fund = load("SELECT symbol, funding_time, funding_rate FROM k_funding_rates")
    basis = load("SELECT symbol, bucket_ts, basis_rate FROM k_basis")
    lsr_top = load(
        "SELECT symbol, bucket_ts, long_short_ratio FROM k_ratios"
        " WHERE source='top_position'"
    )
    lsr_glb = load(
        "SELECT symbol, bucket_ts, long_short_ratio FROM k_ratios"
        " WHERE source='global_account'"
    )
    oi = load("SELECT symbol, bucket_ts, sum_open_interest FROM k_open_interest")

    def deltas(series, relative=False):
        out = {}
        for sym, rows in series.items():
            m = dict(rows)
            ds = []
            for ts, v in rows:
                prev = m.get(ts - HOUR)
                if prev is None:
                    continue
                if relative:
                    if prev == 0:
                        continue
                    ds.append((ts, (v - prev) / prev))
                else:
                    ds.append((ts, v - prev))
            out[sym] = ds
        return out

    d_top = deltas(lsr_top)
    d_glb = deltas(lsr_glb)
    d_oi = deltas(oi, relative=True)

    # familia -> (serie {sym: [(ts, valor)]}, modo do gatilho)
    families = {
        "FUND+": (fund, "high"),
        "FUND-": (fund, "low"),
        "BASIS+": (basis, "high"),
        "BASIS-": (basis, "low"),
        "LSR-TOP-SQZ": (d_top, "abs"),
        "LSR-GLB-SQZ": (d_glb, "abs"),
        "OI-SHOCK": (d_oi, "abs"),
    }

    # janelas das fontes (min/max ts por fonte, pooled)
    def src_window(series):
        all_ts = [ts for rows in series.values() for ts, _ in rows]
        return (min(all_ts), max(all_ts)) if all_ts else (None, None)

    source_windows = {
        "k_funding_rates": src_window(fund),
        "k_basis": src_window(basis),
        "k_ratios_top": src_window(lsr_top),
        "k_ratios_global": src_window(lsr_glb),
        "k_open_interest": src_window(oi),
    }

    thresholds = {}
    events = {}  # fam -> sym -> ts pos-cooldown (elegiveis: referencia T+1h existe)
    pre_cooldown = {}  # fam -> sym -> n elegiveis pre-cooldown

    for fam, (series, mode) in families.items():
        thresholds[fam] = {}
        events[fam] = {}
        pre_cooldown[fam] = {}
        for sym in symbols:
            rows = series.get(sym, [])
            if not rows:
                thresholds[fam][sym] = None
                events[fam][sym] = []
                pre_cooldown[fam][sym] = 0
                continue
            # Desigualdade ESTRITA (proposta CP0): funding tem massa de
            # probabilidade no valor default da Binance (0.0001); em 9/14
            # simbolos p95 == valor modal, e ">= p95" dispararia em ate 28%
            # dos periodos (mercado normal, nao cauda). Estrito nao altera
            # series continuas (basis, deltas) e remove a degenerescencia.
            vals = [v for _, v in rows]
            if mode == "high":
                thr = pctl(vals, 95)
                hits = [ts for ts, v in rows if v > thr]
            elif mode == "low":
                thr = pctl(vals, 5)
                hits = [ts for ts, v in rows if v < thr]
            else:
                thr = pctl([abs(v) for v in vals], 95)
                hits = [ts for ts, v in rows if abs(v) > thr]
            elig = [ts for ts in hits if (ts + HOUR) in price_buckets[sym]]
            thresholds[fam][sym] = thr
            pre_cooldown[fam][sym] = len(elig)
            events[fam][sym] = cooldown_filter(sorted(elig))

    # --- agregacoes, episodios, bordas por horizonte, tercos ---
    report = {}
    cells = []
    for fam in families:
        pooled = sorted(t for sym in symbols for t in events[fam][sym])
        pooled_ev = [(sym, t) for sym in symbols for t in events[fam][sym]]
        btc_ts = sorted(events[fam][BTC])

        # tercos temporais sobre a janela DISPONIVEL da familia
        src_lo, src_hi = src_window(families[fam][0])
        lo = max(src_lo, min(first_price.values()) - HOUR)
        hi = src_hi
        days = (hi - lo) / 86400.0
        e1, e2 = lo + (hi - lo) / 3.0, lo + 2.0 * (hi - lo) / 3.0
        terco = [
            sum(1 for t in pooled if t < e1),
            sum(1 for t in pooled if e1 <= t < e2),
            sum(1 for t in pooled if t >= e2),
        ]
        tmin, tmax = min(terco), max(terco)
        density_flag = (tmin == 0 and tmax > 0) or (tmin > 0 and tmax / tmin > 2.0)

        per_h = {}
        for h in HORIZONS:
            ok_pool = [
                (sym, t)
                for sym, t in pooled_ev
                if (t + HOUR) in price_buckets[sym]
                and (t + HOUR + h * HOUR) in price_buckets[sym]
            ]
            ok_btc = [t for sym, t in ok_pool if sym == BTC]
            n_pool = len(ok_pool)
            ts_pool = [t for _, t in ok_pool]
            ep_pool = len(episodes(ts_pool))
            ep_pool_anc = len(episodes_anchored(ts_pool))
            n_btc = len(ok_btc)
            ep_btc = len(episodes(ok_btc))
            ep_btc_anc = len(episodes_anchored(ok_btc))
            per_h[f"+{h}h"] = {
                "pooled": {"n": n_pool, "episodes": ep_pool, "episodes_anchored": ep_pool_anc},
                "btc": {"n": n_btc, "episodes": ep_btc, "episodes_anchored": ep_btc_anc},
            }
            for agg, n, ep, ep_anc in (
                ("pooled", n_pool, ep_pool, ep_pool_anc),
                ("btc", n_btc, ep_btc, ep_btc_anc),
            ):
                cells.append(
                    {
                        "family": fam,
                        "horizon": f"+{h}h",
                        "agg": agg,
                        "n_events": n,
                        "n_episodes": ep,
                        "n_episodes_anchored": ep_anc,
                        "alive_single_linkage": n >= N_MIN_EVENTS and ep >= N_MIN_EPISODES,
                        "alive_anchored": n >= N_MIN_EVENTS and ep_anc >= N_MIN_EPISODES,
                    }
                )

        report[fam] = {
            "per_symbol_post_cooldown": {s: len(events[fam][s]) for s in symbols},
            "pre_cooldown_total": sum(pre_cooldown[fam].values()),
            "pooled_n": len(pooled),
            "pooled_episodes": len(episodes(pooled)),
            "pooled_episodes_anchored": len(episodes_anchored(pooled)),
            "btc_n": len(btc_ts),
            "btc_episodes": len(episodes(btc_ts)),
            "btc_episodes_anchored": len(episodes_anchored(btc_ts)),
            "window_used": {"from": iso(lo), "to": iso(hi), "days": round(days, 1)},
            "thirds": {
                "counts": terco,
                "edges": [iso(int(e1)), iso(int(e2))],
                "max_min_ratio": (None if tmin == 0 else round(tmax / tmin, 2)),
                "rule_3of3_triggered": bool(density_flag),
                "rule_e_applies": days >= 45.0,
            },
            "per_horizon": per_h,
        }

    inventory = {
        "exp": "EXP-016",
        "phase": "F0",
        "as_of_last_k_prices_bucket": iso(max(last_price.values())),
        "db": DB,
        "symbols": symbols,
        "n_symbols": len(symbols),
        "k_prices_window": {
            "from": iso(min(first_price.values())),
            "to": iso(max(last_price.values())),
            "per_symbol_gaps": {s: int(g) for s, g in gap_check.items() if g != 0},
        },
        "source_windows": {
            k: {"from": iso(a), "to": iso(b)} for k, (a, b) in source_windows.items()
        },
        "rules": {
            "cooldown_h": 24,
            "episode_gap_h": 24,
            "n_min_events": N_MIN_EVENTS,
            "n_min_episodes": N_MIN_EPISODES,
            "oi_shock_metric": "relative 1h change (proposta CP0)",
            "basis_metric": "basis_rate (proposta CP0)",
            "strict_inequality": "v > p95 / v < p5 (proposta CP0; funding tem massa no valor modal 0.0001 — >= p95 dispararia em mercado normal em 9/14 simbolos)",
            "order": "threshold -> elegibilidade(ref T+1h existe) -> cooldown -> episodios",
        },
        "thresholds": {
            fam: {s: (round(v, 8) if v is not None else None) for s, v in d.items()}
            for fam, d in thresholds.items()
        },
        "families": report,
        "cells": cells,
    }

    out = OUTDIR / "f0_inventory.json"
    out.write_text(json.dumps(inventory, indent=2))

    # --- resumo legivel ---
    print(f"F0 inventario — {len(symbols)} simbolos — dados ate {inventory['as_of_last_k_prices_bucket']} UTC")
    print(f"k_prices gaps por simbolo (esperado vazio): {inventory['k_prices_window']['per_symbol_gaps']}")
    print()
    hdr = (
        f"{'familia':<13}{'N pool':>7}{'EpSL':>6}{'EpANC':>7}{'N BTC':>7}"
        f"  {'tercos':<15}{'janela(d)':>9}  3/3?"
    )
    print(hdr)
    for fam, r in report.items():
        t = r["thirds"]
        print(
            f"{fam:<13}{r['pooled_n']:>7}{r['pooled_episodes']:>6}"
            f"{r['pooled_episodes_anchored']:>7}{r['btc_n']:>7}"
            f"  {str(t['counts']):<15}{r['window_used']['days']:>9}"
            f"  {'SIM' if t['rule_3of3_triggered'] else 'nao'}"
            f"{' (regua e nao se aplica: <45d)' if not t['rule_e_applies'] else ''}"
        )
    print()
    a_sl = sum(1 for c in cells if c["alive_single_linkage"])
    a_anc = sum(1 for c in cells if c["alive_anchored"])
    print(
        f"celulas: {len(cells)} total | vivas c/ single-linkage {a_sl}"
        f" | vivas c/ ancora-24h {a_anc}"
    )
    for c in cells:
        s1 = "SL:viva " if c["alive_single_linkage"] else "SL:morta"
        s2 = "ANC:viva " if c["alive_anchored"] else "ANC:morta"
        print(
            f"  {s1} {s2} {c['family']:<13} {c['horizon']:>4} {c['agg']:<6}"
            f" N={c['n_events']:>4} epSL={c['n_episodes']:>4} epANC={c['n_episodes_anchored']:>4}"
        )
    print(f"\nartefato: {out}")


if __name__ == "__main__":
    main()
