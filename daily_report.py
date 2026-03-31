"""
Relatorio diario - envia resumo de performance no Telegram.
Tambem gera o circuit breaker (limite de perda diaria).
"""
import json
import os
import tempfile
from datetime import datetime, date
from config import (
    DAILY_LOSS_LIMIT_PCT, DAILY_MAX_TRADES,
    PAPER_INITIAL_CAPITAL, AGENT_INITIAL_CAPITAL, PUMP_INITIAL_CAPITAL,
)
from telegram_notifier import send_telegram_message
import database as db

LAST_REPORT_FILE = "last_report_date.txt"



def calc_daily_stats(trades):
    """Calculate stats from a list of trade dicts."""
    if not trades:
        return {"count": 0, "pnl_pct": 0, "pnl_usd": 0, "wins": 0, "losses": 0}

    pnl_pct = 0
    pnl_usd = 0
    wins = 0
    losses = 0

    for t in trades:
        p = float(t.get("pnl_pct", 0) or 0)
        u = float(t.get("pnl_usd", 0) or 0)
        pnl_pct += p
        pnl_usd += u
        if p > 0:
            wins += 1
        elif p < 0:
            losses += 1

    return {
        "count": len(trades),
        "pnl_pct": round(pnl_pct, 2),
        "pnl_usd": round(pnl_usd, 2),
        "wins": wins,
        "losses": losses,
    }


def get_open_positions():
    """Get open positions from all systems."""
    positions = []

    # Paper trader
    if os.path.isfile("paper_state.json"):
        with open("paper_state.json", "r") as f:
            state = json.load(f)
        for sym, pos in state.get("positions", {}).items():
            positions.append(f"  {sym}: {pos['type']} @ {pos['entry_price']:.4f} (paper)")

    # Agent trader
    if os.path.isfile("agent_state.json"):
        with open("agent_state.json", "r") as f:
            state = json.load(f)
        for sym, pos in state.get("positions", {}).items():
            positions.append(
                f"  {sym}: {pos['type']} @ {pos['entry_price']:.4f} "
                f"SL:{pos['sl_price']:.4f} TP:{pos['tp_price']:.4f} (agent)"
            )

    # Pump trader
    if os.path.isfile("pump_positions.json"):
        with open("pump_positions.json", "r") as f:
            state = json.load(f)
        for sym, pos in state.get("positions", {}).items():
            positions.append(f"  {sym}: {pos['type']} @ {pos['entry_price']:.6f} (pump)")

    return positions


def get_capital_status():
    """Get capital from all systems."""
    caps = {}

    if os.path.isfile("paper_state.json"):
        with open("paper_state.json", "r") as f:
            caps["Paper"] = json.load(f).get("capital", 0)

    if os.path.isfile("agent_state.json"):
        with open("agent_state.json", "r") as f:
            caps["Agent"] = json.load(f).get("capital", 0)

    if os.path.isfile("pump_positions.json"):
        with open("pump_positions.json", "r") as f:
            caps["Pump"] = json.load(f).get("capital", 0)

    return caps


def generate_report():
    """Generate the daily report text."""
    today = date.today().strftime("%d/%m/%Y")

    # Collect trades from each system
    paper_trades = db.get_trades_today("paper_trades")
    agent_trades = db.get_trades_today("agent_trades")
    pump_trades = db.get_trades_today("pump_trades")

    paper_stats = calc_daily_stats(paper_trades)
    agent_stats = calc_daily_stats(agent_trades)
    pump_stats = calc_daily_stats(pump_trades)

    capitals = get_capital_status()
    positions = get_open_positions()

    # Build report
    lines = [
        f"Relatorio Diario - {today}",
        "",
    ]

    # Paper trading
    if "Paper" in capitals:
        ps = paper_stats
        lines.append(
            f"Paper Trading: {ps['count']} trades | "
            f"{ps['pnl_pct']:+.2f}% (${ps['pnl_usd']:+.2f}) | "
            f"W:{ps['wins']} L:{ps['losses']} | "
            f"Capital: ${capitals['Paper']:.2f}"
        )

    # Agent trading
    if "Agent" in capitals:
        ag = agent_stats
        lines.append(
            f"Multi-Agent: {ag['count']} trades | "
            f"{ag['pnl_pct']:+.2f}% (${ag['pnl_usd']:+.2f}) | "
            f"W:{ag['wins']} L:{ag['losses']} | "
            f"Capital: ${capitals['Agent']:.2f}"
        )

    # Pump trading
    if "Pump" in capitals:
        pm = pump_stats
        lines.append(
            f"Pump Scanner: {pm['count']} trades | "
            f"{pm['pnl_pct']:+.2f}% (${pm['pnl_usd']:+.2f}) | "
            f"W:{pm['wins']} L:{pm['losses']} | "
            f"Capital: ${capitals['Pump']:.2f}"
        )

    # Total
    total_trades = paper_stats["count"] + agent_stats["count"] + pump_stats["count"]
    total_pnl = paper_stats["pnl_usd"] + agent_stats["pnl_usd"] + pump_stats["pnl_usd"]
    total_wins = paper_stats["wins"] + agent_stats["wins"] + pump_stats["wins"]
    total_losses = paper_stats["losses"] + agent_stats["losses"] + pump_stats["losses"]

    lines.append("")
    lines.append(
        f"Total: {total_trades} trades | "
        f"${total_pnl:+.2f} | "
        f"W:{total_wins} L:{total_losses}"
    )

    # Open positions
    if positions:
        lines.append("")
        lines.append(f"Posicoes abertas ({len(positions)}):")
        lines.extend(positions)

    if total_trades == 0 and not positions:
        lines.append("")
        lines.append("Nenhum trade ou posicao aberta hoje.")

    return "\n".join(lines)


