"""Robustness Check — v1.0 vs v1.1 (B1: sl_floor 0.3% → 0.5%).

Three independent tests to validate B1's improvement:
  1. Monthly consistency: v1.0 vs v1.1 on each 30-day block (within-sample)
  2. Out-of-sample holdout: 30 days before the 90-day dev period
  3. Regime breakdown: aggregate all 120 days, compare by regime

Usage:
    cd ~/crypto_ai_bot
    source .venv/bin/activate
    python scripts/robustness_check.py
"""

from __future__ import annotations

import sqlite3
import sys
import time as time_mod
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from momentum.config import MomentumConfig
from momentum.research_db import ensure_tables
from momentum.research_report import generate_report
from momentum.research_runner import run_research_cycle

from scripts.research_matrix import (
    SYMBOLS,
    WARMUP_DAYS,
    WINDOW,
    compute_regimes,
    fetch_candles,
    lookup_regime,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIGS = {
    "v1.0": MomentumConfig(sl_floor_pct=0.3, param_version="momentum-pullback-v1"),
    "v1.1": MomentumConfig(sl_floor_pct=0.5, param_version="momentum-pullback-v1.1"),
}

TOTAL_DAYS = 120   # 30 holdout + 90 dev
MIN_SAMPLE = 30    # Below this, a period verdict is inconclusive

# (name, days_ago_start, days_ago_end)
PERIODS = [
    ("holdout", 120, 90),
    ("month_1", 90, 60),
    ("month_2", 60, 30),
    ("month_3", 30, 0),
]

DB_DIR = PROJECT_ROOT / "research" / "robustness_v1_1"


# ---------------------------------------------------------------------------
# Data slicing — extract a period with WINDOW warmup
# ---------------------------------------------------------------------------

def slice_period_data(
    all_data: dict,
    end_dt: datetime,
    days_ago_start: int,
    days_ago_end: int,
) -> tuple[dict, int]:
    """Create a view of all_data for one period.

    Includes WINDOW candles before the period for evaluation context.
    Returns (period_data, n_steps).
    """
    # Strip tz for comparison with tz-naive Binance timestamps
    end_naive = end_dt.replace(tzinfo=None)
    period_start = end_naive - timedelta(days=days_ago_start)
    period_end = end_naive - timedelta(days=days_ago_end) if days_ago_end > 0 else end_naive

    period_data: dict = {}
    min_steps = float("inf")

    for symbol in SYMBOLS:
        c15 = all_data[symbol]["candles_15m"]

        mask = (c15["time"] >= period_start) & (c15["time"] < period_end)
        period_idx = c15.index[mask]

        if len(period_idx) == 0:
            return {}, 0

        first_idx = period_idx[0]
        last_idx = period_idx[-1]

        context_start = max(0, first_idx - WINDOW)
        warmup_len = first_idx - context_start

        sliced = c15.iloc[context_start : last_idx + 1].reset_index(drop=True)

        period_data[symbol] = {
            "candles_15m": sliced,
            "regimes": all_data[symbol]["regimes"],
        }

        steps = len(period_idx) if warmup_len >= WINDOW else max(0, len(sliced) - WINDOW)
        min_steps = min(min_steps, steps)

    return period_data, int(min_steps) if min_steps != float("inf") else 0


# ---------------------------------------------------------------------------
# Replay one (period × config)
# ---------------------------------------------------------------------------

def replay_period(
    label: str,
    config: MomentumConfig,
    db_path: Path,
    period_data: dict,
    n_steps: int,
) -> dict:
    """Replay config on a period. Returns generate_report() dict."""
    if db_path.exists():
        db_path.unlink()
    ensure_tables(db_path)

    t0 = time_mod.time()
    total_dec = total_opened = total_closed = 0

    for step in range(n_steps):
        idx = WINDOW + step

        def _candle_fn(end_idx: int):
            def fn(symbol, interval, limit):
                c15 = period_data[symbol]["candles_15m"]
                start = max(0, end_idx - WINDOW)
                return c15.iloc[start:end_idx].reset_index(drop=True)
            return fn

        def _regime_fn(end_idx: int):
            def fn(symbol):
                c15 = period_data[symbol]["candles_15m"]
                ts = c15.iloc[end_idx - 1]["time"]
                lbl = lookup_regime(period_data[symbol]["regimes"], ts)
                return {"regime_label": lbl}
            return fn

        result = run_research_cycle(
            SYMBOLS, db_path, config,
            candle_fn=_candle_fn(idx),
            regime_fn=_regime_fn(idx),
        )

        total_dec += result["decisions_recorded"]
        total_opened += result["trades_opened"]
        total_closed += result["trades_closed"]

        if (step + 1) % 2000 == 0 or step == n_steps - 1:
            elapsed = time_mod.time() - t0
            print(
                f"      Step {step + 1:>5d}/{n_steps}  "
                f"dec={total_dec} opened={total_opened} "
                f"closed={total_closed} [{elapsed:.0f}s]",
            )

    print(f"      Done in {time_mod.time() - t0:.1f}s")
    return generate_report(db_path)


# ---------------------------------------------------------------------------
# DB helper queries
# ---------------------------------------------------------------------------

def _query_exits(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT exit_reason, COUNT(*) AS n "
        "FROM momentum_trades WHERE exit_price IS NOT NULL "
        "GROUP BY exit_reason",
    ).fetchall()
    conn.close()
    return {r["exit_reason"]: r["n"] for r in rows}


def _query_trades_raw(db_path: Path) -> list:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT regime, pnl_pct, exit_reason "
        "FROM momentum_trades WHERE exit_price IS NOT NULL",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Comparison builder
# ---------------------------------------------------------------------------

def _pf(pnls: list) -> float:
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0))
    return round(gp / gl, 2) if gl > 0 else float("inf")


