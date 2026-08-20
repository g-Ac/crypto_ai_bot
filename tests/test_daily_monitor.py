"""Tests for scripts/daily_monitor.py — agregacao NET (liquida de fee).

Garante que o /monitor mostra PnL liquido (taker 0,05/lado = 0,10 round-trip),
nao gross. Cobre o coracao do risco: aplicar o custo POR TRADE antes de agregar
avg/total/PF. Ver project_shadow_max_positions_artifact / project_momentum_fee_net.
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from daily_monitor import (  # noqa: E402
    SHADOW_ROUNDTRIP_FEE_PCT,
    _apply_fee,
    _pf,
    shadow_aggregate,
)


def test_roundtrip_fee_e_taker_dois_lados():
    # 0,05/lado x 2 = 0,10 round-trip. NAO o SINGLE_SIDE_FEE_PCT=0.04 global (desatualizado).
    assert SHADOW_ROUNDTRIP_FEE_PCT == 0.10


def test_apply_fee_subtrai_custo_por_trade():
    # cada outcome perde o round-trip inteiro
    assert _apply_fee([0.5, -0.2, 0.05]) == pytest.approx([0.4, -0.3, -0.05])


def test_apply_fee_aceita_fee_custom():
    assert _apply_fee([1.0], fee=0.10) == pytest.approx([0.9])


def test_shadow_aggregate_total_e_avg_sao_net():
    # gross total = 0.35; com 0,10/trade x3 = 0,30 de custo -> net total = 0.05
    stats = shadow_aggregate([0.5, -0.2, 0.05])
    assert stats["n"] == 3
    assert round(stats["total"], 4) == 0.05
    assert round(stats["avg"], 4) == 0.0167


def test_shadow_aggregate_pf_e_net_nao_gross():
    # gross: wins=0.55 / losses=0.20 -> pf_gross=2.75
    # net:   wins=0.40 / losses=0.35 -> pf_net=1.14
    stats = shadow_aggregate([0.5, -0.2, 0.05])
    assert round(stats["pf"], 2) == 1.14


def test_shadow_aggregate_wr_permanece_gross():
    # 2 de 3 outcomes sao gross-positivos; WR/contagem preservada em gross
    stats = shadow_aggregate([0.5, -0.2, 0.05])
    assert stats["wins"] == 2


def test_shadow_aggregate_edge_fino_vira_negativo_apos_fee():
    # reproduz o achado: avg gross 0.06 < custo 0.10 -> net negativo
    stats = shadow_aggregate([0.06] * 100)
    assert stats["avg"] < 0
    assert round(stats["total"], 2) == -4.0


def test_pf_recebe_serie_ja_liquida():
    # _pf nao subtrai fee sozinho; quem aplica e o caller (via _apply_fee)
    net = _apply_fee([1.0, -0.5])  # [0.9, -0.6]
    assert round(_pf(net), 2) == 1.5
