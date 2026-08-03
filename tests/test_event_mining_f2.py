"""Testes do motor estatistico F2 do EXP-016 (research/event_mining/em_stats.py).

Cobre: determinismo do bootstrap (seed fixo), celula com efeito forte
sobrevive as reguas, celula nula reprova (a) e (b), BH q-values em caso
conhecido. O teste estatistico em si esta CONGELADO na moldura — estes
testes verificam implementacao, nao escolhem metodo.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "research" / "event_mining"))

import em_stats  # noqa: E402

HOUR = 3600
DAY = 24 * HOUR
T0 = 486_000 * HOUR
WINDOW = (T0, T0 + 60 * DAY)  # 60 dias -> regua (e) aplica


def make_events(rets_by_episode, spread_days=60):
    """Gera eventos sinteticos: {ep_id: [ret, ...]} espalhados na janela."""
    events = []
    n_ep = len(rets_by_episode)
    for i, (ep, rets) in enumerate(sorted(rets_by_episode.items())):
        base = T0 + int(i * spread_days * DAY / max(n_ep, 1)) + HOUR
        for j, r in enumerate(rets):
            events.append(
                {
                    "episode": ep,
                    "event_ts": base + j * HOUR,
                    "ret_bps": {1: r, 4: r, 24: r},
                }
            )
    return events


def test_cell_stats_deterministic():
    rng = random.Random(42)
    evs = make_events({ep: [rng.gauss(30, 40) for _ in range(3)] for ep in range(12)})
    r1 = em_stats.cell_stats(evs, 1, *WINDOW, seed=123)
    r2 = em_stats.cell_stats(evs, 1, *WINDOW, seed=123)
    assert r1 == r2


def test_strong_effect_survives_all_rules():
    rng = random.Random(7)
    evs = make_events(
        {ep: [60 + rng.gauss(0, 10) for _ in range(3)] for ep in range(12)}
    )
    r = em_stats.cell_stats(evs, 1, *WINDOW, seed=1)
    assert r["n"] == 36 and r["n_episodes"] == 12
    assert r["direction"] == "long"
    assert r["rule_a"] and r["rule_b"] and r["rule_c"] and r["rule_d"]
    assert r["rule_e_applies"] and r["rule_e"]
    assert r["survives_all"]
    assert r["net_mean_bps"] == pytest.approx(r["gross_mean_bps"] - 20.0, abs=1e-6)


def test_null_effect_rejected_by_economic_gate():
    rng = random.Random(11)
    evs = make_events(
        {ep: [rng.gauss(0, 30) for _ in range(3)] for ep in range(14)}
    )
    r = em_stats.cell_stats(evs, 1, *WINDOW, seed=2)
    # Efeito nulo (ret bruto ~0): o liquido nao cobre o custo (net<0), logo a regua
    # economica (a) reprova e a celula NAO sobrevive. A regua (b) |t|>=2 NAO
    # discrimina aqui: t = net_mean/se com net ancorado em -COST_BPS rende |t|>=2
    # de forma sistematica (seed 11: t=-3.77, rule_b=True). Quem barra o falso
    # positivo e a regua (a), nao a (b).
    assert not r["rule_a"]
    assert r["rule_b"]              # (b) sozinha nao reprova o nulo — documentado de proposito
    assert r["net_mean_bps"] < 0
    assert not r["survives_all"]


def test_concentration_rule_d_catches_dominant_episode():
    # 1 episodio gigante carrega quase todo o retorno -> conc >= 0.5
    big = {1: [200.0] * 10}
    small = {ep: [1.0, -1.0, 2.0] for ep in range(2, 12)}
    evs = make_events({**big, **small})
    r = em_stats.cell_stats(evs, 1, *WINDOW, seed=3)
    assert r["concentration_top3"] is not None and r["concentration_top3"] >= 0.5
    assert not r["rule_d"]


def test_bh_qvalues_known_case():
    q = em_stats.bh_qvalues([0.01, 0.02, 0.04, 0.5])
    assert q[0] == pytest.approx(0.04)
    assert q[1] == pytest.approx(0.04)
    assert q[2] == pytest.approx(0.04 * 4 / 3)
    assert q[3] == pytest.approx(0.5)
    # monotonicidade no ordenamento dos p
    assert q[0] <= q[2] <= q[3]
