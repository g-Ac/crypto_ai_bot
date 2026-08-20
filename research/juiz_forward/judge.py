"""Juiz Forward — re-teste pré-registrado EXP-100/101/102 nos 28 símbolos sobre dado
forward (bucket_ts >= corte). Pré-registro: vault 2026-06-17-juiz-forward-prereg.md.

Autônomo (Python puro, sem Claude). Disparado por cron-guard no marco 2026-08-01.
Forward-only: régua congelada em 2026-06-17; testa só o dado posterior. 146 células
(120 dir + 10 xsec + 16 squeeze); BH-FDR CONJUNTO (q=0.10); candidato = expectancy
líquida > 0 + passa FDR + N mínimo. Veredito aceito sem re-rodar (anti-viés temporal).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from research.exp100_screening import data as datamod
from research.exp100_screening import backtest as bt
from research.exp100_screening import signals as sig
from research.exp100_screening import filters as filt
from research.exp100_screening import stats
from research.exp101_xsec import xsec
from research.exp102_squeeze import squeeze as sq

# congelado no pré-registro: dado de teste estritamente posterior ao congelamento
CORTE_FORWARD_TS = int(datetime(2026, 6, 18, 0, 0, tzinfo=timezone.utc).timestamp())
DIAS_MIN_VALIDO = 30
FDR_Q = 0.10
N_MIN_DIR = 30
N_MIN_XSEC = 20
OUT = Path(__file__).resolve().parent / "resultado.json"


def load_forward_panel(corte_ts=CORTE_FORWARD_TS):
    panels = datamod.load_panel()
    out = {}
    for s, df in panels.items():
        f = df[df.index >= corte_ts]
        if len(f) > 0:
            out[s] = f
    return out


def _cells_exp100(panels):
    cells = []
    for fam in sig.FAMILIES:
        for fname in filt.FILTERS:
            for uni in ("todos", "memes", "large_cap"):
                for hz in (4, 24):
                    syms = datamod.universe(panels, uni)
                    e = sig.FAMILIES[fam](panels, syms)
                    e = filt.FILTERS[fname](e, panels)
                    e = bt.dedupe_overlap(e, hz)
                    s = bt.summarize(bt.trade_returns(e, panels, hz), seed=1)
                    cells.append({"exp": "EXP-100", "label": f"{fam}|{fname}|{uni}|H{hz}",
                                  "n": s["n"], "expectancy_bps": s["expectancy_bps"],
                                  "p_value": s["p_value"], "n_min": N_MIN_DIR})
    return cells


def _cells_exp101(panels):
    cells = []
    for scorer in xsec.SCORERS:
        for hz in (4, 24):
            port, _ic = xsec.run_xsec(panels, xsec.SCORERS[scorer], hz, k=4)
            r = np.asarray(port["ret_net_bps"], dtype=float)
            n = len(r)
            cells.append({"exp": "EXP-101", "label": f"{scorer}|H{hz}|xsec",
                          "n": n,
                          "expectancy_bps": float(r.mean()) if n else float("nan"),
                          "p_value": bt.bootstrap_p(r, seed=2) if n else 1.0,
                          "n_min": N_MIN_XSEC})
    return cells


def _cells_exp102(panels):
    cells = []
    for resp in ("reversao", "continuacao"):
        for hz in (4, 24):
            for uni in ("todos", "memes"):
                for use_oi in (False, True):
                    syms = datamod.universe(panels, uni)
                    e = []
                    for s in syms:
                        e += sq.build_entries(panels[s], s, use_oi, resp)
                    e = bt.dedupe_overlap(e, hz)
                    sm = bt.summarize(bt.trade_returns(e, panels, hz), seed=3)
                    cells.append({"exp": "EXP-102", "label": f"{resp}|H{hz}|{uni}|OI={use_oi}",
                                  "n": sm["n"], "expectancy_bps": sm["expectancy_bps"],
                                  "p_value": sm["p_value"], "n_min": N_MIN_DIR})
    return cells


def judge(corte_ts=CORTE_FORWARD_TS, out_path=OUT):
    panels = load_forward_panel(corte_ts)
    dias = 0.0
    if panels:
        lo = min(df.index.min() for df in panels.values())
        hi = max(df.index.max() for df in panels.values())
        dias = (hi - lo) / 86400.0

    cells = _cells_exp100(panels) + _cells_exp101(panels) + _cells_exp102(panels)

    elig = [c for c in cells if c["n"] >= c["n_min"] and np.isfinite(c["p_value"])]
    pvals = [c["p_value"] for c in elig]
    rej = stats.benjamini_hochberg(pvals, q=FDR_Q) if pvals else np.zeros(0, bool)
    for c in cells:
        c["passes_fdr"] = False
    for c, r in zip(elig, rej):
        c["passes_fdr"] = bool(r)

    candidatos = [c for c in cells if c["passes_fdr"] and c["n"] >= c["n_min"]
                  and np.isfinite(c["expectancy_bps"]) and c["expectancy_bps"] > 0]

    if dias < DIAS_MIN_VALIDO:
        veredito = "DADO-INSUFICIENTE"
    elif candidatos:
        veredito = "GO-INVESTIGAR"
    else:
        veredito = "NO-GO"

    payload = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "corte_forward_ts": corte_ts, "dias_forward": round(dias, 1),
        "n_simbolos": len(panels), "n_celulas": len(cells), "n_elegiveis": len(elig),
        "veredito": veredito, "n_candidatos": len(candidatos),
        "candidatos": candidatos, "cells": cells,
    }
    Path(out_path).write_text(json.dumps(payload, indent=2, default=str))
    return payload


if __name__ == "__main__":
    p = judge()
    print(f"JUIZ FORWARD: {p['veredito']} | {p['dias_forward']}d forward, "
          f"{p['n_simbolos']} símbolos, {p['n_elegiveis']}/{p['n_celulas']} elegíveis, "
          f"{p['n_candidatos']} candidatos")
    for c in p["candidatos"]:
        print(f"  -> {c['exp']} {c['label']}: exp={c['expectancy_bps']:.1f}bps "
              f"n={c['n']} p={c['p_value']:.3f}")
