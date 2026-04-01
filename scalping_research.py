"""
Research lab para dataset e scorer do scalping.

Gera:
- dataset achatado em JSON/JSONL/CSV
- relatorio de scorer historico por familia de setup
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import database as db
from runtime_config import (
    SCALPING_OUTCOMES_CSV_FILE,
    SCALPING_OUTCOMES_JSON_FILE,
    SCALPING_OUTCOMES_JSONL_FILE,
    SCALPING_SCORER_REPORT_FILE,
)


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value, digits=4):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _best_signal_source(row: dict) -> str:
    details = row.get("details") or {}
    setup = details.get("setup") or {}
    source = setup.get("best_signal_source")
    return source or "no_signal"


def flatten_outcome_label(row: dict) -> dict:
    details = row.get("details") or {}
    setup = details.get("setup") or {}
    horizons = details.get("horizons") or {}
    eval_window = details.get("evaluation_window") or {}

    flat = {
        "label_id": row.get("id"),
        "audit_id": row.get("audit_id"),
        "audit_timestamp": row.get("audit_timestamp"),
        "labeled_at": row.get("labeled_at"),
        "symbol": row.get("symbol"),
        "scenario_type": row.get("scenario_type"),
        "event_outcome": row.get("event_outcome"),
        "verdict": row.get("verdict"),
        "reason": row.get("reason"),
        "direction": row.get("direction"),
        "best_signal_source": _best_signal_source(row),
        "force_entry_applied": int(bool(row.get("force_entry_applied"))),
        "is_actionable": int(bool(row.get("is_actionable"))),
        "winner_flag": int(bool(row.get("winner_flag"))),
        "loser_flag": int(bool(row.get("loser_flag"))),
        "label_status": row.get("label_status"),
        "max_labeled_horizon": row.get("max_labeled_horizon"),
        "first_touch": row.get("first_touch"),
        "first_touch_minutes": row.get("first_touch_minutes"),
        "time_to_tp1_minutes": row.get("time_to_tp1_minutes"),
        "time_to_tp2_minutes": row.get("time_to_tp2_minutes"),
        "time_to_sl_minutes": row.get("time_to_sl_minutes"),
        "reference_price": row.get("reference_price"),
        "entry_price": row.get("entry_price"),
        "sl_price": row.get("sl_price"),
        "tp1_price": row.get("tp1_price"),
        "tp2_price": row.get("tp2_price"),
        "has_trade_plan": int(bool(setup.get("has_trade_plan"))),
        "evaluation_start_time_utc": eval_window.get("start_time_utc"),
        "evaluation_end_time_utc": eval_window.get("end_time_utc"),
        "candles_fetched": eval_window.get("candles_fetched"),
    }

    for horizon in ("5", "15", "30", "60"):
        data = horizons.get(horizon) or {}
        flat[f"close_return_{horizon}m_pct"] = data.get("close_return_pct")
        flat[f"mfe_{horizon}m_pct"] = data.get("mfe_pct")
        flat[f"mae_{horizon}m_pct"] = data.get("mae_pct")
        flat[f"spot_up_{horizon}m_pct"] = data.get("spot_up_pct")
        flat[f"spot_down_{horizon}m_pct"] = data.get("spot_down_pct")
        flat[f"close_price_{horizon}m"] = data.get("close_price")
        flat[f"high_price_{horizon}m"] = data.get("high_price")
        flat[f"low_price_{horizon}m"] = data.get("low_price")

    return flat


def _write_json(path: str, payload: dict) -> str:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_jsonl(path: str, rows: list[dict]) -> str:
    target = Path(path)
    with target.open("w", encoding="utf-8", newline="") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _write_csv(path: str, rows: list[dict]) -> str:
    target = Path(path)
    fieldnames = sorted({key for row in rows for key in row.keys()}) if rows else []
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(rows)
    return path


def export_outcomes_dataset(days: int = 30, limit: int = 5000) -> dict:
    labels = db.get_scalping_outcome_labels(limit=limit, days=days)
    rows = [flatten_outcome_label(item) for item in labels]
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "days": days,
        "limit": limit,
        "count": len(rows),
        "rows": rows,
    }

    _write_json(SCALPING_OUTCOMES_JSON_FILE, payload)
    _write_jsonl(SCALPING_OUTCOMES_JSONL_FILE, rows)
    _write_csv(SCALPING_OUTCOMES_CSV_FILE, rows)

    return {
        "count": len(rows),
        "generated_at": payload["generated_at"],
        "files": {
            "json": SCALPING_OUTCOMES_JSON_FILE,
            "jsonl": SCALPING_OUTCOMES_JSONL_FILE,
            "csv": SCALPING_OUTCOMES_CSV_FILE,
        },
    }


def _group_key(row: dict) -> tuple[str, str, str, str]:
    return (
        row.get("scenario_type") or "unknown",
        row.get("event_outcome") or "unknown",
        _best_signal_source(row),
        row.get("direction") or "UNKNOWN",
    )


def _score_verdict(complete_actionable: int, win_rate: float, avg_60m: float, profit_gap: float) -> tuple[float, str]:
    if complete_actionable <= 0:
        return 0.0, "insufficient"

    sample_weight = min(complete_actionable / 20.0, 1.0)
    edge_score = ((win_rate - 50.0) * 1.2 + avg_60m * 18.0 + profit_gap * 12.0) * sample_weight
    edge_score = round(edge_score, 2)

    if complete_actionable < 5:
        return edge_score, "insufficient"
    if edge_score >= 18:
        return edge_score, "promising"
    if edge_score <= -18:
        return edge_score, "avoid"
    return edge_score, "watch"


def build_scalping_scorer_report(days: int = 30, limit: int = 5000) -> dict:
    labels = db.get_scalping_outcome_labels(limit=limit, days=days)
    groups: dict[tuple[str, str, str, str], dict] = {}

    for row in labels:
        key = _group_key(row)
        if key not in groups:
            groups[key] = {
                "scenario_type": key[0],
                "event_outcome": key[1],
                "best_signal_source": key[2],
                "direction": key[3],
                "reasons": defaultdict(int),
                "total": 0,
                "complete": 0,
                "partial": 0,
                "actionable": 0,
                "complete_actionable": 0,
                "winners": 0,
                "losers": 0,
                "close_return_5m": [],
                "close_return_15m": [],
                "close_return_30m": [],
                "close_return_60m": [],
            }

        bucket = groups[key]
        bucket["total"] += 1
        if row.get("label_status") == "complete":
            bucket["complete"] += 1
        else:
            bucket["partial"] += 1

        if row.get("is_actionable"):
            bucket["actionable"] += 1
            if row.get("label_status") == "complete":
                bucket["complete_actionable"] += 1
                if row.get("winner_flag"):
                    bucket["winners"] += 1
                if row.get("loser_flag"):
                    bucket["losers"] += 1

        reason = (row.get("reason") or "").strip()
        if reason:
            bucket["reasons"][reason] += 1

        horizons = (row.get("details") or {}).get("horizons") or {}
        for horizon in ("5", "15", "30", "60"):
            value = (horizons.get(horizon) or {}).get("close_return_pct")
            if value is not None:
                bucket[f"close_return_{horizon}m"].append(_safe_float(value))

    scored_groups = []
    summary = {
        "groups_total": len(groups),
        "scored_groups": 0,
        "promising_groups": 0,
        "watch_groups": 0,
        "avoid_groups": 0,
        "insufficient_groups": 0,
    }

    for bucket in groups.values():
        complete_actionable = int(bucket["complete_actionable"])
        winners = int(bucket["winners"])
        losers = int(bucket["losers"])
        decided = winners + losers
        win_rate = (winners / decided * 100.0) if decided else 0.0
        loss_rate = (losers / decided * 100.0) if decided else 0.0
        avg_60m = sum(bucket["close_return_60m"]) / len(bucket["close_return_60m"]) if bucket["close_return_60m"] else 0.0
        avg_15m = sum(bucket["close_return_15m"]) / len(bucket["close_return_15m"]) if bucket["close_return_15m"] else 0.0
        profit_gap = avg_60m - (sum(bucket["close_return_5m"]) / len(bucket["close_return_5m"]) if bucket["close_return_5m"] else 0.0)
        edge_score, recommendation = _score_verdict(complete_actionable, win_rate, avg_60m, profit_gap)

        summary["scored_groups"] += 1
        summary[f"{recommendation}_groups"] += 1

        top_reason = None
        if bucket["reasons"]:
            top_reason = max(bucket["reasons"].items(), key=lambda item: item[1])[0]

        scored_groups.append({
            "setup_key": " | ".join([
                bucket["scenario_type"],
                bucket["event_outcome"],
                bucket["best_signal_source"],
                bucket["direction"],
            ]),
            "scenario_type": bucket["scenario_type"],
            "event_outcome": bucket["event_outcome"],
            "best_signal_source": bucket["best_signal_source"],
            "direction": bucket["direction"],
            "total": bucket["total"],
            "complete": bucket["complete"],
            "partial": bucket["partial"],
            "actionable": bucket["actionable"],
            "complete_actionable": complete_actionable,
            "winners": winners,
            "losers": losers,
            "win_rate": round(win_rate, 2),
            "loss_rate": round(loss_rate, 2),
            "avg_close_return_5m_pct": _round(sum(bucket["close_return_5m"]) / len(bucket["close_return_5m"]), 4) if bucket["close_return_5m"] else 0.0,
            "avg_close_return_15m_pct": _round(avg_15m, 4),
            "avg_close_return_30m_pct": _round(sum(bucket["close_return_30m"]) / len(bucket["close_return_30m"]), 4) if bucket["close_return_30m"] else 0.0,
            "avg_close_return_60m_pct": _round(avg_60m, 4),
            "profit_gap_60m_vs_5m_pct": _round(profit_gap, 4),
            "edge_score": edge_score,
            "recommendation": recommendation,
            "top_reason": top_reason,
        })

    scored_groups.sort(key=lambda item: (item["recommendation"] != "promising", -item["edge_score"], -item["complete_actionable"], -item["total"]))

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "days": days,
        "limit": limit,
        "labels_considered": len(labels),
        "summary": summary,
        "top_promising": [item for item in scored_groups if item["recommendation"] == "promising"][:12],
        "top_avoid": [item for item in scored_groups if item["recommendation"] == "avoid"][:12],
        "watchlist": [item for item in scored_groups if item["recommendation"] == "watch"][:12],
        "insufficient": [item for item in scored_groups if item["recommendation"] == "insufficient"][:12],
        "groups": scored_groups,
    }

    _write_json(SCALPING_SCORER_REPORT_FILE, report)
    return report
