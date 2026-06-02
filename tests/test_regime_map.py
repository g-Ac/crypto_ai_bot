"""Testes do nucleo do mapa de regimes/timeframes (caracterizacao descritiva).

Job 2026-06-01: foundation pra desenhar estrategia de swing/estrutura.
100% descritivo - sem P&L, sem edge, sem GO/NO-GO. So testa o nucleo puro
(resample, classificadores, duracoes, transicoes, estacoes de funding).
I/O (download, ADX via ta) coberto por run real.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import regime_map as rm  # noqa: E402


# ─── resample_ohlc ──────────────────────────────────────────────────────

def test_resample_ohlc_agrega_4_barras():
    rows = [
        {"open": 10, "high": 12, "low": 9, "close": 11},
        {"open": 11, "high": 13, "low": 10, "close": 12},
        {"open": 12, "high": 15, "low": 11, "close": 14},
        {"open": 14, "high": 14, "low": 8, "close": 9},
    ]
    out = rm.resample_ohlc(rows, 4)
    assert len(out) == 1
    assert (out[0]["open"], out[0]["high"], out[0]["low"], out[0]["close"]) == (10, 15, 8, 9)


def test_resample_ohlc_descarta_barra_incompleta():
    rows = [{"open": i, "high": i, "low": i, "close": i} for i in range(10)]
    assert len(rm.resample_ohlc(rows, 4)) == 2  # 10//4, descarta as 2 sobrando


# ─── realized_vol ───────────────────────────────────────────────────────

def test_realized_vol_constante_e_zero():
    v = rm.realized_vol([100, 100, 100, 100, 100], window=2)
    assert v[-1] == pytest.approx(0.0)


def test_realized_vol_positiva_quando_oscila():
    v = rm.realized_vol([100, 110, 100, 110, 100], window=3)
    assert v[-1] > 0


# ─── classify_trend ─────────────────────────────────────────────────────

def test_classify_trend_range_quando_adx_baixo():
    assert rm.classify_trend(adx=15, di_plus=30, di_minus=10, threshold=25) == "range"


def test_classify_trend_up_quando_di_plus_domina():
    assert rm.classify_trend(adx=35, di_plus=30, di_minus=10, threshold=25) == "up"


def test_classify_trend_down_quando_di_minus_domina():
    assert rm.classify_trend(adx=35, di_plus=10, di_minus=30, threshold=25) == "down"


# ─── classify_vol ───────────────────────────────────────────────────────

def test_classify_vol_high_e_low():
    assert rm.classify_vol(0.02, 0.01) == "high"
    assert rm.classify_vol(0.005, 0.01) == "low"


# ─── run_lengths ────────────────────────────────────────────────────────

def test_run_lengths_agrupa_consecutivos():
    assert rm.run_lengths(["a", "a", "b", "a", "a", "a"]) == [("a", 2), ("b", 1), ("a", 3)]


def test_run_lengths_vazio():
    assert rm.run_lengths([]) == []


# ─── transition_matrix ──────────────────────────────────────────────────

def test_transition_matrix_normaliza_por_origem():
    # a->a, a->b, b->a : de 'a' saem 2 (0.5/0.5); de 'b' sai 1 (1.0 pra a)
    m = rm.transition_matrix(["a", "a", "b", "a"])
    assert m["a"]["a"] == pytest.approx(0.5)
    assert m["a"]["b"] == pytest.approx(0.5)
    assert m["b"]["a"] == pytest.approx(1.0)


# ─── funding_seasons ────────────────────────────────────────────────────

def test_funding_seasons_identifica_gordo_e_negativo():
    funding = [0.0, 0.04, 0.05, 0.0, -0.02, -0.03, 0.0]
    seasons = rm.funding_seasons(funding, hi_thresh=0.03, neg_thresh=-0.01)
    assert ("gordo", 2) in seasons
    assert ("negativo", 2) in seasons


# ─── pct_summary ────────────────────────────────────────────────────────

def test_pct_summary_mediana_e_p90():
    s = rm.pct_summary([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert s["median"] == pytest.approx(5.5)
    assert s["p90"] == pytest.approx(9.1)
