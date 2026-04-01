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
    SCALPING_INITIAL_CAPITAL,
)
from telegram_notifier import send_telegram_message, send_circuit_breaker_alert
import database as db
from runtime_config import (
    LAST_REPORT_FILE,
    PAPER_STATE_FILE,
    AGENT_STATE_FILE,
    PUMP_STATE_FILE,
    SCALPING_STATE_FILE,
)



def calc_daily_stats(trades):
    """Calculate stats from a list of trade dicts."""
    if not trades:
        return {"count": 0, "pnl_pct": 0, "pnl_usd": 0, "wins": 0, "losses": 0}

    # Filtrar trades de abertura (exit_reason='open') para nao inflar contagem
    trades = [t for t in trades if t.get("exit_reason") != "open"]
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
    if os.path.isfile(PAPER_STATE_FILE):
        with open(PAPER_STATE_FILE, "r") as f:
            state = json.load(f)
        for sym, pos in state.get("positions", {}).items():
            positions.append(f"  {sym}: {pos['type']} @ {pos['entry_price']:.4f} (paper)")

    # Agent trader
    if os.path.isfile(AGENT_STATE_FILE):
        with open(AGENT_STATE_FILE, "r") as f:
            state = json.load(f)
        for sym, pos in state.get("positions", {}).items():
            positions.append(
                f"  {sym}: {pos['type']} @ {pos['entry_price']:.4f} "
                f"SL:{pos['sl_price']:.4f} TP:{pos['tp_price']:.4f} (agent)"
            )

    # Pump trader
    if os.path.isfile(PUMP_STATE_FILE):
        with open(PUMP_STATE_FILE, "r") as f:
            state = json.load(f)
        for sym, pos in state.get("positions", {}).items():
            positions.append(f"  {sym}: {pos['type']} @ {pos['entry_price']:.6f} (pump)")

    # Scalping
    if os.path.isfile(SCALPING_STATE_FILE):
        with open(SCALPING_STATE_FILE, "r") as f:
            state = json.load(f)
        for sym, pos in state.get("positions", {}).items():
            positions.append(
                f"  {sym}: {pos['direction']} @ {pos['entry_price']:.4f} "
                f"SL:{pos['sl_price']:.4f} TP1:{pos['tp1_price']:.4f} (scalping)"
            )

    return positions


def get_capital_status():
    """Get capital from all systems."""
    caps = {}

    if os.path.isfile(PAPER_STATE_FILE):
        with open(PAPER_STATE_FILE, "r") as f:
            caps["Paper"] = json.load(f).get("capital", 0)

    if os.path.isfile(AGENT_STATE_FILE):
        with open(AGENT_STATE_FILE, "r") as f:
            caps["Agent"] = json.load(f).get("capital", 0)

    if os.path.isfile(PUMP_STATE_FILE):
        with open(PUMP_STATE_FILE, "r") as f:
            caps["Pump"] = json.load(f).get("capital", 0)

    if os.path.isfile(SCALPING_STATE_FILE):
        with open(SCALPING_STATE_FILE, "r") as f:
            caps["Scalping"] = json.load(f).get("capital", 0)

    return caps


def generate_report():
    """Generate the daily report text."""
    today = date.today().strftime("%d/%m/%Y")

    # Collect trades from each system
    paper_trades = db.get_trades_today("paper_trades")
    agent_trades = db.get_trades_today("agent_trades")
    pump_trades = db.get_trades_today("pump_trades")
    scalping_trades = db.get_trades_today("scalping_trades")

    paper_stats = calc_daily_stats(paper_trades)
    agent_stats = calc_daily_stats(agent_trades)
    pump_stats = calc_daily_stats(pump_trades)
    scalping_stats = calc_daily_stats(scalping_trades)

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

    # Scalping
    if "Scalping" in capitals:
        sc = scalping_stats
        lines.append(
            f"Scalping: {sc['count']} trades | "
            f"{sc['pnl_pct']:+.2f}% (${sc['pnl_usd']:+.2f}) | "
            f"W:{sc['wins']} L:{sc['losses']} | "
            f"Capital: ${capitals['Scalping']:.2f}"
        )

    # Total
    all_stats = [paper_stats, agent_stats, pump_stats, scalping_stats]
    total_trades = sum(s["count"] for s in all_stats)
    total_pnl = sum(s["pnl_usd"] for s in all_stats)
    total_wins = sum(s["wins"] for s in all_stats)
    total_losses = sum(s["losses"] for s in all_stats)

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
    """Called each cycle - sends report once per day.

    Nao depende mais de janela fixa (00:00-00:10). Basta nao ter sido
    enviado hoje.  Se o bot esteve offline a meia-noite, o relatorio
    sera enviado no proximo ciclo apos o retorno.
    """
    send_daily_report()


