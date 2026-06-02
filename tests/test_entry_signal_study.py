"""Testes do nucleo do estudo de validacao do sinal de entrada do v1.1.

Contexto: analise exploratoria 1a/1b/2/3 (Gabriel, 2026-06-01).
  1a = timing carrega informacao? (Monte Carlo: randomiza so o timestamp)
  1b = direcao carrega informacao? (permuta long/short, mesma composicao)
  2  = bootstrap IC do PF (cruza 1.0?)
  3  = a separacao MAE/MFE win/loss e significante? (permutacao)

So testa o NUCLEO puro. I/O (candles CSV, banco) e coberto por run real,
seguindo o padrao do projeto (cf. test_funding_harvest_study.py).

A logica de SAIDA NAO e reimplementada: simulate_from_entry reusa
check_exit de momentum.research_runner (zero train/serve skew).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import entry_signal_study as ess  # noqa: E402


# ─── profit_factor ──────────────────────────────────────────────────────

def test_profit_factor_basico():
    # ganhos 2+1=3 ; perdas |-1|=1 -> PF 3.0
    assert ess.profit_factor([2.0, 1.0, -1.0]) == pytest.approx(3.0)


def test_profit_factor_sem_perdas_e_infinito():
    assert ess.profit_factor([1.0, 2.0]) == float("inf")


def test_profit_factor_sem_ganhos_e_zero():
    assert ess.profit_factor([-1.0, -2.0]) == 0.0


# ─── make_exit_prices (geometria — o detalhe critico do 1b) ─────────────

def test_make_exit_prices_long_sl_abaixo_tp_acima():
    sl, tp1, tp2 = ess.make_exit_prices(
        100.0, "LONG", sl_dist_pct=1.0, tp1_dist_pct=0.5, tp2_dist_pct=1.5)
    assert sl == pytest.approx(99.0)
    assert tp1 == pytest.approx(100.5)
    assert tp2 == pytest.approx(101.5)


def test_make_exit_prices_short_inverte_os_lados():
    # ESTE e o teste que impede o 1b de virar lixo: short poe SL acima, TP abaixo
    sl, tp1, tp2 = ess.make_exit_prices(
        100.0, "SHORT", sl_dist_pct=1.0, tp1_dist_pct=0.5, tp2_dist_pct=1.5)
    assert sl == pytest.approx(101.0)
    assert tp1 == pytest.approx(99.5)
    assert tp2 == pytest.approx(98.5)


# ─── simulate_from_entry (reusa check_exit) ─────────────────────────────

def _candles(rows):
    """rows: list de (high, low, close)."""
    return [{"high": h, "low": l, "close": c} for (h, l, c) in rows]


def test_simulate_long_bate_tp1():
    # entrada no close=100 do candle 0; candle 1 cruza tp1=100.5
    candles = _candles([(100, 100, 100), (101, 100, 100.8)])
    r = ess.simulate_from_entry(candles, entry_idx=0, direction="LONG",
                                sl=99.0, tp1=100.5, tp2=101.5, timeout_candles=16)
    assert r["exit_reason"] == "tp1_hit"
    assert r["pnl_pct"] == pytest.approx(0.5)


def test_simulate_long_bate_sl():
    candles = _candles([(100, 100, 100), (100, 98.5, 99.0)])
    r = ess.simulate_from_entry(candles, entry_idx=0, direction="LONG",
                                sl=99.0, tp1=100.5, tp2=101.5, timeout_candles=16)
    assert r["exit_reason"] == "sl_hit"
    assert r["pnl_pct"] == pytest.approx(-1.0)


def test_simulate_nao_olha_o_proprio_candle_de_entrada():
    # se o candle de entrada (idx 0) ja tivesse cruzado o TP, seria look-ahead.
    # a saida so pode ser avaliada de idx 1 em diante.
    candles = _candles([(200, 100, 100), (100.1, 99.9, 100.0)])
    r = ess.simulate_from_entry(candles, entry_idx=0, direction="LONG",
                                sl=98.0, tp1=100.5, tp2=101.5, timeout_candles=16)
    assert r["exit_reason"] != "tp1_hit"  # nao usou o high=200 do candle de entrada


def test_simulate_timeout_sai_no_close():
    candles = _candles([(100, 100, 100), (100.1, 99.9, 100.05), (100.1, 99.9, 100.02)])
    r = ess.simulate_from_entry(candles, entry_idx=0, direction="LONG",
                                sl=98.0, tp1=102.0, tp2=103.0, timeout_candles=2)
    assert r["exit_reason"] == "timeout"
    assert r["pnl_pct"] == pytest.approx(0.02)


def test_simulate_sl_tem_prioridade_no_mesmo_candle():
    # candle cruza SL e TP1 juntos -> SL vence (worst-case, identico ao check_exit)
    candles = _candles([(100, 100, 100), (101, 98, 100)])
    r = ess.simulate_from_entry(candles, entry_idx=0, direction="LONG",
                                sl=99.0, tp1=100.5, tp2=101.5, timeout_candles=16)
    assert r["exit_reason"] == "sl_hit"


# ─── apply_cost (fee simetrico — banco e bruto) ─────────────────────────

def test_apply_cost_subtrai_roundtrip():
    # pnl bruto 0.5% menos custo round-trip 0.08% -> 0.42%
    assert ess.apply_cost(0.5, cost_roundtrip_pct=0.08) == pytest.approx(0.42)


def test_apply_cost_zero_nao_altera():
    assert ess.apply_cost(0.5, cost_roundtrip_pct=0.0) == pytest.approx(0.5)


# ─── percentile_of (posiciona o PF real na distribuicao nula — 1a/1b) ───

def test_percentile_of_meio():
    assert ess.percentile_of(2.5, [1.0, 2.0, 3.0, 4.0]) == pytest.approx(50.0)


def test_percentile_of_cauda_direita():
    assert ess.percentile_of(5.0, [1.0, 2.0, 3.0, 4.0]) == pytest.approx(100.0)


def test_percentile_of_cauda_esquerda():
    assert ess.percentile_of(0.5, [1.0, 2.0, 3.0, 4.0]) == pytest.approx(0.0)


# ─── bootstrap_ci (Analise 2) ───────────────────────────────────────────

def test_bootstrap_ci_deterministico_com_seed():
    pnls = [1.0, -1.0, 2.0, -0.5, 0.5, -1.5] * 5
    lo1, hi1 = ess.bootstrap_ci(pnls, n_iter=1000, rng=np.random.default_rng(42))
    lo2, hi2 = ess.bootstrap_ci(pnls, n_iter=1000, rng=np.random.default_rng(42))
    assert lo1 <= hi1
    assert (lo1, hi1) == (lo2, hi2)  # mesma seed -> mesmo resultado


def test_bootstrap_ci_todos_positivos_pf_infinito():
    lo, hi = ess.bootstrap_ci([1.0, 2.0, 3.0], n_iter=100, rng=np.random.default_rng(0))
    assert lo == float("inf")
    assert hi == float("inf")


# ─── permutation_pvalue (Analise 3) ─────────────────────────────────────

def test_permutation_pvalue_separacao_obvia_e_significante():
    a = [1.0, 1.1, 0.9, 1.0, 1.05]      # "vencedores"
    b = [-1.0, -1.1, -0.9, -1.0, -0.95]  # "perdedores"
    p = ess.permutation_pvalue(a, b, n_iter=2000, rng=np.random.default_rng(1))
    assert p < 0.05


def test_permutation_pvalue_sem_separacao_nao_e_significante():
    a = [1.0, -1.0, 0.5, -0.5]
    b = [0.6, -0.6, 0.4, -0.4]
    p = ess.permutation_pvalue(a, b, n_iter=2000, rng=np.random.default_rng(2))
    assert p > 0.05
