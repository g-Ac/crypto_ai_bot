"""Compare baseline v1.1 (matrix_v1_90d.db) vs BE50 variant (matrix_v1_90d_be50.db).

Outputs head-to-head report: WR, PF, exits, timeout savings.
Usage: python scripts/compare_be50.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE = PROJECT_ROOT / "research" / "matrix_v1_90d.db"
VARIANT = PROJECT_ROOT / "research" / "matrix_v1_90d_be50.db"


def stats(db: Path) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT exit_reason, pnl_pct, mfe_pct, mae_pct, duration_candles "
        "FROM momentum_trades WHERE exit_reason IS NOT NULL"
    ).fetchall()
    conn.close()

    total = len(rows)
    wins = [r for r in rows if r["pnl_pct"] > 0]
    losses = [r for r in rows if r["pnl_pct"] <= 0]

    by_reason: dict = {}
    for r in rows:
        by_reason.setdefault(r["exit_reason"], []).append(r)

    gross_win = sum(r["pnl_pct"] for r in wins) * 100
    gross_loss = abs(sum(r["pnl_pct"] for r in losses)) * 100
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "wr": (len(wins) / total * 100) if total else 0,
        "avg_win_pct": (sum(r["pnl_pct"] for r in wins) / len(wins) * 100) if wins else 0,
        "avg_loss_pct": (sum(r["pnl_pct"] for r in losses) / len(losses) * 100) if losses else 0,
        "sum_pnl_pct": sum(r["pnl_pct"] for r in rows) * 100,
        "pf": pf,
        "by_reason": {k: {
            "n": len(v),
            "avg_pnl": sum(r["pnl_pct"] for r in v) / len(v) * 100 if v else 0,
            "sum_pnl": sum(r["pnl_pct"] for r in v) * 100,
        } for k, v in by_reason.items()},
    }


def fmt_reason(reason: str, d: dict) -> str:
    return f"{reason:<14} n={d['n']:>3}  avg={d['avg_pnl']:+.3f}%  sum={d['sum_pnl']:+.2f}%"


def main():
    if not BASELINE.exists():
        print(f"ERROR: baseline not found at {BASELINE}")
        sys.exit(1)
    if not VARIANT.exists():
        print(f"ERROR: variant not found at {VARIANT}")
        sys.exit(1)

    b = stats(BASELINE)
    v = stats(VARIANT)

    print("=" * 70)
    print("  BASELINE v1.1 (BE disabled)   vs   VARIANT v1.1 + BE50")
    print("=" * 70)
    print()
    print(f"{'Metric':<22} {'Baseline':>14} {'BE50':>14} {'Delta':>14}")
    print("-" * 70)

    def row(label, bv, vv, fmt="{:.2f}"):
        delta = vv - bv
        sign = "+" if delta >= 0 else ""
        print(f"{label:<22} {fmt.format(bv):>14} {fmt.format(vv):>14} "
              f"{sign}{fmt.format(delta):>13}")

    row("Total trades", b["total"], v["total"], "{:.0f}")
    row("Wins", b["wins"], v["wins"], "{:.0f}")
    row("Losses", b["losses"], v["losses"], "{:.0f}")
    row("Win rate %", b["wr"], v["wr"])
    row("Avg win %", b["avg_win_pct"], v["avg_win_pct"], "{:.3f}")
    row("Avg loss %", b["avg_loss_pct"], v["avg_loss_pct"], "{:.3f}")
    row("Sum PnL %", b["sum_pnl_pct"], v["sum_pnl_pct"])
    row("Profit factor", b["pf"], v["pf"], "{:.3f}")
    print()

    all_reasons = set(b["by_reason"]) | set(v["by_reason"])
    print("EXITS BY REASON")
    print("-" * 70)
    for r in sorted(all_reasons):
        bd = b["by_reason"].get(r, {"n": 0, "avg_pnl": 0, "sum_pnl": 0})
        vd = v["by_reason"].get(r, {"n": 0, "avg_pnl": 0, "sum_pnl": 0})
        print(f"  BASELINE  {fmt_reason(r, bd)}")
        print(f"  BE50      {fmt_reason(r, vd)}")
        print()

    # BE50-specific: "breakeven" exit_reason only exists in variant
    be_exits = v["by_reason"].get("breakeven", {"n": 0})
    baseline_timeouts = b["by_reason"].get("timeout", {"n": 0, "sum_pnl": 0})
    variant_timeouts = v["by_reason"].get("timeout", {"n": 0, "sum_pnl": 0})
    timeout_delta_n = variant_timeouts["n"] - baseline_timeouts["n"]
    timeout_delta_pnl = variant_timeouts["sum_pnl"] - baseline_timeouts["sum_pnl"]

    print("BE50 IMPACT")
    print("-" * 70)
    print(f"  Breakeven exits (variant only): {be_exits['n']}")
    print(f"  Timeout count delta:   {timeout_delta_n:+d}  "
          f"(baseline={baseline_timeouts['n']}, variant={variant_timeouts['n']})")
    print(f"  Timeout sum PnL delta: {timeout_delta_pnl:+.2f}%  "
          f"(baseline={baseline_timeouts['sum_pnl']:+.2f}%, "
          f"variant={variant_timeouts['sum_pnl']:+.2f}%)")
    print()


if __name__ == "__main__":
    main()
