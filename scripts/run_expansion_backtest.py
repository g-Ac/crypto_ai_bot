#!/usr/bin/env python
"""Run main 365d + holdout 90d backtest for EXP-005.

Reads preflight JSON for the frozen universe.
Writes results to a SQLite DB.

Usage:
    python scripts/run_expansion_backtest.py \
        --preflight research/expansion_v1_preflight.json \
        --start 2025-04-27 --end 2026-04-27 \
        --holdout-start 2025-01-27 --holdout-end 2025-04-27 \
        --db research/expansion_v1_365d.db \
        --capital-pool 35000 --risk-fraction 0.01
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.data_loader import (
    align_candles_by_timestamp,
    fetch_klines_paginated,
    validate_gap_threshold,
)
from momentum.expansion.research_db import (
    init_db, insert_decision, insert_run, insert_trade,
)
from momentum.expansion.research_runner import run_portfolio_backtest
from momentum.expansion.signal_engine_adapter import evaluate_signal_for_symbol


def _ms(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _signal_fn(*, candles, symbol, regime_label, timestamp, config=None):
    return evaluate_signal_for_symbol(
        candles=candles, symbol=symbol, regime_label=regime_label, timestamp=timestamp,
    )


def _persist(db_path: str, run_id: str, result, label: str):
    for t in result.trades:
        insert_trade(db_path, {**t, "run_id": run_id})
    for d in result.decisions:
        insert_decision(db_path, {**d, "run_id": run_id})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--preflight", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--holdout-start", required=True)
    p.add_argument("--holdout-end", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--capital-pool", type=float, default=35000.0)
    p.add_argument("--risk-fraction", type=float, default=0.01)
    args = p.parse_args()

    with open(args.preflight) as f:
        pf_data = json.load(f)
    universe = tuple(pf_data["universe"])
    if not universe:
        print("ERROR: empty universe in preflight", file=sys.stderr)
        return 2

    config = ExpansionConfig(universe=universe)
    end_ms = _ms(args.end)
    start_ms = _ms(args.start)
    total_candles_main = (end_ms - start_ms) // 900_000 + 10
    holdout_start_ms = _ms(args.holdout_start)
    holdout_end_ms = _ms(args.holdout_end)
    total_candles_holdout = (holdout_end_ms - holdout_start_ms) // 900_000 + 10

    # Fetch and align main window
    print("Fetching main window candles...")
    raw_main = {}
    for sym in universe:
        df = fetch_klines_paginated(sym, "15m", end_ms, total_candles_main)
        df = df[df["close_time_ms"] >= start_ms].reset_index(drop=True)
        raw_main[sym] = df
    candles_main = align_candles_by_timestamp(raw_main)
    expected = (end_ms - start_ms) // 900_000
    for sym, df in candles_main.items():
        validate_gap_threshold(symbol=sym, expected=expected, actual=len(df), threshold_pct=0.5)

    # Fetch and align holdout window
    print("Fetching holdout window candles...")
    raw_hold = {}
    for sym in universe:
        df = fetch_klines_paginated(sym, "15m", holdout_end_ms, total_candles_holdout)
        df = df[df["close_time_ms"] >= holdout_start_ms].reset_index(drop=True)
        raw_hold[sym] = df
    candles_holdout = align_candles_by_timestamp(raw_hold)
    expected_hold = (holdout_end_ms - holdout_start_ms) // 900_000
    for sym, df in candles_holdout.items():
        validate_gap_threshold(symbol=sym, expected=expected_hold, actual=len(df), threshold_pct=0.5)

    # Run main + holdout
    init_db(args.db)
    run_id = uuid.uuid4().hex
    config_hash = hashlib.sha256(json.dumps(pf_data, sort_keys=True).encode()).hexdigest()[:12]
    insert_run(args.db, {
        "run_id": run_id, "config_hash": config_hash,
        "universe_json": json.dumps(list(universe)),
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "completed_at": None, "verdict": None,
    })

    print("Running main backtest...")
    main_result = run_portfolio_backtest(
        config=config, candles_by_symbol=candles_main, signal_fn=_signal_fn,
        capital_pool_usdt=args.capital_pool, risk_fraction=args.risk_fraction,
    )
    _persist(args.db, run_id + "_main", main_result, "main")

    print("Running holdout backtest...")
    holdout_result = run_portfolio_backtest(
        config=config, candles_by_symbol=candles_holdout, signal_fn=_signal_fn,
        capital_pool_usdt=args.capital_pool, risk_fraction=args.risk_fraction,
    )
    _persist(args.db, run_id + "_holdout", holdout_result, "holdout")

    print(f"\n=== MAIN ===")
    print(json.dumps(main_result.metrics, indent=2, default=str))
    print(f"\n=== HOLDOUT ===")
    print(json.dumps(holdout_result.metrics, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
