"""Modelo de custo (fee) do Momentum paper trading.

Transforma PnL bruto em liquido debitando fee de execucao por lado.
NAO altera a logica de entrada/saida nem os parametros congelados da v1.1 —
apenas mede/debita custo de execucao.

Slippage fica fora deste modelo por enquanto: paper nao tem book/spread real,
entao fingir um numero seria falsa precisao. A coluna de slippage e gravada
como 0 ate existir um sensor real de microestrutura.
"""
from __future__ import annotations

from audit_helpers import calc_total_cost_bps


def compute_trade_costs(
    gross_pnl_pct: float,
    position_size_usd: float,
    entry_fee_rate: float,
    exit_fee_rate: float,
    fee_model: str = "flat",
) -> dict:
    """Calcula gross -> net de um trade fechado.

    Args:
        gross_pnl_pct: PnL bruto em % do notional (vindo do check_exit).
        position_size_usd: Notional da posicao (o mesmo usado no sizing v1.1).
        entry_fee_rate: Taxa de entrada em % por lado (ex: 0.04 = 0.04%).
        exit_fee_rate: Taxa de saida em % por lado.
        fee_model: Rotulo do modelo de custo, para rastreabilidade.

    Returns:
        dict com gross/fee/net em USD, % e bps. A fee incide sobre o notional
        de entrada nos dois lados — aproximacao conservadora e simples; a
        diferenca de notional na saida e de 2a ordem e foi deixada de fora.
    """
    gross_pnl_usd = position_size_usd * gross_pnl_pct / 100.0
    fee_entry_usd = position_size_usd * entry_fee_rate / 100.0
    fee_exit_usd = position_size_usd * exit_fee_rate / 100.0
    total_fee_usd = fee_entry_usd + fee_exit_usd

    net_pnl_usd = gross_pnl_usd - total_fee_usd
    net_pnl_pct = gross_pnl_pct - (entry_fee_rate + exit_fee_rate)

    fee_entry_bps = entry_fee_rate * 100.0
    fee_exit_bps = exit_fee_rate * 100.0
    total_cost_bps = calc_total_cost_bps(fee_entry_bps, fee_exit_bps)

    return {
        "gross_pnl_pct": round(gross_pnl_pct, 4),
        "gross_pnl_usd": round(gross_pnl_usd, 2),
        "entry_fee_rate": entry_fee_rate,
        "exit_fee_rate": exit_fee_rate,
        "fee_entry_usd": round(fee_entry_usd, 4),
        "fee_exit_usd": round(fee_exit_usd, 4),
        "fee_entry_bps": round(fee_entry_bps, 2),
        "fee_exit_bps": round(fee_exit_bps, 2),
        "total_fee_usd": round(total_fee_usd, 4),
        "total_cost_bps": total_cost_bps,
        "net_pnl_pct": round(net_pnl_pct, 4),
        "net_pnl_usd": round(net_pnl_usd, 2),
        "fee_model": fee_model,
    }
