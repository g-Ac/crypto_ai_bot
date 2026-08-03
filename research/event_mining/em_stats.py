#!/usr/bin/env python3
"""em_stats — motor estatistico da F2 (varredura) do EXP-016 Event Mining.

Implementa as 5 reguas da moldura congelada (BRIEFING Secao 5), com o teste
estatistico CONGELADO na regua (b), interpretado e fixado assim:

- direcao da celula = sinal da media bruta observada (travada p/ forward);
- retorno direcional por evento = direcao * ret_bps; liquido = direcional - 20;
- bootstrap cluster por EPISODIO: B=10.000 reamostragens com reposicao dos
  ids de episodio (tamanho = n_episodios observado), estatistica = media
  LIQUIDA da celula na replica (direcao fixa da observada);
- SE = desvio-padrao das 10.000 medias; t = media_liquida_obs / SE;
  gate (b): |t| >= 2.0;
- p-value percentil bicaudal (inversao do IC): p = min(1, 2*min(
  (1+#{m* <= 0})/(B+1), (1+#{m* >= 0})/(B+1))) — reportado e usado no BH;
- seed deterministico por celula: SEED_BASE + indice fixo (ordem
  FAMILIES x HORIZONS); mesmo input -> mesmos numeros, sempre.

Reguas (todas simultaneas por celula):
(a) economica: |media bruta| >= 25/35/50 bps (1h/4h/24h) E liquida > 0;
(b) estatistica: |t| >= 2.0 (acima);
(c) amostra: N >= 30 E N_episodios >= 10;
(d) concentracao: top-3 episodios (por contribuicao direcional bruta) < 50%
    do retorno agregado direcional bruto (total <= 0 -> reprova);
(e) estabilidade: sinal da media bruta do horizonte por terco temporal ==
    sinal global em >= 2/3 tercos; se densidade de eventos max/min > 2x
    entre tercos -> exige 3/3. So se aplica a fontes com >= 45 dias;
    BASIS (31d) carrega flag 'terco-fraco' e (e) nao e gate.

BH (FDR 10%) sobre os p-values das 21 celulas = CONTEXTO obrigatorio do
CP2, nao gate (pre-registrado na moldura).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from em_lib import FAMILIES, HORIZONS

HERE = Path(__file__).resolve().parent
EVENTS_DB = HERE / "events.db"
OUT_JSON = HERE / "f2_results.json"

COST_BPS = 20.0
ECON_MIN = {1: 25.0, 4: 35.0, 24: 50.0}
B = 10_000
SEED_BASE = 20_260_612
T_GATE = 2.0
N_MIN, EP_MIN = 30, 10
RULE_E_MIN_DAYS = 45.0

CELL_ORDER = [(fam, h) for fam in FAMILIES for h in HORIZONS]


def load_events(db_path=EVENTS_DB):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT family, symbol, event_ts, episode, ret_1h_bps, ret_4h_bps,"
        " ret_24h_bps FROM f1_events ORDER BY family, event_ts, symbol"
    ).fetchall()
    meta = {
        k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM f1_meta")
    }
    events = [
        {
            "family": fam,
            "symbol": sym,
            "event_ts": ts,
            "episode": ep,
            "ret_bps": {1: r1, 4: r4, 24: r24},
        }
        for fam, sym, ts, ep, r1, r4, r24 in rows
    ]
    return events, meta


def cell_stats(cell_events, h, window_lo, window_hi, seed):
    """Estatisticas de UMA celula (familia x horizonte, pooled).
    cell_events: eventos da familia (qualquer simbolo) com campos
    episode/ret_bps/event_ts. Usa apenas eventos com retorno no horizonte."""
    pts = [
        (e["episode"], float(e["ret_bps"][h]), e["event_ts"])
        for e in cell_events
        if e["ret_bps"][h] is not None
    ]
    n = len(pts)
    if n == 0:
        return {"n": 0, "alive_c": False}
    rets = np.array([r for _, r, _ in pts])
    eps = np.array([ep for ep, _, _ in pts])
    ep_ids = sorted(set(eps.tolist()))
    n_ep = len(ep_ids)

    gross_mean = float(rets.mean())
    direction = 1 if gross_mean >= 0 else -1
    dir_rets = direction * rets
    net_rets = dir_rets - COST_BPS
    net_mean = float(net_rets.mean())  # = |gross_mean| - 20

    # bootstrap cluster por episodio (teste congelado)
    rng = np.random.default_rng(seed)
    by_ep = {ep: net_rets[eps == ep] for ep in ep_ids}
    boot = np.empty(B)
    for b in range(B):
        sample = rng.choice(ep_ids, size=n_ep, replace=True)
        boot[b] = float(np.concatenate([by_ep[ep] for ep in sample]).mean())
    se = float(boot.std(ddof=1))
    t = net_mean / se if se > 0 else float("inf")
    p_low = (1 + int((boot <= 0).sum())) / (B + 1)
    p_high = (1 + int((boot >= 0).sum())) / (B + 1)
    p = min(1.0, 2.0 * min(p_low, p_high))

    # regua d: concentracao por episodio (contribuicao direcional bruta)
    contrib = {ep: float(dir_rets[eps == ep].sum()) for ep in ep_ids}
    total = sum(contrib.values())
    top3 = sorted(contrib.values(), reverse=True)[:3]
    conc = (sum(top3) / total) if total > 0 else float("inf")

    # regua e: tercos temporais (janela usavel da familia)
    e1 = window_lo + (window_hi - window_lo) / 3.0
    e2 = window_lo + 2.0 * (window_hi - window_lo) / 3.0
    thirds = []
    for lo, hi in ((window_lo, e1), (e1, e2), (e2, window_hi + 1)):
        sub = [r for _, r, ts in pts if lo <= ts < hi]
        thirds.append(
            {
                "n": len(sub),
                "gross_mean": (float(np.mean(sub)) if sub else None),
                "sign_match": (
                    bool(np.sign(np.mean(sub)) == np.sign(gross_mean))
                    if sub and gross_mean != 0
                    else False
                ),
            }
        )
    counts = [td["n"] for td in thirds]
    density_2x = min(counts) == 0 or (max(counts) / max(min(counts), 1) > 2.0)
    required = 3 if density_2x else 2
    matches = sum(1 for td in thirds if td["sign_match"])

    days = (window_hi - window_lo) / 86400.0
    rule_e_applies = days >= RULE_E_MIN_DAYS

    fam_dom = max(np.bincount(eps).max(), 0)
    res = {
        "n": n,
        "n_episodes": n_ep,
        "gross_mean_bps": round(gross_mean, 3),
        "direction": "long" if direction > 0 else "short",
        "net_mean_bps": round(net_mean, 3),
        "boot_se_bps": round(se, 3),
        "t": round(t, 3),
        "p_value": round(p, 6),
        "concentration_top3": (round(conc, 4) if np.isfinite(conc) else None),
        "dominant_episode_frac": round(float(fam_dom) / n, 4),
        "thirds": thirds,
        "thirds_required": required,
        "thirds_matches": matches,
        "window_days": round(days, 1),
        "rule_e_applies": rule_e_applies,
        "rule_a": bool(abs(gross_mean) >= ECON_MIN[h] and net_mean > 0),
        "rule_b": bool(abs(t) >= T_GATE),
        "rule_c": bool(n >= N_MIN and n_ep >= EP_MIN),
        "rule_d": bool(np.isfinite(conc) and conc < 0.5),
        "rule_e": bool(matches >= required) if rule_e_applies else None,
    }
    gates = [res["rule_a"], res["rule_b"], res["rule_c"], res["rule_d"]]
    if rule_e_applies:
        gates.append(res["rule_e"])
    res["survives_all"] = all(gates)
    return res


def bh_qvalues(pvals):
    """q-values de Benjamini-Hochberg (contexto, nao gate)."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank_from_end, i in enumerate(reversed(order)):
        j = m - rank_from_end  # posicao 1-based no ordenamento
        prev = min(prev, pvals[i] * m / j)
        q[i] = prev
    return q


