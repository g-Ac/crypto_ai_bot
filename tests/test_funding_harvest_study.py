"""Testes do nucleo aritmetico do estudo de funding harvest.

Pre-registro: docs/pre_registros/PREREG_funding_harvest.md
So testa a matematica (breakeven, episodios, P&L, anualizacao) — I/O do banco
nao e testado (segue o padrao do projeto: cálculo testado, I/O coberto por run real).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import funding_harvest_study as fh  # noqa: E402


# ─── breakeven_threshold ────────────────────────────────────────────────

def test_breakeven_threshold():
    # T = custo_round_trip / holding_periods. c=0.003, H=90.
    assert fh.breakeven_threshold(0.003, 90) == pytest.approx(0.003 / 90)


# ─── find_episodes (agrupa periodos contiguos >= T) ─────────────────────

def test_find_episodes_agrupa_contiguos():
    series = [0.0005, 0.002, 0.0015, 0.0, 0.003]
    eps = fh.find_episodes(series, threshold=0.001)
    assert len(eps) == 2
    assert eps[0] == pytest.approx([0.002, 0.0015])
    assert eps[1] == pytest.approx([0.003])


def test_find_episodes_vazio_quando_nada_acima():
    eps = fh.find_episodes([0.0001, -0.001, 0.0], threshold=0.001)
    assert eps == []


def test_find_episodes_episodio_unico_cobrindo_tudo():
    eps = fh.find_episodes([0.002, 0.003, 0.0025], threshold=0.001)
    assert len(eps) == 1
    assert len(eps[0]) == 3


# ─── episode_pnl ────────────────────────────────────────────────────────

def test_episode_pnl_receita_menos_custo():
    # 3x 0.002 = 0.006 de funding; custo 0.003 -> liquido 0.003
    assert fh.episode_pnl([0.002, 0.002, 0.002], cost_round_trip=0.003) == pytest.approx(0.003)


def test_episode_pnl_negativo_se_custo_supera_funding():
    assert fh.episode_pnl([0.0005], cost_round_trip=0.003) == pytest.approx(0.0005 - 0.003)


# ─── harvest_reactive (cenario B) ───────────────────────────────────────

def test_harvest_reactive_soma_episodios_e_custos():
    # T=0.001, custo=0.003. Episodios: [0.002,0.0015]=0.0035 e [0.003]=0.003
    # gross=0.0065; custo=2*0.003=0.006; net=0.0005
    series = [0.0005, 0.002, 0.0015, 0.0, 0.003]
    r = fh.harvest_reactive(series, threshold=0.001, cost_round_trip=0.003)
    assert r["n_episodes"] == 2
    assert r["gross_funding"] == pytest.approx(0.0065)
    assert r["total_cost"] == pytest.approx(0.006)
    assert r["net"] == pytest.approx(0.0005)
    assert r["periods_in_market"] == 3


# ─── harvest_passive (cenario A) ────────────────────────────────────────

def test_harvest_passive_soma_tudo_um_round_trip():
    # passivo: soma todo funding (inclui negativo), 1 round-trip de custo
    r = fh.harvest_passive([0.002, -0.001, 0.003], cost_round_trip=0.003)
    assert r["gross_funding"] == pytest.approx(0.004)
    assert r["total_cost"] == pytest.approx(0.003)
    assert r["net"] == pytest.approx(0.001)


def test_harvest_passive_serie_vazia():
    r = fh.harvest_passive([], cost_round_trip=0.003)
    assert r["gross_funding"] == 0.0
    assert r["net"] == 0.0


# ─── annualize ──────────────────────────────────────────────────────────

def test_annualize_8h_periods():
    # 1095 = 3 periodos/dia * 365 dias
    assert fh.annualize(0.01, n_periods_8h=90) == pytest.approx(0.01 * 1095 / 90)


def test_annualize_zero_periods_nao_quebra():
    assert fh.annualize(0.0, n_periods_8h=0) == 0.0
