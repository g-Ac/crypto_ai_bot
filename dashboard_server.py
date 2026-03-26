"""
Dashboard Web — painel de controle do Crypto AI Bot.
Acesso: http://<ip-do-pi>:5000

Rotas:
  GET  /            — painel principal
  GET  /api/status  — JSON com todos os dados (auto-refresh AJAX)
  POST /pause       — pausa o bot
  POST /resume      — retoma o bot
"""
import os
import json
import time
import requests
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, jsonify
import database as db
from telegram_commands import is_paused, _set_paused
from daily_report import calc_daily_stats, get_capital_status
from config import PAPER_INITIAL_CAPITAL, AGENT_INITIAL_CAPITAL, PUMP_INITIAL_CAPITAL

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BOT_DIR, "templates"))


def _get_pi_stats():
    """Coleta metricas do hardware: CPU, RAM, disco, temperatura, uptime."""
    try:
        import psutil

        cpu_pct = psutil.cpu_percent(interval=0.5)
        mem     = psutil.virtual_memory()
        disk    = psutil.disk_usage("/")

        # Temperatura — leitura direta do kernel (Raspberry Pi)
        temp = None
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp = round(int(f.read().strip()) / 1000.0, 1)
        except Exception:
            try:
                sensors = psutil.sensors_temperatures()
                for key in ("cpu_thermal", "coretemp", "acpitz"):
                    if sensors.get(key):
                        temp = round(sensors[key][0].current, 1)
                        break
            except Exception:
                pass

        # Uptime
        uptime_sec = time.time() - psutil.boot_time()
        days    = int(uptime_sec // 86400)
        hours   = int((uptime_sec % 86400) // 3600)
        minutes = int((uptime_sec % 3600) // 60)
        uptime_str = (f"{days}d " if days else "") + f"{hours}h {minutes}m"

        return {
            "available":    True,
            "cpu_pct":      round(cpu_pct, 1),
            "mem_pct":      round(mem.percent, 1),
            "mem_used_mb":  round(mem.used  / 1024 / 1024),
            "mem_total_mb": round(mem.total / 1024 / 1024),
            "disk_pct":     round(disk.percent, 1),
            "disk_used_gb": round(disk.used  / 1024 ** 3, 1),
            "disk_total_gb":round(disk.total / 1024 ** 3, 1),
            "temp_c":       temp,
            "uptime":       uptime_str,
        }
    except ImportError:
        return {"available": False, "error": "psutil nao instalado"}
    except Exception as e:
        return {"available": False, "error": str(e)}


def _get_live_positions():
    """Le posicoes abertas dos arquivos de estado e adiciona P&L ao vivo via Binance."""
    state_files = [
        ("paper_state.json",    "Paper"),
        ("agent_state.json",    "Agent"),
        ("pump_positions.json", "Pump"),
    ]

    raw = []
    symbols_needed = set()

    for fname, system in state_files:
        path = os.path.join(BOT_DIR, fname)
        if not os.path.isfile(path):
            continue
        try:
            state = json.load(open(path))
            for sym, pos in state.get("positions", {}).items():
                symbols_needed.add(sym)
                raw.append({
                    "system":      system,
                    "symbol":      sym,
                    "type":        pos.get("type", ""),
                    "entry_price": float(pos.get("entry_price", 0)),
                    "sl_price":    pos.get("sl_price"),
                    "tp_price":    pos.get("tp_price"),
                })
        except Exception:
            continue

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
            if pos["type"] == "LONG":
                pos["pnl_pct"] = round((current - entry) / entry * 100, 2)
            else:
                pos["pnl_pct"] = round((entry - current) / entry * 100, 2)
            pos["current_price"] = current
        else:
            pos["pnl_pct"]       = None
            pos["current_price"] = None

    return raw


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _build_status():
    """Coleta todos os dados necessarios para o dashboard."""
    paused = is_paused()

    # Capital atual de cada sistema (lido dos arquivos de estado)
    caps = get_capital_status()
    paper_cap = caps.get("Paper", PAPER_INITIAL_CAPITAL)
    agent_cap = caps.get("Agent", AGENT_INITIAL_CAPITAL)
    pump_cap  = caps.get("Pump",  PUMP_INITIAL_CAPITAL)

    def _ret(current, initial):
        return round((current - initial) / initial * 100, 2)

    # Trades de hoje
    paper_today = db.get_trades_today("paper_trades")
    agent_today = db.get_trades_today("agent_trades")
    pump_today  = db.get_trades_today("pump_trades")

    paper_stats = calc_daily_stats(paper_today)
    agent_stats = calc_daily_stats(agent_today)
    pump_stats  = calc_daily_stats(pump_today)

    # Posicoes abertas com P&L ao vivo
    positions = _get_live_positions()

    # Trades de hoje por sistema (corrigido: era get_recent_trades)
    paper_recent = db.get_trades_today("paper_trades")
    agent_recent = db.get_trades_today("agent_trades")
    pump_recent  = db.get_trades_today("pump_trades")

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

    # Circuit breaker status
    from daily_report import is_circuit_broken
    cb_paper = is_circuit_broken("paper")
    cb_agent = is_circuit_broken("agent")
    cb_pump  = is_circuit_broken("pump")

    return {
        "paused": paused,
        "last_update": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "pi": _get_pi_stats(),
        "capital": {
            "paper": {"value": round(paper_cap, 2), "ret": _ret(paper_cap, PAPER_INITIAL_CAPITAL), "cb": cb_paper},
            "agent": {"value": round(agent_cap, 2), "ret": _ret(agent_cap, AGENT_INITIAL_CAPITAL), "cb": cb_agent},
            "pump":  {"value": round(pump_cap,  2), "ret": _ret(pump_cap,  PUMP_INITIAL_CAPITAL),  "cb": cb_pump},
        },
        "stats_today": {
            "paper": paper_stats,
            "agent": agent_stats,
            "pump":  pump_stats,
        },
        "positions": positions,
        "trades": {
            "paper": paper_recent,
            "agent": agent_recent,
            "pump":  pump_recent,
        },
        "chart": {
            "paper": paper_chart,
            "agent": agent_chart,
            "pump":  pump_chart,
        },
    }


# ── ROTAS ─────────────────────────────────────────────────────────────────────

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


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    print("Dashboard disponivel em http://0.0.0.0:5000")
    # host=0.0.0.0 permite acesso pela rede local (celular no mesmo Wi-Fi)
    app.run(host="0.0.0.0", port=5000, debug=False)
