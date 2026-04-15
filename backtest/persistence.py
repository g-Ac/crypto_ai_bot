"""Persist backtest artifacts to disk — one directory per run.

Every backtest execution MUST produce:
  - metrics.json    — aggregate metrics
  - trades.csv      — full trade ledger
  - decisions.csv   — decision log (every cycle)
  - coverage.json   — data quality report
  - report.md       — human-readable report

Directory structure:
  data/backtest_runs/<run_id>/
    metrics.json
    trades.csv
    decisions.csv
    coverage.json
    report.md
"""
from __future__ import annotations

import csv
import json
import logging
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from backtest.metrics import FunnelStats, compute_metrics
from backtest.report import build_report
from defensive.models import BacktestRunMeta, ClosedTrade, TradeDecision

logger = logging.getLogger(__name__)

RUNS_DIR = Path("data/backtest_runs")


def _get_git_sha() -> str:
    """Get current git SHA, or 'unknown' if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def save_run(
    meta: BacktestRunMeta,
    trades: List[ClosedTrade],
    decisions: List[TradeDecision],
    coverage: Optional[Dict] = None,
    compare_trades: Optional[Dict[str, List[ClosedTrade]]] = None,
) -> Path:
    """Save all backtest artifacts to disk.

    Args:
        meta: Run metadata.
        trades: Closed trades.
        decisions: All pipeline decisions.
        coverage: Data quality report dict.
        compare_trades: Optional comparison strategies.

    Returns:
        Path to the run directory.
    """
    run_dir = RUNS_DIR / meta.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Fill git SHA if missing
    if not meta.git_sha:
        meta.git_sha = _get_git_sha()

    # 1. metrics.json
    metrics = compute_metrics(trades)
    metrics_dict = asdict(metrics)
    metrics_dict["run_id"] = meta.run_id
    metrics_dict["strategy"] = meta.strategy.value
    metrics_dict["config_hash"] = meta.config_hash
    metrics_dict["param_version"] = meta.param_version
    metrics_dict["git_sha"] = meta.git_sha
    metrics_dict["period_start"] = meta.period_start
    metrics_dict["period_end"] = meta.period_end
    metrics_dict["candles_total"] = meta.candles_total

    _write_json(run_dir / "metrics.json", metrics_dict)

    # 2. trades.csv
    _write_trades_csv(run_dir / "trades.csv", trades)

    # 3. decisions.csv
    _write_decisions_csv(run_dir / "decisions.csv", decisions)

    # 4. coverage.json
    coverage_data = coverage or {
        "coverage_ohlcv_pct": meta.coverage_ohlcv_pct,
        "coverage_oi_pct": meta.coverage_oi_pct,
        "coverage_liquidations_pct": meta.coverage_liquidations_pct,
        "coverage_funding_pct": meta.coverage_funding_pct,
        "coverage_basis_pct": meta.coverage_basis_pct,
        "candles_total": meta.candles_total,
        "candles_eligible_enhanced": meta.candles_eligible_enhanced,
        "gaps_detected": meta.gaps_detected,
        "gap_details": meta.gap_details,
        "dataset_id": meta.dataset_id,
        "period_start": meta.period_start,
        "period_end": meta.period_end,
    }
    _write_json(run_dir / "coverage.json", coverage_data)

    # 5. report.md
    report_text = build_report(
        meta, trades, decisions,
        config_hash=meta.config_hash,
        compare_trades=compare_trades,
    )
    (run_dir / "report.md").write_text(report_text, encoding="utf-8")

    logger.info("Backtest artifacts saved to %s", run_dir)
    return run_dir


def _write_json(path: Path, data: Dict) -> None:
    """Write dict as formatted JSON."""
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _write_trades_csv(path: Path, trades: List[ClosedTrade]) -> None:
    """Write trades to CSV with all fields."""
    if not trades:
        path.write_text("", encoding="utf-8")
        return

    rows = []
    for t in trades:
        d = asdict(t)
        # Flatten enums to values
        for k, v in d.items():
            if hasattr(v, "value"):
                d[k] = v.value
            elif isinstance(v, list):
                d[k] = ";".join(str(getattr(x, "value", x)) for x in v)
        rows.append(d)

    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_decisions_csv(path: Path, decisions: List[TradeDecision]) -> None:
    """Write decisions to CSV (flat, no nested objects)."""
    if not decisions:
        path.write_text("", encoding="utf-8")
        return

    rows = []
    for d in decisions:
        row = {
            "timestamp": d.timestamp,
            "cycle_id": d.cycle_id,
            "symbol": d.symbol,
            "strategy": d.strategy.value,
            "outcome": d.outcome.value,
            "regime": d.regime.value,
            "session": d.session.value,
            "direction": d.direction.value,
            "compression_active": d.compression.active,
            "compression_percentile": d.compression.bb_width_percentile,
            "breakout_detected": d.breakout.detected,
            "breakout_direction": d.breakout.direction.value,
            "breakout_volume_ratio": d.breakout.volume_ratio,
            "reclaim_detected": d.reclaim_detected,
            "trap_confirmed": d.trap.confirmed,
            "trap_score": d.trap.score,
            "trap_evidence": ";".join(e.value for e in d.trap.evidence),
            "entry_price": d.entry_price,
            "sl_price": d.sl_price,
            "tp1_price": d.tp1_price,
            "z_score": d.z_score,
            "daily_loss_pct": d.daily_loss_pct,
            "consecutive_losses": d.consecutive_losses,
            "config_version": d.config_version,
            "param_version": d.param_version,
        }
        rows.append(row)

    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def list_runs() -> List[Dict]:
    """List all saved backtest runs with summary info."""
    if not RUNS_DIR.exists():
        return []

    runs = []
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        metrics_file = run_dir / "metrics.json"
        if metrics_file.exists():
            data = json.loads(metrics_file.read_text(encoding="utf-8"))
            runs.append({
                "run_id": run_dir.name,
                "strategy": data.get("strategy", ""),
                "total_trades": data.get("total_trades", 0),
                "profit_factor": data.get("profit_factor", 0),
                "period": f"{data.get('period_start', '')} → {data.get('period_end', '')}",
            })
    return runs