def should_send_report():
    """Check if report was already sent today."""
    today = date.today().isoformat()
    if os.path.isfile(LAST_REPORT_FILE):
        with open(LAST_REPORT_FILE, "r") as f:
            last = f.read().strip()
        if last == today:
            return False
    return True


def mark_report_sent():
    content = date.today().isoformat()
    dir_name = os.path.dirname(os.path.abspath(LAST_REPORT_FILE)) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as f:
        f.write(content)
        tmp_path = f.name
    os.replace(tmp_path, LAST_REPORT_FILE)


def send_daily_report():
    """Send report if not sent today yet."""
    if not should_send_report():
        return

    report = generate_report()
    print(f"\n  {report}")
    send_telegram_message(report)
    mark_report_sent()


def check_daily_report():
    """Called each cycle - sends report once per day after midnight."""
    now = datetime.now()
    if now.hour == 0 and now.minute < 10:
        send_daily_report()


# ============================================================
#  CIRCUIT BREAKER
# ============================================================

def _get_current_capital(system):
    """Get current capital from state file for a given system."""
    state_files = {
        "paper": "paper_state.json",
        "agent": "agent_state.json",
        "pump": "pump_positions.json",
    }
    fallback = {
        "paper": PAPER_INITIAL_CAPITAL,
        "agent": AGENT_INITIAL_CAPITAL,
        "pump": PUMP_INITIAL_CAPITAL,
    }
    path = state_files.get(system)
    if path and os.path.isfile(path):
        try:
            with open(path, "r") as f:
                return json.load(f).get("capital", fallback[system])
        except Exception:
            pass
    return fallback.get(system, 10000)


def is_circuit_broken(system="agent"):
    """Check if daily loss limit or max trades reached."""
    if system == "agent":
        trades = db.get_trades_today("agent_trades")
    elif system == "pump":
        trades = db.get_trades_today("pump_trades")
    elif system == "paper":
        trades = db.get_trades_today("paper_trades")
    else:
        return False

    stats = calc_daily_stats(trades)

    # Check max trades
    if stats["count"] >= DAILY_MAX_TRADES:
        print(f"  [CIRCUIT BREAKER] {system}: limite de {DAILY_MAX_TRADES} trades/dia atingido")
        return True

    # Use max(initial, current) as reference for daily loss %
    initial_capitals = {
        "paper": PAPER_INITIAL_CAPITAL,
        "agent": AGENT_INITIAL_CAPITAL,
        "pump": PUMP_INITIAL_CAPITAL,
    }
    baseline = initial_capitals.get(system, 10000)
    current_capital = _get_current_capital(system)
    reference_capital = max(baseline, current_capital)
    if reference_capital <= 0:
        reference_capital = baseline

    real_loss_pct = (stats["pnl_usd"] / reference_capital) * 100
    if real_loss_pct <= -DAILY_LOSS_LIMIT_PCT:
        print(f"  [CIRCUIT BREAKER] {system}: perda diaria de {real_loss_pct:.2f}% excede limite de -{DAILY_LOSS_LIMIT_PCT}%")
        return True

    return False


if __name__ == "__main__":
    report = generate_report()
    print(report)
    print("\nEnviando para Telegram...")
    send_telegram_message(report)
    mark_report_sent()
    print("Enviado.")