# ============================================================
#  CIRCUIT BREAKER
# ============================================================

def _get_current_capital(system):
    """Get current capital from state file for a given system."""
    state_files = {
        "paper": PAPER_STATE_FILE,
        "agent": AGENT_STATE_FILE,
        "pump": PUMP_STATE_FILE,
        "scalping": SCALPING_STATE_FILE,
    }
    fallback = {
        "paper": PAPER_INITIAL_CAPITAL,
        "agent": AGENT_INITIAL_CAPITAL,
        "pump": PUMP_INITIAL_CAPITAL,
        "scalping": SCALPING_INITIAL_CAPITAL,
    }
    path = state_files.get(system)
    if path and os.path.isfile(path):
        try:
            with open(path, "r") as f:
                return json.load(f).get("capital", fallback[system])
        except Exception:
            pass
    return fallback.get(system, 10000)


def check_circuit_breaker(system="agent"):
    """Read-only check: daily loss limit or max trades reached. No side effects."""
    table_map = {
        "agent": "agent_trades",
        "pump": "pump_trades",
        "paper": "paper_trades",
        "scalping": "scalping_trades",
    }
    table = table_map.get(system)
    if not table:
        return False

    trades = db.get_trades_today(table)
    stats = calc_daily_stats(trades)

    if stats["count"] >= DAILY_MAX_TRADES:
        return True

    initial_capitals = {
        "paper": PAPER_INITIAL_CAPITAL,
        "agent": AGENT_INITIAL_CAPITAL,
        "pump": PUMP_INITIAL_CAPITAL,
        "scalping": SCALPING_INITIAL_CAPITAL,
    }
    baseline = initial_capitals.get(system, 10000)
    current_capital = _get_current_capital(system)
    reference_capital = max(baseline, current_capital)
    if reference_capital <= 0:
        reference_capital = baseline

    real_loss_pct = (stats["pnl_usd"] / reference_capital) * 100
    if real_loss_pct <= -DAILY_LOSS_LIMIT_PCT:
        return True

    return False


def enforce_circuit_breaker(system="agent"):
    """Check circuit breaker and send Telegram alert if broken.

    Use in main loops where the alert side effect is desired.
    For read-only checks (dashboard, status), use check_circuit_breaker().
    """
    table_map = {
        "agent": "agent_trades",
        "pump": "pump_trades",
        "paper": "paper_trades",
        "scalping": "scalping_trades",
    }
    table = table_map.get(system)
    if not table:
        return False

    trades = db.get_trades_today(table)
    stats = calc_daily_stats(trades)

    if stats["count"] >= DAILY_MAX_TRADES:
        print(f"  [CIRCUIT BREAKER] {system}: limite de {DAILY_MAX_TRADES} trades/dia atingido")
        send_circuit_breaker_alert(system, f"Limite de {DAILY_MAX_TRADES} trades/dia atingido ({stats['count']} trades)")
        return True

    initial_capitals = {
        "paper": PAPER_INITIAL_CAPITAL,
        "agent": AGENT_INITIAL_CAPITAL,
        "pump": PUMP_INITIAL_CAPITAL,
        "scalping": SCALPING_INITIAL_CAPITAL,
    }
    baseline = initial_capitals.get(system, 10000)
    current_capital = _get_current_capital(system)
    reference_capital = max(baseline, current_capital)
    if reference_capital <= 0:
        reference_capital = baseline

    real_loss_pct = (stats["pnl_usd"] / reference_capital) * 100
    if real_loss_pct <= -DAILY_LOSS_LIMIT_PCT:
        print(f"  [CIRCUIT BREAKER] {system}: perda diaria de {real_loss_pct:.2f}% excede limite de -{DAILY_LOSS_LIMIT_PCT}%")
        send_circuit_breaker_alert(
            system,
            f"Perda diaria de {real_loss_pct:.2f}% excede limite de -{DAILY_LOSS_LIMIT_PCT}% "
            f"(${stats['pnl_usd']:+.2f})"
        )
        return True

    return False


# DEPRECATED: use enforce_circuit_breaker() (com alerta) ou check_circuit_breaker() (read-only)
is_circuit_broken = enforce_circuit_breaker


if __name__ == "__main__":
    report = generate_report()
    print(report)
    print("\nEnviando para Telegram...")
    send_telegram_message(report)
    mark_report_sent()
    print("Enviado.")
