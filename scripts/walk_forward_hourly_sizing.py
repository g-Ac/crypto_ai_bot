"""Walk-forward hourly sizing validation — 3 folds, expanding window.

Hypothesis: modulating position size by hour-of-day (based on historical PF
per hour) improves risk-adjusted return out-of-sample.

Procedure:
  Fit:  derive step-function multipliers from training trades
        (0.5 if PF < 0.8, 1.5 if PF > 1.5, else 1.0; min_n=10)
  Score: apply multipliers to test-set PnL, compare to unweighted.

Folds (expanding window, by trade ordinal — not date):
  Fold 1: train trades[0:50%],  test trades[50:67%]
  Fold 2: train trades[0:67%],  test trades[67:83%]
  Fold 3: train trades[0:83%],  test trades[83:100%]

Verdict:
  PASS      if 3/3 folds show delta > +5%
  AMBIGUOUS if 2/3
  FAIL      otherwise (or multiplier instability across folds)

Read-only. Does not modify any DB.
"""
from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

DB = Path("/home/pi/crypto_ai_bot/research/matrix_v1_90d.db")

SQL = """
SELECT
    t.id AS trade_id,
    t.pnl_pct,
    t.exit_reason,
    d.timestamp,
    d.symbol,
    d.regime,
    d.session_bucket,
    d.direction
FROM momentum_trades t
JOIN momentum_decisions d ON d.id = t.decision_id
WHERE t.exit_reason IS NOT NULL
ORDER BY d.timestamp
"""

MIN_N_PER_HOUR = 10
PF_LOW_THRESHOLD = 0.8
PF_HIGH_THRESHOLD = 1.5
MULT_NEUTRAL = 1.0
DELTA_PASS_PCT = 5.0


def _parse_args() -> tuple[float, float]:
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mult-low", type=float, default=0.5,
                        help="Multiplier for hours with PF < PF_LOW_THRESHOLD")
    parser.add_argument("--mult-high", type=float, default=1.5,
                        help="Multiplier for hours with PF > PF_HIGH_THRESHOLD")
    args, _ = parser.parse_known_args()
    return args.mult_low, args.mult_high


MULT_LOW, MULT_HIGH = _parse_args()


@dataclass
class Trade:
    hour: int
    pnl_pct: float
    timestamp: str


def load_trades() -> List[Trade]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(SQL).fetchall()
    conn.close()
    trades: List[Trade] = []
    for r in rows:
        ts = r["timestamp"]
        try:
            hour = int(ts[11:13])
        except (ValueError, IndexError):
            hour = 0
        trades.append(Trade(hour=hour, pnl_pct=r["pnl_pct"], timestamp=ts))
    return trades


def profit_factor(trades: List[Trade]) -> float:
    wins = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
    losses = abs(sum(t.pnl_pct for t in trades if t.pnl_pct <= 0))
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def sum_bps(trades: List[Trade]) -> float:
    return sum(t.pnl_pct for t in trades) * 100.0


def multipliers_from_train(train: List[Trade]) -> Dict[int, float]:
    by_hour: Dict[int, List[Trade]] = {}
    for t in train:
        by_hour.setdefault(t.hour, []).append(t)
    mult: Dict[int, float] = {}
    for h in range(24):
        g = by_hour.get(h, [])
        if len(g) < MIN_N_PER_HOUR:
            mult[h] = MULT_NEUTRAL
            continue
        pf = profit_factor(g)
        if pf < PF_LOW_THRESHOLD:
            mult[h] = MULT_LOW
        elif pf > PF_HIGH_THRESHOLD:
            mult[h] = MULT_HIGH
        else:
            mult[h] = MULT_NEUTRAL
    return mult


def score(test: List[Trade], mult: Dict[int, float]) -> tuple[float, float]:
    base = sum_bps(test)
    adj = sum(t.pnl_pct * mult.get(t.hour, 1.0) for t in test) * 100.0
    return base, adj


