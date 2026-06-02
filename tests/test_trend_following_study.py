"""Testes do nucleo do EXP-014: trend-following diario (teste final BTC/ETH/SOL).

Pre-compromissos (Gabriel, 2026-06-02): ultima candidata; inconclusivo=NO-GO;
parametros congelados a priori (stop 2*ATR, trailing chandelier 3*ATR, ADX>25).
So testa o nucleo puro (simulador de trailing = o coracao). I/O por run real.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import trend_following_study as ts  # noqa: E402


def _c(rows):
    """rows: list de (high, low, close)."""
    return [{"high": h, "low": low, "close": c} for (h, low, c) in rows]


# ─── simulate_trend_exit: corta rapido quem nao engrena ─────────────────

def test_long_corta_rapido_no_stop_inicial():
    # entry 100, atr 5 -> stop inicial 100-2*5=90. candle cai a low 89 -> stop em 90
    candles = _c([(100, 100, 100), (95, 89, 90)])
    r = ts.simulate_trend_exit(candles, 0, "LONG", 100.0, atr=5.0, adx_after=[30])
    assert r["exit_reason"] == "trail_stop"
    assert r["pnl_pct"] == pytest.approx(-10.0)  # (90-100)/100


# ─── deixa a vencedora correr e sai no trailing (cauda) ─────────────────

def test_long_deixa_correr_e_sai_no_trailing():
    # atr 5, trail 3*5=15. sobe a high 150 (stop sobe p/ 135); depois low 134 -> sai em 135
    candles = _c([(100, 100, 100), (150, 140, 148), (140, 134, 135)])
    r = ts.simulate_trend_exit(candles, 0, "LONG", 100.0, atr=5.0, adx_after=[30, 30])
    assert r["exit_reason"] == "trail_stop"
    assert r["pnl_pct"] == pytest.approx(35.0)  # (135-100)/100


# ─── sai por fim de regime quando ADX cai ───────────────────────────────

def test_sai_por_regime_quando_adx_cai():
    candles = _c([(100, 100, 100), (102, 99, 101), (103, 100, 101)])
    r = ts.simulate_trend_exit(candles, 0, "LONG", 100.0, atr=5.0, adx_after=[30, 20])
    assert r["exit_reason"] == "regime_end"
    assert r["pnl_pct"] == pytest.approx(1.0)  # close 101 da barra onde adx<25


# ─── short e simetrico ──────────────────────────────────────────────────

def test_short_stop_inicial_simetrico():
    # entry 100 short, atr 5 -> stop inicial 110. high 111 -> stop
    candles = _c([(100, 100, 100), (111, 105, 108)])
    r = ts.simulate_trend_exit(candles, 0, "SHORT", 100.0, atr=5.0, adx_after=[30])
    assert r["exit_reason"] == "trail_stop"
    assert r["pnl_pct"] == pytest.approx(-10.0)  # (100-110)/100


def test_stop_nunca_afrouxa_long():
    # trailing e ratchet: uma vez que sobe, nao desce mesmo se o preco recuar sem bater
    candles = _c([(100, 100, 100), (150, 140, 148), (149, 140, 141), (140, 134, 135)])
    r = ts.simulate_trend_exit(candles, 0, "LONG", 100.0, atr=5.0, adx_after=[30, 30, 30])
    # stop fixou em 135 (150-15); barra 3 low 134 <= 135 -> sai em 135
    assert r["pnl_pct"] == pytest.approx(35.0)


# ─── find_entries: 1 trade por estacao de tendencia ─────────────────────

def test_find_entries_inicio_de_cada_estacao():
    labels = ["range", "up", "up", "range", "down", "down"]
    assert ts.find_entries(labels) == [(1, "LONG"), (4, "SHORT")]


def test_find_entries_troca_direcao_sem_range_no_meio():
    labels = ["up", "up", "down"]
    assert ts.find_entries(labels) == [(0, "LONG"), (2, "SHORT")]


# ─── concentracao: quanto do lucro vem dos top-k ────────────────────────

def test_concentration_top2_share():
    # ganhos [10,5,1,1] soma 17; top2 = 15
    assert ts.concentration_top_k([10, 5, 1, 1, -2, -1], 2) == pytest.approx(15 / 17)


def test_concentration_sem_ganhos_e_zero():
    assert ts.concentration_top_k([-1, -2], 2) == 0.0


# ─── buy-and-hold ───────────────────────────────────────────────────────

def test_buy_and_hold_return():
    assert ts.buy_and_hold_return([100, 120, 150]) == pytest.approx(50.0)
