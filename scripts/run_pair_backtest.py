#!/usr/bin/env python
"""CLI: run pair trading backtest over a date range and persist to SQLite.

Usage:
    python scripts/run_pair_backtest.py \
        --start 2026-01-15 --end 2026-04-15 \
        --db research/pair_v1_90d.db

Fetches BTC/ETH 15m candles via Binance REST, runs backtest, writes results.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Ensure repo root on path so `pair_trading` imports work when run from scripts/
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from pair_trading.config import PairConfig
from pair_trading.historical_data import fetch_synced_pair
from pair_trading.metrics import compute_metrics
from pair_trading.research_db import fetch_all_trades, init_db
from pair_trading.research_runner import run_backtest


def _parse_date(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--db", required=True, help="Output SQLite path")
    parser.add_argument("--execution-shift", type=int, default=1,
                        help="1=correct (default). 0=diagnostic (look-ahead leak)")
    parser.add_argument("--slippage", type=float, default=0.0,
                        help="Slippage per leg per side, in percent (e.g. 0.05 = 0.05%%).")
    args = parser.parse_args()

    start_ms = _parse_date(args.start)
    end_ms = _parse_date(args.end)

    # 15m candle = 900000 ms. Add warmup margin (192 candles = 48h).
    total_ms = end_ms - start_ms
    n_15m = total_ms // 900_000
    warmup_margin = 192
    fetch_limit = int(n_15m) + warmup_margin

    print(f"Fetching {fetch_limit} candles for BTCUSDT + ETHUSDT 15m ending {args.end}...")
    btc_close, eth_close, close_times = fetch_synced_pair(
        "BTCUSDT", "ETHUSDT", "15m", fetch_limit, end_time_ms=end_ms,
    )
    print(f"Got {len(btc_close)} aligned candles from "
          f"{datetime.fromtimestamp(close_times[0]/1000, tz=timezone.utc).isoformat()} "
          f"to {datetime.fromtimestamp(close_times[-1]/1000, tz=timezone.utc).isoformat()}")

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    init_db(args.db)
    from dataclasses import replace
    cfg = replace(PairConfig(), slippage_pct=args.slippage)

    summary = run_backtest(
        db_path=args.db,
        config=cfg,
        btc_close=btc_close,
        eth_close=eth_close,
        close_times_ms=close_times,
        execution_shift=args.execution_shift,
    )
    print(f"Backtest done: {summary}")

    trades = fetch_all_trades(args.db)
    metrics = compute_metrics(trades)
    print(f"\n=== Metrics (execution_shift={args.execution_shift}) ===")
    for k, v in metrics.items():
        print(f"  {k:20s} = {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
