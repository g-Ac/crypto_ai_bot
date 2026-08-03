"""Invariantes do ETL F1 do EXP-016 Event Mining (research/event_mining/em_lib.py).

Cobre os 5 invariantes da F1 do BRIEFING:
(i)   evento em t usa apenas dados <= t (com threshold fixo; o threshold
      full-window e excecao de lookahead declarada na moldura);
(ii)  retorno usa apenas dados > t;
(iii) cooldown 24h first-event-then-skip, sem duplicatas;
(iv)  preco de referencia = open_price do bucket T+1h; close_price (parcial)
      nunca e lido — plantado como lixo (-999) no mini-DB;
(v)   clusterizacao de episodios reprodutivel e invariante a ordem de entrada.

Mais: gatilho estrito (empate no threshold NAO dispara — decisao CP0) e
reprodutibilidade do build no snapshot real (skip se ausente).
"""

from __future__ import annotations

import random
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "research" / "event_mining"))

import em_lib  # noqa: E402

HOUR = em_lib.HOUR
T0 = 486_000 * HOUR  # base alinhada em hora cheia


# ─── mini-DB sintetico ───────────────────────────────────────────────────


def make_db(path, n_hours=200, shuffle_seed=None):
    """Mini-DB com o schema minimo das tabelas k_* usadas pelo em_lib.
    close_price = -999 em TODAS as linhas (se algum codigo ler close, os
    retornos explodem e os testes quebram). Dados deterministicos."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE k_prices (symbol TEXT, bucket_ts INTEGER, open_price REAL,
            close_price REAL, high_price REAL, low_price REAL, volume REAL,
            collected_at INTEGER, taker_buy_base REAL DEFAULT 0);
        CREATE TABLE k_funding_rates (symbol TEXT, funding_time INTEGER,
            funding_rate REAL, mark_price REAL, collected_at INTEGER);
        CREATE TABLE k_basis (symbol TEXT, bucket_ts INTEGER, basis REAL,
            basis_rate REAL, index_price REAL, futures_price REAL,
            collected_at INTEGER);
        CREATE TABLE k_ratios (symbol TEXT, bucket_ts INTEGER, source TEXT,
            long_short_ratio REAL, long_account REAL, short_account REAL,
            collected_at INTEGER);
        CREATE TABLE k_open_interest (symbol TEXT, bucket_ts INTEGER,
            sum_open_interest REAL, sum_open_interest_value REAL,
            collected_at INTEGER);
        """
    )
    rows_prices, rows_fund, rows_basis, rows_ratios, rows_oi = [], [], [], [], []
    rng = random.Random(7)
    for sym in ("AAA", "BBB"):
        ratio_top, ratio_glb, oi_level = 1.0, 2.0, 1000.0
        for i in range(n_hours):
            ts = T0 + i * HOUR
            open_p = 100.0 + i * 0.1 + (5.0 if sym == "BBB" else 0.0)
            rows_prices.append((sym, ts, open_p, -999.0, -999.0, -999.0, 1.0, 0))
            rows_basis.append((sym, ts, None, 0.0001 * ((i % 11) - 5), None, None, 0))
            ratio_top += rng.uniform(-0.02, 0.02)
            ratio_glb += rng.uniform(-0.02, 0.02)
            if i == 50:  # salto plantado -> evento LSR/OI garantido
                ratio_top += 0.5
                ratio_glb += 0.5
                oi_level *= 1.30
            else:
                oi_level *= 1.0 + rng.uniform(-0.001, 0.001)
            rows_ratios.append((sym, ts, "top_position", ratio_top, None, None, 0))
            rows_ratios.append((sym, ts, "global_account", ratio_glb, None, None, 0))
            rows_oi.append((sym, ts, oi_level, None, 0))
            if i % 8 == 0:
                rate = 0.0001 if i != 96 else 0.0030  # extremo plantado em i=96
                if i == 8:
                    rate = -0.0025  # extremo negativo plantado
                rows_fund.append((sym, ts, rate, None, 0))
    if shuffle_seed is not None:
        sh = random.Random(shuffle_seed)
        for rows in (rows_prices, rows_fund, rows_basis, rows_ratios, rows_oi):
            sh.shuffle(rows)
    conn.executemany(
        "INSERT INTO k_prices (symbol,bucket_ts,open_price,close_price,"
        "high_price,low_price,volume,collected_at) VALUES (?,?,?,?,?,?,?,?)",
        rows_prices,
    )
    conn.executemany("INSERT INTO k_funding_rates VALUES (?,?,?,?,?)", rows_fund)
    conn.executemany("INSERT INTO k_basis VALUES (?,?,?,?,?,?,?)", rows_basis)
    conn.executemany("INSERT INTO k_ratios VALUES (?,?,?,?,?,?,?)", rows_ratios)
    conn.executemany("INSERT INTO k_open_interest VALUES (?,?,?,?,?)", rows_oi)
    conn.commit()
    return conn


