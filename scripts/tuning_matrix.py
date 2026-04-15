"""Tuning Matrix v1.1 — Exit/Risk Shape variants.

Runs 5 variants + v1 baseline on the same 90-day dataset.
Compares PF, edge ratio, timeout %, total PnL, breakdowns.

Usage:
    cd ~/crypto_ai_bot
    source .venv/bin/activate
    python scripts/tuning_matrix.py
"""

from __future__ import annotations

import sqlite3
import sys
import time as time_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from momentum.config import MomentumConfig
from momentum.research_db import ensure_tables
from momentum.research_report import generate_report
from momentum.research_runner import run_research_cycle

# Reuse fetch/regime logic from research_matrix
from scripts.research_matrix import (
    BINANCE_URL,
    SYMBOLS,
    WARMUP_DAYS,
    WINDOW,
    compute_regimes,
    fetch_candles,
    lookup_regime,
)


# ---------------------------------------------------------------------------
# Variant definitions
# ---------------------------------------------------------------------------

VARIANTS = {
    "v1_baseline": MomentumConfig(sl_floor_pct=0.3, param_version="momentum-pullback-v1"),
    "A1_timeout12": MomentumConfig(sl_floor_pct=0.3, timeout_candles=12, param_version="momentum-pullback-v1"),
    "A2_breakeven": MomentumConfig(sl_floor_pct=0.3, breakeven_trigger_pct=0.5, param_version="momentum-pullback-v1"),
    "B1_floor05": MomentumConfig(sl_floor_pct=0.5, param_version="momentum-pullback-v1"),
    "B2_floor08": MomentumConfig(sl_floor_pct=0.8, param_version="momentum-pullback-v1"),
    "C1_tp1_half": MomentumConfig(sl_floor_pct=0.3, tp1_factor=0.5, param_version="momentum-pullback-v1"),
}

DAYS = 90
DB_DIR = PROJECT_ROOT / "research" / "tuning_v1_1"


# ---------------------------------------------------------------------------
# Replay (same as research_matrix but takes config + db_path)
# ---------------------------------------------------------------------------

def replay_variant(
    name: str,
    config: MomentumConfig,
    db_path: Path,
    all_data: dict,
    n_steps: int,
) -> dict:
    """Replay one variant. Returns generate_report() dict."""
    if db_path.exists():
        db_path.unlink()
    ensure_tables(db_path)

    t_start = time_mod.time()
    total_dec = 0
    total_opened = 0
    total_closed = 0

    for step in range(n_steps):
        idx = WINDOW + step

        def _make_candle_fn(end_idx: int):
            def candle_fn(symbol, interval, limit):
                c15 = all_data[symbol]["candles_15m"]
                start = max(0, end_idx - WINDOW)
                return c15.iloc[start:end_idx].reset_index(drop=True)
            return candle_fn

        def _make_regime_fn(end_idx: int):
            def regime_fn(symbol):
                c15 = all_data[symbol]["candles_15m"]
                ts = c15.iloc[end_idx - 1]["time"]
                label = lookup_regime(all_data[symbol]["regimes"], ts)
                return {"regime_label": label}
            return regime_fn

        result = run_research_cycle(
            SYMBOLS, db_path, config,
            candle_fn=_make_candle_fn(idx),
            regime_fn=_make_regime_fn(idx),
        )

        total_dec += result["decisions_recorded"]
        total_opened += result["trades_opened"]
        total_closed += result["trades_closed"]

        if (step + 1) % 2000 == 0 or step == n_steps - 1:
            elapsed = time_mod.time() - t_start
            print(
                f"    Step {step + 1:>5d}/{n_steps}  "
                f"dec={total_dec}  opened={total_opened}  "
                f"closed={total_closed}  [{elapsed:.0f}s]"
            )

    elapsed = time_mod.time() - t_start
    print(f"    Done in {elapsed:.1f}s")

    return generate_report(db_path)


# ---------------------------------------------------------------------------
# Breakdown queries
# ---------------------------------------------------------------------------

