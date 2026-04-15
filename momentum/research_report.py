"""Research Mode reporting for Momentum Pullback.

Two public functions:
  generate_report(db_path, days) → structured dict
  format_report(report)          → human-readable text

No dashboard, no HTML — just data and text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from momentum.research_db import get_decisions, get_trades


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_report(
    db_path: str | Path,
    *,
    days: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a structured report from research data.

    Args:
        db_path: Path to the research SQLite database.
        days: Only include data from the last N days.

    Returns:
        Nested dict with sections: overview, funnel, trades, exits,
        mfe_mae, retracement, breakdowns, research_flags.
    """
    decisions = get_decisions(db_path, days=days)
    all_trades = get_trades(db_path, days=days)
    closed = [t for t in all_trades if t["exit_price"] is not None]
    open_trades = [t for t in all_trades if t["exit_price"] is None]

    return {
        "overview": _overview(decisions, all_trades, closed, open_trades),
        "funnel": _funnel(decisions),
        "trades": _trade_stats(closed),
        "exits": _exit_breakdown(closed),
        "mfe_mae": _mfe_mae_stats(closed),
        "retracement": _retracement_distribution(decisions),
        "breakdowns": _breakdowns(closed),
        "research_flags": _research_flags(closed),
    }


def format_report(report: Dict[str, Any]) -> str:
    """Render a generate_report() dict as human-readable text."""
    lines: list[str] = []
    _fmt_overview(lines, report["overview"])
    _fmt_funnel(lines, report["funnel"])
    _fmt_trades(lines, report["trades"])
    _fmt_exits(lines, report["exits"])
    _fmt_mfe_mae(lines, report["mfe_mae"])
    _fmt_retracement(lines, report["retracement"])
    _fmt_breakdowns(lines, report["breakdowns"])
    _fmt_research_flags(lines, report["research_flags"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _overview(
    decisions: list, trades: list, closed: list, open_trades: list,
) -> Dict[str, Any]:
    return {
        "total_decisions": len(decisions),
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_trades": len(open_trades),
    }


def _funnel(decisions: list) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for d in decisions:
        outcome = d.get("outcome", "unknown")
        counts[outcome] = counts.get(outcome, 0) + 1

    total = len(decisions)
    pcts: Dict[str, float] = {}
    for k, v in counts.items():
        pcts[k] = round(v / total * 100, 1) if total > 0 else 0.0

    return {"counts": counts, "percentages": pcts, "total": total}


def _trade_stats(closed: list) -> Dict[str, Any]:
    if not closed:
        return _empty_trade_stats()

    pnls = [t["pnl_pct"] for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0

    return {
        "count": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1),
        "avg_pnl": round(sum(pnls) / len(pnls), 4),
        "total_pnl": round(sum(pnls), 4),
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "profit_factor": (
            round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")
        ),
        "avg_duration": round(
            sum(t["duration_candles"] or 0 for t in closed) / len(closed), 1
        ),
    }


def _empty_trade_stats() -> Dict[str, Any]:
    return {
        "count": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
        "avg_pnl": 0.0, "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        "profit_factor": 0.0, "avg_duration": 0.0,
    }


def _exit_breakdown(closed: list) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    pnls: Dict[str, list] = {}
    for t in closed:
        reason = t.get("exit_reason", "unknown")
        counts[reason] = counts.get(reason, 0) + 1
        pnls.setdefault(reason, []).append(t["pnl_pct"])

    breakdown: Dict[str, Any] = {}
    for reason in counts:
        reason_pnls = pnls[reason]
        breakdown[reason] = {
            "count": counts[reason],
            "avg_pnl": round(sum(reason_pnls) / len(reason_pnls), 4),
            "total_pnl": round(sum(reason_pnls), 4),
        }
    return breakdown


def _mfe_mae_stats(closed: list) -> Dict[str, Any]:
    if not closed:
        return {
            "avg_mfe": 0.0, "avg_mae": 0.0,
            "max_mfe": 0.0, "worst_mae": 0.0,
            "edge_ratio": 0.0,
        }

    mfes = [t["mfe_pct"] for t in closed]
    maes = [t["mae_pct"] for t in closed]
    avg_mfe = sum(mfes) / len(mfes)
    avg_mae = sum(maes) / len(maes)

    return {
        "avg_mfe": round(avg_mfe, 4),
        "avg_mae": round(avg_mae, 4),
        "max_mfe": round(max(mfes), 4),
        "worst_mae": round(min(maes), 4),
        "edge_ratio": (
            round(avg_mfe / abs(avg_mae), 2) if avg_mae != 0 else float("inf")
        ),
    }


def _retracement_distribution(decisions: list) -> Dict[str, Any]:
    """Analyse retracement_pct from TRADE decisions.

    Returns mean, median, buckets (10% wide), and near-boundary counts.
    """
    values = [
        d["retracement_pct"]
        for d in decisions
        if d.get("outcome") == "trade" and d.get("retracement_pct", 0) > 0
    ]

    if not values:
        return _empty_retracement()

    values_sorted = sorted(values)
    n = len(values_sorted)
    mean = sum(values_sorted) / n
    median = (
        values_sorted[n // 2]
        if n % 2 == 1
        else (values_sorted[n // 2 - 1] + values_sorted[n // 2]) / 2
    )

    # Buckets: 30-40, 40-50, 50-60, 60-70
    buckets = {"30-40": 0, "40-50": 0, "50-60": 0, "60-70": 0}
    for v in values_sorted:
        if v < 40:
            buckets["30-40"] += 1
        elif v < 50:
            buckets["40-50"] += 1
        elif v < 60:
            buckets["50-60"] += 1
        else:
            buckets["60-70"] += 1

    # Near-boundary: within 5% of the 30% and 70% limits
    near_30 = sum(1 for v in values_sorted if v <= 35)
    near_70 = sum(1 for v in values_sorted if v >= 65)

    return {
        "count": n,
        "mean": round(mean, 2),
        "median": round(median, 2),
        "min": round(values_sorted[0], 2),
        "max": round(values_sorted[-1], 2),
        "buckets": buckets,
        "near_30_count": near_30,
        "near_70_count": near_70,
    }


def _empty_retracement() -> Dict[str, Any]:
    return {
        "count": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0,
        "buckets": {"30-40": 0, "40-50": 0, "50-60": 0, "60-70": 0},
        "near_30_count": 0, "near_70_count": 0,
    }


def _breakdowns(closed: list) -> Dict[str, Any]:
    return {
        "by_regime": _breakdown_by(closed, "regime"),
        "by_session": _breakdown_by(closed, "session_bucket"),
        "by_direction": _breakdown_by(closed, "direction"),
    }


def _breakdown_by(closed: list, field: str) -> Dict[str, Any]:
    groups: Dict[str, list] = {}
    for t in closed:
        key = t.get(field, "unknown") or "unknown"
        groups.setdefault(key, []).append(t["pnl_pct"])

    result: Dict[str, Any] = {}
    for key, pnls in sorted(groups.items()):
        wins = sum(1 for p in pnls if p > 0)
        result[key] = {
            "count": len(pnls),
            "wins": wins,
            "win_rate": round(wins / len(pnls) * 100, 1),
            "avg_pnl": round(sum(pnls) / len(pnls), 4),
            "total_pnl": round(sum(pnls), 4),
        }
    return result


def _research_flags(closed: list) -> Dict[str, Any]:
    if not closed:
        return {
            "retested_impulse_end": 0, "retested_pct": 0.0,
            "lost_pullback_extreme": 0, "lost_pct": 0.0,
        }

    retested = sum(1 for t in closed if t.get("retested_impulse_end"))
    lost = sum(1 for t in closed if t.get("lost_pullback_extreme"))
    n = len(closed)

    return {
        "retested_impulse_end": retested,
        "retested_pct": round(retested / n * 100, 1),
        "lost_pullback_extreme": lost,
        "lost_pct": round(lost / n * 100, 1),
    }


# ---------------------------------------------------------------------------
# Text formatters
# ---------------------------------------------------------------------------

def _fmt_overview(lines: list, o: dict) -> None:
    lines.append("=" * 50)
    lines.append("MOMENTUM PULLBACK — RESEARCH REPORT")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"Decisions registradas: {o['total_decisions']}")
    lines.append(f"Trades totais:         {o['total_trades']}")
    lines.append(f"  Fechados:            {o['closed_trades']}")
    lines.append(f"  Abertos:             {o['open_trades']}")
    lines.append("")


def _fmt_funnel(lines: list, f: dict) -> None:
    lines.append("--- FUNIL DE DECISOES ---")
    if f["total"] == 0:
        lines.append("  (sem dados)")
        lines.append("")
        return
    for outcome, count in sorted(f["counts"].items(), key=lambda x: -x[1]):
        pct = f["percentages"][outcome]
        lines.append(f"  {outcome:<25s} {count:>5d}  ({pct:>5.1f}%)")
    lines.append("")


def _fmt_trades(lines: list, t: dict) -> None:
    lines.append("--- PERFORMANCE ---")
    if t["count"] == 0:
        lines.append("  (sem trades fechados)")
        lines.append("")
        return
    lines.append(f"  Trades fechados:   {t['count']}")
    lines.append(f"  Win rate:          {t['win_rate']:.1f}% ({t['wins']}W / {t['losses']}L)")
    lines.append(f"  PnL medio:         {t['avg_pnl']:+.4f}%")
    lines.append(f"  PnL total:         {t['total_pnl']:+.4f}%")
    lines.append(f"  Media wins:        {t['avg_win']:+.4f}%")
    lines.append(f"  Media losses:      {t['avg_loss']:+.4f}%")
    pf = t["profit_factor"]
    pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
    lines.append(f"  Profit factor:     {pf_str}")
    lines.append(f"  Duracao media:     {t['avg_duration']:.1f} candles")
    lines.append("")


def _fmt_exits(lines: list, exits: dict) -> None:
    lines.append("--- SAIDAS POR MOTIVO ---")
    if not exits:
        lines.append("  (sem dados)")
        lines.append("")
        return
    for reason, data in sorted(exits.items(), key=lambda x: -x[1]["count"]):
        lines.append(
            f"  {reason:<12s}  n={data['count']:>3d}  "
            f"avg={data['avg_pnl']:+.4f}%  total={data['total_pnl']:+.4f}%"
        )
    lines.append("")


def _fmt_mfe_mae(lines: list, m: dict) -> None:
    lines.append("--- MFE / MAE ---")
    if m["avg_mfe"] == 0 and m["avg_mae"] == 0:
        lines.append("  (sem dados)")
        lines.append("")
        return
    lines.append(f"  MFE medio:         {m['avg_mfe']:+.4f}%")
    lines.append(f"  MFE maximo:        {m['max_mfe']:+.4f}%")
    lines.append(f"  MAE medio:         {m['avg_mae']:+.4f}%")
    lines.append(f"  MAE pior:          {m['worst_mae']:+.4f}%")
    er = m["edge_ratio"]
    er_str = f"{er:.2f}" if er != float("inf") else "inf"
    lines.append(f"  Edge ratio:        {er_str}")
    lines.append("")


def _fmt_retracement(lines: list, r: dict) -> None:
    lines.append("--- DISTRIBUICAO RETRACEMENT (trades) ---")
    if r["count"] == 0:
        lines.append("  (sem dados)")
        lines.append("")
        return
    lines.append(f"  Sinais com trade:  {r['count']}")
    lines.append(f"  Media:             {r['mean']:.2f}%")
    lines.append(f"  Mediana:           {r['median']:.2f}%")
    lines.append(f"  Min / Max:         {r['min']:.2f}% / {r['max']:.2f}%")
    lines.append("  Faixas:")
    for bucket, count in r["buckets"].items():
        bar = "#" * count
        lines.append(f"    {bucket}%:  {count:>3d}  {bar}")
    lines.append(f"  Perto de 30% (<=35%): {r['near_30_count']}")
    lines.append(f"  Perto de 70% (>=65%): {r['near_70_count']}")
    lines.append("")


def _fmt_breakdowns(lines: list, b: dict) -> None:
    for label, key in [
        ("REGIME", "by_regime"),
        ("SESSAO", "by_session"),
        ("DIRECAO", "by_direction"),
    ]:
        lines.append(f"--- BREAKDOWN POR {label} ---")
        data = b[key]
        if not data:
            lines.append("  (sem dados)")
            lines.append("")
            continue
        for name, stats in sorted(data.items()):
            lines.append(
                f"  {name:<15s}  n={stats['count']:>3d}  "
                f"WR={stats['win_rate']:>5.1f}%  "
                f"avg={stats['avg_pnl']:+.4f}%  "
                f"total={stats['total_pnl']:+.4f}%"
            )
        lines.append("")


def _fmt_research_flags(lines: list, f: dict) -> None:
    lines.append("--- RESEARCH FLAGS ---")
    lines.append(
        f"  Retested impulse end:    {f['retested_impulse_end']} "
        f"({f['retested_pct']:.1f}%)"
    )
    lines.append(
        f"  Lost pullback extreme:   {f['lost_pullback_extreme']} "
        f"({f['lost_pct']:.1f}%)"
    )
    lines.append("")
