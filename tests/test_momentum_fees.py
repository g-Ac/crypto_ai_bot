"""Testes do modelo de custo (fee) do Momentum paper trading.

Mede gross -> net por trade fechado. NAO altera a logica de entrada/saida
nem os parametros congelados da v1.1 — apenas debita custo de execucao.
"""
import pytest

from momentum.fees import compute_trade_costs


def test_long_lucrativo_debita_fee_dos_dois_lados():
    r = compute_trade_costs(
        gross_pnl_pct=1.0, position_size_usd=1000.0,
        entry_fee_rate=0.04, exit_fee_rate=0.04,
    )
    assert r["gross_pnl_usd"] == pytest.approx(10.0)
    assert r["fee_entry_usd"] == pytest.approx(0.4)
    assert r["fee_exit_usd"] == pytest.approx(0.4)
    assert r["total_fee_usd"] == pytest.approx(0.8)
    assert r["net_pnl_usd"] == pytest.approx(9.2)
    assert r["net_pnl_pct"] == pytest.approx(0.92)


def test_breakeven_quando_gross_igual_ao_round_trip_fee():
    # 0.08% gross = exatamente 0.04 + 0.04 round-trip -> net zero.
    # Este e o ponto onde a fee come todo o edge bruto.
    r = compute_trade_costs(
        gross_pnl_pct=0.08, position_size_usd=1000.0,
        entry_fee_rate=0.04, exit_fee_rate=0.04,
    )
    assert r["net_pnl_usd"] == pytest.approx(0.0, abs=1e-9)
    assert r["net_pnl_pct"] == pytest.approx(0.0, abs=1e-9)


def test_perdedor_fica_mais_perdedor_com_fee():
    r = compute_trade_costs(
        gross_pnl_pct=-0.5, position_size_usd=1000.0,
        entry_fee_rate=0.04, exit_fee_rate=0.04,
    )
    assert r["gross_pnl_usd"] == pytest.approx(-5.0)
    assert r["net_pnl_usd"] == pytest.approx(-5.8)
    assert r["net_pnl_pct"] == pytest.approx(-0.58)


def test_fee_em_bps_reusa_helper_de_custo():
    r = compute_trade_costs(
        gross_pnl_pct=1.0, position_size_usd=1000.0,
        entry_fee_rate=0.04, exit_fee_rate=0.04,
    )
    assert r["fee_entry_bps"] == pytest.approx(4.0)
    assert r["fee_exit_bps"] == pytest.approx(4.0)
    assert r["total_cost_bps"] == pytest.approx(8.0)


def test_liquidity_assimetrica_maker_entry_taker_exit():
    # Estrutura pronta pra comparar maker-only vs taker no futuro.
    r = compute_trade_costs(
        gross_pnl_pct=1.0, position_size_usd=1000.0,
        entry_fee_rate=0.02, exit_fee_rate=0.05,
    )
    assert r["net_pnl_pct"] == pytest.approx(0.93)  # 1.0 - (0.02 + 0.05)
    assert r["total_fee_usd"] == pytest.approx(0.7)


def test_fee_model_label_preservado():
    r = compute_trade_costs(
        gross_pnl_pct=1.0, position_size_usd=1000.0,
        entry_fee_rate=0.04, exit_fee_rate=0.04,
        fee_model="flat_taker_v1",
    )
    assert r["fee_model"] == "flat_taker_v1"


def test_size_zero_nao_quebra():
    r = compute_trade_costs(
        gross_pnl_pct=1.0, position_size_usd=0.0,
        entry_fee_rate=0.04, exit_fee_rate=0.04,
    )
    assert r["gross_pnl_usd"] == 0.0
    assert r["total_fee_usd"] == 0.0
    assert r["net_pnl_usd"] == 0.0
