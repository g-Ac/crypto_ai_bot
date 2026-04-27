#!/usr/bin/env python
"""Evaluate the 10-criteria GO/NO-GO from robustness + slippage runs.

Usage:
    python scripts/evaluate_expansion_go_no_go.py \
        --robustness research/expansion_v1_robustness.json \
        --slippage-010-db research/expansion_v1_slip010.db \
        --c2-json research/expansion_v1_c2.json \
        --c3-json research/expansion_v1_c3_normalized.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from momentum.expansion.go_no_go import evaluate_expansion
from momentum.expansion.metrics import compute_portfolio_metrics
from momentum.expansion.research_db import fetch_all_trades


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--robustness", required=True)
    p.add_argument("--slippage-010-db", required=True)
    p.add_argument("--c2-json", required=True)
    p.add_argument("--c3-json", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    with open(args.robustness) as f:
        rob = json.load(f)
    with open(args.c2_json) as f:
        c2 = json.load(f)
    with open(args.c3_json) as f:
        c3 = json.load(f)

    slip_trades = fetch_all_trades(args.slippage_010_db)
    slip_metrics = compute_portfolio_metrics(slip_trades)

    fold_pfs = [f["profit_factor"] for f in rob["fold_metrics"]]

    res = evaluate_expansion(
        main_metrics=rob["main_metrics"],
        holdout_metrics=rob["holdout_metrics"],
        fold_pfs=fold_pfs,
        loo_symbol=rob["loo_symbol"],
        loo_fold={int(k): v for k, v in rob["loo_fold"].items()},
        c2_metrics=c2,
        c3_normalized_metrics=c3,
        slippage_010_metrics=slip_metrics,
        per_symbol_stats=rob["per_symbol_stats"],
    )

    print(json.dumps(res, indent=2, default=str))
    if args.out:
        _atomic_write_json(args.out, res)
    return 0 if res["passes"] else 1


if __name__ == "__main__":
    sys.exit(main())
