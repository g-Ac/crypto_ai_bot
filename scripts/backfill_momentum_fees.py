"""Backfill de custo (fee) nos trades historicos do momentum_trades.

Trades fechados ANTES da medicao de fee (commit 35fc717) tem net/fee = NULL.
Este script preenche gross/fee/net retroativamente usando o MESMO helper dos
trades novos (momentum.fees.compute_trade_costs) e a MESMA taxa configurada
(MOMENTUM_PAPER_*_FEE_RATE, default taker real 0.05/lado). gross_pnl_usd e
preservado igual ao pnl_usd legado; net = gross - fee.

So toca linhas com net_pnl_usd IS NULL => idempotente: rodar 2x nao muda nada
depois da 1a vez, e nunca sobrescreve trades medidos nativamente. Marca
fee_model='flat_taker_backfill' para distinguir do net medido em tempo real.

Uso:
    python scripts/backfill_momentum_fees.py            # dry-run (nao escreve)
    python scripts/backfill_momentum_fees.py --apply    # aplica o UPDATE
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime_config import DB_FILE
from config import MOMENTUM_PAPER_ENTRY_FEE_RATE, MOMENTUM_PAPER_EXIT_FEE_RATE
from momentum.fees import compute_trade_costs

FEE_MODEL_BACKFILL = "flat_taker_backfill"


def backfill(db_path: str, apply: bool) -> dict:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, pnl_pct, pnl_usd, position_size_usd "
        "FROM momentum_trades WHERE net_pnl_usd IS NULL ORDER BY id"
    ).fetchall()

    n = 0
    sum_gross = sum_fee = sum_net = 0.0
    for r in rows:
        size = r["position_size_usd"] or 0.0
        gross_pct = r["pnl_pct"] if r["pnl_pct"] is not None else 0.0
        costs = compute_trade_costs(
            gross_pnl_pct=gross_pct,
            position_size_usd=size,
            entry_fee_rate=MOMENTUM_PAPER_ENTRY_FEE_RATE,
            exit_fee_rate=MOMENTUM_PAPER_EXIT_FEE_RATE,
            fee_model=FEE_MODEL_BACKFILL,
        )
        # Preserva o gross legado (pnl_usd realmente registrado); net = gross - fee.
        gross_usd = r["pnl_usd"] if r["pnl_usd"] is not None else costs["gross_pnl_usd"]
        net_usd = round(gross_usd - costs["total_fee_usd"], 2)

        if apply:
            conn.execute(
                "UPDATE momentum_trades SET "
                "gross_pnl_pct=?, gross_pnl_usd=?, entry_fee_rate=?, exit_fee_rate=?, "
                "fee_entry_usd=?, fee_exit_usd=?, fee_entry_bps=?, fee_exit_bps=?, "
                "total_fee_usd=?, total_cost_bps=?, net_pnl_pct=?, net_pnl_usd=?, "
                "fee_model=?, entry_liquidity_assumption=?, exit_liquidity_assumption=? "
                "WHERE id=?",
                (gross_pct, gross_usd, costs["entry_fee_rate"], costs["exit_fee_rate"],
                 costs["fee_entry_usd"], costs["fee_exit_usd"], costs["fee_entry_bps"],
                 costs["fee_exit_bps"], costs["total_fee_usd"], costs["total_cost_bps"],
                 costs["net_pnl_pct"], net_usd, FEE_MODEL_BACKFILL, "taker", "taker",
                 r["id"]),
            )
        n += 1
        sum_gross += gross_usd
        sum_fee += costs["total_fee_usd"]
        sum_net += net_usd

    if apply:
        conn.commit()
    conn.close()
    return {"n": n, "gross": round(sum_gross, 2), "fee": round(sum_fee, 2),
            "net": round(sum_net, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="aplica o UPDATE (default: dry-run)")
    ap.add_argument("--db", default=DB_FILE, help="caminho do bot.db (default: runtime atual)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] db={args.db}")
    print(f"taxa: entry={MOMENTUM_PAPER_ENTRY_FEE_RATE}% exit={MOMENTUM_PAPER_EXIT_FEE_RATE}% "
          f"(round-trip {MOMENTUM_PAPER_ENTRY_FEE_RATE + MOMENTUM_PAPER_EXIT_FEE_RATE}%)")
    res = backfill(args.db, args.apply)
    print(f"trades sem net (alvo): {res['n']}")
    print(f"  SUM gross: ${res['gross']:+.2f}")
    print(f"  SUM fee:   ${res['fee']:.2f}")
    print(f"  SUM net:   ${res['net']:+.2f}")
    if not args.apply:
        print("\n(dry-run — nada gravado. Rode com --apply para aplicar.)")


if __name__ == "__main__":
    main()
