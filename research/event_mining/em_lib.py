"""em_lib — nucleo do ETL do EXP-016 Event Mining (grade congelada no CP0).

Grade congelada (BRIEFING.md Secao 5 + ratificacoes do CP0 em 2026-06-12):
- 7 familias: FUND+/FUND- (k_funding_rates, grade nativa), BASIS+/BASIS-
  (k_basis.basis_rate), LSR-TOP-SQZ / LSR-GLB-SQZ (|delta 1h| do ratio por
  source), OI-SHOCK (|delta 1h relativo| de sum_open_interest).
- Threshold: percentil empirico (interpolacao linear) por simbolo sobre a
  janela inteira da fonte; gatilho ESTRITO (> p95 / < p5; |d| > p95).
- Elegibilidade: bucket de referencia T+1h existe em k_prices.
- Cooldown: rolante first-event-then-skip, 24h, por simbolo+familia.
- Episodio (pooled, por familia): janela de 24h ancorada no primeiro evento
  (anti-chaining, ratificado no CP0); ordenacao deterministica (ts, symbol).
- Retorno forward: ref = open_price do bucket T+1h; alvo = open_price do
  bucket T+1h+h. PROIBIDO ler close_price (parcial — Secao 4 item 8); as
  queries deste modulo selecionam apenas open_price.
- Borda: sem bucket alvo no horizonte -> retorno None (descartado do
  horizonte, sem truncar nem imputar).

Invariantes (testados em tests/test_event_mining_f1.py):
(i) evento em t usa apenas dados <= t (dado threshold fixo; o threshold
    full-window e excecao de lookahead DECLARADA na moldura);
(ii) retorno usa apenas dados > t;
(iii) cooldown sem duplicatas e gap >= 24h por simbolo+familia;
(iv) referencia = open_price de T+1h, close_price nunca e lido;
(v) clusterizacao de episodios reprodutivel (mesma entrada -> mesmos ids).
"""

from __future__ import annotations

import sqlite3

import numpy as np

HOUR = 3600
COOLDOWN = 24 * HOUR
EPISODE_GAP = 24 * HOUR
HORIZONS = (1, 4, 24)
BPS = 10_000.0

# familia -> (fonte logica, modo do gatilho)
FAMILIES = {
    "FUND+": ("fund", "high"),
    "FUND-": ("fund", "low"),
    "BASIS+": ("basis", "high"),
    "BASIS-": ("basis", "low"),
    "LSR-TOP-SQZ": ("lsr_top_delta", "abs"),
    "LSR-GLB-SQZ": ("lsr_glb_delta", "abs"),
    "OI-SHOCK": ("oi_reldelta", "abs"),
}


# ─── primitivas puras ────────────────────────────────────────────────────


def pctl(vals, q: float) -> float:
    return float(np.percentile(np.asarray(vals, dtype=float), q, method="linear"))


def compute_threshold(values, mode: str) -> float:
    if mode == "high":
        return pctl(values, 95)
    if mode == "low":
        return pctl(values, 5)
    if mode == "abs":
        return pctl([abs(v) for v in values], 95)
    raise ValueError(f"modo desconhecido: {mode}")


def detect_events(rows, mode: str, thr: float):
    """Gatilho ESTRITO sobre (ts, valor). So olha o valor do proprio ts —
    nenhum dado posterior participa (invariante i, dado thr fixo)."""
    if mode == "high":
        return [ts for ts, v in rows if v > thr]
    if mode == "low":
        return [ts for ts, v in rows if v < thr]
    if mode == "abs":
        return [ts for ts, v in rows if abs(v) > thr]
    raise ValueError(f"modo desconhecido: {mode}")


def cooldown_filter(ts_sorted):
    """First-event-then-skip 24h. Entrada deve estar ordenada."""
    out, next_ok = [], None
    for t in ts_sorted:
        if next_ok is None or t >= next_ok:
            out.append(t)
            next_ok = t + COOLDOWN
    return out


def deltas(rows, relative: bool = False):
    """Delta 1h exato: (ts, v_t - v_{t-1h}) ou relativo. Buckets sem o
    anterior exato sao descartados (gap -> sem delta)."""
    m = dict(rows)
    out = []
    for ts, v in rows:
        prev = m.get(ts - HOUR)
        if prev is None:
            continue
        if relative:
            if prev == 0:
                continue
            out.append((ts, (v - prev) / prev))
        else:
            out.append((ts, v - prev))
    return out


def assign_episodes(events):
    """events = [(ts, symbol), ...] de UMA familia (pooled).
    Retorna {(ts, symbol): episode_id} com janela de 24h ancorada no primeiro
    evento do episodio. Deterministico: ordena por (ts, symbol)."""
    ordered = sorted(events)
    ids, anchor, ep = {}, None, 0
    for ts, sym in ordered:
        if anchor is None or ts - anchor >= EPISODE_GAP:
            ep += 1
            anchor = ts
        ids[(ts, sym)] = ep
    return ids


def forward_returns(opens: dict, t: int):
    """opens = {bucket_ts: open_price} do simbolo. ref = open(T+1h);
    retorno bps por horizonte ou None na borda. So usa buckets > t (ii)."""
    ref = opens.get(t + HOUR)
    if ref is None or ref <= 0:
        return None, {h: None for h in HORIZONS}
    rets = {}
    for h in HORIZONS:
        target = opens.get(t + HOUR + h * HOUR)
        rets[h] = None if target is None else (target / ref - 1.0) * BPS
    return ref, rets


