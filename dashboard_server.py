"""
Dashboard Web — painel de controle do Crypto AI Bot.
Acesso: http://<ip-do-pi>:5000

Rotas:
  GET  /            — painel principal
  GET  /api/status  — JSON com todos os dados (auto-refresh AJAX)
  POST /pause       — pausa o bot
  POST /resume      — retoma o bot
  GET  /api/trades  — historico de trades com filtro de periodo
  GET  /api/logs    — logs recentes de qualquer subsistema
"""
import os
import json
import shutil
import requests
from datetime import datetime, date, timedelta
from flask import Flask, render_template, redirect, url_for, jsonify, request
import database as db
from database import get_all_time_stats, get_stats_by_symbol, get_trades_range
from telegram_commands import is_paused, _set_paused
from daily_report import calc_daily_stats, get_capital_status
from config import PAPER_INITIAL_CAPITAL, AGENT_INITIAL_CAPITAL, PUMP_INITIAL_CAPITAL
from signal_types import ScalpingConfig

SCALPING_INITIAL_CAPITAL = 10000
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BOT_DIR, "templates"))


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

    # Check processes via supervisor (Linux) or log file timestamps
    try:
        result = subprocess.run(
            ["pgrep", "-f", "main.py"], capture_output=True, timeout=3
        )
        status["main_bot"] = result.returncode == 0
    except Exception:
        # Windows fallback: check log file modification time
        pass

    try:
        result = subprocess.run(
            ["pgrep", "-f", "pump_scanner.py"], capture_output=True, timeout=3
        )
        status["pump_scanner"] = result.returncode == 0
    except Exception:
        pass

    # Check last cycle timestamp from main log
    log_dir = os.path.join(BOT_DIR, "logs")
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
    logs_dir = os.path.join(BOT_DIR, "logs")
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
            all_lines = f.readlines()
        # Retorna as ultimas N linhas, stripped
        return [line.rstrip("\n\r") for line in all_lines[-lines:]]
    except Exception:
        return []


# ── LIVE POSITIONS ───────────────────────────────────────────────────────────

def _get_live_positions():
    """Le posicoes abertas dos arquivos de estado e adiciona P&L ao vivo via Binance."""
    state_files = [
        ("paper_state.json",    "Paper"),
        ("agent_state.json",    "Agent"),
        ("pump_positions.json", "Pump"),
    ]

    raw = []
    symbols_needed = set()

    # --- Paper, Agent, Pump positions ---
    for fname, system in state_files:
        path = os.path.join(BOT_DIR, fname)
        if not os.path.isfile(path):
            continue
        try:
            state = json.load(open(path))
            for sym, pos in state.get("positions", {}).items():
                symbols_needed.add(sym)
                entry = {
                    "system":      system,
                    "symbol":      sym,
                    "type":        pos.get("type", ""),
                    "entry_price": float(pos.get("entry_price", 0)),
                    "sl_price":    pos.get("sl_price"),
                    "tp_price":    pos.get("tp_price"),
                }
                # Agent confidence (stored in agent_state.json positions)
                if system == "Agent" and "analyst_confidence" in pos:
                    entry["analyst_confidence"] = pos["analyst_confidence"]
                raw.append(entry)
        except Exception:
            continue

    # --- Scalping positions (different field names) ---
    scalping_path = os.path.join(BOT_DIR, "scalping_state.json")
    if os.path.isfile(scalping_path):
        try:
            scalping_state = json.load(open(scalping_path))
            for sym, pos in scalping_state.get("positions", {}).items():
                symbols_needed.add(sym)
                raw.append({
                    "system":           "Scalping",
                    "symbol":           sym,
                    "type":             pos.get("direction", ""),
                    "entry_price":      float(pos.get("entry_price", 0)),
                    "sl_price":         pos.get("sl_price"),
                    "tp1_price":        pos.get("tp1_price"),
                    "tp2_price":        pos.get("tp2_price"),
                    "tp_price":         pos.get("tp1_price"),  # compat: use tp1 as primary
                    "leverage":         pos.get("leverage", 1),
                    "confluence_score": pos.get("confluence_score", 0),
                    "tp1_hit":          pos.get("tp1_hit", False),
                    "position_size_usd": pos.get("position_size_usd", 0),
                    "source":           pos.get("source", ""),
                })
        except Exception:
            pass

    if not raw:
        return []

    # Busca todos os precos de uma vez (1 request)
    prices = {}
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/ticker/price", timeout=5
        )
        if resp.status_code == 200:
            for item in resp.json():
                if item["symbol"] in symbols_needed:
                    prices[item["symbol"]] = float(item["price"])
    except Exception:
        pass

    # Calcula P&L ao vivo para cada posicao
    for pos in raw:
        entry   = pos["entry_price"]
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