def main():
    events, meta = load_events()
    src_windows = meta["source_windows"]
    fam_to_table = {
        "FUND+": "k_funding_rates",
        "FUND-": "k_funding_rates",
        "BASIS+": "k_basis",
        "BASIS-": "k_basis",
        "LSR-TOP-SQZ": "k_ratios",
        "LSR-GLB-SQZ": "k_ratios",
        "OI-SHOCK": "k_open_interest",
    }
    import datetime as dt

    def parse(s):
        return int(
            dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )

    first_price = parse(src_windows["k_prices"]["from"])
    results = {}
    for idx, (fam, h) in enumerate(CELL_ORDER):
        fam_ev = [e for e in events if e["family"] == fam]
        w = src_windows[fam_to_table[fam]]
        lo = max(parse(w["from"]), first_price - 3600)
        hi = parse(w["to"])
        results[f"{fam}|+{h}h"] = cell_stats(fam_ev, h, lo, hi, SEED_BASE + idx)

    cells = list(results)
    pvals = [results[c]["p_value"] for c in cells]
    for c, qv in zip(cells, bh_qvalues(pvals)):
        results[c]["q_value_bh"] = round(qv, 6)

    n_tests = len(cells)
    out = {
        "exp": "EXP-016",
        "phase": "F2",
        "as_of": meta.get("as_of"),
        "n_tests_run": n_tests,
        "n_tests_a_priori": 42,
        "note_multiplicity": (
            "42 celulas a priori; 21 (BTC) morreram na F0 por amostra antes de"
            " qualquer retorno; 21 testadas"
        ),
        "expected_false_positives_at_5pct": round(0.05 * n_tests, 2),
        "cost_bps": COST_BPS,
        "bootstrap": {"B": B, "seed_base": SEED_BASE, "stat": "media liquida"},
        "cells": results,
        "survivors": [c for c in cells if results[c]["survives_all"]],
    }
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"F2 sweep — {n_tests} celulas | FP esperados a 5%: {out['expected_false_positives_at_5pct']}")
    hdr = (
        f"{'celula':<19}{'N':>4}{'ep':>4}{'bruta':>8}{'liq':>8}{'t':>7}"
        f"{'p':>9}{'q(BH)':>9}{'conc3':>7}{'e':>4}  reguas  sobrevive"
    )
    print(hdr)
    for c in cells:
        r = results[c]
        rules = "".join(
            ("a" if r["rule_a"] else "-")
            + ("b" if r["rule_b"] else "-")
            + ("c" if r["rule_c"] else "-")
            + ("d" if r["rule_d"] else "-")
            + (("e" if r["rule_e"] else "-") if r["rule_e_applies"] else "x")
        )
        print(
            f"{c:<19}{r['n']:>4}{r['n_episodes']:>4}{r['gross_mean_bps']:>8.1f}"
            f"{r['net_mean_bps']:>8.1f}{r['t']:>7.2f}{r['p_value']:>9.4f}"
            f"{r['q_value_bh']:>9.4f}"
            f"{(r['concentration_top3'] if r['concentration_top3'] is not None else float('nan')):>7.2f}"
            f"{r['thirds_matches']:>2}/{r['thirds_required']}"
            f"  {rules:<6}  {'SIM' if r['survives_all'] else 'nao'}"
        )
    print(f"\nsobreviventes: {out['survivors'] or 'nenhum'}")
    print(f"artefato: {OUT_JSON}")


if __name__ == "__main__":
    main()