# ─── gatilho estrito ─────────────────────────────────────────────────────


def test_strict_trigger_excludes_threshold_value():
    rows = [(T0, 1.0), (T0 + HOUR, 2.0), (T0 + 2 * HOUR, 3.0)]
    assert em_lib.detect_events(rows, "high", 2.0) == [T0 + 2 * HOUR]
    assert em_lib.detect_events(rows, "low", 2.0) == [T0]
    assert em_lib.detect_events([(T0, -2.0), (T0 + HOUR, 2.0)], "abs", 2.0) == []


# ─── invariante (i): sem lookahead na deteccao (threshold fixo) ─────────


def test_i_detection_ignores_future_data():
    t_cut = T0 + 50 * HOUR
    base = [(T0 + i * HOUR, 0.01 * (i % 7)) for i in range(100)]
    past = [r for r in base if r[0] <= t_cut]
    futuro_a = [(ts, v) for ts, v in base if ts > t_cut]
    futuro_b = [(ts, v + 99.0) for ts, v in futuro_a]  # futuro perturbado
    thr = 0.05
    ev_a = em_lib.detect_events(past + futuro_a, "high", thr)
    ev_b = em_lib.detect_events(past + futuro_b, "high", thr)
    assert [t for t in ev_a if t <= t_cut] == [t for t in ev_b if t <= t_cut]


# ─── invariante (ii): retorno so usa buckets > t ─────────────────────────


def test_ii_returns_use_only_future_buckets():
    opens = {T0 + i * HOUR: 100.0 + i for i in range(30)}
    t = T0 + 2 * HOUR
    ref, rets = em_lib.forward_returns(opens, t)
    assert ref == opens[t + HOUR]
    assert rets[1] == pytest.approx((opens[t + 2 * HOUR] / ref - 1) * 1e4)
    assert rets[4] == pytest.approx((opens[t + 5 * HOUR] / ref - 1) * 1e4)
    assert rets[24] == pytest.approx((opens[t + 25 * HOUR] / ref - 1) * 1e4)
    # perturbar passado (inclusive o proprio t) nao muda nada
    opens2 = dict(opens)
    for k in list(opens2):
        if k <= t:
            opens2[k] = 1e9
    ref2, rets2 = em_lib.forward_returns(opens2, t)
    assert (ref2, rets2) == (ref, rets)
    # borda: sem bucket alvo -> None naquele horizonte
    opens3 = {k: v for k, v in opens.items() if k <= t + 5 * HOUR}
    _, rets3 = em_lib.forward_returns(opens3, t)
    assert rets3[1] is not None and rets3[4] is not None and rets3[24] is None


# ─── invariante (iii): cooldown 24h, first-event-then-skip, sem dups ────