def _pf_str(pf: float) -> str:
    return f"{pf:.2f}" if pf != float("inf") else "inf"


def _er_str(er: float) -> str:
    return f"{er:.2f}" if er != float("inf") else "inf"


def build_comparison(all_results: dict, end_dt: datetime) -> str:
    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────
    lines.append("=" * 92)
    lines.append("  ROBUSTNESS CHECK — v1.0 vs v1.1 (B1: sl_floor 0.3% → 0.5%)")
    lines.append("=" * 92)
    lines.append("")

    for pname, d_start, d_end in PERIODS:
        dt_s = end_dt - timedelta(days=d_start)
        dt_e = end_dt - timedelta(days=d_end) if d_end > 0 else end_dt
        tag = " (out-of-sample)" if pname == "holdout" else ""
        lines.append(f"  {pname:<10s}: {dt_s:%Y-%m-%d} → {dt_e:%Y-%m-%d}{tag}")
    lines.append(f"  Min sample: {MIN_SAMPLE} trades")
    lines.append("")

    # ── Main comparison table ───────────────────────────────────────────
    hdr = (
        f"  {'Period':<10s} {'Ver':>5s} {'N':>5s} {'WR%':>6s} "
        f"{'PF':>6s} {'ER':>6s} {'AvgPnL':>8s} {'TotalPnL':>10s} "
        f"{'SL%':>6s} {'TO%':>6s}"
    )
    lines.append(hdr)
    lines.append("  " + "-" * 80)

    for pname, _, _ in PERIODS:
        if pname not in all_results:
            continue
        for ver in ["v1.0", "v1.1"]:
            r = all_results[pname][ver]
            t = r["report"]["trades"]
            m = r["report"]["mfe_mae"]
            n = t["count"]

            if n == 0:
                lines.append(f"  {pname:<10s} {ver:>5s}     0 trades")
                continue

            exits = _query_exits(r["db_path"])
            sl_pct = round(exits.get("sl_hit", 0) / n * 100, 1)
            to_pct = round(exits.get("timeout", 0) / n * 100, 1)

            lines.append(
                f"  {pname:<10s} {ver:>5s} {n:>5d} {t['win_rate']:>5.1f}% "
                f"{_pf_str(t['profit_factor']):>6s} {_er_str(m['edge_ratio']):>6s} "
                f"{t['avg_pnl']:>+7.4f}% {t['total_pnl']:>+9.4f}% "
                f"{sl_pct:>5.1f}% {to_pct:>5.1f}%"
            )
        lines.append("")

    # ── TEST 1: Monthly Consistency ─────────────────────────────────────
    lines.append("=" * 60)
    lines.append("  TEST 1: CONSISTENCIA MENSAL (within-sample)")
    lines.append("=" * 60)
    lines.append("")

    conclusive = 0
    v11_wins = 0

    for pname in ["month_1", "month_2", "month_3"]:
        t10 = all_results[pname]["v1.0"]["report"]["trades"]
        t11 = all_results[pname]["v1.1"]["report"]["trades"]
        m10 = all_results[pname]["v1.0"]["report"]["mfe_mae"]
        m11 = all_results[pname]["v1.1"]["report"]["mfe_mae"]
        n10, n11 = t10["count"], t11["count"]

        if n10 < MIN_SAMPLE or n11 < MIN_SAMPLE:
            lines.append(
                f"  {pname}: INCONCLUSIVO — amostra insuficiente "
                f"(v1.0 n={n10}, v1.1 n={n11}, min={MIN_SAMPLE})"
            )
            continue

        conclusive += 1
        pf10, pf11 = t10["profit_factor"], t11["profit_factor"]

        if pf11 >= pf10:
            v11_wins += 1
            tag = "v1.1 VENCE"
        else:
            tag = "v1.0 vence"

        # Show all requested metrics
        db10 = all_results[pname]["v1.0"]["db_path"]
        db11 = all_results[pname]["v1.1"]["db_path"]
        ex10 = _query_exits(db10)
        ex11 = _query_exits(db11)
        sl10 = round(ex10.get("sl_hit", 0) / n10 * 100, 1)
        sl11 = round(ex11.get("sl_hit", 0) / n11 * 100, 1)
        to10 = round(ex10.get("timeout", 0) / n10 * 100, 1)
        to11 = round(ex11.get("timeout", 0) / n11 * 100, 1)

        lines.append(f"  {pname}: {tag}")
        lines.append(
            f"    PF {_pf_str(pf10)}→{_pf_str(pf11)}  "
            f"WR {t10['win_rate']:.1f}%→{t11['win_rate']:.1f}%  "
            f"PnL {t10['total_pnl']:+.2f}%→{t11['total_pnl']:+.2f}%"
        )
        lines.append(
            f"    ER {_er_str(m10['edge_ratio'])}→{_er_str(m11['edge_ratio'])}  "
            f"SL% {sl10:.1f}%→{sl11:.1f}%  "
            f"TO% {to10:.1f}%→{to11:.1f}%"
        )

    lines.append("")
    if conclusive == 0:
        test1 = "INCONCLUSIVO"
        lines.append("  Resultado: INCONCLUSIVO — nenhum mes com amostra suficiente")
    elif v11_wins >= (conclusive + 1) // 2:
        test1 = "PASS"
        lines.append(
            f"  Resultado: PASS — v1.1 melhor em "
            f"{v11_wins}/{conclusive} meses conclusivos"
        )
    else:
        test1 = "FAIL"
        lines.append(
            f"  Resultado: FAIL — v1.1 melhor em apenas "
            f"{v11_wins}/{conclusive} meses conclusivos"
        )
    lines.append("")

    # ── TEST 2: Holdout Out-of-Sample ───────────────────────────────────
    lines.append("=" * 60)
    lines.append("  TEST 2: HOLDOUT OUT-OF-SAMPLE (30 dias)")
    lines.append("=" * 60)
    lines.append("")

    r10 = all_results["holdout"]["v1.0"]
    r11 = all_results["holdout"]["v1.1"]
    t10 = r10["report"]["trades"]
    t11 = r11["report"]["trades"]
    n10, n11 = t10["count"], t11["count"]

    if n10 < MIN_SAMPLE or n11 < MIN_SAMPLE:
        test2 = "INCONCLUSIVO"
        lines.append(
            f"  INCONCLUSIVO — amostra insuficiente "
            f"(v1.0 n={n10}, v1.1 n={n11}, min={MIN_SAMPLE})"
        )
    else:
        m10 = r10["report"]["mfe_mae"]
        m11 = r11["report"]["mfe_mae"]
        ex10 = _query_exits(r10["db_path"])
        ex11 = _query_exits(r11["db_path"])

        sl10 = round(ex10.get("sl_hit", 0) / n10 * 100, 1)
        sl11 = round(ex11.get("sl_hit", 0) / n11 * 100, 1)
        to10 = round(ex10.get("timeout", 0) / n10 * 100, 1)
        to11 = round(ex11.get("timeout", 0) / n11 * 100, 1)

        pf10, pf11 = t10["profit_factor"], t11["profit_factor"]

        lines.append(
            f"  {'Metrica':<14s} {'v1.0':>10s} {'v1.1':>10s} {'Delta':>10s}"
        )
        lines.append(f"  {'-' * 46}")
        lines.append(
            f"  {'PF':<14s} {_pf_str(pf10):>10s} {_pf_str(pf11):>10s}"
        )
        lines.append(
            f"  {'Win Rate':<14s} {t10['win_rate']:>9.1f}% "
            f"{t11['win_rate']:>9.1f}% "
            f"{t11['win_rate'] - t10['win_rate']:>+9.1f}%"
        )
        lines.append(
            f"  {'Total PnL':<14s} {t10['total_pnl']:>+9.2f}% "
            f"{t11['total_pnl']:>+9.2f}% "
            f"{t11['total_pnl'] - t10['total_pnl']:>+9.2f}%"
        )
        lines.append(
            f"  {'Edge Ratio':<14s} {m10['edge_ratio']:>10.2f} "
            f"{m11['edge_ratio']:>10.2f} "
            f"{m11['edge_ratio'] - m10['edge_ratio']:>+10.2f}"
        )
        lines.append(
            f"  {'SL Hit %':<14s} {sl10:>9.1f}% {sl11:>9.1f}% "
            f"{sl11 - sl10:>+9.1f}%"
        )
        lines.append(
            f"  {'Timeout %':<14s} {to10:>9.1f}% {to11:>9.1f}% "
            f"{to11 - to10:>+9.1f}%"
        )
        lines.append("")

        if pf10 == float("inf") or pf11 == float("inf"):
            pf_delta = 0.0
        else:
            pf_delta = pf11 - pf10

        if pf11 >= pf10:
            test2 = "PASS"
            lines.append("  Resultado: PASS — v1.1 igual ou melhor no holdout")
        elif pf_delta >= -0.10:
            test2 = "PASS"
            lines.append(
                f"  Resultado: PASS (marginal) — v1.1 levemente pior "
                f"(PF delta {pf_delta:+.2f})"
            )
        else:
            test2 = "FAIL"
            lines.append(
                f"  Resultado: FAIL — v1.1 regrediu no holdout "
                f"(PF delta {pf_delta:+.2f})"
            )
    lines.append("")

    # ── TEST 3: Regime Breakdown ────────────────────────────────────────
    lines.append("=" * 60)
    lines.append("  TEST 3: BREAKDOWN POR REGIME (120 dias)")
    lines.append("=" * 60)
    lines.append("")

    regime_pnls: dict[str, dict[str, list]] = {
        "v1.0": defaultdict(list),
        "v1.1": defaultdict(list),
    }
    for pname in all_results:
        for ver in ["v1.0", "v1.1"]:
            for t in _query_trades_raw(all_results[pname][ver]["db_path"]):
                regime_pnls[ver][t["regime"]].append(t["pnl_pct"])

    all_regimes = sorted(
        set(regime_pnls["v1.0"].keys()) | set(regime_pnls["v1.1"].keys()),
    )

    lines.append(
        f"  {'Regime':<14s} {'Ver':>5s} {'N':>5s} {'WR%':>6s} "
        f"{'PF':>6s} {'TotalPnL':>10s} {'Nota':>10s}"
    )
    lines.append(f"  {'-' * 60}")

    for regime in all_regimes:
        for ver in ["v1.0", "v1.1"]:
            pnls = regime_pnls[ver].get(regime, [])
            n = len(pnls)
            if n == 0:
                lines.append(f"  {regime:<14s} {ver:>5s}     0")
                continue

            wins = sum(1 for p in pnls if p > 0)
            wr = round(wins / n * 100, 1)
            total = round(sum(pnls), 4)
            pf = _pf(pnls)
            note = "n baixo" if n < MIN_SAMPLE else ""

            lines.append(
                f"  {regime:<14s} {ver:>5s} {n:>5d} {wr:>5.1f}% "
                f"{_pf_str(pf):>6s} {total:>+9.4f}% {note:>10s}"
            )
        lines.append("")

    # Evaluate: TRENDING must not collapse (>20% PF drop)
    trending_collapsed = False
    pnls_t10 = regime_pnls["v1.0"].get("TRENDING", [])
    pnls_t11 = regime_pnls["v1.1"].get("TRENDING", [])

    if len(pnls_t10) >= MIN_SAMPLE and len(pnls_t11) >= MIN_SAMPLE:
        pf_t10 = _pf(pnls_t10)
        pf_t11 = _pf(pnls_t11)
        if pf_t10 != float("inf") and pf_t11 < pf_t10 * 0.80:
            trending_collapsed = True

    if trending_collapsed:
        test3 = "FAIL"
        lines.append("  Resultado: FAIL — v1.1 colapsou em TRENDING")
    else:
        test3 = "PASS"
        lines.append(
            "  Resultado: PASS — v1.1 nao colapsou em nenhum regime"
        )
        wt10 = len(regime_pnls["v1.0"].get("WEAK_TREND", []))
        wt11 = len(regime_pnls["v1.1"].get("WEAK_TREND", []))
        if wt10 < MIN_SAMPLE or wt11 < MIN_SAMPLE:
            lines.append(
                f"  (cautela: WEAK_TREND com amostra baixa — "
                f"v1.0 n={wt10}, v1.1 n={wt11})"
            )
    lines.append("")

    # ── FINAL VERDICT ───────────────────────────────────────────────────
    lines.append("=" * 60)
    lines.append("  VEREDITO FINAL")
    lines.append("=" * 60)
    lines.append("")

    tests = [
        ("Consistencia Mensal", test1),
        ("Holdout OOS", test2),
        ("Breakdown Regime", test3),
    ]

    pass_count = sum(1 for _, r in tests if r == "PASS")
    fail_count = sum(1 for _, r in tests if r == "FAIL")
    inc_count = sum(1 for _, r in tests if r == "INCONCLUSIVO")

    for name, result in tests:
        lines.append(f"  {name:<25s}: {result}")
    lines.append("")

    if pass_count == 3:
        lines.append("  >>> v1.1 CONFIRMADA como baseline robusta <<<")
        lines.append("  >>> Liberada para AVALIACAO de paper trading <<<")
    elif pass_count >= 2 and fail_count == 0:
        lines.append("  >>> v1.1 CONFIRMADA com ressalvas <<<")
        lines.append(
            f"  >>> {inc_count} teste(s) inconclusivo(s) — "
            f"prosseguir com cautela <<<"
        )
    elif fail_count > 0:
        failed = [n for n, r in tests if r == "FAIL"]
        lines.append(
            f"  >>> v1.1 NAO CONFIRMADA — falhou em: "
            f"{', '.join(failed)} <<<"
        )
        lines.append("  >>> Considerar reverter para v1.0 <<<")
    else:
        lines.append(
            "  >>> INCONCLUSIVO — amostra insuficiente para decisao <<<"
        )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_robustness():
    print("=" * 60)
    print("  ROBUSTNESS CHECK — v1.0 vs v1.1")
    print("=" * 60)
    print(f"  Configs: {list(CONFIGS.keys())}")
    print(f"  Periods: {[p[0] for p in PERIODS]}")
    print(f"  Min sample: {MIN_SAMPLE}")
    print()

    # --- Fetch 120 days of data once ---
    end_dt = datetime.now(timezone.utc)
    # +2 days buffer for WINDOW warmup on the holdout period
    start_15m = end_dt - timedelta(days=TOTAL_DAYS + 2)
    start_1h = end_dt - timedelta(days=TOTAL_DAYS + WARMUP_DAYS)
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

    DB_DIR.mkdir(parents=True, exist_ok=True)

    # --- Run all (period × version) combinations ---
    all_results: dict = {}

    for pname, d_start, d_end in PERIODS:
        print()
        dt_s = end_dt - timedelta(days=d_start)
        dt_e = end_dt - timedelta(days=d_end) if d_end > 0 else end_dt
        print(f"  === {pname} ({dt_s:%Y-%m-%d} → {dt_e:%Y-%m-%d}) ===")

        period_data, n_steps = slice_period_data(
            all_data, end_dt, d_start, d_end,
        )
        print(f"  Steps: {n_steps}")

        if n_steps == 0:
            print("  SKIP — no data for this period")
            continue

        all_results[pname] = {}

        for ver, config in CONFIGS.items():
            print(f"    --- {ver} ---")
            db_path = DB_DIR / f"{pname}_{ver.replace('.', '_')}.db"
            report = replay_period(
                f"{pname}/{ver}", config, db_path, period_data, n_steps,
            )
            all_results[pname][ver] = {"report": report, "db_path": db_path}

    # --- Build and save comparison ---
    print()
    comparison = build_comparison(all_results, end_dt)

    report_path = DB_DIR / "comparison.txt"
    report_path.write_text(comparison, encoding="utf-8")

    print(comparison)
    print(f"  Saved to: {report_path}")

    return all_results


if __name__ == "__main__":
    run_robustness()
