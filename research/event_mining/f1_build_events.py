#!/usr/bin/env python3
"""F1 — ETL do EXP-016 Event Mining: snapshot congelado + dataset de eventos.

1. Congela snapshot das tabelas k_* (source_snapshot.db) na primeira execucao
   — o bot.db e vivo (coletor horario no cron :05); todo o pipeline F1-F3
   roda do snapshot para ser reprodutivel. Validacao 13/07 = dados novos.
2. Constroi o dataset da grade congelada (em_lib.build_dataset) e grava
   events.db (tabelas f1_events + f1_meta).
3. Imprime o relatorio de sanidade do CP1: janelas declaradas, N por celula
   e por episodio, cross-check vs f0_inventory.json, distribuicao temporal
   (top episodios, fracao do dominante), candidatos a spot-check.

NAO imprime nenhuma media de retorno por celula — descoberta e F2/CP2.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import em_lib

HERE = Path(__file__).resolve().parent
SOURCE_DB = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")
SNAPSHOT = HERE / "source_snapshot.db"
EVENTS_DB = HERE / "events.db"
F0_JSON = HERE / "f0_inventory.json"
TABLES = ("k_prices", "k_ratios", "k_funding_rates", "k_basis", "k_open_interest")


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def create_snapshot():
    if SNAPSHOT.exists():
        print(f"snapshot ja existe (reuso): {SNAPSHOT.name}")
        return
    conn = sqlite3.connect(SNAPSHOT)
    conn.execute("ATTACH DATABASE ? AS src", (f"file:{SOURCE_DB}?mode=ro",))
    for t in TABLES:
        conn.execute(f"CREATE TABLE {t} AS SELECT * FROM src.{t}")
    conn.commit()
    conn.close()
    print(f"snapshot criado: {SNAPSHOT.name}")


def main():
    create_snapshot()
    conn = sqlite3.connect(f"file:{SNAPSHOT}?mode=ro", uri=True)

    # janelas declaradas (armadilha 5: declarar sempre)
    windows = {}
    for t in TABLES:
        col = "funding_time" if t == "k_funding_rates" else "bucket_ts"
        lo, hi, n = conn.execute(f"SELECT MIN({col}), MAX({col}), COUNT(*) FROM {t}").fetchone()
        windows[t] = {"from": iso(lo), "to": iso(hi), "rows": n}

    events, meta = em_lib.build_dataset(conn)
    meta["as_of"] = windows["k_prices"]["to"]
    meta["source_windows"] = windows
    em_lib.write_db(events, meta, EVENTS_DB)
    counts = em_lib.cell_counts(events)

    print(f"\nas-of (ultimo bucket k_prices do snapshot): {meta['as_of']} UTC")
    print("janelas das fontes no snapshot:")
    for t, w in windows.items():
        print(f"  {t:<16} {w['from']} -> {w['to']}  ({w['rows']} linhas)")
    print(f"\neventos gravados em {EVENTS_DB.name}: {len(events)}")

    # N por celula vs regua (c): N>=30 E episodios>=10
    f0 = json.loads(F0_JSON.read_text()) if F0_JSON.exists() else None
    print(f"\n{'celula':<22}{'N':>5}{'ep':>5}  regua-c  vs F0 (N/ep)")
    for fam in em_lib.FAMILIES:
        for h in em_lib.HORIZONS:
            c = counts[(fam, h)]
            ok = c["n"] >= 30 and c["episodes"] >= 10
            ref = ""
            if f0:
                f0c = f0["families"][fam]["per_horizon"][f"+{h}h"]["pooled"]
                dn = c["n"] - f0c["n"]
                de = c["episodes"] - f0c["episodes_anchored"]
                ref = f"{'igual' if dn == 0 and de == 0 else f'dN={dn:+d} dEp={de:+d}'}"
            print(
                f"{fam + ' +' + str(h) + 'h':<22}{c['n']:>5}{c['episodes']:>5}"
                f"  {'VIVA' if ok else 'MORTA':<7}  {ref}"
            )

    # distribuicao temporal por familia: top-3 episodios e fracao dominante
    print(f"\n{'familia':<13}{'N':>5}{'ep':>4}  top-3 episodios (n eventos)  frac. dominante")
    for fam in em_lib.FAMILIES:
        fam_ev = [e for e in events if e["family"] == fam]
        if not fam_ev:
            continue
        by_ep = {}
        for e in fam_ev:
            by_ep.setdefault(e["episode"], []).append(e)
        sizes = sorted(((len(v), k) for k, v in by_ep.items()), reverse=True)
        top3 = sizes[:3]
        dom_n, dom_ep = sizes[0]
        dom_ts = min(e["event_ts"] for e in by_ep[dom_ep])
        frac = dom_n / len(fam_ev)
        top_str = ", ".join(f"ep{k}:{n}" for n, k in top3)
        print(
            f"{fam:<13}{len(fam_ev):>5}{len(by_ep):>4}  {top_str:<28} "
            f"{frac:5.1%} (inicia {iso(dom_ts)})"
        )

    # candidatos a spot-check (deterministicos): 1o FUND-, mediano BASIS+,
    # ultimo OI-SHOCK — linhas cruas conferidas manualmente no CP1
    print("\nspot-check (3 eventos para conferencia manual contra dados crus):")

    def fmt(e):
        r = {h: (None if v is None else round(v, 2)) for h, v in e["ret_bps"].items()}
        return (
            f"  {e['family']:<13} {e['symbol']:<10} t={iso(e['event_ts'])}"
            f" metric={e['metric']:.6g} thr={e['threshold']:.6g}"
            f" ref={e['ref_price']:.6g}@{iso(e['ref_ts'])} ep={e['episode']}"
            f" ret_bps={r}"
        )

    fund_neg = [e for e in events if e["family"] == "FUND-"]
    basis_pos = [e for e in events if e["family"] == "BASIS+"]
    oi_ev = [e for e in events if e["family"] == "OI-SHOCK"]
    picks = [fund_neg[0], basis_pos[len(basis_pos) // 2], oi_ev[-1]]
    for e in picks:
        print(fmt(e))


if __name__ == "__main__":
    main()
