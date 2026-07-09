"""Colhedor — juiz genérico forward-only. Generaliza o judge.py SEM tocá-lo.

Roda no marco (via cron idempotente). Para cada pré-registro `frozen` cujo marco
venceu: re-instancia a spec, mede SÓ no dado forward (bucket_ts >= corte_ts),
aplica BH-FDR conjunto por `batch_id` e grava o verdict. Python puro, determinístico,
SEM Claude — é isso que mantém o julgamento livre de viés de seleção. Veredito aceito
sem re-rodar; um pré-registro `judged` nunca é re-julgado (idempotência via status).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from research.exp100_screening import backtest as bt
from research.exp100_screening import data as datamod
from research.exp100_screening import stats
from research.gerador_prereg import catalogo as cat
from research.gerador_prereg import schema

FDR_Q = 0.10
HERE = Path(__file__).resolve().parent
JOURNAL_DEFAULT = HERE / "journal.jsonl"
OUT_DEFAULT = HERE / "resultado.json"


def _forward_panels(panels, corte_ts):
    """Só o dado que não existia no congelamento (forward-only)."""
    out = {}
    for s, df in panels.items():
        f = df[df.index >= corte_ts]
        if len(f) > 0:
            out[s] = f
    return out


def _dias(panels):
    if not panels:
        return 0.0
    lo = min(df.index.min() for df in panels.values())
    hi = max(df.index.max() for df in panels.values())
    return (hi - lo) / 86400.0


def _f(x):
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return xf if np.isfinite(xf) else None


def _measure(rec, panels, seed):
    fp = _forward_panels(panels, rec["forward"]["corte_ts"])
    trades = cat.build_trades(rec["spec"], fp)
    s = bt.summarize(trades, seed=seed)
    s["dias_forward"] = round(_dias(fp), 1)
    return s


def _parse_marco(s):
    return datetime.fromisoformat(s).date()


def colher(journal_path=JOURNAL_DEFAULT, panels=None, hoje=None,
           out_path=OUT_DEFAULT, load=True):
    """Julga os pré-registros vencidos. Retorna o payload e grava resultado.json +
    verdicts no journal. `panels`/`hoje` injetáveis p/ teste (fixtures sintéticas)."""
    journal_path = str(journal_path)
    recs = schema.read_journal(journal_path)
    if hoje is None:
        hoje = datetime.now(timezone.utc).date()
    if panels is None:
        if not load:
            raise ValueError("panels=None e load=False: nada para julgar")
        panels = datamod.load_panel()

    a_julgar = [r for r in recs
                if r["status"] == "frozen" and _parse_marco(r["forward"]["marco"]) <= hoje]

    por_batch = defaultdict(list)
    for i, r in enumerate(a_julgar):
        por_batch[r["batch_id"]].append((r, _measure(r, panels, seed=i + 1)))

    batches, candidatos, julgados = {}, [], []
    for batch_id, items in por_batch.items():
        elig_idx = [j for j, (r, m) in enumerate(items)
                    if m["n"] >= r["forward"]["n_min"] and np.isfinite(m["p_value"])]
        pvals = [items[j][1]["p_value"] for j in elig_idx]
        rej = stats.benjamini_hochberg(pvals, q=FDR_Q) if pvals else np.zeros(0, bool)
        passes = [False] * len(items)
        for j, ok in zip(elig_idx, rej):
            passes[j] = bool(ok)

        n_cand = 0
        for j, (r, m) in enumerate(items):
            is_cand = bool(passes[j] and m["n"] >= r["forward"]["n_min"]
                           and np.isfinite(m["expectancy_bps"])
                           and m["expectancy_bps"] > r["forward"]["threshold"])
            r["status"] = "judged"
            r["verdict"] = {
                "veredito_batch": None,                    # preenchido após o loop
                "expectancy_net_bps": _f(m["expectancy_bps"]),
                "n": int(m["n"]), "pf": _f(m["pf"]), "win_rate": _f(m["win_rate"]),
                "p_value": _f(m["p_value"]), "passes_fdr": passes[j],
                "is_candidato": is_cand, "dias_forward": m["dias_forward"],
                "label": cat.spec_signature(r["spec"]),
                "julgado_em": datetime.now(timezone.utc).isoformat(),
            }
            julgados.append(r["id"])
            if is_cand:
                n_cand += 1
                candidatos.append({"id": r["id"], "batch_id": batch_id,
                                   "label": cat.spec_signature(r["spec"]),
                                   "expectancy_net_bps": _f(m["expectancy_bps"]),
                                   "n": int(m["n"]), "p_value": _f(m["p_value"])})

        if not elig_idx:
            vbatch = "DADO-INSUFICIENTE"
        elif n_cand > 0:
            vbatch = "GO-INVESTIGAR"
        else:
            vbatch = "NO-GO"
        for (r, m) in items:
            r["verdict"]["veredito_batch"] = vbatch
        batches[batch_id] = {"veredito": vbatch, "n_candidatos": n_cand,
                             "n_julgados": len(items), "n_elegiveis": len(elig_idx),
                             "dias_forward": max((m["dias_forward"] for (_, m) in items),
                                                 default=0.0)}

    schema.rewrite(journal_path, recs)   # idempotente: judged não re-entra
    payload = {"gerado_em": datetime.now(timezone.utc).isoformat(),
               "hoje": hoje.isoformat(), "n_julgados": len(julgados),
               "julgados": julgados, "batches": batches, "candidatos": candidatos}
    Path(out_path).write_text(json.dumps(payload, indent=2, default=str))
    return payload


if __name__ == "__main__":
    p = colher()
    print(f"COLHEDOR: {p['n_julgados']} julgados, {len(p['candidatos'])} candidato(s)")
    for b, info in p["batches"].items():
        print(f"  {b}: {info['veredito']} ({info['n_candidatos']}/{info['n_julgados']} cand, "
              f"{info['dias_forward']}d)")
