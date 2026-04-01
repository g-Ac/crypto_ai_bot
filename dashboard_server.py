"""
Dashboard Web — painel de controle do Crypto AI Bot.
Acesso: http://<ip-do-pi>:5000

Rotas:
  GET  /            — painel principal
  GET  /comparison  — comparador visual entre runtimes
  GET  /scalping/outcomes — replay rotulado do scalping
  GET  /scalping/scorer — scorer historico de setups
  GET  /api/status  — JSON com todos os dados (auto-refresh AJAX)
  GET  /api/compare — JSON com comparacao entre runtimes
  GET  /api/scalping/audit — trilha detalhada do scalping
  GET  /api/scalping/outcomes — labels forward do scalping
  GET  /api/scalping/scorer — score historico por familia de setup
  GET  /api/scalping/outcomes/export — gera dataset JSON/JSONL/CSV
  POST /pause       — pausa o bot
  POST /resume      — retoma o bot
  GET  /api/trades  — historico de trades com filtro de periodo
  GET  /api/logs    — logs recentes de qualquer subsistema
"""
import os
import json
import shutil
import time
import functools
import base64
from collections import Counter, deque
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from flask import Flask, render_template, redirect, url_for, jsonify, request, Response
import database as db
from compare_instances import build_snapshot, compare_snapshots
from database import (
    get_all_time_stats,
    get_scalping_audit_log,
    get_scalping_funnel_stats,
    get_scalping_outcome_labels,
    get_stats_by_symbol,
    get_trades_range,
)
from telegram_commands import is_paused, _set_paused
from daily_report import calc_daily_stats, get_capital_status
from config import PAPER_INITIAL_CAPITAL, AGENT_INITIAL_CAPITAL, PUMP_INITIAL_CAPITAL, SCALPING_INITIAL_CAPITAL, DASHBOARD_USER, DASHBOARD_PASS
from scalping_research import build_scalping_scorer_report, export_outcomes_dataset
from signal_types import ScalpingConfig
from runtime_config import (
    APP_DIR,
    BOT_ID,
    BOT_LABEL,
    DASHBOARD_PORT,
    LOG_DIR,
    PAPER_STATE_FILE,
    AGENT_STATE_FILE,
    PUMP_STATE_FILE,
    RUNTIME_BASE_DIR,
    SCALPING_STATE_FILE,
    runtime_metadata,
)

APP_ROOT = str(APP_DIR)
app = Flask(__name__, template_folder=os.path.join(APP_ROOT, "templates"))

# ── HTTP Basic Auth para rotas POST (controle) ──────────────────────────────
# Protege endpoints que mudam estado (pause/resume).
# Credenciais vem de config.py (que le env vars DASHBOARD_USER / DASHBOARD_PASS).
# Se ambas estiverem vazias, auth fica desabilitada — WARNING e' logado na inicializacao.
_DASHBOARD_USER = DASHBOARD_USER
_DASHBOARD_PASS = DASHBOARD_PASS
_AUTH_ENABLED = bool(_DASHBOARD_USER and _DASHBOARD_PASS)


def _check_basic_auth(auth_header):
    """Valida header Authorization: Basic <base64(user:pass)>."""
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        user, password = decoded.split(":", 1)
        return user == _DASHBOARD_USER and password == _DASHBOARD_PASS
    except Exception:
        return False


