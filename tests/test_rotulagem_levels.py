"""Testes do rotulagem_levels — fundos/topos/suportes automaticos (geometria pura).

Marca o que o olho marcaria com uma caneta: pivos de minima/maxima e niveis
tocados mais de uma vez. Sem indicador, sem opiniao — so geometria dos candles.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import rotulagem_levels


def _c(time, low, high):
    """Candle minimo: so o que importa pra pivo (low/high). open/close no meio."""
    mid = (low + high) / 2
    return {"time": time, "open": mid, "high": high, "low": low, "close": mid}


def test_swing_points_acha_fundo_e_topo():
    # vale (fundo no t=3) seguido de pico (topo no t=5)
    candles = [
        _c(1, low=9, high=11),
        _c(2, low=8, high=10),
        _c(3, low=6, high=9),    # swing low
        _c(4, low=7, high=10),
        _c(5, low=9, high=13),   # swing high
        _c(6, low=10, high=12),
        _c(7, low=9, high=11),
    ]
    pts = rotulagem_levels.swing_points(candles, k=2)
    assert 3 in [p["time"] for p in pts["lows"]]
    assert 5 in [p["time"] for p in pts["highs"]]
    # o fundo carrega o preco do low daquele candle
    fundo = next(p for p in pts["lows"] if p["time"] == 3)
    assert fundo["price"] == 6


def test_support_levels_agrupa_fundos_no_mesmo_nivel():
    candles = [
        _c(1, low=105, high=108),
        _c(2, low=100, high=104),    # fundo ~100
        _c(3, low=104, high=107),
        _c(4, low=100.1, high=103),  # fundo ~100 de novo -> suporte
        _c(5, low=103, high=106),
    ]
    levels = rotulagem_levels.support_levels(candles, k=1, tol=0.005)
    assert any(abs(lv["price"] - 100) < 1 and lv["touches"] >= 2 for lv in levels)


def test_support_levels_fundos_distantes_nao_agrupam():
    candles = [
        _c(1, low=105, high=108),
        _c(2, low=90, high=104),     # fundo isolado em 90
        _c(3, low=104, high=107),
        _c(4, low=100, high=103),    # fundo em 100, longe de 90
        _c(5, low=103, high=106),
    ]
    levels = rotulagem_levels.support_levels(candles, k=1, tol=0.005)
    assert len(levels) == 2
    assert all(lv["touches"] == 1 for lv in levels)
