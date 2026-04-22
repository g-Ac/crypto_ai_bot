#!/usr/bin/env python
"""CLI: read a completed backtest DB and run all 4 robustness tests.

Usage:
    python scripts/run_pair_robustness.py \
        --main-db research/pair_v1_90d.db \
        --holdout-db research/pair_v1_holdout.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from pair_trading.research_db import fetch_all_trades
from pair_trading.robustness_check import (
    correlation_bucket_analysis,
    holdout_oos,
    monthly_consistency,
    regime_breakdown,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--main-db", required=True, help="Main 90d backtest DB")
    p.add_argument("--holdout-db", required=True, help="Holdout 30d DB")
    p.add_argument("--out", default="-", help="Output JSON path or - for stdout")
    args = p.parse_args()

    main_trades = fetch_all_trades(args.main_db)
    holdout_trades = fetch_all_trades(args.holdout_db)

    results = {
        "main_db": args.main_db,
        "holdout_db": args.holdout_db,
        "n_main_trades": len(main_trades),
        "n_holdout_trades": len(holdout_trades),
        "test_1_monthly_consistency": monthly_consistency(main_trades, n_months=3),
        "test_2_holdout_oos": holdout_oos(holdout_trades, pf_threshold=0.8),
        "test_3_regime_breakdown": regime_breakdown(main_trades, min_trades_per_regime=20, pf_floor=0.5),
        "test_4_correlation_bucket": correlation_bucket_analysis(main_trades),
    }
    results["all_pass"] = all(
        results[k]["passes"]
        for k in ("test_1_monthly_consistency", "test_2_holdout_oos",
                  "test_3_regime_breakdown", "test_4_correlation_bucket")
    )

    out = json.dumps(results, indent=2, default=str)
    if args.out == "-":
        print(out)
    else:
        Path(args.out).write_text(out)
        print(f"Results written to {args.out}")
        print(f"All pass: {results['all_pass']}")
    return 0 if results["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
