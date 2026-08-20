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
import glob
import json
import re
import shutil
import sqlite3
import time
import functools
import base64
from collections import Counter, deque
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from flask import Flask, render_template, redirect, url_for, jsonify, request, Response
import database as db
import market
import raiox_data
import mercado_data
import paper_data
import rotulagem_data
import rotulagem_levels
import rotulagem_candles
from compare_instances import build_snapshot, compare_snapshots
from database import (
    get_scalping_audit_log,
    get_scalping_funnel_stats,
    get_scalping_outcome_labels,
    get_trades_range,
)
from telegram_commands import is_paused, _set_paused
from daily_report import calc_daily_stats, get_capital_status
from config import MOMENTUM_INITIAL_CAPITAL, DASHBOARD_USER, DASHBOARD_PASS, BINANCE_SPOT_TICKER_URL
from scalping_research import build_scalping_scorer_report, export_outcomes_dataset
from signal_types import ScalpingConfig
from runtime_config import (
    APP_DIR,
    BOT_ID,
    BOT_LABEL,
    DASHBOARD_PORT,
    DB_FILE,
    LOG_DIR,
    MOMENTUM_STATE_FILE,
    RUNTIME_BASE_DIR,
    runtime_metadata,
    runtime_path,
)


APP_ROOT = str(APP_DIR)
app = Flask(__name__, template_folder=os.path.join(APP_ROOT, "templates"),
            static_folder=os.path.join(APP_ROOT, "static"))