def fold_indices(n: int) -> list[tuple[int, int, int]]:
    """Return list of (train_end, test_start, test_end) for 3 folds."""
    return [
        (n // 2,     n // 2,     (n * 2) // 3),
        ((n * 2) // 3, (n * 2) // 3, (n * 5) // 6),
        ((n * 5) // 6, (n * 5) // 6, n),
    ]


def _format_mult(m: float) -> str:
    if abs(m - MULT_LOW) < 1e-9:
        return f"{m:.2f}↓"
    if abs(m - MULT_HIGH) < 1e-9:
        return f"{m:.2f}↑"
    return f"{m:.2f} "


def main():
    trades = load_trades()
    n = len(trades)
    print(f"Total trades: {n}")
    print(f"Date range:   {trades[0].timestamp[:10]} to "
          f"{trades[-1].timestamp[:10]}")
    print(f"Multipliers:  low={MULT_LOW} (for PF<{PF_LOW_THRESHOLD}), "
          f"high={MULT_HIGH} (for PF>{PF_HIGH_THRESHOLD}), "
          f"min_n={MIN_N_PER_HOUR}")
    print()

    folds = fold_indices(n)
    fold_results = []
    all_mults: List[Dict[int, float]] = []

    for i, (tr_end, te_start, te_end) in enumerate(folds, 1):
        train = trades[:tr_end]
        test = trades[te_start:te_end]

        mult = multipliers_from_train(train)
        all_mults.append(mult)
        base, adj = score(test, mult)
        delta_bps = adj - base
        delta_pct = (delta_bps / base * 100.0) if base != 0 else 0.0

        fold_results.append({
            "i": i,
            "train_range": (0, tr_end),
            "test_range": (te_start, te_end),
            "n_train": len(train),
            "n_test": len(test),
            "test_date_start": test[0].timestamp[:10] if test else "",
            "test_date_end": test[-1].timestamp[:10] if test else "",
            "base_bps": base,
            "adj_bps": adj,
            "delta_bps": delta_bps,
            "delta_pct": delta_pct,
            "pf_base": profit_factor(test),
            "pf_adj_est": _pf_with_mult(test, mult),
            "mult": mult,
        })

    print("=" * 80)
    print("  FOLDS")
    print("=" * 80)
    header = f"{'fold':>4} {'train_n':>8} {'test_n':>7} {'test_dates':<22} " \
             f"{'base_bps':>10} {'adj_bps':>10} {'Δ bps':>9} {'Δ %':>7} " \
             f"{'pf_base':>8} {'pf_adj':>8}"
    print(header)
    print("-" * 80)
    for r in fold_results:
        dates = f"{r['test_date_start']}→{r['test_date_end']}"
        print(f"{r['i']:>4} {r['n_train']:>8} {r['n_test']:>7} {dates:<22} "
              f"{r['base_bps']:>+10.2f} {r['adj_bps']:>+10.2f} "
              f"{r['delta_bps']:>+9.2f} {r['delta_pct']:>+6.1f}% "
              f"{r['pf_base']:>8.2f} {r['pf_adj_est']:>8.2f}")

    print()
    print("=" * 80)
    print("  MULTIPLIER STABILITY (hour × fold)")
    print("=" * 80)
    print(f"{'hour':>4}  {'F1':>5} {'F2':>5} {'F3':>5}   {'flag'}")
    print("-" * 80)
    flips = 0
    active_hours = 0
    for h in range(24):
        m1 = all_mults[0].get(h, 1.0)
        m2 = all_mults[1].get(h, 1.0)
        m3 = all_mults[2].get(h, 1.0)
        vals = [m1, m2, m3]
        has_up = any(v == MULT_HIGH for v in vals)
        has_down = any(v == MULT_LOW for v in vals)
        if has_up and has_down:
            flag = "FLIP ⚠"
            flips += 1
        elif all(v == MULT_NEUTRAL for v in vals):
            flag = "—"
        elif len(set(vals)) == 1:
            flag = "STABLE"
            active_hours += 1
        else:
            flag = "partial"
            active_hours += 1
        print(f"{h:>4}  {_format_mult(m1):>5} {_format_mult(m2):>5} "
              f"{_format_mult(m3):>5}   {flag}")

    print()
    print("=" * 80)
    print("  VERDICT")
    print("=" * 80)
    passing = sum(1 for r in fold_results if r["delta_pct"] >= DELTA_PASS_PCT)
    degrading = sum(1 for r in fold_results if r["delta_pct"] <= -DELTA_PASS_PCT)

    print(f"  Folds com Δ ≥ +{DELTA_PASS_PCT:.0f}%: {passing}/3")
    print(f"  Folds com Δ ≤ -{DELTA_PASS_PCT:.0f}%: {degrading}/3")
    print(f"  Horas com flip de multiplicador entre folds: {flips}")
    print()

    if passing == 3 and flips == 0:
        verdict = "PASS — sizing horário carrega edge real"
    elif passing >= 2 and flips <= 2:
        verdict = "AMBÍGUO — continua research, não implementa"
    elif degrading >= 2 or flips >= 4:
        verdict = "FAIL — sizing horário é ruído ou instável"
    else:
        verdict = "INCONCLUSIVO — pode ser amostra pequena"

    print(f"  → {verdict}")
    print()

    sum_base = sum(r["base_bps"] for r in fold_results)
    sum_adj = sum(r["adj_bps"] for r in fold_results)
    print(f"  Oos agregado:  base={sum_base:+.2f} bps   adj={sum_adj:+.2f} bps"
          f"   Δ={sum_adj - sum_base:+.2f} bps")


def _pf_with_mult(trades: List[Trade], mult: Dict[int, float]) -> float:
    wins = sum(t.pnl_pct * mult.get(t.hour, 1.0)
               for t in trades if t.pnl_pct > 0)
    losses = abs(sum(t.pnl_pct * mult.get(t.hour, 1.0)
                     for t in trades if t.pnl_pct <= 0))
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


if __name__ == "__main__":
    main()
