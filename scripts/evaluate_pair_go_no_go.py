#!/usr/bin/env python
"""Evaluate BACKTEST → ROBUSTNESS gate from a backtest DB.

Usage:
    python scripts/evaluate_pair_go_no_go.py \
        --main-db research/pair_v1_90d.db \
        --slippage-005-db research/pair_v1_90d_slip005.db \
        --slippage-010-db research/pair_v1_90d_slip010.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from pair_trading.baselines import buy_and_hold_pf, random_trader_pf_distribution
from pair_trading.go_no_go import evaluate_backtest_to_robustness
from pair_trading.historical_data import fetch_synced_pair
from pair_trading.metrics import compute_metrics
from pair_trading.research_db import fetch_all_trades


def _pf_from_db(db_path: str) -> float:
    trades = fetch_all_trades(db_path)
    return compute_metrics(trades)["profit_factor"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--main-db", required=True)
    p.add_argument("--slippage-005-db", required=True)
    p.add_argument("--slippage-010-db", required=True)
    p.add_argument("--start", required=True, help="YYYY-MM-DD of backtest start")
    p.add_argument("--end", required=True, help="YYYY-MM-DD of backtest end")
    args = p.parse_args()

    main_trades = fetch_all_trades(args.main_db)
    metrics = compute_metrics(main_trades)

    # Fetch prices for baselines
    from datetime import datetime, timezone
    end_ms = int(datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc).timestamp() * 1000)
    total_ms = end_ms - int(datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc).timestamp() * 1000)
    limit = int(total_ms // 900_000) + 10
    btc, eth, _ = fetch_synced_pair("BTCUSDT", "ETHUSDT", "15m", limit, end_time_ms=end_ms)

    btc_pf = buy_and_hold_pf(btc)
    eth_pf = buy_and_hold_pf(eth)

    # Random trader baseline — match N trades and average hold of actual pair
    n_trades = metrics["n_trades"] or 1
    avg_hold_candles = 48  # assumption ≈ 12h avg hold; could be computed from trades
    pf_dist = random_trader_pf_distribution(
        btc, n_trades=n_trades, avg_hold=avg_hold_candles,
        n_runs=100, seed=42,
    )
    p95 = float(np.percentile(pf_dist, 95))

    pf_005 = _pf_from_db(args.slippage_005_db)
    pf_010 = _pf_from_db(args.slippage_010_db)

    result = evaluate_backtest_to_robustness(
        metrics=metrics,
        buy_hold_btc_pf=btc_pf,
        buy_hold_eth_pf=eth_pf,
        random_trader_p95_pf=p95,
        slippage_sensitivity_pf_at_005=pf_005,
        slippage_sensitivity_pf_at_010=pf_010,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["passes"] else 1


if __name__ == "__main__":
    sys.exit(main())