# Flask cacheia templates em memoria quando debug=False. Sem auto-reload,
# editar templates exige restart do servico — bug silencioso dificil de cacar.
app.config["TEMPLATES_AUTO_RELOAD"] = True

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
# Unico sistema ativo. Paper/Agent/Pump/Scalping foram aposentados (CLAUDE.md);
# mante-los aqui rendia linhas de leaderboard com capital inicial estatico.
SYSTEM_META = {
    "momentum": {"label": "Momentum Pullback", "color": "#5fb7ff"},
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


_json_cache = {}
_json_cache_ts = 0


def _read_json(path, default=None):
    global _json_cache_ts
    if default is None:
        default = {}
    # Per-request cache: invalidate after 2s to avoid stale reads across requests
    now = time.monotonic()
    if now - _json_cache_ts > 2:
        _json_cache.clear()
        _json_cache_ts = now
    str_path = str(path)
    if str_path in _json_cache:
        return _json_cache[str_path]
    if not os.path.isfile(str_path):
        result = default
    else:
        try:
            with open(str_path, "r", encoding="utf-8") as f:
                result = json.load(f)
        except Exception:
            result = default
    _json_cache[str_path] = result
    return result


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
            # LIQUIDO quando o sistema reporta fee (momentum); o bruto fica ao
            # lado, explicito, para nao passar por retorno real.
            "capital_value": round(_safe_float(
                capital_row.get("net_value", capital_row.get("value"))), 2),
            "return_pct": round(_safe_float(
                capital_row.get("net_ret", capital_row.get("ret"))), 2),
            "gross_capital_value": round(_safe_float(capital_row.get("value")), 2),
            "gross_return_pct": round(_safe_float(capital_row.get("ret")), 2),
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
    # Sanitize: only allow alphanumeric, dash, underscore, dot (no path traversal)
    _SLUG_RE = re.compile(r'^[a-zA-Z0-9._-]+$')
    if left and not _SLUG_RE.match(left):
        return {"ok": False, "error": f"Invalid instance ID: {left}", "instances": [], "query": {}}
    if right and not _SLUG_RE.match(right):
        return {"ok": False, "error": f"Invalid instance ID: {right}", "instances": [], "query": {}}
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
        resp = requests.get(BINANCE_SPOT_TICKER_URL, timeout=2)
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

def _resolve_active_log(prefix):
    """Resolve o log ATIVO de um processo pelo mtime — nao pelo nome com a data.

    O supervisor calcula o nome uma unica vez no spawn (`supervisor.get_log_path`)
    e mantem o file handle aberto enquanto o processo vive: um run que atravessa a
    meia-noite continua escrevendo no arquivo do dia em que subiu. Montar
    f"{prefix}_{hoje}.log" cega o leitor a partir do 2o dia — foi o que deixou o
    dashboard sem ciclo e sem logs desde 2026-07-29 (supervisor de pe desde 28/07).
    """
    try:
        candidates = glob.glob(os.path.join(str(LOG_DIR), f"{prefix}_*.log"))
        return max(candidates, key=os.path.getmtime) if candidates else None
    except (OSError, ValueError):
        return None


# O handler de topo do loop do main.py imprime "Erro: {e}" — SEM colchetes
# (main.py). Contar so "[erro]" deixava passar justamente a falha que mata o
# ciclo. "(ignorado)" fica de fora de proposito: o proprio codigo declara que
# seguiu adiante, nao e erro de ciclo.
_ERROR_MARKERS = re.compile(r"(?:^|\W)(erro|error)\b|traceback \(most recent", re.I)
_ERROR_IGNORED = re.compile(r"\(ignorado\)", re.I)
_ERROR_TAIL_BYTES = 512 * 1024


def _count_recent_errors(log_path, tail_bytes=_ERROR_TAIL_BYTES):
    """Conta marcadores de erro na cauda do log ativo.

    Nao da para contar "erros de hoje": as linhas do main.py nao carregam
    timestamp de escrita (as datas no texto sao do candle, em UTC) e o journal do
    systemd fica vazio porque o supervisor redireciona stdout para arquivo. O log
    ativo acumula todos os dias do run atual, entao ler o arquivo inteiro somaria
    dias antigos e travaria o overall fora de "healthy" para sempre.

    Le por SEEK na cauda, nao com deque sobre o arquivo todo: o dashboard atualiza
    a cada 15s e o log ja passa de 8 MB (varrer tudo custava ~0,13s por refresh e
    cresce linearmente com o arquivo).
    """
    try:
        size = os.path.getsize(log_path)
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            if size > tail_bytes:
                f.seek(size - tail_bytes)
                f.readline()  # descarta a linha partida pelo seek
            lines = f.readlines()
    except OSError:
        return 0
    return sum(
        1 for line in lines
        if _ERROR_MARKERS.search(line) and not _ERROR_IGNORED.search(line)
    )


CYCLE_STALE_SECONDS = 660  # 2 ciclos de 5min + folga


def _get_cycle_age_seconds():
    """Idade do ultimo ciclo COMPLETO do main.py, em segundos (None se indeterminado).

    NAO usa o mtime do log: o supervisor abre o mesmo arquivo e escreve o banner
    "Iniciado em ..." a CADA respawn (supervisor.run_bot), e o backoff maximo dele
    e 300s — abaixo de qualquer limiar razoavel. Um main.py em crash loop manteria
    o log sempre fresco e o painel diria "healthy" sem um unico ciclo ter rodado:
    trocariamos o falso negativo antigo por um falso positivo, que e pior.

    `momentum_state.json` e reescrito por `save_state()` no fim de
    process_momentum_cycle, incondicionalmente — so existe se um ciclo completou.
    """
    try:
        return time.time() - os.path.getmtime(MOMENTUM_STATE_FILE)
    except OSError:
        return None


def _get_bot_status():
    """Verifica se o bot esta operacional: processo vivo, ciclo recente, sem erros."""
    import subprocess
    status = {
        "main_bot": False,
        "dashboard": True,  # se estamos aqui, dashboard esta vivo
        "last_cycle_ok": False,
        "last_cycle_ago": "N/A",
        "errors_recent": 0,
        "overall": "offline",  # offline, degraded, healthy
    }

    cycle_age = _get_cycle_age_seconds()
    if cycle_age is not None:
        status["last_cycle_ago"] = f"{int(cycle_age)}s"
        status["last_cycle_ok"] = cycle_age < CYCLE_STALE_SECONDS

    main_log = _resolve_active_log("main_bot")
    if main_log:
        status["errors_recent"] = _count_recent_errors(main_log)

    # O processo em si vem do pgrep, com escopo no caminho absoluto do runtime:
    # "-f main.py" casaria qualquer cmdline que contenha a string (outro BOT_ID,
    # um editor, o proprio shell desta checagem).
    try:
        result = subprocess.run(
            ["pgrep", "-f", os.path.join(str(APP_DIR), "main.py")],
            capture_output=True, timeout=3,
        )
        status["main_bot"] = result.returncode == 0
    except Exception:
        # Sem pgrep, um ciclo recente ainda e prova de vida.
        status["main_bot"] = bool(status["last_cycle_ok"])

    # Portao de saude: apenas os processos que o supervisor de fato gerencia
    # (supervisor.BOTS = main_bot + dashboard). O pump_scanner saiu daqui junto com
    # a aposentadoria do sistema — exigi-lo travava o overall em "degraded" para
    # sempre, porque `pgrep pump_scanner.py` nunca mais acha nada.
    all_up = status["main_bot"] and status["dashboard"]
    if all_up and status["last_cycle_ok"] and status["errors_recent"] == 0:
        status["overall"] = "healthy"
    elif all_up and status["last_cycle_ok"]:
        status["overall"] = "degraded"  # rodando, mas com erros
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

    source="main"      → logs/main_bot_*.log (o ativo, resolvido por mtime)
    source="scalping"  → logs/scalping.log
    source="pump"      → logs/pump_scanner_*.log (o ativo, resolvido por mtime)

    Resolve por mtime porque o nome carrega a data do SPAWN, nao a de hoje —
    ver `_resolve_active_log`.
    """
    logs_dir = str(LOG_DIR)

    if source == "main":
        log_file = _resolve_active_log("main_bot")
    elif source == "scalping":
        log_file = os.path.join(logs_dir, "scalping.log")
    elif source == "pump":
        log_file = _resolve_active_log("pump_scanner")
    elif re.match(r'^[a-zA-Z0-9_-]+$', source):
        log_file = os.path.join(logs_dir, f"{source}.log")
    else:
        return []

    if not log_file or not os.path.isfile(log_file):
        return []

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            tail = deque(f, maxlen=lines)
        return [line.rstrip("\n\r") for line in tail]
    except Exception:
        return []


# ── LIVE POSITIONS ───────────────────────────────────────────────────────────

def _get_live_positions():
    """Le posicoes abertas do momentum e adiciona P&L ao vivo via Binance.

    Momentum-only: os states de paper/agent/pump/scalping nao sao mais escritos
    por ninguem — liam sempre {} e so custavam I/O a cada refresh.
    """
    raw = []
    symbols_needed = set()

    momentum_state = _read_json(MOMENTUM_STATE_FILE, {})
    for sym, pos in (momentum_state.get("positions") or {}).items():
        symbols_needed.add(sym)
        raw.append({
            "system":            "Momentum",
            "symbol":            sym,
            "type":              pos.get("direction", ""),
            "entry_price":       _safe_float(pos.get("entry_price")),
            "sl_price":          pos.get("sl_price"),
            "tp1_price":         pos.get("tp1_price"),
            "tp2_price":         pos.get("tp2_price"),
            "tp_price":          pos.get("tp1_price"),
            "position_size_usd": _safe_float(pos.get("position_size_usd")),
            "regime":            pos.get("regime", ""),
            "open_time":         pos.get("open_time", ""),
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


# ── AI BRAIN ────────────────────────────────────────────────────────────────

def _get_raw_ai_decisions(limit: int = 50) -> list[dict]:
    """Fetch most recent raw AI decisions from the database."""
    try:
        conn = db._get_conn()
        rows = conn.execute(
            "SELECT * FROM ai_decisions ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _collect_trade_reviews(limit: int = 30) -> list[dict]:
    """Scan runtime trade_reviews/ for trade_review_report.json files."""
    reviews = []
    reviews_dir = Path(RUNTIME_BASE_DIR) / BOT_ID / "trade_reviews"
    if not reviews_dir.exists():
        return reviews

    try:
        dirs = sorted(reviews_dir.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True)
    except Exception:
        return reviews

    for child in dirs[:limit]:
        report_path = child / "trade_review_report.json"
        data = _read_json(str(report_path), None)
        if data is None:
            continue
        # Fields may be at top level or inside trade_identity
        identity = data.get("trade_identity") or {}
        reviews.append({
            "folder": child.name,
            "system": identity.get("system") or data.get("system", "unknown"),
            "symbol": identity.get("symbol") or data.get("symbol", "unknown"),
            "classification": data.get("classification", "unknown"),
            "root_causes": data.get("root_causes", []),
            "things_done_well": data.get("things_done_well", []),
            "mistakes": data.get("mistakes", []),
            "lesson_learned": data.get("lesson") or data.get("lesson_learned", ""),
            "timestamp": identity.get("timestamp") or data.get("timestamp", ""),
            "tags": data.get("tags", []),
        })
    return reviews


def _read_pattern_memory() -> dict:
    """Read the latest pattern_memory_report.json from runtime.

    Normalizes Counter.most_common() tuples into dicts for JSON/JS.
    """
    path = Path(RUNTIME_BASE_DIR) / BOT_ID / "pattern_memory_report.json"
    raw = _read_json(str(path), {})
    summary = raw.get("summary") or raw

    def _normalize_counter_list(items):
        """Convert [(label, count), ...] or [{"name":..., "count":...}] to uniform dicts."""
        result = []
        for item in (items or []):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                result.append({"label": str(item[0]), "count": int(item[1])})
            elif isinstance(item, dict):
                result.append(item)
        return result

    return {
        "top_mistakes": _normalize_counter_list(summary.get("top_mistakes", [])),
        "top_root_causes": _normalize_counter_list(summary.get("top_root_causes", [])),
        "top_lessons": _normalize_counter_list(summary.get("top_lessons", [])),
        "top_things_done_well": _normalize_counter_list(summary.get("top_things_done_well", [])),
        "top_tags": _normalize_counter_list(summary.get("top_tags", [])),
        "top_classifications": _normalize_counter_list(summary.get("top_classifications", [])),
        "synthesis": raw.get("synthesis"),
    }


def _read_validation_audit() -> dict:
    """Read the latest validation_audit_report.json from runtime.

    Normalizes the per-system data into a flat dict the JS can render.
    """
    path = Path(RUNTIME_BASE_DIR) / BOT_ID / "strategy_validation_report.json"
    raw = _read_json(str(path), {})
    systems_raw = raw.get("systems") or {}

    per_system = {}
    for key, data in systems_raw.items():
        m = data.get("metrics") or {}
        exp = data.get("expectancy") or {}
        per_system[key] = {
            "total_trades": _safe_int(m.get("total_trades")),
            "win_rate": _safe_float(m.get("win_rate")),
            "profit_factor": _safe_float(m.get("profit_factor")),
            "expectancy": _safe_float(exp.get("expectancy_pct") or exp.get("per_trade")),
            "max_drawdown_pct": _safe_float(m.get("max_drawdown_pct")),
            "total_pnl_usd": _safe_float(m.get("total_pnl_usd")),
            "verdict": data.get("verdict", "unknown"),
        }

    return {
        "generated_at": raw.get("generated_at", ""),
        "days": _safe_int(raw.get("days")),
        "portfolio_summary": raw.get("portfolio_summary") or {},
        "per_system": per_system,
    }


def _build_ai_brain_payload() -> dict:
    """Collect all AI Brain data for the dashboard."""
    try:
        ai_summary = db.get_ai_decisions_summary(days=30)
    except Exception:
        ai_summary = {
            "total": 0, "approvals": 0, "approval_rate": 0,
            "avg_confidence": 0, "avg_latency_ms": 0,
            "by_system": {}, "by_prompt_version": {},
            "fallbacks": 0, "parse_failures": 0,
        }

    raw_decisions = _get_raw_ai_decisions(limit=50)
    trade_reviews = _collect_trade_reviews(limit=30)
    pattern_memory = _read_pattern_memory()
    validation_audit = _read_validation_audit()

    return {
        "summary": ai_summary,
        "decisions": raw_decisions,
        "trade_reviews": trade_reviews,
        "pattern_memory": pattern_memory,
        "validation_audit": validation_audit,
    }


# ── MOMENTUM (unico sistema ativo) ───────────────────────────────────────────
#
# Helpers proprios porque os genericos de database.py (get_all_time_stats,
# get_cumulative_pnl, get_stats_by_symbol) somam pnl_pct/pnl_usd/capital_after —
# todos BRUTOS. No momentum a fee e ~2x o edge bruto: os mesmos 283 trades dao
# +3,96% no gross e -24,67% no liquido. Tudo abaixo le net_pnl_*, caindo para o
# gross so quando a fee nao foi medida (linhas antigas com net NULL).

def _net_pnl_pct(trade):
    value = trade.get("net_pnl_pct")
    return _safe_float(trade.get("pnl_pct")) if value in (None, "") else _safe_float(value)


def _net_pnl_usd(trade):
    value = trade.get("net_pnl_usd")
    return _safe_float(trade.get("pnl_usd")) if value in (None, "") else _safe_float(value)


def _compute_momentum_metrics(trades, initial_capital):
    """Metricas do momentum pelo LIQUIDO. Espelha _compute_trade_metrics."""
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0, "avg_pnl_pct": 0,
            "largest_win": 0, "largest_loss": 0, "profit_factor": 0,
            "max_drawdown_pct": 0, "is_net": True,  # vazio: nada bruto entrou
        }

    pct_values = [_net_pnl_pct(t) for t in trades]
    usd_values = [_net_pnl_usd(t) for t in trades]
    wins = [v for v in pct_values if v > 0]
    sum_wins = sum(v for v in usd_values if v > 0)
    sum_losses = abs(sum(v for v in usd_values if v < 0))

    # capital_after e bruto: reconstroi a curva liquida do inicio para o drawdown.
    # get_* devolve o mais recente primeiro, entao inverte para ficar cronologico.
    equity, running = [], _safe_float(initial_capital)
    for value in reversed(usd_values):
        running += value
        equity.append(running)
    peak, max_drawdown_pct = equity[0] if equity else 0, 0
    for capital in equity:
        peak = max(peak, capital)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - capital) / peak * 100)

    return {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_pnl_pct": round(sum(pct_values) / len(pct_values), 2),
        "largest_win": round(max(pct_values), 2),
        "largest_loss": round(min(pct_values), 2),
        "profit_factor": round(sum_wins / sum_losses, 2) if sum_losses > 0 else 0,
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        # False quando algum trade caiu no fallback gross (fee nao medida) —
        # o painel nao deve afirmar "liquido" sobre um agregado misto.
        "is_net": all(t.get("net_pnl_usd") not in (None, "") for t in trades),
    }


def _momentum_equity_chart(trades):
    """PnL LIQUIDO acumulado por dia (mesma forma dos charts antigos)."""
    daily = {}
    for trade in trades:
        day = (trade.get("timestamp") or "")[:10]
        if day:
            daily[day] = daily.get(day, 0.0) + _net_pnl_usd(trade)
    chart, acc = [], 0.0
    for day in sorted(daily):
        acc += daily[day]
        chart.append({"day": day, "pnl": round(acc, 2)})
    return chart


def _momentum_by_symbol(trades):
    """Performance por simbolo, no liquido."""
    by_symbol = {}
    for trade in trades:
        sym = trade.get("symbol") or "--"
        row = by_symbol.setdefault(
            sym, {"symbol": sym, "trades": 0, "wins": 0, "losses": 0,
                  "total_pnl": 0.0, "_pct_sum": 0.0}
        )
        row["trades"] += 1
        pct = _net_pnl_pct(trade)
        row["_pct_sum"] += pct
        if pct > 0:
            row["wins"] += 1
        elif pct < 0:
            row["losses"] += 1
        row["total_pnl"] += _net_pnl_usd(trade)
    rows = sorted(by_symbol.values(), key=lambda r: r["total_pnl"], reverse=True)
    for row in rows:
        row["total_pnl"] = round(row["total_pnl"], 2)
        # media dos PERCENTUAIS. O codigo antigo dividia o total em USD pelo
        # numero de trades e gravava nesse campo — o frontend renderiza com "%".
        row["avg_pnl_pct"] = round(row["_pct_sum"] / row["trades"], 2) if row["trades"] else 0
        row["avg_pnl_usd"] = round(row["total_pnl"] / row["trades"], 2) if row["trades"] else 0
        del row["_pct_sum"]
    return rows


def _momentum_alltime_totals():
    """Totais all-time do momentum — direto do BANCO, nunca do state.

    `momentum_state.json` nao serve para isto: seu `total_fee_usd` so acumula os
    trades cuja fee foi medida no fechamento (fee_model='flat_taker'); os demais
    tiveram a fee backfilled apenas no banco. Hoje o state diz 148,88 de fee onde
    o banco soma 286,25 — derivar o liquido do state subestimaria a perda em ~137
    USD (net -10,9% em vez dos -24,7% reais). Mesmo erro de familia do "+10,42%
    que circula e gross".
    """
    empty = {"net_usd": 0.0, "gross_usd": 0.0, "fee_usd": 0.0,
             "trades": 0, "is_net": True}
    try:
        conn = db._get_conn()
    except Exception:
        return empty
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS trades, "
            "COALESCE(SUM(COALESCE(net_pnl_usd, pnl_usd)), 0) AS net_usd, "
            "COALESCE(SUM(pnl_usd), 0) AS gross_usd, "
            "COALESCE(SUM(total_fee_usd), 0) AS fee_usd, "
            "SUM(net_pnl_usd IS NULL) AS sem_net "
            "FROM momentum_trades"
        ).fetchone()
    except Exception:
        return empty
    finally:
        conn.close()
    return {
        "net_usd": _safe_float(row["net_usd"]),
        "gross_usd": _safe_float(row["gross_usd"]),
        "fee_usd": _safe_float(row["fee_usd"]),
        "trades": _safe_int(row["trades"]),
        "is_net": _safe_int(row["sem_net"]) == 0,
    }


def _get_momentum_funnel(hours=24):
    """Funil de decisoes do momentum (substitui o funil do scalping aposentado).

    `opened` sai de blocked_by='none', NAO de outcome='trade': outcome diz que o
    SINAL foi de trade, mas a abertura ainda podia ser barrada depois por
    max_positions/cooldown/suspended (paper_executor regrava a linha com o motivo).
    All-time o banco tem 1.088 linhas com outcome='trade' para 283 posicoes reais
    — usar outcome inflaria `opened` em ~4x.
    """
    empty = {"total": 0, "breakdown": {}, "opened": 0, "hours": hours}
    try:
        conn = db._get_conn()
    except Exception:
        return empty
    try:
        rows = conn.execute(
            "SELECT outcome, blocked_by, COUNT(*) AS count FROM momentum_decisions "
            "WHERE timestamp > datetime('now', ?) GROUP BY outcome, blocked_by",
            (f"-{hours} hours",),
        ).fetchall()
    except Exception:
        return empty
    finally:
        conn.close()

    breakdown, opened = {}, 0
    for row in rows:
        count = int(row["count"])
        blocked_by = row["blocked_by"] or ""
        if blocked_by == "none":
            opened += count
            key = "opened"
        else:
            key = blocked_by or row["outcome"] or "unknown"
        breakdown[key] = breakdown.get(key, 0) + count
    return {
        "total": sum(breakdown.values()),
        "breakdown": breakdown,
        "opened": opened,
        "hours": hours,
    }


# ── HELPERS ──────────────────────────────────────────────────────────────────

def _build_status(include_logs=True, include_trades=True):
    """Coleta todos os dados necessarios para o dashboard.

    MOMENTUM-ONLY desde 2026-08-03: paper/agent/pump/scalping foram aposentados
    (ver CLAUDE.md) e vinham entregando capital ESTATICO — `get_capital_status()`
    ja devolvia so {"Momentum": ...} e os `.get("Paper", FALLBACK)` daqui caiam no
    capital inicial hardcoded. Todo numero de PnL abaixo e LIQUIDO.
    """
    paused = is_paused()

    # Capital do momentum: o state guarda o BRUTO de proposito (governa o sizing
    # v1.1); o liquido sai descontando a fee acumulada. Os dois vao no payload —
    # o bruto porque e o que dimensiona a posicao, o liquido porque e a verdade.
    caps = get_capital_status()
    momentum_state = _read_json(MOMENTUM_STATE_FILE, {})
    momentum_cap = _safe_float(
        caps.get("Momentum", momentum_state.get("capital", MOMENTUM_INITIAL_CAPITAL)),
        MOMENTUM_INITIAL_CAPITAL,
    )

    def _ret(current, initial):
        return round((current - initial) / initial * 100, 2) if initial else 0

    momentum_today = db.get_trades_today("momentum_trades")
    momentum_trades_30d = get_trades_range("momentum_trades", days=30, limit=2000)
    momentum_stats_today = calc_daily_stats(momentum_today)  # NET-first

    # All-time vem do BANCO (ver _momentum_alltime_totals: o state subestima a fee).
    # O capital liquido e reconstruido do capital inicial + net acumulado, e nao
    # do capital bruto do state — assim os dois lados vem da mesma fonte.
    alltime = _momentum_alltime_totals()
    momentum_net_total = alltime["net_usd"]
    momentum_fee_total = alltime["fee_usd"]
    momentum_net_cap = round(MOMENTUM_INITIAL_CAPITAL + momentum_net_total, 2)

    # Ancora do drawdown da janela: o capital liquido no INICIO dos 30 dias, nao
    # o capital inicial de abril. Ancorar em 1000 colocaria a curva ~250 USD acima
    # da real e, como dd = (pico-vale)/pico, o denominador inflado encolheria todo
    # o percentual.
    window_net = sum(_net_pnl_usd(t) for t in momentum_trades_30d)
    momentum_window_start_cap = momentum_net_cap - window_net

    # Posicoes abertas com P&L ao vivo
    positions = _get_live_positions()

    # Circuit breaker (read-only, sem alertas Telegram)
    from daily_report import check_circuit_breaker
    cb_momentum = check_circuit_breaker("momentum")

    momentum_metrics = _compute_momentum_metrics(momentum_trades_30d, momentum_window_start_cap)
    metrics_per_system = {"momentum": momentum_metrics}

    metrics = {
        "total_trades": momentum_metrics["total_trades"],
        "win_rate": momentum_metrics["win_rate"],
        "profit_factor": momentum_metrics["profit_factor"],
        "max_drawdown_pct": momentum_metrics["max_drawdown_pct"],
        "largest_win": momentum_metrics["largest_win"],
        "largest_loss": momentum_metrics["largest_loss"],
        "avg_pnl_pct": momentum_metrics["avg_pnl_pct"],
        "is_net": momentum_metrics["is_net"],
        "per_system": metrics_per_system,
    }

    by_symbol = _momentum_by_symbol(momentum_trades_30d)

    momentum_chart = _momentum_equity_chart(momentum_trades_30d)
    charts = {"momentum": momentum_chart, "total": momentum_chart}

    capital = {
        "momentum": {
            "value": round(momentum_cap, 2),
            "ret": _ret(momentum_cap, MOMENTUM_INITIAL_CAPITAL),
            "net_value": momentum_net_cap,
            "net_ret": _ret(momentum_net_cap, MOMENTUM_INITIAL_CAPITAL),
            "fee_usd": round(momentum_fee_total, 2),
            "cb": cb_momentum,
        },
    }
    stats_today = {"momentum": momentum_stats_today}
    total_initial_capital = MOMENTUM_INITIAL_CAPITAL
    portfolio_value = momentum_net_cap  # headline e o LIQUIDO
    total_chart = charts["total"]
    total_curve_current = total_chart[-1]["pnl"] if total_chart else 0
    total_curve_peak = max((point["pnl"] for point in total_chart), default=0)
    best_system_key = "momentum"

    # Week PnL: soma P&L dos ultimos 7 dias (hoje + 6 anteriores)
    seven_days_ago = (date.today() - timedelta(days=6)).isoformat()
    week_pnl_usd = 0.0
    if momentum_chart:
        before = [p for p in momentum_chart if p["day"] < seven_days_ago]
        base = before[-1]["pnl"] if before else 0
        week_pnl_usd = momentum_chart[-1]["pnl"] - base

    # Exposure: soma de position_size_usd / portfolio_value
    total_notional = sum(_safe_float(p.get("position_size_usd")) for p in positions)
    exposure_pct = round(total_notional / portfolio_value * 100, 2) if portfolio_value else 0

    # Last trade timestamp (mais recente entre todos os sistemas)
    # Normaliza formatos mistos (isoformat "T" vs strftime espaco) antes de comparar
    def _norm_ts(ts):
        """Normaliza timestamp para formato comparavel YYYY-MM-DD HH:MM:SS."""
        if not ts:
            return ""
        return ts.replace("T", " ").split(".")[0]

    last_trade_ts = None
    _best_norm = ""
    for t in (momentum_today or momentum_trades_30d):
        ts_norm = _norm_ts(t.get("timestamp") or "")
        if ts_norm and ts_norm > _best_norm:
            _best_norm = ts_norm
            last_trade_ts = ts_norm

    summary = {
        "portfolio_value": round(portfolio_value, 2),  # LIQUIDO
        "portfolio_ret": _ret(portfolio_value, total_initial_capital),
        "gross_value": round(momentum_cap, 2),
        "gross_ret": _ret(momentum_cap, total_initial_capital),
        "net_total_usd": round(momentum_net_total, 2),
        "is_net": alltime["is_net"],
        "today_pnl_usd": round(sum(_safe_float(item.get("pnl_usd")) for item in stats_today.values()), 2),
        "week_pnl_usd": round(week_pnl_usd, 2),
        "curve_current": round(total_curve_current, 2),
        "curve_peak": round(total_curve_peak, 2),
        "curve_drawdown": round(total_curve_peak - total_curve_current, 2),
        "exposure_pct": exposure_pct,
        "last_trade_ts": last_trade_ts,
        "best_system": {
            "key": best_system_key,
            # LIQUIDO — o "ret" bruto do capital fica em gross_ret; aqui engana.
            "ret": capital[best_system_key]["net_ret"],
            "value": capital[best_system_key]["net_value"],
        },
        "open_positions": len(positions),
    }

    # System health
    health = _get_system_health()

    # Bot operational status -- checks if processes are alive and last cycle was recent
    bot_status = _get_bot_status()
    funnel = _get_momentum_funnel(hours=24)
    strategy_leaderboard = _build_system_leaderboard(capital, stats_today, metrics_per_system)

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
        "funnel": funnel,
        "insights": {"system_leaderboard": strategy_leaderboard},
        "logs": logs,
    }

    # ai_brain saiu do payload: eram ~25 dos 30 KB, com decisoes de ABRIL de
    # sistemas desativados, recarregadas a cada auto-refresh. Quem precisar chama
    # /api/ai-brain, que ja existia e serve exatamente isso.

    if include_trades:
        status["trades"] = {"momentum": momentum_today}
    else:
        status["trades"] = {}

    return status


# ── ROTAS ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Dashboard V2 — novo frontend."""
    return render_template("dashboard.html", active_page="dashboard")


@app.route("/analytics")
def analytics_page():
    return render_template("analytics.html", active_page="analytics")


@app.route("/system")
def system_page():
    return render_template("system.html", active_page="system")


@app.route("/raiox/")
def raiox_page():
    return render_template("raiox.html", active_page="raiox")


@app.route("/api/raiox/trades")
def api_raiox_trades():
    conn = db._get_conn()
    try:
        out = raiox_data.list_trades(conn, MOMENTUM_STATE_FILE)
    finally:
        conn.close()
    return jsonify({"ok": True, **out})


@app.route("/api/raiox/trade/<int:trade_id>")
def api_raiox_trade(trade_id):
    conn = db._get_conn()
    try:
        detail = raiox_data.trade_detail(conn, trade_id)
    finally:
        conn.close()
    if detail is None:
        return jsonify({"ok": False, "error": "not_found", "message": "trade nao encontrado"}), 404
    return jsonify({"ok": True, "trade": detail})


# get_candles_fn das rotas paper — indirecao p/ monkeypatch nos testes
_paper_candles_fn = market.get_candles

# Simbolos validos para /api/raiox/candles: raiox canonicos + universo do paper.
# DOGEUSDT e valido (esta em PAPER_SYMBOLS); 1000PEPEUSDT nao (excluido de PAPER_SYMBOLS).
_CANDLES_VALID_SYMBOLS = raiox_data.VALID_SYMBOLS | set(paper_data.PAPER_SYMBOLS)


def _binance_candles_adapter(symbol, interval, limit):
    """Adapta market.get_candles para o formato consumido por raiox_data.fetch_candles."""
    df = market.get_candles(symbol, interval, limit)
    if not hasattr(df, "copy"):
        return df
    df = df.copy()
    if "time_s" not in df.columns:
        raw_time = df["time"].astype("int64")
        # pandas pode estar em datetime64[ns/us/ms/s] dependendo da origem;
        # normaliza para epoch segundos sem truncar timestamp para valores como 1780.
        max_raw = int(raw_time.max())
        if max_raw > 10**17:      # ns
            df["time_s"] = raw_time // 1_000_000_000
        elif max_raw > 10**14:    # us
            df["time_s"] = raw_time // 1_000_000
        elif max_raw > 10**11:    # ms
            df["time_s"] = raw_time // 1_000
        else:                     # s
            df["time_s"] = raw_time

    class _Records:
        def to_dict(self, orient):
            return df[["time_s", "open", "high", "low", "close"]].to_dict(orient)

    return _Records()


@app.route("/api/raiox/candles")
def api_raiox_candles():
    symbol = request.args.get("symbol", "")
    interval = request.args.get("interval", "")
    if symbol not in _CANDLES_VALID_SYMBOLS:
        return jsonify({"ok": False, "error": "symbol_invalido", "message": "simbolo nao suportado"}), 400
    if interval not in raiox_data.VALID_INTERVALS:
        return jsonify({"ok": False, "error": "interval_invalido", "message": "timeframe invalido"}), 400
    try:
        start_s = int(request.args.get("start", "0"))
        end_s = int(request.args.get("end", "0"))
        margin = int(request.args.get("margin", "20"))
    except ValueError:
        return jsonify({"ok": False, "error": "param_invalido", "message": "start/end/margin invalidos"}), 400
    if start_s >= end_s:
        return jsonify({"ok": False, "error": "intervalo_invalido", "message": "start >= end"}), 400
    margin = max(0, min(margin, 300))
    try:
        out = raiox_data.fetch_candles(
            symbol, interval, start_s, end_s, int(time.time()),
            get_candles_fn=_binance_candles_adapter, margin=margin,
        )
    except Exception:
        return jsonify({
            "ok": False,
            "error": "binance_unavailable",
            "message": "nao consegui carregar os candles agora",
        }), 502
    if not out["ok"]:
        return jsonify(out), 400
    return jsonify(out)


@app.route("/raiox/mapa")
def raiox_mapa_page():
    return render_template("mapa.html", active_page="mapa")


@app.route("/api/raiox/mapa")
def api_raiox_mapa():
    symbol = request.args.get("symbol", "")
    if symbol not in raiox_data.VALID_SYMBOLS:
        return jsonify({"ok": False, "error": "symbol_invalido", "message": "simbolo nao suportado"}), 400
    conn = db._get_conn()
    try:
        out = raiox_data.trades_overlay(conn, symbol)
    finally:
        conn.close()
    return jsonify(out)


@app.route("/raiox/mercado")
def mercado_page():
    conn = db._get_conn()
    try:
        view = mercado_data.macro_view(conn, int(time.time()))
    finally:
        conn.close()
    return render_template("mercado.html", view=view, active_page="mercado")


@app.route("/raiox/mercado/<symbol>")
def mercado_symbol_page(symbol):
    sym = mercado_data.normalize_symbol(symbol)
    if sym is None:
        return redirect("/raiox/mercado")
    conn = db._get_conn()
    try:
        view = mercado_data.symbol_view(conn, sym, int(time.time()))
    finally:
        conn.close()
    return render_template("mercado_symbol.html", view=view, active_page="mercado")


@app.route("/raiox/paper")
def paper_page():
    conn = db._get_conn()
    try:
        view = paper_data.registro_view(conn, int(time.time()),
                                        request.args.get("symbol", "BTCUSDT"))
    finally:
        conn.close()
    return render_template("paper.html", view=view, active_page="paper", errors=None, form=None)


@app.route("/raiox/paper/criar", methods=["POST"])
@require_post_auth
def paper_criar():
    now_s = int(time.time())
    # Formulario HTML usa entry_price/stop_price/target_price diretamente (spec 2026-06-11)
    form = request.form.to_dict()
    sym = paper_data.normalize_symbol(form.get("symbol", "")) or "BTCUSDT"
    conn = db._get_conn()
    try:
        res = paper_data.create_trade(conn, _paper_candles_fn, now_s, form)
        if res["ok"]:
            return redirect(f"/raiox/paper?symbol={sym}")
        view = paper_data.registro_view(conn, now_s, sym)
    finally:
        conn.close()
    return render_template("paper.html", view=view, active_page="paper",
                           errors=res["errors"], form=form), 400


@app.route("/raiox/paper/<int:trade_id>/anular", methods=["POST"])
@require_post_auth
def paper_anular(trade_id):
    conn = db._get_conn()
    try:
        paper_data.void_trade(conn, int(time.time()), trade_id,
                              request.form.get("reason", ""))
    finally:
        conn.close()
    return redirect("/raiox/paper")


@app.route("/raiox/paper/<int:trade_id>/fechar", methods=["POST"])
@require_post_auth
def paper_fechar(trade_id):
    conn = db._get_conn()
    try:
        paper_data.close_manual(conn, _paper_candles_fn, int(time.time()), trade_id)
    finally:
        conn.close()
    return redirect("/raiox/paper")


# ── Rotulagem cega (experimento do olho) ─────────────────────────────
# Mede se o olho do trader separa trade bom de ruido SEM ver o resultado.
# Indirecao p/ monkeypatch da Binance REST nos testes.
_rotulagem_candles_fn = rotulagem_candles.blind_candles


@app.route("/rotulagem")
def rotulagem_page():
    return render_template("rotulagem.html", active_page="rotulagem")


@app.route("/api/rotulagem/next")
def api_rotulagem_next():
    """Proximo trade nao rotulado + candles CEGOS (cortados no entry) + niveis.
    NUNCA inclui exit/pnl/sl/tp — o resultado nao pode vazar pro olho."""
    conn = db._get_conn()
    try:
        all_ids = [r[0] for r in conn.execute(
            "SELECT id FROM momentum_trades ORDER BY timestamp ASC")]
        labeled = rotulagem_data.labeled_trade_ids(conn)
        pending = [i for i in all_ids if i not in labeled]
        progress = {"done": len(labeled), "total": len(all_ids)}
        if not pending:
            return jsonify({"ok": True, "done": True, "progress": progress})
        trade_id = pending[0]
        detail = raiox_data.trade_detail(conn, trade_id)
    finally:
        conn.close()
    if detail is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    try:
        candles = _rotulagem_candles_fn(detail["symbol"], detail["entry_time_s"], "15m", 80)
    except Exception:
        return jsonify({"ok": False, "error": "binance_unavailable",
                        "message": "nao consegui carregar os candles agora"}), 502
    swings = rotulagem_levels.swing_points(candles, k=3)
    supports = [lv for lv in rotulagem_levels.support_levels(candles, k=3, tol=0.0015)
                if lv["touches"] >= 2]
    return jsonify({
        "ok": True, "done": False, "progress": progress,
        "trade_id": trade_id,
        "symbol": detail["symbol"],
        "direction": detail["direction"],
        "entry_time_s": detail["entry_time_s"],
        "candles": candles,
        "swings": swings,
        "supports": supports,
    })


@app.route("/api/rotulagem/label", methods=["POST"])
@require_post_auth
def api_rotulagem_label():
    """Grava o veredito do olho (gostei/nao + 4 pistas + palpite de saida)."""
    body = request.get_json(silent=True) or {}
    try:
        trade_id = int(body.get("trade_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "errors": ["trade_id invalido"]}), 400
    guess = body.get("exit_price_guess")
    payload = {
        "trade_id": trade_id,
        "verdict": body.get("verdict"),
        "cues": body.get("cues") or {},
        "exit_price_guess": float(guess) if guess not in (None, "") else None,
        "now_s": int(time.time()),
    }
    conn = db._get_conn()
    try:
        res = rotulagem_data.save_label(conn, payload)
        if res.get("ok"):
            conn.commit()
    finally:
        conn.close()
    return jsonify(res), (200 if res.get("ok") else 400)


@app.route("/legacy")
def legacy_index():
    """Dashboard V1 — mantido para fallback."""
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


@app.route("/api/ai-brain")
def api_ai_brain():
    return jsonify(_build_ai_brain_payload())


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
      system — momentum (default) ou scalping/paper/agent/pump (historico)
      days   — quantidade de dias para trás (default: 7)

    Os sistemas aposentados seguem consultaveis (o historico nao some), mas o
    default virou momentum — o unico que ainda produz trades.
    """
    system = request.args.get("system", "momentum").lower()
    days = request.args.get("days", "7")

    try:
        days = int(days)
    except ValueError:
        days = 7

    table_map = {
        "momentum": "momentum_trades",
        "paper": "paper_trades",
        "agent": "agent_trades",
        "pump":  "pump_trades",
    }

    if system == "scalping":
        from database import get_scalping_trades
        trades = get_scalping_trades(days=days, limit=200)
        # Filtros opcionais para scalping
        regime = request.args.get("regime", "").upper()
        session = request.args.get("session", "").lower()
        if regime:
            trades = [t for t in trades if (t.get("market_regime") or "").upper() == regime]
        if session:
            trades = [t for t in trades if (t.get("session_bucket") or "").lower() == session]
    else:
        table = table_map.get(system)
        if not table:
            return jsonify({"error": f"unknown system: {system}"}), 400
        trades = get_trades_range(table, days=days)

    return jsonify({"trades": trades})


@app.route("/api/processes")
def api_processes():
    """Lista processos do bot com PID, RAM, status via psutil."""
    try:
        import psutil
    except ImportError:
        return jsonify({"processes": [], "error": "psutil not installed"})

    TARGETS = {
        "supervisor.py": "Supervisor",
        "main.py": "Main Bot",
        "pump_scanner.py": "Pump Scanner",
        "dashboard_server.py": "Dashboard",
    }
    result = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "status", "create_time"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cmd_str = " ".join(cmdline)
            for script, label in TARGETS.items():
                if script in cmd_str:
                    mem = proc.info.get("memory_info")
                    ram_mb = round(mem.rss / 1024 / 1024, 1) if mem else 0
                    uptime_s = time.time() - (proc.info.get("create_time") or time.time())
                    result.append({
                        "name": label,
                        "script": script,
                        "pid": proc.info["pid"],
                        "ram_mb": ram_mb,
                        "status": proc.info.get("status", "unknown"),
                        "uptime_s": round(uptime_s),
                    })
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    result.sort(key=lambda x: x["script"])
    return jsonify({"processes": result})


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


# ── V2 DASHBOARD ─────────────────────────────────────────────────────────────

_MICRO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]


def _get_dashboard_db():
    conn = sqlite3.connect(str(DB_FILE), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/api/microstructure/history")
def api_microstructure_history():
    from database import get_microstructure_history
    symbol = request.args.get("symbol", "BTCUSDT")
    hours = _safe_int(request.args.get("hours", "24"), 24)
    resolution = _safe_int(request.args.get("resolution", "5"), 5)

    # Limites de seguranca
    hours = max(1, min(hours, 24 * 60))        # max 60 dias
    resolution = max(1, min(resolution, 1440)) # min 1 min, max 1 dia

    data = get_microstructure_history(symbol, hours=hours, resolution_minutes=resolution)
    return jsonify({
        "symbol": symbol,
        "hours": hours,
        "resolution_minutes": resolution,
        "count": len(data),
        "data": data,
    })


@app.route("/api/microstructure/latest")
def api_microstructure_latest():
    conn = _get_dashboard_db()
    result = {}
    try:
        for sym in _MICRO_SYMBOLS:
            row = conn.execute(
                "SELECT * FROM market_microstructure WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
                (sym,),
            ).fetchone()
            dec = conn.execute(
                "SELECT signal_subtype, confluence_direction, confluence_score "
                "FROM scalping_decisions WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
                (sym,),
            ).fetchone()
            result[sym] = {
                "microstructure": dict(row) if row else None,
                "last_decision": dict(dec) if dec else None,
            }
    finally:
        conn.close()
    return jsonify(result)


@app.route("/api/signal-subtypes")
def api_signal_subtypes():
    days = max(1, min(_safe_int(request.args.get("days", "7"), 7), 30))
    conn = _get_dashboard_db()
    try:
        since = (date.today() - timedelta(days=days)).isoformat()

        dist_rows = conn.execute(
            "SELECT COALESCE(signal_subtype, 'unknown') AS st, COUNT(*) AS cnt "
            "FROM scalping_decisions WHERE timestamp >= ? GROUP BY st",
            (since,),
        ).fetchall()
        distribution = {r["st"]: r["cnt"] for r in dist_rows}

        daily_rows = conn.execute(
            "SELECT DATE(timestamp) AS d, COALESCE(signal_subtype, 'unknown') AS st, COUNT(*) AS cnt "
            "FROM scalping_decisions WHERE timestamp >= ? GROUP BY d, st ORDER BY d",
            (since,),
        ).fetchall()
        daily_map = {}
        for r in daily_rows:
            day = r["d"]
            if day not in daily_map:
                daily_map[day] = {"date": day, "none": 0, "cascade": 0, "divergence": 0, "continuation": 0, "unknown": 0}
            st = r["st"] if r["st"] in ("none", "cascade", "divergence", "continuation") else "unknown"
            daily_map[day][st] += r["cnt"]
        daily = list(daily_map.values())

        recent = conn.execute(
            "SELECT timestamp, symbol, signal_subtype, confluence_direction, confluence_score, outcome "
            "FROM scalping_decisions "
            "WHERE timestamp >= ? AND COALESCE(signal_subtype, 'none') NOT IN ('none', 'unknown') "
            "ORDER BY timestamp DESC LIMIT 20",
            (since,),
        ).fetchall()
        recent_signals = [dict(r) for r in recent]
    finally:
        conn.close()

    return jsonify({
        "distribution": distribution,
        "daily": daily,
        "recent_signals": recent_signals,
    })


# ── EQUITY CURVE ──────────────────────────────────────────────────────────────

@app.route("/api/equity")
def api_equity():
    """Equity curve data por sistema (PnL cumulativo diario)."""
    days = max(1, min(_safe_int(request.args.get("days", "30"), 30), 90))

    def _cumulative(raw):
        result = []
        acc = 0.0
        for row in raw:
            acc += _safe_float(row.get("daily_pnl", 0))
            result.append({"day": row["day"], "pnl": round(acc, 2)})
        return result

    pump_chart = _cumulative(db.get_cumulative_pnl("pump_trades", days))

    # Scalping: get_cumulative_pnl nao funciona para scalping_trades (tabela
    # nao esta na whitelist de _validate_table), entao query direto
    from database import _get_conn
    conn = _get_conn()
    try:
        scalping_raw = [dict(r) for r in conn.execute(
            "SELECT date(timestamp) as day, SUM(pnl_usd) as daily_pnl "
            "FROM scalping_trades WHERE timestamp >= date('now', ?) "
            "AND exit_reason != 'open' "
            "GROUP BY day ORDER BY day",
            (f"-{days} days",),
        ).fetchall()]
    finally:
        conn.close()
    scalping_chart = _cumulative(scalping_raw)

    return jsonify({
        "days": days,
        "pump": pump_chart,
        "scalping": scalping_chart,
    })


@app.route("/equity")
def equity_page():
    return render_template("equity.html", active_page="equity")


# ── FUNNEL ────────────────────────────────────────────────────────────────────

@app.route("/api/funnel")
def api_funnel():
    hours = max(1, min(_safe_int(request.args.get("hours", "24"), 24), 168))
    from diagnose_funnel import get_funnel_data
    return jsonify(get_funnel_data(hours))


@app.route("/scalping/funnel")
def scalping_funnel_page():
    hours = max(1, min(_safe_int(request.args.get("hours", "24"), 24), 168))
    from diagnose_funnel import get_funnel_data
    data = get_funnel_data(hours)
    data["runtime_links"] = _build_runtime_links(request.host, request.scheme)
    data["instance"] = runtime_metadata()
    return render_template("scalping_funnel.html", funnel=data)


# ── PIP-BOY SSE ──────────────────────────────────────────────────────────────

@app.route("/stream/logs")
def stream_logs():
    """SSE: real-time log stream. Each line sent as 'log' event."""
    source = request.args.get("source", "main")
    ALLOWED = {"main", "scalping", "pump", "supervisor", "dashboard"}
    if source not in ALLOWED:
        source = "main"

    log_path = _resolve_log_path(source)

    def generate():
        try:
            with open(log_path, "r", errors="replace") as f:
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if line:
                        clean = line.rstrip()
                        if clean:
                            yield f"event: log\ndata: {clean}\n\n"
                    else:
                        time.sleep(0.5)
        except FileNotFoundError:
            yield f"event: log\ndata: > LOG FILE NOT FOUND: {source}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _resolve_log_path(source: str) -> str:
    """Resolve log source name to file path."""
    log_map = {
        "main": "main_bot.log",
        "scalping": "main_bot.log",
        "pump": "pump_scanner.log",
        "supervisor": "supervisor.log",
        "dashboard": "dashboard.log",
    }
    filename = log_map.get(source, "main_bot.log")
    return os.path.join(str(LOG_DIR), filename)


# ── PIP-BOY PAGES ────────────────────────────────────────────────────────────

@app.route("/pip/")
@app.route("/pip/status")
def pip_status():
    return render_template("pipboy/status.html", active_tab="status")


@app.route("/pip/trades")
def pip_trades():
    return render_template("pipboy/trades.html", active_tab="trades")


@app.route("/pip/analysis")
def pip_analysis():
    return render_template("pipboy/analysis.html", active_tab="analysis")


@app.route("/pip/logs")
def pip_logs():
    return render_template("pipboy/logs.html", active_tab="logs")


@app.route("/pip/system")
def pip_system():
    return render_template("pipboy/system.html", active_tab="system")


# ── PIP-BOY PARTIALS ─────────────────────────────────────────────────────────

@app.route("/pip/partial/ticker")
def pip_partial_ticker():
    status = _build_status(include_logs=False, include_trades=False)
    return render_template("pipboy/partials/ticker.html", s=status)


@app.route("/pip/partial/kpis")
def pip_partial_kpis():
    status = _build_status(include_logs=False, include_trades=False)
    return render_template("pipboy/partials/kpi_cards.html", s=status)


@app.route("/pip/partial/positions")
def pip_partial_positions():
    status = _build_status(include_logs=False, include_trades=False)
    return render_template("pipboy/partials/positions.html",
                           positions=status["positions"])


@app.route("/pip/partial/status_bar")
def pip_partial_status_bar():
    status = _build_status(include_logs=False, include_trades=False)
    return render_template("pipboy/partials/status_bar.html", s=status)


@app.route("/pip/partial/equity")
def pip_partial_equity():
    from ascii_charts import render_equity_curve
    system = request.args.get("system", "total")
    days = _safe_int(request.args.get("days", "30"), 30)
    status = _build_status(include_logs=False, include_trades=False)
    chart_data = status["chart"].get(system, status["chart"].get("total", []))
    if days and chart_data:
        chart_data = chart_data[-days:]
    ascii_chart = render_equity_curve(chart_data, width=min(50, len(chart_data) or 1))
    return render_template("pipboy/partials/equity_chart.html",
                           chart=ascii_chart, system=system, days=days)


@app.route("/pip/partial/trades")
def pip_partial_trades():
    system = request.args.get("system", "scalping")
    days = _safe_int(request.args.get("days", "7"), 7)
    page = _safe_int(request.args.get("page", "1"), 1)
    per_page = 15

    if system == "scalping":
        from database import get_scalping_trades
        all_trades = get_scalping_trades(days=days, limit=500)
    else:
        table_map = {"paper": "paper_trades", "agent": "agent_trades", "pump": "pump_trades"}
        table = table_map.get(system, "pump_trades")
        all_trades = get_trades_range(table, days=days)

    total = len(all_trades)
    start = (page - 1) * per_page
    trades = all_trades[start:start + per_page]
    total_pages = (total + per_page - 1) // per_page

    return render_template("pipboy/partials/trade_log.html",
                           trades=trades, system=system, days=days,
                           page=page, total_pages=total_pages)


@app.route("/pip/partial/daily_pnl")
def pip_partial_daily_pnl():
    from ascii_charts import render_daily_pnl
    days = _safe_int(request.args.get("days", "14"), 14)
    status = _build_status(include_logs=False, include_trades=False)
    total_chart = status["chart"].get("total", [])
    daily = []
    for i, point in enumerate(total_chart):
        prev_pnl = total_chart[i - 1]["pnl"] if i > 0 else 0
        daily.append({"day": point["day"], "pnl": point["pnl"] - prev_pnl})
    daily = daily[-days:]
    ascii_chart = render_daily_pnl(daily, width=days)
    return render_template("pipboy/partials/daily_pnl.html",
                           chart=ascii_chart, days=days)


@app.route("/pip/partial/funnel")
def pip_partial_funnel():
    hours = _safe_int(request.args.get("hours", "24"), 24)
    days = max(1, hours // 24) if hours >= 24 else 1
    funnel = get_scalping_funnel_stats(days=days)
    return render_template("pipboy/partials/funnel.html",
                           funnel=funnel, hours=hours)


@app.route("/pip/partial/gauges")
def pip_partial_gauges():
    from database import get_scalping_trades
    trades = get_scalping_trades(days=30, limit=500)

    by_regime = {}
    for t in trades:
        regime = t.get("market_regime", "UNKNOWN") or "UNKNOWN"
        if regime not in by_regime:
            by_regime[regime] = {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0}
        by_regime[regime]["total"] += 1
        pnl = float(t.get("pnl_pct", 0) or 0)
        by_regime[regime]["pnl"] += pnl
        if pnl > 0:
            by_regime[regime]["wins"] += 1
        else:
            by_regime[regime]["losses"] += 1

    by_session = {}
    for t in trades:
        session = t.get("session_bucket", "unknown") or "unknown"
        if session not in by_session:
            by_session[session] = {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0}
        by_session[session]["total"] += 1
        pnl = float(t.get("pnl_pct", 0) or 0)
        by_session[session]["pnl"] += pnl
        if pnl > 0:
            by_session[session]["wins"] += 1
        else:
            by_session[session]["losses"] += 1

    return render_template("pipboy/partials/gauges.html",
                           by_regime=by_regime, by_session=by_session)


@app.route("/pip/partial/scorer")
def pip_partial_scorer():
    days = _safe_int(request.args.get("days", "30"), 30)
    payload = _build_scalping_scorer_payload(days=str(days), limit="5000")
    return render_template("pipboy/partials/scorer.html", scorer=payload)


@app.route("/pip/partial/errors")
def pip_partial_errors():
    logs = _get_recent_logs(source="main", lines=200)
    errors = [l for l in logs if "ERROR" in l.upper() or "ERR" in l.upper()]
    warnings = [l for l in logs if "WARNING" in l.upper() or "WARN" in l.upper()]
    return render_template("pipboy/partials/error_summary.html",
                           errors=errors[-20:], warnings=warnings[-20:],
                           error_count=len(errors), warning_count=len(warnings))


@app.route("/pip/partial/health")
def pip_partial_health():
    health = _get_system_health()
    return render_template("pipboy/partials/health_meters.html", health=health)


@app.route("/pip/partial/processes")
def pip_partial_processes():
    resp = api_processes()
    data = resp.get_json()
    return render_template("pipboy/partials/processes.html",
                           processes=data.get("processes", []))


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