def require_post_auth(fn):
    """Decorator: exige HTTP Basic Auth em rotas POST quando credenciais estao configuradas."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if _AUTH_ENABLED and not _check_basic_auth(request.headers.get("Authorization", "")):
            return Response(
                "Autenticacao necessaria para esta operacao.\n",
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="Dashboard Control"'},
            )
        return fn(*args, **kwargs)
    return wrapper


_PRICE_CACHE = {"fetched_at": 0.0, "prices": {}}
_RESEARCH_CACHE = {"fetched_at": 0.0, "payload": None}
SYSTEM_META = {
    "paper": {"label": "Paper Trading", "color": "#5fb7ff"},
    "agent": {"label": "Multi-Agent", "color": "#35d08f"},
    "pump": {"label": "Pump Scanner", "color": "#ff9f66"},
    "scalping": {"label": "Scalping", "color": "#b592ff"},
}


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_json(path, default=None):
    if default is None:
        default = {}
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _build_system_leaderboard(capital: dict, stats_today: dict, metrics_per_system: dict) -> list[dict]:
    rows = []
    for key, meta in SYSTEM_META.items():
        capital_row = capital.get(key) or {}
        day_row = stats_today.get(key) or {}
        metrics_row = metrics_per_system.get(key) or {}
        rows.append({
            "key": key,
            "label": meta["label"],
            "color": meta["color"],
            "capital_value": round(_safe_float(capital_row.get("value")), 2),
            "return_pct": round(_safe_float(capital_row.get("ret")), 2),
            "today_pnl_usd": round(_safe_float(day_row.get("pnl_usd")), 2),
            "today_trades": _safe_int(day_row.get("count")),
            "today_wins": _safe_int(day_row.get("wins")),
            "today_losses": _safe_int(day_row.get("losses")),
            "win_rate": round(_safe_float(metrics_row.get("win_rate")), 2),
            "profit_factor": round(_safe_float(metrics_row.get("profit_factor")), 2),
            "avg_pnl_pct": round(_safe_float(metrics_row.get("avg_pnl_pct")), 2),
            "max_drawdown_pct": round(_safe_float(metrics_row.get("max_drawdown_pct")), 2),
            "total_trades": _safe_int(metrics_row.get("total_trades")),
            "circuit_breaker": bool(capital_row.get("cb")),
        })

    rows.sort(
        key=lambda item: (
            item["return_pct"],
            item["today_pnl_usd"],
            item["profit_factor"],
            item["win_rate"],
        ),
        reverse=True,
    )
    return rows


def _collect_top_setup_candidates(report: dict, limit: int = 6) -> list[dict]:
    ordered_buckets = (
        ("promising", report.get("top_promising") or []),
        ("watch", report.get("watchlist") or []),
        ("insufficient", report.get("insufficient") or []),
        ("avoid", report.get("top_avoid") or []),
    )
    results = []
    seen = set()

    for recommendation, rows in ordered_buckets:
        for row in rows:
            setup_key = row.get("setup_key") or f"{recommendation}:{len(results)}"
            if setup_key in seen:
                continue
            seen.add(setup_key)
            results.append({
                "setup_key": setup_key,
                "recommendation": recommendation,
                "scenario_type": row.get("scenario_type") or "unknown",
                "event_outcome": row.get("event_outcome") or "unknown",
                "best_signal_source": row.get("best_signal_source") or "unknown",
                "direction": row.get("direction") or "UNKNOWN",
                "complete_actionable": _safe_int(row.get("complete_actionable")),
                "total": _safe_int(row.get("total")),
                "win_rate": round(_safe_float(row.get("win_rate")), 2),
                "avg_close_return_60m_pct": round(_safe_float(row.get("avg_close_return_60m_pct")), 4),
                "profit_gap_60m_vs_5m_pct": round(_safe_float(row.get("profit_gap_60m_vs_5m_pct")), 4),
                "edge_score": round(_safe_float(row.get("edge_score")), 2),
                "top_reason": row.get("top_reason") or "",
            })
            if len(results) >= limit:
                return results

    return results


def _build_strategy_research_snapshot() -> dict:
    outcomes_payload = _build_scalping_outcomes_payload(days=7, limit=250)
    scorer_report = build_scalping_scorer_report(days=30, limit=5000)

    outcomes_summary = outcomes_payload.get("summary") or {}
    scorer_summary = scorer_report.get("summary") or {}

    return {
        "generated_at": scorer_report.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "outcomes_summary": outcomes_summary,
        "scorer_summary": scorer_summary,
        "top_reasons": (outcomes_summary.get("top_reasons") or [])[:6],
        "top_setups": _collect_top_setup_candidates(scorer_report, limit=6),
        "recommendation_counts": {
            "promising": _safe_int(scorer_summary.get("promising_groups")),
            "watch": _safe_int(scorer_summary.get("watch_groups")),
            "avoid": _safe_int(scorer_summary.get("avoid_groups")),
            "insufficient": _safe_int(scorer_summary.get("insufficient_groups")),
        },
    }


def _get_strategy_research_snapshot(max_age_seconds: int = 180) -> dict:
    now = time.time()
    cached_payload = _RESEARCH_CACHE.get("payload")
    cached_at = _safe_float(_RESEARCH_CACHE.get("fetched_at"))
    if cached_payload and (now - cached_at) < max_age_seconds:
        return cached_payload

    try:
        payload = _build_strategy_research_snapshot()
    except Exception:
        return cached_payload or {
            "generated_at": "",
            "outcomes_summary": {},
            "scorer_summary": {},
            "top_reasons": [],
            "top_setups": [],
            "recommendation_counts": {
                "promising": 0,
                "watch": 0,
                "avoid": 0,
                "insufficient": 0,
            },
        }

    _RESEARCH_CACHE["payload"] = payload
    _RESEARCH_CACHE["fetched_at"] = now
    return payload


def _extract_host_name(host_value: str | None) -> str:
    if not host_value:
        return "127.0.0.1"
    if host_value.startswith("[") and "]" in host_value:
        return host_value.split("]", 1)[0].strip("[")
    if ":" in host_value:
        return host_value.rsplit(":", 1)[0]
    return host_value


def _discover_runtime_instances():
    base_dir = Path(RUNTIME_BASE_DIR)
    if not base_dir.exists():
        return []

    instances = []
    for child in sorted(base_dir.iterdir()):
        if not child.is_dir():
            continue
        manifest = _read_json(child / "runtime_manifest.json", {})
        bot_id = manifest.get("bot_id") or child.name
        label = manifest.get("label") or str(bot_id).upper()
        port = _safe_int(manifest.get("dashboard_port"), 0)
        version_tag = manifest.get("version_tag") or "unknown"
        instances.append({
            "bot_id": bot_id,
            "label": label,
            "dashboard_port": port,
            "version_tag": version_tag,
            "runtime_dir": str(child),
            "is_current": bot_id == BOT_ID,
        })
    return instances


def _default_compare_pair(instances, left=None, right=None):
    bot_ids = [item["bot_id"] for item in instances]

    if left and right:
        return left, right

    if "baseline" in bot_ids and "v2" in bot_ids:
        return left or "baseline", right or "v2"

    if BOT_ID in bot_ids and len(bot_ids) > 1:
        peer_id = next((item for item in bot_ids if item != BOT_ID), BOT_ID)
        return left or BOT_ID, right or peer_id

    if len(bot_ids) >= 2:
        return left or bot_ids[0], right or bot_ids[1]

    if len(bot_ids) == 1:
        only = bot_ids[0]
        return left or only, right or only

    return left or BOT_ID, right or BOT_ID


def _build_runtime_links(host_value=None, scheme="http"):
    host_name = _extract_host_name(host_value)
    links = []
    for item in _discover_runtime_instances():
        port = item.get("dashboard_port")
        if port:
            url = f"{scheme}://{host_name}:{port}/"
        else:
            url = "/"
        links.append({**item, "url": url})
    return links


def _build_comparison_payload(left=None, right=None, days=1):
    instances = _discover_runtime_instances()
    left, right = _default_compare_pair(instances, left=left, right=right)
    days = max(1, min(_safe_int(days, 1), 30))
    known_ids = {item["bot_id"] for item in instances}

    payload = {
        "ok": False,
        "instances": instances,
        "query": {
            "left": left,
            "right": right,
            "days": days,
        },
    }

    if len(instances) < 2:
        payload["error"] = "Ainda nao existem dois runtimes prontos para comparacao."
        return payload

    if left not in known_ids:
        payload["error"] = f"Runtime esquerdo nao encontrado: {left}"
        return payload

    if right not in known_ids:
        payload["error"] = f"Runtime direito nao encontrado: {right}"
        return payload

    if left == right:
        payload["error"] = "Escolha duas instancias diferentes para comparar."
        return payload

    left_dir = Path(RUNTIME_BASE_DIR) / left
    right_dir = Path(RUNTIME_BASE_DIR) / right
    payload["report"] = compare_snapshots(
        build_snapshot(left_dir, days),
        build_snapshot(right_dir, days),
    )
    payload["ok"] = True
    return payload


def _build_scalping_audit_payload(days=1, limit=100, outcome=""):
    days = max(1, min(_safe_int(days, 1), 30))
    limit = max(1, min(_safe_int(limit, 100), 500))
    outcome = (outcome or "").strip()

    rows = get_scalping_audit_log(limit=limit, days=days, outcome=outcome)
    outcome_counter = Counter()
    reason_counter = Counter()
    summary = {
        "events": len(rows),
        "opened": 0,
        "closed": 0,
        "wins": 0,
        "losses": 0,
        "blocked": 0,
        "realized_pnl_usd": 0.0,
        "forced_entries": 0,
    }

    for row in rows:
        event_outcome = row.get("outcome") or "unknown"
        outcome_counter[event_outcome] += 1

        reason = (row.get("reason") or "").strip()
        if reason:
            reason_counter[reason] += 1

        if event_outcome == "opened":
            summary["opened"] += 1

        if event_outcome.startswith("closed_"):
            summary["closed"] += 1
            pnl_usd = _safe_float(row.get("pnl_usd"), 0.0)
            summary["realized_pnl_usd"] += pnl_usd
            if pnl_usd > 0:
                summary["wins"] += 1
            elif pnl_usd < 0:
                summary["losses"] += 1

        if "block" in event_outcome or event_outcome in {"cooldown", "in_position", "ai_rejected", "risk_blocked"}:
            summary["blocked"] += 1

        if row.get("force_entry_applied"):
            summary["forced_entries"] += 1

    return {
        "ok": True,
        "query": {
            "days": days,
            "limit": limit,
            "outcome": outcome,
        },
        "summary": {
            **summary,
            "realized_pnl_usd": round(summary["realized_pnl_usd"], 2),
            "outcome_breakdown": dict(outcome_counter),
            "top_reasons": [{"reason": key, "count": value} for key, value in reason_counter.most_common(8)],
        },
        "rows": rows,
        "count": len(rows),
    }


def _build_scalping_outcomes_payload(days=7, limit=100, scenario_type="", verdict=""):
    days = max(1, min(_safe_int(days, 7), 30))
    limit = max(1, min(_safe_int(limit, 100), 500))
    scenario_type = (scenario_type or "").strip()
    verdict = (verdict or "").strip()

    rows = get_scalping_outcome_labels(
        limit=limit,
        days=days,
        scenario_type=scenario_type,
        verdict=verdict,
    )

    scenario_counter = Counter()
    verdict_counter = Counter()
    reason_counter = Counter()
    summary = {
        "labeled_events": len(rows),
        "complete_labels": 0,
        "partial_labels": 0,
        "actionable": 0,
        "winners": 0,
        "losers": 0,
        "blocked_winners": 0,
        "blocked_losers": 0,
        "forced_winners": 0,
        "forced_losers": 0,
        "executed_winners": 0,
        "executed_losers": 0,
    }
    close_ret_60 = []

    for row in rows:
        scenario = row.get("scenario_type") or "unknown"
        label_verdict = row.get("verdict") or "unknown"
        scenario_counter[scenario] += 1
        verdict_counter[label_verdict] += 1

        reason = (row.get("reason") or "").strip()
        if reason:
            reason_counter[reason] += 1

        if row.get("label_status") == "complete":
            summary["complete_labels"] += 1
        else:
            summary["partial_labels"] += 1

        if row.get("is_actionable"):
            summary["actionable"] += 1

        if row.get("winner_flag"):
            summary["winners"] += 1
            if scenario == "blocked":
                summary["blocked_winners"] += 1
            elif scenario == "forced":
                summary["forced_winners"] += 1
            elif scenario == "executed":
                summary["executed_winners"] += 1

        if row.get("loser_flag"):
            summary["losers"] += 1
            if scenario == "blocked":
                summary["blocked_losers"] += 1
            elif scenario == "forced":
                summary["forced_losers"] += 1
            elif scenario == "executed":
                summary["executed_losers"] += 1

        horizons = (row.get("details") or {}).get("horizons") or {}
        close_60 = ((horizons.get("60") or {}).get("close_return_pct"))
        if close_60 is not None:
            close_ret_60.append(_safe_float(close_60))

    summary["avg_close_return_60m_pct"] = round(
        sum(item for item in close_ret_60 if item is not None) / len(close_ret_60), 4
    ) if close_ret_60 else 0.0

    return {
        "ok": True,
        "query": {
            "days": days,
            "limit": limit,
            "scenario_type": scenario_type,
            "verdict": verdict,
        },
        "summary": {
            **summary,
            "scenario_breakdown": dict(scenario_counter),
            "verdict_breakdown": dict(verdict_counter),
            "top_reasons": [{"reason": key, "count": value} for key, value in reason_counter.most_common(8)],
        },
        "rows": rows,
        "count": len(rows),
    }


def _build_scalping_scorer_payload(days=30, limit=5000):
    days = max(1, min(_safe_int(days, 30), 90))
    limit = max(1, min(_safe_int(limit, 5000), 20000))

    report = build_scalping_scorer_report(days=days, limit=limit)
    export_info = export_outcomes_dataset(days=days, limit=limit)

    return {
        "ok": True,
        "query": {
            "days": days,
            "limit": limit,
        },
        "report": report,
        "export": export_info,
    }


def _extract_trade_timestamp(trade):
    return trade.get("timestamp") or trade.get("exit_time") or trade.get("entry_time") or ""


def _parse_trade_datetime(raw_ts):
    if not raw_ts:
        return None
    try:
        normalized = str(raw_ts).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _normalize_scalping_trade(trade):
    ts = _extract_trade_timestamp(trade)
    direction = trade.get("direction") or trade.get("type") or ""
    pnl_pct = trade.get("pnl_pct")
    if pnl_pct is None:
        entry = _safe_float(trade.get("entry_price"))
        exit_price = _safe_float(trade.get("exit_price"))
        if entry and exit_price:
            if str(direction).upper() in ("SHORT", "SELL"):
                pnl_pct = (entry - exit_price) / entry * 100
            else:
                pnl_pct = (exit_price - entry) / entry * 100
        else:
            pnl_pct = 0

    return {
        "timestamp": ts,
        "entry_time": trade.get("entry_time"),
        "exit_time": trade.get("exit_time"),
        "symbol": trade.get("symbol", "--"),
        "type": direction,
        "entry_price": _safe_float(trade.get("entry_price")),
        "exit_price": _safe_float(trade.get("exit_price")),
        "pnl_pct": round(_safe_float(pnl_pct), 4),
        "pnl_usd": round(_safe_float(trade.get("pnl_usd")), 2),
        "exit_reason": trade.get("exit_reason") or trade.get("reason") or "signal",
        "analyst_confidence": trade.get("analyst_confidence"),
        "capital_after": trade.get("capital_after"),
    }


def _get_scalping_history(days=None, limit=100):
    scalping_state = _read_json(SCALPING_STATE_FILE, {})
    history = scalping_state.get("history", [])
    if not history:
        return []

    cutoff = None
    today_only = False
    if days is not None and days > 0:
        cutoff = datetime.now() - timedelta(days=days)
    elif days == 0:
        today_only = True

    rows = []
    for trade in history:
        row = _normalize_scalping_trade(trade)
        row_dt = _parse_trade_datetime(row["timestamp"])
        if cutoff and row_dt and row_dt < cutoff:
            continue
        if today_only and (row.get("timestamp") or "")[:10] != date.today().isoformat():
            continue
        row["_sort_dt"] = row_dt or datetime.min
        rows.append(row)

    rows.sort(key=lambda item: item["_sort_dt"], reverse=True)
    if limit:
        rows = rows[:limit]

    for row in rows:
        row.pop("_sort_dt", None)
    return rows


def _compute_trade_metrics(trades):
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "avg_pnl_pct": 0,
            "largest_win": 0,
            "largest_loss": 0,
            "profit_factor": 0,
            "max_drawdown_pct": 0,
        }

    wins = [t for t in trades if _safe_float(t.get("pnl_pct")) > 0]
    losses = [t for t in trades if _safe_float(t.get("pnl_pct")) < 0]
    pnl_pct_values = [_safe_float(t.get("pnl_pct")) for t in trades]
    pnl_usd_values = [_safe_float(t.get("pnl_usd")) for t in trades]

    sum_wins = sum(value for value in pnl_usd_values if value > 0)
    sum_losses = abs(sum(value for value in pnl_usd_values if value < 0))
    capitals = [
        _safe_float(t.get("capital_after"))
        for t in trades
        if t.get("capital_after") not in (None, "")
    ]

    max_drawdown_pct = 0
    if capitals:
        peak = capitals[0]
        for capital in capitals:
            if capital > peak:
                peak = capital
            if peak > 0:
                dd = (peak - capital) / peak * 100
                if dd > max_drawdown_pct:
                    max_drawdown_pct = dd

    return {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "avg_pnl_pct": round(sum(pnl_pct_values) / len(pnl_pct_values), 2) if pnl_pct_values else 0,
        "largest_win": round(max(pnl_pct_values), 2) if pnl_pct_values else 0,
        "largest_loss": round(min(pnl_pct_values), 2) if pnl_pct_values else 0,
        "profit_factor": round(sum_wins / sum_losses, 2) if sum_losses > 0 else (99.0 if sum_wins > 0 else 0),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
    }


def _merge_cumulative_charts(charts_by_system):
    all_days = sorted({
        row["day"]
        for rows in charts_by_system.values()
        for row in rows
    })
    if not all_days:
        return []

    series_maps = {
        key: {row["day"]: _safe_float(row.get("pnl")) for row in rows}
        for key, rows in charts_by_system.items()
    }
    running = {key: 0.0 for key in charts_by_system.keys()}
    merged = []

    for day in all_days:
        total = 0.0
        for key, series_map in series_maps.items():
            if day in series_map:
                running[key] = series_map[day]
            total += running[key]
        merged.append({"day": day, "pnl": round(total, 2)})

    return merged


def _get_market_prices(symbols_needed):
    if not symbols_needed:
        return {}

    now = time.time()
    cache_age = now - _PRICE_CACHE["fetched_at"]
    if _PRICE_CACHE["prices"] and cache_age < 15:
        return {
            symbol: _PRICE_CACHE["prices"].get(symbol)
            for symbol in symbols_needed
            if symbol in _PRICE_CACHE["prices"]
        }

    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=2)
        if resp.status_code == 200:
            prices = {
                item["symbol"]: _safe_float(item["price"])
                for item in resp.json()
                if item.get("symbol")
            }
            _PRICE_CACHE["prices"] = prices
            _PRICE_CACHE["fetched_at"] = now
    except Exception:
        # Return stale cache on failure instead of empty dict
        return {
            symbol: _PRICE_CACHE["prices"].get(symbol)
            for symbol in symbols_needed
            if symbol in _PRICE_CACHE["prices"]
        }

    return {
        symbol: _PRICE_CACHE["prices"].get(symbol)
        for symbol in symbols_needed
        if symbol in _PRICE_CACHE["prices"]
    }


# ── SYSTEM HEALTH ────────────────────────────────────────────────────────────

def _get_bot_status():
    """Verifica se o bot esta operacional: processos vivos, ultimo ciclo recente, sem erros."""
    import subprocess
    status = {
        "main_bot": False,
        "pump_scanner": False,
        "dashboard": True,  # se estamos aqui, dashboard esta vivo
        "last_cycle_ok": False,
        "last_cycle_ago": "N/A",
        "errors_today": 0,
        "overall": "offline",  # offline, degraded, healthy
    }

    # Em modo multi-instancia, os logs do runtime isolado sao a melhor fonte.
    # pgrep fica apenas como fallback quando os logs nao existem.
    log_dir = str(LOG_DIR)
    today = datetime.now().strftime("%Y-%m-%d")
    main_log = os.path.join(log_dir, f"main_bot_{today}.log")
    if os.path.isfile(main_log):
        try:
            mtime = os.path.getmtime(main_log)
            age_seconds = (datetime.now() - datetime.fromtimestamp(mtime)).total_seconds()
            status["last_cycle_ago"] = f"{int(age_seconds)}s"
            status["last_cycle_ok"] = age_seconds < 600  # less than 10 min = healthy
            # Also mark main_bot alive if log was updated recently
            if age_seconds < 600:
                status["main_bot"] = True
        except Exception:
            pass

        # Count errors in today's log
        try:
            with open(main_log, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            status["errors_today"] = content.lower().count("[erro]") + content.lower().count("traceback")
        except Exception:
            pass

    # Also check pump scanner log
    pump_log = os.path.join(log_dir, f"pump_scanner_{today}.log")
    if os.path.isfile(pump_log):
        try:
            mtime = os.path.getmtime(pump_log)
            age_seconds = (datetime.now() - datetime.fromtimestamp(mtime)).total_seconds()
            if age_seconds < 120:  # pump runs every 60s
                status["pump_scanner"] = True
        except Exception:
            pass

    if not status["main_bot"]:
        try:
            result = subprocess.run(
                ["pgrep", "-f", "main.py"], capture_output=True, timeout=3
            )
            status["main_bot"] = result.returncode == 0
        except Exception:
            pass

    if not status["pump_scanner"]:
        try:
            result = subprocess.run(
                ["pgrep", "-f", "pump_scanner.py"], capture_output=True, timeout=3
            )
            status["pump_scanner"] = result.returncode == 0
        except Exception:
            pass

    # Overall status
    all_up = status["main_bot"] and status["pump_scanner"] and status["dashboard"]
    if all_up and status["last_cycle_ok"] and status["errors_today"] == 0:
        status["overall"] = "healthy"
    elif all_up and status["last_cycle_ok"]:
        status["overall"] = "degraded"  # running but has errors
    elif status["main_bot"]:
        status["overall"] = "degraded"
    else:
        status["overall"] = "offline"

    return status


def _get_system_health():
    """Coleta metricas de saude do sistema sem dependencia do psutil.
    Le /proc/ diretamente (Raspberry Pi / Linux), com fallback para Windows.
    """
    health = {}

    # --- CPU usage ---
    try:
        with open("/proc/stat", "r") as f:
            lines = f.readlines()
        # Primeira linha: cpu  user nice system idle iowait irq softirq ...
        parts = lines[0].split()
        idle = int(parts[4])
        total = sum(int(p) for p in parts[1:])
        # Sem snapshot anterior, reportamos cores disponiveis e idle %
        health["cpu_cores"] = os.cpu_count() or 1
        health["cpu_idle_ticks"] = idle
        health["cpu_total_ticks"] = total
        health["cpu_usage_pct"] = round((1 - idle / total) * 100, 1) if total > 0 else 0
    except Exception:
        health["cpu_cores"] = os.cpu_count() or 1
        health["cpu_usage_pct"] = "N/A"

    # --- RAM ---
    try:
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split()
                key = parts[0].rstrip(":")
                meminfo[key] = int(parts[1])  # em kB
        total_mb = meminfo.get("MemTotal", 0) / 1024
        avail_mb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / 1024
        used_mb = total_mb - avail_mb
        health["ram_total_mb"] = round(total_mb, 1)
        health["ram_used_mb"] = round(used_mb, 1)
        health["ram_usage_pct"] = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0
    except Exception:
        health["ram_total_mb"] = "N/A"
        health["ram_used_mb"] = "N/A"
        health["ram_usage_pct"] = "N/A"

    # --- Disk ---
    try:
        usage = shutil.disk_usage("/")
        total_gb = usage.total / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        health["disk_total_gb"] = round(total_gb, 1)
        health["disk_used_gb"] = round(used_gb, 1)
        health["disk_free_gb"] = round(free_gb, 1)
        health["disk_usage_pct"] = round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0
    except Exception:
        health["disk_total_gb"] = "N/A"
        health["disk_used_gb"] = "N/A"
        health["disk_free_gb"] = "N/A"
        health["disk_usage_pct"] = "N/A"

    # --- Temperature (Raspberry Pi) ---
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            raw = f.read().strip()
        health["temperature_c"] = round(int(raw) / 1000, 1)
    except Exception:
        health["temperature_c"] = "N/A"

    # --- Uptime ---
    try:
        with open("/proc/uptime", "r") as f:
            raw = f.read().strip()
        uptime_secs = float(raw.split()[0])
        days = int(uptime_secs // 86400)
        hours = int((uptime_secs % 86400) // 3600)
        mins = int((uptime_secs % 3600) // 60)
        health["uptime"] = f"{days}d {hours}h {mins}m"
        health["uptime_seconds"] = round(uptime_secs, 0)
    except Exception:
        health["uptime"] = "N/A"
        health["uptime_seconds"] = "N/A"

    return health


# ── RECENT LOGS ──────────────────────────────────────────────────────────────

def _get_recent_logs(source="main", lines=30):
    """Le as ultimas N linhas de um arquivo de log.

    source="main"     → logs/main_bot_YYYY-MM-DD.log
    source="scalping"  → logs/scalping.log
    source="pump"      → logs/pump_scanner_YYYY-MM-DD.log
    """
    logs_dir = str(LOG_DIR)
    today = date.today().isoformat()

    if source == "main":
        log_file = os.path.join(logs_dir, f"main_bot_{today}.log")
    elif source == "scalping":
        log_file = os.path.join(logs_dir, "scalping.log")
    elif source == "pump":
        log_file = os.path.join(logs_dir, f"pump_scanner_{today}.log")
    else:
        log_file = os.path.join(logs_dir, f"{source}.log")

    if not os.path.isfile(log_file):
        return []

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            tail = deque(f, maxlen=lines)
        return [line.rstrip("\n\r") for line in tail]
    except Exception:
        return []


# ── LIVE POSITIONS ───────────────────────────────────────────────────────────

def _get_live_positions():
    """Le posicoes abertas dos arquivos de estado e adiciona P&L ao vivo via Binance."""
    state_files = [
        (PAPER_STATE_FILE, "Paper"),
        (AGENT_STATE_FILE, "Agent"),
        (PUMP_STATE_FILE, "Pump"),
    ]

    raw = []
    symbols_needed = set()

    # --- Paper, Agent, Pump positions ---
    for path, system in state_files:
        state = _read_json(path, {})
        for sym, pos in state.get("positions", {}).items():
            symbols_needed.add(sym)
            entry = {
                "system":      system,
                "symbol":      sym,
                "type":        pos.get("type", ""),
                "entry_price": _safe_float(pos.get("entry_price")),
                "sl_price":    pos.get("sl_price"),
                "tp_price":    pos.get("tp_price"),
            }
            if system == "Agent" and "analyst_confidence" in pos:
                entry["analyst_confidence"] = pos["analyst_confidence"]
            raw.append(entry)

    # --- Scalping positions (different field names) ---
    scalping_state = _read_json(SCALPING_STATE_FILE, {})
    for sym, pos in scalping_state.get("positions", {}).items():
        symbols_needed.add(sym)
        raw.append({
            "system":           "Scalping",
            "symbol":           sym,
            "type":             pos.get("direction", ""),
            "entry_price":      _safe_float(pos.get("entry_price")),
            "sl_price":         pos.get("sl_price"),
            "tp1_price":        pos.get("tp1_price"),
            "tp2_price":        pos.get("tp2_price"),
            "tp_price":         pos.get("tp1_price"),
            "leverage":         pos.get("leverage", 1),
            "confluence_score": pos.get("confluence_score", 0),
            "tp1_hit":          pos.get("tp1_hit", False),
            "position_size_usd": _safe_float(pos.get("position_size_usd")),
            "source":           pos.get("source", ""),
        })

    if not raw:
        return []

    prices = _get_market_prices(symbols_needed)

    # Calcula P&L ao vivo para cada posicao
    for pos in raw:
        entry = pos["entry_price"]
        current = prices.get(pos["symbol"])
        if current and entry:
            direction = pos["type"].upper()
            if direction in ("LONG", "BUY"):
                pos["pnl_pct"] = round((current - entry) / entry * 100, 2)
            else:
                pos["pnl_pct"] = round((entry - current) / entry * 100, 2)
            pos["current_price"] = current
        else:
            pos["pnl_pct"]       = None
            pos["current_price"] = None

    return raw


# ── HELPERS ──────────────────────────────────────────────────────────────────

def _build_status(include_logs=True, include_trades=True):
    """Coleta todos os dados necessarios para o dashboard."""
    paused = is_paused()

    # Capital atual de cada sistema (lido dos arquivos de estado)
    caps = get_capital_status()
    paper_cap = caps.get("Paper", PAPER_INITIAL_CAPITAL)
    agent_cap = caps.get("Agent", AGENT_INITIAL_CAPITAL)
    pump_cap  = caps.get("Pump",  PUMP_INITIAL_CAPITAL)

    # Scalping capital (from scalping_state.json)
    scalping_cap = SCALPING_INITIAL_CAPITAL
    scalping_state = _read_json(SCALPING_STATE_FILE, {})
    scalping_cap = _safe_float(
        scalping_state.get("capital", SCALPING_INITIAL_CAPITAL),
        SCALPING_INITIAL_CAPITAL,
    )
    scalping_trades_30d = _get_scalping_history(days=30, limit=500)
    scalping_recent = _get_scalping_history(days=1, limit=100)
    today_str = date.today().isoformat()
    scalping_today = [
        trade for trade in scalping_recent
        if (trade.get("timestamp") or "")[:10] == today_str
    ]
    scalping_total_trades = _safe_int(scalping_state.get("total_trades"), len(scalping_trades_30d))

    def _ret(current, initial):
        return round((current - initial) / initial * 100, 2) if initial else 0

    # Trades de hoje
    paper_today = db.get_trades_today("paper_trades")
    agent_today = db.get_trades_today("agent_trades")
    pump_today  = db.get_trades_today("pump_trades")

    paper_stats = calc_daily_stats(paper_today)
    agent_stats = calc_daily_stats(agent_today)
    pump_stats  = calc_daily_stats(pump_today)

    scalping_stats_today = calc_daily_stats(scalping_today)

    # Posicoes abertas com P&L ao vivo
    positions = _get_live_positions()

    # Trades de hoje por sistema
    paper_recent = paper_today
    agent_recent = agent_today
    pump_recent = pump_today

    # Dados do grafico P&L acumulado (30 dias)
    def _cumulative(daily_rows):
        """Converte P&L diario em acumulado para o grafico."""
        result = []
        acc = 0.0
        for row in daily_rows:
            acc += float(row.get("daily_pnl") or 0)
            result.append({"day": row["day"], "pnl": round(acc, 2)})
        return result

    paper_chart = _cumulative(db.get_cumulative_pnl("paper_trades", 30))
    agent_chart = _cumulative(db.get_cumulative_pnl("agent_trades", 30))
    pump_chart  = _cumulative(db.get_cumulative_pnl("pump_trades",  30))

    # Scalping chart (from scalping_state.json history)
    scalping_chart = []
    daily_pnl = {}
    for trade in scalping_trades_30d:
        ts = trade.get("timestamp", "")
        if ts:
            day = ts[:10]
            daily_pnl[day] = daily_pnl.get(day, 0) + _safe_float(trade.get("pnl_usd"))
    acc = 0.0
    for day in sorted(daily_pnl.keys()):
        acc += daily_pnl[day]
        scalping_chart.append({"day": day, "pnl": round(acc, 2)})

    # Circuit breaker status (read-only, no Telegram alerts)
    from daily_report import check_circuit_breaker
    cb_paper = check_circuit_breaker("paper")
    cb_agent = check_circuit_breaker("agent")
    cb_pump  = check_circuit_breaker("pump")
    cb_scalping = check_circuit_breaker("scalping")

    # Advanced metrics (30 days) -- per system
    metrics_per_system = {
        "paper":    get_all_time_stats("paper_trades", 30),
        "agent":    get_all_time_stats("agent_trades", 30),
        "pump":     get_all_time_stats("pump_trades",  30),
        "scalping": _compute_trade_metrics(scalping_trades_30d),
    }

    all_totals = sum(m["total_trades"] for m in metrics_per_system.values())
    all_wins = sum(
        m.get("win_rate", 0) * m["total_trades"] / 100
        for m in metrics_per_system.values()
        if m["total_trades"]
    )
    all_wins = int(all_wins)
    combined_win_rate = (all_wins / all_totals * 100) if all_totals > 0 else 0

    all_largest_win = max((m.get("largest_win", 0) for m in metrics_per_system.values()), default=0)
    all_largest_loss = min((m.get("largest_loss", 0) for m in metrics_per_system.values()), default=0)
    all_max_dd = max((m.get("max_drawdown_pct", 0) for m in metrics_per_system.values()), default=0)

    sum_pf_num = sum(m.get("profit_factor", 0) * m["total_trades"] for m in metrics_per_system.values() if m["total_trades"])
    sum_pf_den = sum(m["total_trades"] for m in metrics_per_system.values() if m["total_trades"])
    combined_pf = (sum_pf_num / sum_pf_den) if sum_pf_den > 0 else 0
    combined_avg = sum(m.get("avg_pnl_pct", 0) * m["total_trades"] for m in metrics_per_system.values() if m["total_trades"])
    combined_avg = (combined_avg / sum_pf_den) if sum_pf_den > 0 else 0

    metrics = {
        "total_trades": all_totals,
        "win_rate": round(combined_win_rate, 1),
        "profit_factor": round(combined_pf, 2),
        "max_drawdown_pct": round(all_max_dd, 2),
        "largest_win": round(all_largest_win, 2),
        "largest_loss": round(all_largest_loss, 2),
        "avg_pnl_pct": round(combined_avg, 2),
        "per_system": metrics_per_system,
    }

    # Per-symbol performance (30 days) -- merge all systems
    by_symbol_raw = {}
    for table in ["paper_trades", "agent_trades", "pump_trades"]:
        for row in get_stats_by_symbol(table, 30):
            sym = row["symbol"]
            if sym not in by_symbol_raw:
                by_symbol_raw[sym] = {"symbol": sym, "trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
            by_symbol_raw[sym]["trades"] += row["trades"]
            by_symbol_raw[sym]["wins"] += row["wins"]
            by_symbol_raw[sym]["losses"] += row["losses"]
            by_symbol_raw[sym]["total_pnl"] += _safe_float(row["total_pnl"])

    for trade in scalping_trades_30d:
        sym = trade.get("symbol", "--")
        if sym not in by_symbol_raw:
            by_symbol_raw[sym] = {"symbol": sym, "trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
        by_symbol_raw[sym]["trades"] += 1
        pnl_pct = _safe_float(trade.get("pnl_pct"))
        if pnl_pct > 0:
            by_symbol_raw[sym]["wins"] += 1
        elif pnl_pct < 0:
            by_symbol_raw[sym]["losses"] += 1
        by_symbol_raw[sym]["total_pnl"] += _safe_float(trade.get("pnl_usd"))

    by_symbol = sorted(by_symbol_raw.values(), key=lambda x: x["total_pnl"], reverse=True)
    for s in by_symbol:
        s["total_pnl"] = round(s["total_pnl"], 2)
        s["avg_pnl_pct"] = round(s["total_pnl"] / s["trades"], 2) if s["trades"] else 0

    charts = {
        "paper": paper_chart,
        "agent": agent_chart,
        "pump": pump_chart,
        "scalping": scalping_chart,
    }
    charts["total"] = _merge_cumulative_charts({
        "paper": paper_chart,
        "agent": agent_chart,
        "pump": pump_chart,
        "scalping": scalping_chart,
    })

    capital = {
        "paper": {"value": round(paper_cap, 2), "ret": _ret(paper_cap, PAPER_INITIAL_CAPITAL), "cb": cb_paper},
        "agent": {"value": round(agent_cap, 2), "ret": _ret(agent_cap, AGENT_INITIAL_CAPITAL), "cb": cb_agent},
        "pump": {"value": round(pump_cap, 2), "ret": _ret(pump_cap, PUMP_INITIAL_CAPITAL), "cb": cb_pump},
        "scalping": {"value": round(scalping_cap, 2), "ret": _ret(scalping_cap, SCALPING_INITIAL_CAPITAL), "cb": cb_scalping},
    }
    stats_today = {
        "paper": paper_stats,
        "agent": agent_stats,
        "pump": pump_stats,
        "scalping": scalping_stats_today,
    }
    total_initial_capital = (
        PAPER_INITIAL_CAPITAL
        + AGENT_INITIAL_CAPITAL
        + PUMP_INITIAL_CAPITAL
        + SCALPING_INITIAL_CAPITAL
    )
    portfolio_value = sum(system["value"] for system in capital.values())
    total_chart = charts["total"]
    total_curve_current = total_chart[-1]["pnl"] if total_chart else 0
    total_curve_peak = max((point["pnl"] for point in total_chart), default=0)
    best_system_key = max(capital.keys(), key=lambda key: capital[key]["ret"])

    summary = {
        "portfolio_value": round(portfolio_value, 2),
        "portfolio_ret": _ret(portfolio_value, total_initial_capital),
        "today_pnl_usd": round(sum(_safe_float(item.get("pnl_usd")) for item in stats_today.values()), 2),
        "curve_current": round(total_curve_current, 2),
        "curve_peak": round(total_curve_peak, 2),
        "curve_drawdown": round(total_curve_peak - total_curve_current, 2),
        "best_system": {
            "key": best_system_key,
            "ret": capital[best_system_key]["ret"],
            "value": capital[best_system_key]["value"],
        },
        "open_positions": len(positions),
    }

    # System health
    health = _get_system_health()

    # Bot operational status -- checks if processes are alive and last cycle was recent
    bot_status = _get_bot_status()
    scalping_funnel = get_scalping_funnel_stats(days=1)
    strategy_leaderboard = _build_system_leaderboard(capital, stats_today, metrics_per_system)
    strategy_research = _get_strategy_research_snapshot()

    logs = _get_recent_logs(source="main", lines=20) if include_logs else []

    status = {
        "paused": paused,
        "last_update": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "instance": runtime_metadata(),
        "capital": capital,
        "stats_today": stats_today,
        "summary": summary,
        "positions": positions,
        "chart": charts,
        "metrics": metrics,
        "by_symbol": by_symbol,
        "health": health,
        "bot_status": bot_status,
        "scalping_funnel": scalping_funnel,
        "insights": {
            "system_leaderboard": strategy_leaderboard,
            "research": strategy_research,
        },
        "logs": logs,
    }

    if include_trades:
        status["trades"] = {
            "paper": paper_recent,
            "agent": agent_recent,
            "pump": pump_recent,
            "scalping": scalping_today,
        }
    else:
        status["trades"] = {}

    return status


# ── ROTAS ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    status = _build_status(include_logs=True, include_trades=True)
    runtime_links = _build_runtime_links(request.host, request.scheme)
    default_left, default_right = _default_compare_pair(runtime_links)
    comparison_url = url_for("comparison_page", left=default_left, right=default_right, days=1)
    audit_url = url_for("scalping_audit_page", days=1, limit=100)
    outcomes_url = url_for("scalping_outcomes_page", days=7, limit=100)
    scorer_url = url_for("scalping_scorer_page", days=30, limit=5000)
    return render_template(
        "index.html",
        dashboard=status,
        runtime_links=runtime_links,
        comparison_url=comparison_url,
        audit_url=audit_url,
        outcomes_url=outcomes_url,
        scorer_url=scorer_url,
        comparison_pair_label=f"{default_left} x {default_right}",
    )


@app.route("/api/status")
def api_status():
    return jsonify(_build_status(include_logs=False, include_trades=False))


@app.route("/api/version")
def api_version():
    return jsonify(runtime_metadata())


@app.route("/comparison")
def comparison_page():
    payload = _build_comparison_payload(
        left=request.args.get("left"),
        right=request.args.get("right"),
        days=request.args.get("days", "1"),
    )
    payload["runtime_links"] = _build_runtime_links(request.host, request.scheme)
    return render_template("comparison.html", comparison=payload)


@app.route("/scalping/audit")
def scalping_audit_page():
    payload = _build_scalping_audit_payload(
        days=request.args.get("days", "1"),
        limit=request.args.get("limit", "100"),
        outcome=request.args.get("outcome", ""),
    )
    payload["runtime_links"] = _build_runtime_links(request.host, request.scheme)
    payload["instance"] = runtime_metadata()
    return render_template("scalping_audit.html", audit=payload)


@app.route("/scalping/outcomes")
def scalping_outcomes_page():
    payload = _build_scalping_outcomes_payload(
        days=request.args.get("days", "7"),
        limit=request.args.get("limit", "100"),
        scenario_type=request.args.get("scenario_type", ""),
        verdict=request.args.get("verdict", ""),
    )
    payload["runtime_links"] = _build_runtime_links(request.host, request.scheme)
    payload["instance"] = runtime_metadata()
    return render_template("scalping_outcomes.html", outcomes=payload)


@app.route("/scalping/scorer")
def scalping_scorer_page():
    payload = _build_scalping_scorer_payload(
        days=request.args.get("days", "30"),
        limit=request.args.get("limit", "5000"),
    )
    payload["runtime_links"] = _build_runtime_links(request.host, request.scheme)
    payload["instance"] = runtime_metadata()
    return render_template("scalping_scorer.html", scorer=payload)


@app.route("/api/compare")
def api_compare():
    payload = _build_comparison_payload(
        left=request.args.get("left"),
        right=request.args.get("right"),
        days=request.args.get("days", "1"),
    )
    payload["runtime_links"] = _build_runtime_links(request.host, request.scheme)
    status_code = 200 if payload.get("ok") else 400
    return jsonify(payload), status_code


@app.route("/api/scalping/audit")
def api_scalping_audit():
    payload = _build_scalping_audit_payload(
        days=request.args.get("days", "1"),
        limit=request.args.get("limit", "100"),
        outcome=request.args.get("outcome", ""),
    )
    return jsonify(payload)


@app.route("/api/scalping/outcomes")
def api_scalping_outcomes():
    payload = _build_scalping_outcomes_payload(
        days=request.args.get("days", "7"),
        limit=request.args.get("limit", "100"),
        scenario_type=request.args.get("scenario_type", ""),
        verdict=request.args.get("verdict", ""),
    )
    return jsonify(payload)


@app.route("/api/scalping/scorer")
def api_scalping_scorer():
    payload = _build_scalping_scorer_payload(
        days=request.args.get("days", "30"),
        limit=request.args.get("limit", "5000"),
    )
    return jsonify(payload)


@app.route("/api/scalping/outcomes/export")
def api_scalping_outcomes_export():
    days = max(1, min(_safe_int(request.args.get("days", "30"), 30), 90))
    limit = max(1, min(_safe_int(request.args.get("limit", "5000"), 5000), 20000))
    payload = {
        "ok": True,
        "query": {
            "days": days,
            "limit": limit,
        },
        "export": export_outcomes_dataset(days=days, limit=limit),
    }
    return jsonify(payload)


@app.route("/pause", methods=["POST"])
@require_post_auth
def pause():
    _set_paused(True)
    return redirect(url_for("index"))


@app.route("/resume", methods=["POST"])
@require_post_auth
def resume():
    _set_paused(False)
    return redirect(url_for("index"))


@app.route("/api/trades")
def api_trades():
    """Historico de trades com filtro de periodo.

    Query params:
      system — paper, agent, pump (default: paper)
      days   — quantidade de dias para trás (default: 7)
    """
    system = request.args.get("system", "paper").lower()
    days = request.args.get("days", "7")

    try:
        days = int(days)
    except ValueError:
        days = 7

    table_map = {
        "paper": "paper_trades",
        "agent": "agent_trades",
        "pump":  "pump_trades",
    }

    if system == "scalping":
        trades = _get_scalping_history(days=days, limit=150)
    else:
        table = table_map.get(system)
        if not table:
            return jsonify({"error": f"unknown system: {system}"}), 400
        trades = get_trades_range(table, days=days)

    return jsonify({"trades": trades})


@app.route("/api/logs")
def api_logs():
    """Logs recentes de um subsistema.

    Query params:
      source — main, scalping, pump (default: main)
      lines  — quantidade de linhas (default: 50)
    """
    ALLOWED_LOG_SOURCES = {"main", "scalping", "pump", "main_bot", "pump_scanner", "dashboard", "supervisor"}

    source = request.args.get("source", "main")
    if source not in ALLOWED_LOG_SOURCES:
        return jsonify({"error": f"invalid log source: {source}"}), 400

    lines = request.args.get("lines", "50")

    try:
        lines = int(lines)
    except ValueError:
        lines = 50

    # Limita a 500 linhas para nao sobrecarregar
    lines = min(lines, 500)

    log_lines = _get_recent_logs(source=source, lines=lines)
    return jsonify({"logs": log_lines})


# ── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    if not _AUTH_ENABLED:
        print(
            "WARNING: Dashboard rodando SEM autenticacao nas rotas POST (pause/resume).\n"
            "         Qualquer dispositivo na rede pode controlar o bot.\n"
            "         Defina DASHBOARD_USER e DASHBOARD_PASS para proteger."
        )
    else:
        print(f"Dashboard auth habilitada (user: {_DASHBOARD_USER})")
    print(f"Dashboard {BOT_ID} ({BOT_LABEL}) disponivel em http://0.0.0.0:{DASHBOARD_PORT}")
    # host=0.0.0.0 permite acesso pela rede local (celular no mesmo Wi-Fi)
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False)