# ─── carga do banco (somente leituras permitidas pela moldura) ──────────


def load_price_opens(conn: sqlite3.Connection):
    """Apenas bucket_ts e open_price — close_price NUNCA e selecionado (iv)."""
    opens = {}
    for sym, ts, op in conn.execute(
        "SELECT symbol, bucket_ts, open_price FROM k_prices"
    ):
        opens.setdefault(sym, {})[int(ts)] = float(op)
    return opens


def load_sources(conn: sqlite3.Connection):
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

    return {
        "fund": fund,
        "basis": basis,
        "lsr_top_delta": {s: deltas(r) for s, r in lsr_top.items()},
        "lsr_glb_delta": {s: deltas(r) for s, r in lsr_glb.items()},
        "oi_reldelta": {s: deltas(r, relative=True) for s, r in oi.items()},
    }


# ─── build ───────────────────────────────────────────────────────────────


def build_dataset(conn: sqlite3.Connection):
    """Constroi a lista de eventos da grade congelada com retornos forward.

    Retorna (events, meta). Cada evento:
    {family, symbol, event_ts, metric, threshold, ref_ts, ref_price,
     episode, ret_bps: {1: x|None, 4: ..., 24: ...}}
    """
    opens = load_price_opens(conn)
    sources = load_sources(conn)
    symbols = sorted(opens)

    events = []
    thresholds = {}
    for fam, (src_name, mode) in FAMILIES.items():
        series = sources[src_name]
        fam_events = []
        thresholds[fam] = {}
        for sym in symbols:
            rows = series.get(sym, [])
            if not rows:
                thresholds[fam][sym] = None
                continue
            thr = compute_threshold([v for _, v in rows], mode)
            thresholds[fam][sym] = thr
            vals = dict(rows)
            hits = detect_events(rows, mode, thr)
            elig = [t for t in hits if (t + HOUR) in opens[sym]]
            kept = cooldown_filter(sorted(elig))
            # invariante iii: gap >= 24h e sem duplicatas
            assert len(set(kept)) == len(kept), f"duplicatas em {fam}/{sym}"
            assert all(
                b - a >= COOLDOWN for a, b in zip(kept, kept[1:])
            ), f"cooldown violado em {fam}/{sym}"
            for t in kept:
                ref, rets = forward_returns(opens[sym], t)
                assert ref is not None, f"evento sem referencia {fam}/{sym}@{t}"
                fam_events.append(
                    {
                        "family": fam,
                        "symbol": sym,
                        "event_ts": t,
                        "metric": vals[t],
                        "threshold": thr,
                        "ref_ts": t + HOUR,
                        "ref_price": ref,
                        "ret_bps": rets,
                    }
                )
        ep_ids = assign_episodes([(e["event_ts"], e["symbol"]) for e in fam_events])
        for e in fam_events:
            e["episode"] = ep_ids[(e["event_ts"], e["symbol"])]
        events.extend(fam_events)

    events.sort(key=lambda e: (e["family"], e["event_ts"], e["symbol"]))
    meta = {
        "symbols": symbols,
        "thresholds": thresholds,
        "horizons": list(HORIZONS),
        "cooldown_h": COOLDOWN // HOUR,
        "episode_rule": "anchored-24h, ordem (ts, symbol)",
        "trigger": "estrito: > p95 / < p5 / |d| > p95",
        "price_ref": "open_price do bucket T+1h (close_price nunca lido)",
    }
    return events, meta


def cell_counts(events):
    """Contagens por celula (familia x horizonte, pooled): N e N_episodios."""
    out = {}
    for fam in FAMILIES:
        fam_ev = [e for e in events if e["family"] == fam]
        for h in HORIZONS:
            ok = [e for e in fam_ev if e["ret_bps"][h] is not None]
            out[(fam, h)] = {
                "n": len(ok),
                "episodes": len({e["episode"] for e in ok}),
            }
    return out


def write_db(events, meta, db_path):
    """Persiste o dataset em SQLite (research/event_mining/events.db)."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        DROP TABLE IF EXISTS f1_events;
        CREATE TABLE f1_events (
            family      TEXT    NOT NULL,
            symbol      TEXT    NOT NULL,
            event_ts    INTEGER NOT NULL,
            metric      REAL    NOT NULL,
            threshold   REAL    NOT NULL,
            ref_ts      INTEGER NOT NULL,
            ref_price   REAL    NOT NULL,
            episode     INTEGER NOT NULL,
            ret_1h_bps  REAL,
            ret_4h_bps  REAL,
            ret_24h_bps REAL,
            PRIMARY KEY (family, symbol, event_ts)
        );
        DROP TABLE IF EXISTS f1_meta;
        CREATE TABLE f1_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    conn.executemany(
        "INSERT INTO f1_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                e["family"],
                e["symbol"],
                e["event_ts"],
                e["metric"],
                e["threshold"],
                e["ref_ts"],
                e["ref_price"],
                e["episode"],
                e["ret_bps"][1],
                e["ret_bps"][4],
                e["ret_bps"][24],
            )
            for e in events
        ],
    )
    import json

    for k, v in meta.items():
        conn.execute(
            "INSERT INTO f1_meta VALUES (?,?)",
            (k, json.dumps(v, ensure_ascii=False)),
        )
    conn.commit()
    conn.close()