def test_iii_cooldown_gap_and_no_duplicates():
    dense = [T0 + i * HOUR for i in range(120)]
    kept = em_lib.cooldown_filter(dense)
    assert kept == [T0, T0 + 24 * HOUR, T0 + 48 * HOUR, T0 + 72 * HOUR, T0 + 96 * HOUR]
    assert all(b - a >= em_lib.COOLDOWN for a, b in zip(kept, kept[1:]))
    assert em_lib.cooldown_filter([T0, T0, T0 + HOUR]) == [T0]  # dup na entrada
    # exatamente 24h depois e elegivel (rolante, nao janela calendario)
    assert em_lib.cooldown_filter([T0, T0 + 24 * HOUR]) == [T0, T0 + 24 * HOUR]


# ─── invariante (iv): referencia = open(T+1h); close nunca lido ─────────


def test_iv_build_uses_open_t_plus_1_and_never_close(tmp_path):
    db = tmp_path / "mini.db"
    conn = make_db(db)
    events, meta = em_lib.build_dataset(conn)
    assert events, "mini-DB deveria gerar eventos"
    opens = em_lib.load_price_opens(conn)
    for e in events:
        assert e["ref_ts"] == e["event_ts"] + HOUR
        assert e["ref_price"] == opens[e["symbol"]][e["ref_ts"]]
        assert e["ref_price"] > 0  # close lixo (-999) jamais vaza
        for h, r in e["ret_bps"].items():
            if r is None:
                continue
            target = opens[e["symbol"]].get(e["ref_ts"] + h * HOUR)
            assert target is not None
            assert r == pytest.approx((target / e["ref_price"] - 1) * 1e4)
    # extremos plantados de funding viram eventos FUND+/FUND-
    fams = {e["family"] for e in events}
    assert "FUND+" in fams and "FUND-" in fams


# ─── invariante (v): episodios reprodutiveis e invariantes a ordem ──────


def test_v_episodes_deterministic_and_order_invariant():
    evs = [
        (T0, "AAA"),
        (T0 + 10 * HOUR, "BBB"),
        (T0 + 23 * HOUR, "AAA"),
        (T0 + 24 * HOUR, "BBB"),
        (T0 + 50 * HOUR, "AAA"),
    ]
    ids = em_lib.assign_episodes(evs)
    # ancora-24h: [0,10,23]=ep1; 24h reabre (>= gap da ancora 0) = ep2; 50h = ep3
    assert ids[(T0, "AAA")] == ids[(T0 + 10 * HOUR, "BBB")] == ids[(T0 + 23 * HOUR, "AAA")]
    assert ids[(T0 + 24 * HOUR, "BBB")] == ids[(T0, "AAA")] + 1
    assert ids[(T0 + 50 * HOUR, "AAA")] == ids[(T0 + 24 * HOUR, "BBB")] + 1
    shuffled = list(evs)
    random.Random(0).shuffle(shuffled)
    assert em_lib.assign_episodes(shuffled) == ids


def test_v_build_reproducible_and_insert_order_invariant(tmp_path):
    conn_a = make_db(tmp_path / "a.db")
    conn_b = make_db(tmp_path / "b.db", shuffle_seed=123)  # mesmas linhas, ordem outra
    ev_a, _ = em_lib.build_dataset(conn_a)
    ev_b, _ = em_lib.build_dataset(conn_b)
    ev_a2, _ = em_lib.build_dataset(conn_a)
    assert ev_a == ev_a2
    assert ev_a == ev_b


# ─── snapshot real: build deterministico (skip se snapshot ausente) ─────

SNAPSHOT = PROJECT_ROOT / "research" / "event_mining" / "source_snapshot.db"


@pytest.mark.skipif(not SNAPSHOT.exists(), reason="snapshot F1 ainda nao criado")
def test_build_on_real_snapshot_reproducible():
    conn = sqlite3.connect(f"file:{SNAPSHOT}?mode=ro", uri=True)
    ev1, meta1 = em_lib.build_dataset(conn)
    ev2, meta2 = em_lib.build_dataset(conn)
    assert ev1 == ev2 and meta1 == meta2
    counts = em_lib.cell_counts(ev1)
    assert len(counts) == 21  # 7 familias x 3 horizontes (pooled)
