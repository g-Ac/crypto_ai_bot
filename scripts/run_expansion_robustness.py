#!/usr/bin/env python
"""Run walk-forward + LOO from a populated backtest DB.

Reads expansion_v1_365d.db (main run), partitions trades into 12 folds by
entry_ts, computes LOO-by-symbol and LOO-by-fold, and writes JSON.

Usage:
    python scripts/run_expansion_robustness.py \
        --db research/expansion_v1_365d.db \
        --out research/expansion_v1_robustness.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from momentum.expansion.leave_one_out import loo_by_fold, loo_by_symbol
from momentum.expansion.metrics import compute_portfolio_metrics
from momentum.expansion.research_db import fetch_all_trades


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def _partition_trades_by_month(trades: list[dict], n_folds: int = 12) -> list[dict]:
    """Partition trades into n_folds equal-sized buckets by entry_ts ordering."""
    sorted_trades = sorted(trades, key=lambda t: t["entry_ts"])
    n = len(sorted_trades)
    if n == 0 or n_folds == 0:
        return [{"fold_idx": i, "trades": []} for i in range(n_folds)]
    per = max(1, n // n_folds)
    out = []
    for i in range(n_folds):
        start = i * per
        end = (i + 1) * per if i < n_folds - 1 else n
        out.append({"fold_idx": i, "trades": sorted_trades[start:end]})
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--n-folds", type=int, default=12)
    args = p.parse_args()

    trades = fetch_all_trades(args.db)
    main_trades = [t for t in trades if t["run_id"].endswith("_main")]
    holdout_trades = [t for t in trades if t["run_id"].endswith("_holdout")]

    main_metrics = compute_portfolio_metrics(main_trades)
    holdout_metrics = compute_portfolio_metrics(holdout_trades)

    universe = sorted({t["symbol"] for t in main_trades})
    loo_sym = loo_by_symbol(main_trades, universe)
    folds = _partition_trades_by_month(main_trades, n_folds=args.n_folds)
    loo_fold_result = loo_by_fold(folds)

    fold_metrics = []
    for f in folds:
        m = compute_portfolio_metrics(f["trades"])
        fold_metrics.append({"fold_idx": f["fold_idx"], **m})

    per_symbol_stats = {
        sym: compute_portfolio_metrics([t for t in main_trades if t["symbol"] == sym])
        for sym in universe
    }

    payload = {
        "main_metrics": main_metrics,
        "holdout_metrics": holdout_metrics,
        "fold_metrics": fold_metrics,
        "loo_symbol": {sym: loo_sym[sym] for sym in universe},
        "loo_fold": {idx: loo_fold_result[idx] for idx in loo_fold_result},
        "per_symbol_stats": per_symbol_stats,
        "generated_at": datetime.utcnow().isoformat(),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(args.out, payload)
    print(f"Robustness written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