def _query_sl_buckets(db_path: Path) -> list:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT
            CASE
                WHEN ABS(sl_price - entry_price) / entry_price * 100 < 0.5 THEN 'tight_lt05'
                WHEN ABS(sl_price - entry_price) / entry_price * 100 < 1.0 THEN 'med_05_10'
                WHEN ABS(sl_price - entry_price) / entry_price * 100 < 2.0 THEN 'wide_10_20'
                ELSE 'vwide_gt20'
            END AS bucket,
            COUNT(*) AS n,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) AS wins,
            ROUND(AVG(pnl_pct), 4) AS avg_pnl,
            ROUND(SUM(pnl_pct), 4) AS total_pnl,
            SUM(CASE WHEN exit_reason = 'sl_hit' THEN 1 ELSE 0 END) AS sl_exits
        FROM momentum_trades WHERE exit_price IS NOT NULL
        GROUP BY bucket ORDER BY bucket
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _query_ret_buckets(db_path: Path) -> list:
    """Win rate by retracement bucket (join decisions→trades)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT
            CASE
                WHEN d.retracement_pct < 40 THEN '30-40'
                WHEN d.retracement_pct < 50 THEN '40-50'
                WHEN d.retracement_pct < 60 THEN '50-60'
                ELSE '60-70'
            END AS bucket,
            COUNT(*) AS n,
            SUM(CASE WHEN t.pnl_pct > 0 THEN 1 ELSE 0 END) AS wins,
            ROUND(AVG(t.pnl_pct), 4) AS avg_pnl,
            ROUND(SUM(t.pnl_pct), 4) AS total_pnl
        FROM momentum_trades t
        JOIN momentum_decisions d ON t.decision_id = d.id
        WHERE t.exit_price IS NOT NULL
        GROUP BY bucket ORDER BY bucket
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _query_exit_reasons(db_path: Path) -> list:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT exit_reason, COUNT(*) AS n,
               ROUND(AVG(pnl_pct), 4) AS avg_pnl,
               ROUND(SUM(pnl_pct), 4) AS total_pnl
        FROM momentum_trades WHERE exit_price IS NOT NULL
        GROUP BY exit_reason ORDER BY n DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Comparison table
# ---------------------------------------------------------------------------

def build_comparison(results: dict) -> str:
    lines = []

    # --- Main comparison ---
    lines.append("=" * 90)
    lines.append("  TUNING MATRIX v1.1 — COMPARISON TABLE")
    lines.append("=" * 90)
    lines.append("")

    header = (
        f"  {'Variant':<16s} {'Trades':>6s} {'WR%':>6s} {'PF':>6s} "
        f"{'ER':>6s} {'AvgPnL':>8s} {'TotalPnL':>10s} "
        f"{'TO%':>6s} {'AvgDur':>6s}"
    )
    lines.append(header)
    lines.append("  " + "-" * 84)

    for name, report in results.items():
        t = report["trades"]
        m = report["mfe_mae"]
        exits = report["exits"]

        n_closed = t["count"]
        if n_closed == 0:
            continue

        timeout_n = exits.get("timeout", {}).get("count", 0)
        timeout_pct = round(timeout_n / n_closed * 100, 1)
        pf = t["profit_factor"]
        pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
        er = m["edge_ratio"]
        er_str = f"{er:.2f}" if er != float("inf") else "inf"

        lines.append(
            f"  {name:<16s} {n_closed:>6d} {t['win_rate']:>5.1f}% "
            f"{pf_str:>6s} {er_str:>6s} "
            f"{t['avg_pnl']:>+7.4f}% {t['total_pnl']:>+9.4f}% "
            f"{timeout_pct:>5.1f}% {t['avg_duration']:>5.1f}"
        )

    lines.append("")

    # --- Exit breakdown per variant ---
    lines.append("--- EXIT REASONS PER VARIANT ---")
    for name in results:
        db_path = DB_DIR / f"{name}.db"
        if not db_path.exists():
            continue
        exits = _query_exit_reasons(db_path)
        parts = [f"{name:<16s}"]
        for e in exits:
            parts.append(f"{e['exit_reason']}={e['n']}")
        lines.append("  " + "  ".join(parts))
    lines.append("")

    # --- SL bucket breakdown per variant ---
    lines.append("--- SL DISTANCE BUCKETS PER VARIANT ---")
    for name in results:
        db_path = DB_DIR / f"{name}.db"
        if not db_path.exists():
            continue
        lines.append(f"  {name}:")
        for b in _query_sl_buckets(db_path):
            wr = round(b["wins"] / b["n"] * 100, 1) if b["n"] > 0 else 0
            lines.append(
                f"    {b['bucket']:<15s}  n={b['n']:>3d}  "
                f"WR={wr:>5.1f}%  avg={b['avg_pnl']:+.4f}%  "
                f"sl_exits={b['sl_exits']}"
            )
    lines.append("")

    # --- Retracement bucket breakdown per variant ---
    lines.append("--- RETRACEMENT BUCKETS PER VARIANT ---")
    for name in results:
        db_path = DB_DIR / f"{name}.db"
        if not db_path.exists():
            continue
        lines.append(f"  {name}:")
        for b in _query_ret_buckets(db_path):
            wr = round(b["wins"] / b["n"] * 100, 1) if b["n"] > 0 else 0
            lines.append(
                f"    {b['bucket']:<8s}  n={b['n']:>3d}  "
                f"WR={wr:>5.1f}%  avg={b['avg_pnl']:+.4f}%  "
                f"total={b['total_pnl']:+.4f}%"
            )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_tuning():
    print("=" * 55)
    print("  TUNING MATRIX v1.1 — EXIT/RISK SHAPE")
    print("=" * 55)
    print(f"  Variants: {list(VARIANTS.keys())}")
    print(f"  Period:   {DAYS} days")
    print()

    # --- Fetch data once ---
    end_dt = datetime.now(timezone.utc)
    start_15m = end_dt - timedelta(days=DAYS)
    start_1h = end_dt - timedelta(days=DAYS + WARMUP_DAYS)
    start_15m_ms = int(start_15m.timestamp() * 1000)
    start_1h_ms = int(start_1h.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    all_data: dict = {}
    for symbol in SYMBOLS:
        print(f"  [{symbol}] Fetching 15m...", end="", flush=True)
        c15 = fetch_candles(symbol, "15m", start_15m_ms, end_ms)
        print(f" {len(c15)}", end="  ", flush=True)

        print("1h...", end="", flush=True)
        c1h = fetch_candles(symbol, "1h", start_1h_ms, end_ms)
        print(f" {len(c1h)}", end="  ", flush=True)

        regimes = compute_regimes(c1h)
        valid = (regimes["regime_label"] != "UNKNOWN").sum()
        print(f"regimes: {valid}")

        all_data[symbol] = {"candles_15m": c15, "regimes": regimes}

    min_len = min(len(all_data[s]["candles_15m"]) for s in SYMBOLS)
    n_steps = min_len - WINDOW

    DB_DIR.mkdir(parents=True, exist_ok=True)

    # --- Run variants ---
    results = {}
    for name, config in VARIANTS.items():
        print()
        print(f"  === {name} ===")
        print(f"  Config: timeout={config.timeout_candles}, "
              f"sl_floor={config.sl_floor_pct}%, "
              f"tp1_factor={config.tp1_factor}, "
              f"breakeven={config.breakeven_trigger_pct}")

        db_path = DB_DIR / f"{name}.db"
        report = replay_variant(name, config, db_path, all_data, n_steps)
        results[name] = report

    # --- Comparison ---
    print()
    comparison = build_comparison(results)

    report_path = DB_DIR / "comparison.txt"
    report_path.write_text(comparison, encoding="utf-8")

    print(comparison)
    print(f"  Saved to: {report_path}")

    return results


if __name__ == "__main__":
    run_tuning()
