#!/usr/bin/env python3
"""F2 — Lente diagnostica v1.1 do EXP-016 (BRIEFING Secao 6/F2).

Anexa a cada trade real (momentum_trades) e shadow (momentum_shadow_outcomes)
o estado exogeno mais recente DISPONIVEL antes da entrada — join por
disponibilidade (ultimo registro k_* com ts <= entry) — e reporta se
winners/losers se separam por estado. DIAGNOSTICO, nao vira filtro do v1.1.

Decisoes de medicao (declaradas):
- Trades reais: timestamp da tabela e o FECHAMENTO (UTC). Entry estimada =
  timestamp - duration_candles*15min (erro <= 1 candle de 15m).
- Shadow: decision_timestamp = entrada (UTC naive, conferido vs relogio).
  Filtra complete=1.
- Estado k_*: snapshots de abertura de hora; staleness ate ~55min em
  operacao + ate 15min do erro de entry estimada. Staleness reportada.
- k_basis so cobre desde 11/05; trades anteriores ficam sem basis
  (cobertura declarada por fonte).
- Winners: pnl_pct > 0 (bruto, nos dois datasets — shadow nao tem fees).
- Separacao W vs L: mediana por grupo + rank-sum (aproximacao normal com
  correcao de empates) — DESCRITIVO, sem gate.
- Flag por familia: evento da grade (events.db) no MESMO simbolo nas 24h
  anteriores a entrada.
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import sqlite3
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BOT_DB = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")
SNAPSHOT = HERE / "source_snapshot.db"
EVENTS_DB = HERE / "events.db"
OUT = HERE / "f2_v11_lens.json"
HOUR = 3600


def parse_utc(s: str) -> int:
    s = s.strip().replace("T", " ")
    if "+" in s:
        s = s.split("+")[0]
    if "." in s:
        s = s.split(".")[0]
    return int(
        dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=dt.timezone.utc)
        .timestamp()
    )


def ranksum_z(a, b):
    """Mann-Whitney U via aproximacao normal com correcao de empates."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n1, n2 = len(a), len(b)
    if n1 < 3 or n2 < 3:
        return None, None
    allv = np.concatenate([a, b])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(len(allv))
    sorted_v = allv[order]
    i = 0
    while i < len(sorted_v):
        j = i
        while j + 1 < len(sorted_v) and sorted_v[j + 1] == sorted_v[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    r1 = ranks[:n1].sum()
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0
    # correcao de empates na variancia
    _, counts = np.unique(allv, return_counts=True)
    n = n1 + n2
    tie_term = ((counts**3 - counts).sum()) / (n * (n - 1)) if n > 1 else 0.0
    var = n1 * n2 / 12.0 * ((n + 1) - tie_term)
    if var <= 0:
        return None, None
    z = (u1 - mu) / math.sqrt(var)
    p = math.erfc(abs(z) / math.sqrt(2))
    return round(z, 3), round(p, 4)


def load_state_series():
    conn = sqlite3.connect(f"file:{SNAPSHOT}?mode=ro", uri=True)

    def series(sql):
        d = {}
        for sym, ts, v in conn.execute(sql):
            if v is not None:
                d.setdefault(sym, []).append((int(ts), float(v)))
        for s in d:
            d[s].sort()
        return d

    fund = series("SELECT symbol, funding_time, funding_rate FROM k_funding_rates")
    basis = series("SELECT symbol, bucket_ts, basis_rate FROM k_basis")
    top = series(
        "SELECT symbol, bucket_ts, long_short_ratio FROM k_ratios WHERE source='top_position'"
    )
    glb = series(
        "SELECT symbol, bucket_ts, long_short_ratio FROM k_ratios WHERE source='global_account'"
    )
    oi = series("SELECT symbol, bucket_ts, sum_open_interest FROM k_open_interest")
    return {"funding": fund, "basis_rate": basis, "lsr_top": top, "lsr_glb": glb, "oi": oi}


def last_leq(rows, ts):
    """(valor, staleness_s, ts_usado) do ultimo registro com ts_k <= ts."""
    keys = [r[0] for r in rows]
    i = bisect.bisect_right(keys, ts) - 1
    if i < 0:
        return None, None, None
    return rows[i][1], ts - rows[i][0], rows[i][0]


def delta_1h(rows, ts_used, relative=False):
    m = dict(rows)
    if ts_used is None or (ts_used - HOUR) not in m:
        return None
    prev, cur = m[ts_used - HOUR], m[ts_used]
    if relative:
        return (cur - prev) / prev if prev else None
    return cur - prev


def main():
    state = load_state_series()
    ev_conn = sqlite3.connect(f"file:{EVENTS_DB}?mode=ro", uri=True)
    events_by_fam_sym = {}
    for fam, sym, ts in ev_conn.execute(
        "SELECT family, symbol, event_ts FROM f1_events"
    ):
        events_by_fam_sym.setdefault((fam, sym), []).append(ts)
    for v in events_by_fam_sym.values():
        v.sort()
    families = sorted({k[0] for k in events_by_fam_sym})

    bot = sqlite3.connect(f"file:{BOT_DB}?mode=ro", uri=True)
    datasets = {}
    real = [
        {
            "entry_ts": parse_utc(ts) - (dur or 0) * 900,
            "symbol": sym,
            "pnl": pnl,
            "net_pnl": net,
        }
        for ts, sym, dur, pnl, net in bot.execute(
            "SELECT timestamp, symbol, duration_candles, pnl_pct, net_pnl_pct"
            " FROM momentum_trades"
        )
    ]
    shadow = [
        {"entry_ts": parse_utc(ts), "symbol": sym, "pnl": pnl, "net_pnl": None}
        for ts, sym, pnl in bot.execute(
            "SELECT decision_timestamp, symbol, pnl_pct FROM momentum_shadow_outcomes"
            " WHERE complete=1 AND pnl_pct IS NOT NULL"
        )
    ]
    datasets["real"] = real
    datasets["shadow"] = shadow

    metrics = ("funding", "basis_rate", "lsr_top", "lsr_glb", "d1h_lsr_top", "d1h_lsr_glb", "d1h_oi_rel")
    report = {"as_of": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    for name, trades in datasets.items():
        rows = []
        for t in trades:
            sym, ts = t["symbol"], t["entry_ts"]
            st, stale = {}, {}
            for key in ("funding", "basis_rate", "lsr_top", "lsr_glb"):
                v, lag, used = last_leq(state[key].get(sym, []), ts)
                st[key] = v
                stale[key] = lag
                if key == "lsr_top":
                    st["d1h_lsr_top"] = delta_1h(state["lsr_top"].get(sym, []), used)
                if key == "lsr_glb":
                    st["d1h_lsr_glb"] = delta_1h(state["lsr_glb"].get(sym, []), used)
            _, lag_oi, used_oi = last_leq(state["oi"].get(sym, []), ts)
            st["d1h_oi_rel"] = delta_1h(state["oi"].get(sym, []), used_oi, relative=True)
            stale["oi"] = lag_oi
            flags = {}
            for fam in families:
                evs = events_by_fam_sym.get((fam, sym), [])
                i = bisect.bisect_right(evs, ts) - 1
                flags[fam] = bool(i >= 0 and ts - evs[i] <= 24 * HOUR)
            rows.append({**t, "state": st, "stale": stale, "flags": flags})

        winners = [r for r in rows if (r["pnl"] or 0) > 0]
        losers = [r for r in rows if (r["pnl"] or 0) <= 0]
        sep = {}
        for m in metrics:
            wv = [r["state"][m] for r in winners if r["state"].get(m) is not None]
            lv = [r["state"][m] for r in losers if r["state"].get(m) is not None]
            if len(wv) >= 3 and len(lv) >= 3:
                z, p = ranksum_z(wv, lv)
                sep[m] = {
                    "n_w": len(wv),
                    "n_l": len(lv),
                    "median_w": round(float(np.median(wv)), 6),
                    "median_l": round(float(np.median(lv)), 6),
                    "z": z,
                    "p": p,
                }
        fam_split = {}
        for fam in families:
            with_f = [r["pnl"] for r in rows if r["flags"][fam] and r["pnl"] is not None]
            without = [r["pnl"] for r in rows if not r["flags"][fam] and r["pnl"] is not None]
            if len(with_f) >= 5:
                fam_split[fam] = {
                    "n_with": len(with_f),
                    "n_without": len(without),
                    "wr_with": round(sum(1 for p in with_f if p > 0) / len(with_f), 3),
                    "wr_without": round(
                        sum(1 for p in without if p > 0) / len(without), 3
                    ),
                    "mean_pnl_with": round(float(np.mean(with_f)), 4),
                    "mean_pnl_without": round(float(np.mean(without)), 4),
                }
        stl = {
            k: {
                "p50_min": round(
                    float(np.median([r["stale"][k] for r in rows if r["stale"].get(k) is not None]))
                    / 60.0,
                    1,
                ),
                "max_min": round(
                    max(r["stale"][k] for r in rows if r["stale"].get(k) is not None) / 60.0, 1
                ),
                "coverage": round(
                    sum(1 for r in rows if r["stale"].get(k) is not None) / len(rows), 3
                ),
            }
            for k in ("funding", "basis_rate", "lsr_top", "oi")
            if any(r["stale"].get(k) is not None for r in rows)
        }
        report[name] = {
            "n": len(rows),
            "n_winners": len(winners),
            "n_losers": len(losers),
            "separation_by_state": sep,
            "event_flag_split": fam_split,
            "staleness_min": stl,
        }

    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    for name in ("real", "shadow"):
        r = report[name]
        print(f"\n=== {name}: n={r['n']} (W {r['n_winners']} / L {r['n_losers']}) ===")
        print("separacao W vs L por estado (mediana W | mediana L | z | p):")
        for m, s in r["separation_by_state"].items():
            print(
                f"  {m:<13} {s['median_w']:>12.6g} | {s['median_l']:>12.6g}"
                f" | z={s['z']:>6} | p={s['p']}"
            )
        print("split por evento recente (<=24h, mesmo simbolo):")
        for fam, s in r["event_flag_split"].items():
            print(
                f"  {fam:<13} com: n={s['n_with']:>4} wr={s['wr_with']:.0%} pnl={s['mean_pnl_with']:+.3f}%"
                f" | sem: n={s['n_without']:>4} wr={s['wr_without']:.0%} pnl={s['mean_pnl_without']:+.3f}%"
            )
        print(f"staleness (min) e cobertura: {json.dumps(r['staleness_min'])}")
    print(f"\nartefato: {OUT}")


if __name__ == "__main__":
    main()