def _build_status():
    """Coleta todos os dados necessarios para o dashboard."""
    paused = is_paused()

    # Capital atual de cada sistema (lido dos arquivos de estado)
    caps = get_capital_status()
    paper_cap = caps.get("Paper", PAPER_INITIAL_CAPITAL)
    agent_cap = caps.get("Agent", AGENT_INITIAL_CAPITAL)
    pump_cap  = caps.get("Pump",  PUMP_INITIAL_CAPITAL)

    # Scalping capital (from scalping_state.json)
    scalping_cap = SCALPING_INITIAL_CAPITAL
    scalping_total_trades = 0
    scalping_wins = 0
    scalping_losses = 0
    scalping_path = os.path.join(BOT_DIR, "scalping_state.json")
    if os.path.isfile(scalping_path):
        try:
            sc_state = json.load(open(scalping_path))
            scalping_cap = float(sc_state.get("capital", SCALPING_INITIAL_CAPITAL))
            scalping_total_trades = int(sc_state.get("total_trades", 0))
            scalping_wins = int(sc_state.get("wins", 0))
            scalping_losses = int(sc_state.get("losses", 0))
        except Exception:
            pass

    def _ret(current, initial):
        return round((current - initial) / initial * 100, 2) if initial else 0

    # Trades de hoje
    paper_today = db.get_trades_today("paper_trades")
    agent_today = db.get_trades_today("agent_trades")
    pump_today  = db.get_trades_today("pump_trades")

    paper_stats = calc_daily_stats(paper_today)
    agent_stats = calc_daily_stats(agent_today)
    pump_stats  = calc_daily_stats(pump_today)

    # Scalping stats hoje (from scalping_state.json history)
    scalping_stats_today = {
        "total_trades": scalping_total_trades,
        "wins": scalping_wins,
        "losses": scalping_losses,
        "win_rate": round((scalping_wins / scalping_total_trades * 100), 1) if scalping_total_trades > 0 else 0,
    }

    # Posicoes abertas com P&L ao vivo
    positions = _get_live_positions()

    # Trades de hoje por sistema
    paper_recent = paper_today
    agent_recent = agent_today
    pump_recent  = pump_today

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
    if os.path.isfile(scalping_path):
        try:
            sc_state = json.load(open(scalping_path))
            history = sc_state.get("history", [])
            daily_pnl = {}
            for trade in history:
                ts = trade.get("exit_time", trade.get("entry_time", ""))
                if ts:
                    day = ts[:10]
                    daily_pnl[day] = daily_pnl.get(day, 0) + float(trade.get("pnl_usd", 0))
            acc = 0.0
            for day in sorted(daily_pnl.keys()):
                acc += daily_pnl[day]
                scalping_chart.append({"day": day, "pnl": round(acc, 2)})
        except Exception:
            pass

    # Circuit breaker status
    from daily_report import is_circuit_broken
    cb_paper = is_circuit_broken("paper")
    cb_agent = is_circuit_broken("agent")
    cb_pump  = is_circuit_broken("pump")

    # Advanced metrics (30 days) -- per system
    metrics_per_system = {
        "paper":    get_all_time_stats("paper_trades", 30),
        "agent":    get_all_time_stats("agent_trades", 30),
        "pump":     get_all_time_stats("pump_trades",  30),
    }

    # Combined metrics across all systems
    all_totals = sum(m["total_trades"] for m in metrics_per_system.values()) + scalping_total_trades
    all_wins = sum(m.get("win_rate", 0) * m["total_trades"] / 100 for m in metrics_per_system.values() if m["total_trades"]) + scalping_wins
    all_wins = int(all_wins)
    combined_win_rate = (all_wins / all_totals * 100) if all_totals > 0 else 0

    # Best/worst trade and profit factor across all systems
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
            by_symbol_raw[sym]["total_pnl"] += float(row["total_pnl"] or 0)
    by_symbol = sorted(by_symbol_raw.values(), key=lambda x: x["total_pnl"], reverse=True)
    for s in by_symbol:
        s["total_pnl"] = round(s["total_pnl"], 2)
        s["avg_pnl_pct"] = round(s["total_pnl"] / s["trades"], 2) if s["trades"] else 0

    # System health
    health = _get_system_health()

    # Bot operational status -- checks if processes are alive and last cycle was recent
    bot_status = _get_bot_status()

    # Recent logs (last 20 lines of main log)
    logs = _get_recent_logs(source="main", lines=20)

    return {
        "paused": paused,
        "last_update": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "capital": {
            "paper":    {"value": round(paper_cap, 2),    "ret": _ret(paper_cap, PAPER_INITIAL_CAPITAL),    "cb": cb_paper},
            "agent":    {"value": round(agent_cap, 2),    "ret": _ret(agent_cap, AGENT_INITIAL_CAPITAL),    "cb": cb_agent},
            "pump":     {"value": round(pump_cap,  2),    "ret": _ret(pump_cap,  PUMP_INITIAL_CAPITAL),     "cb": cb_pump},
            "scalping": {"value": round(scalping_cap, 2), "ret": _ret(scalping_cap, SCALPING_INITIAL_CAPITAL), "cb": False},
        },
        "stats_today": {
            "paper":    paper_stats,
            "agent":    agent_stats,
            "pump":     pump_stats,
            "scalping": scalping_stats_today,
        },
        "positions": positions,
        "trades": {
            "paper": paper_recent,
            "agent": agent_recent,
            "pump":  pump_recent,
        },
        "chart": {
            "paper":    paper_chart,
            "agent":    agent_chart,
            "pump":     pump_chart,
            "scalping": scalping_chart,
        },
        "metrics":   metrics,
        "by_symbol": by_symbol,
        "health":    health,
        "bot_status": bot_status,
        "logs":      logs,
    }


# ── ROTAS ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    status = _build_status()
    return render_template("index.html", **status)


@app.route("/api/status")
def api_status():
    return jsonify(_build_status())


@app.route("/pause", methods=["POST"])
def pause():
    _set_paused(True)
    return redirect(url_for("index"))


@app.route("/resume", methods=["POST"])
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

    table = table_map.get(system)
    if not table:
        return jsonify({"error": f"unknown system: {system}"}), 400

    trades = get_trades_range(table, days=days)
    return jsonify(trades)


@app.route("/api/logs")
def api_logs():
    """Logs recentes de um subsistema.

    Query params:
      source — main, scalping, pump (default: main)
      lines  — quantidade de linhas (default: 50)
    """
    source = request.args.get("source", "main")
    lines = request.args.get("lines", "50")

    try:
        lines = int(lines)
    except ValueError:
        lines = 50

    # Limita a 500 linhas para nao sobrecarregar
    lines = min(lines, 500)

    log_lines = _get_recent_logs(source=source, lines=lines)
    return jsonify(log_lines)


# ── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    print("Dashboard disponivel em http://0.0.0.0:5000")
    # host=0.0.0.0 permite acesso pela rede local (celular no mesmo Wi-Fi)
    app.run(host="0.0.0.0", port=5000, debug=False)
