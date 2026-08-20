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
    SCALPING_INITIAL_CAPITAL, MOMENTUM_INITIAL_CAPITAL,
)
from telegram_notifier import send_telegram_message, send_circuit_breaker_alert
import database as db
from runtime_config import (
    LAST_REPORT_FILE,
    PAPER_STATE_FILE,
    AGENT_STATE_FILE,
    PUMP_STATE_FILE,
    SCALPING_STATE_FILE,
    MOMENTUM_STATE_FILE,
)



def _pnl_net_first(t, net_key, gross_key):
    """Prefere o PnL LIQUIDO (net) quando registrado; cai pro gross senao (rows/tabelas
    antigas sem fee). Evita reportar lucro bruto como se fosse o resultado."""
    v = t.get(net_key)
    return float(v) if v is not None else float(t.get(gross_key, 0) or 0)


def calc_daily_stats(trades):
    """Stats de uma lista de trade dicts. Usa PnL LIQUIDO (net_pnl_pct/net_pnl_usd) quando
    disponivel — o headline e o resultado real, nao o bruto. Cai pro gross onde nao houver
    fee registrado (backward-compat). Expoe gross_pnl_pct + is_net para transparencia."""
    zero = {"count": 0, "pnl_pct": 0, "pnl_usd": 0, "wins": 0, "losses": 0,
            "gross_pnl_pct": 0, "is_net": False}
    if not trades:
        return dict(zero)

    # Filtrar trades de abertura (exit_reason='open') para nao inflar contagem
    trades = [t for t in trades if t.get("exit_reason") != "open"]
    if not trades:
        return dict(zero)

    pnl_pct = pnl_usd = gross_pct = 0.0
    wins = losses = 0
    any_net = False
    for t in trades:
        p = _pnl_net_first(t, "net_pnl_pct", "pnl_pct")   # LIQUIDO (headline honesto)
        u = _pnl_net_first(t, "net_pnl_usd", "pnl_usd")
        gross_pct += float(t.get("pnl_pct", 0) or 0)
        if t.get("net_pnl_pct") is not None:
            any_net = True
        pnl_pct += p
        pnl_usd += u
        if p > 0:                                          # win/loss pela realidade LIQUIDA
            wins += 1
        elif p < 0:
            losses += 1

    return {
        "count": len(trades),
        "pnl_pct": round(pnl_pct, 2),
        "pnl_usd": round(pnl_usd, 2),
        "wins": wins,
        "losses": losses,
        "gross_pnl_pct": round(gross_pct, 2),
        "is_net": any_net,
    }


def get_open_positions():
    """Get open positions from active systems."""
    positions = []

    # Momentum
    if os.path.isfile(MOMENTUM_STATE_FILE):
        with open(MOMENTUM_STATE_FILE, "r") as f:
            state = json.load(f)
        for sym, pos in state.get("positions", {}).items():
            positions.append(
                f"  {sym}: {pos['direction']} @ {pos['entry_price']:.4f} "
                f"SL:{pos['sl_price']:.4f} TP1:{pos['tp1_price']:.4f} (momentum)"
            )

    return positions


def get_capital_status():
    """Get capital from active systems."""
    caps = {}

    if os.path.isfile(MOMENTUM_STATE_FILE):
        with open(MOMENTUM_STATE_FILE, "r") as f:
            caps["Momentum"] = json.load(f).get("capital", 0)

    return caps


def generate_report():
    """Generate the daily report text."""
    today = date.today().strftime("%d/%m/%Y")

    # Collect trades from each system
    momentum_trades = db.get_trades_today("momentum_trades")
    momentum_stats = calc_daily_stats(momentum_trades)

    capitals = get_capital_status()
    positions = get_open_positions()

    # Build report
    lines = [
        f"Relatorio Diario - {today}",
        "",
    ]

    # Momentum
    if "Momentum" in capitals:
        mo = momentum_stats
        lines.append(
            f"Momentum: {mo['count']} trades | "
            f"{mo['pnl_pct']:+.2f}% (${mo['pnl_usd']:+.2f}) | "
            f"W:{mo['wins']} L:{mo['losses']} | "
            f"Capital: ${capitals['Momentum']:.2f}"
        )

    # Total
    all_stats = [momentum_stats]
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


def _append_scalping_breakdown(lines: list):
    """Adiciona secao de breakdown do scalping ao relatorio."""
    # Funil de decisoes (24h)
    decisions = db.get_scalping_decisions_summary(hours=24)
    if decisions:
        total_dec = sum(decisions.values())
        passed = decisions.get("none", 0)
        pct = (passed / total_dec * 100) if total_dec > 0 else 0
        blockers = " | ".join(
            f"{k} {v}" for k, v in decisions.items() if k != "none"
        )
        lines.append("")
        lines.append(f"Scalping Funil (24h):")
        lines.append(f"  Decisoes: {total_dec} | Passou: {passed} ({pct:.1f}%)")
        if blockers:
            lines.append(f"  Bloqueado: {blockers}")

    # Trades por regime
    by_regime = db.get_scalping_trades_by_regime(hours=24)
    if by_regime:
        lines.append("")
        lines.append("Scalping por Regime:")
        for r in by_regime:
            regime = r["market_regime"] or "N/A"
            count = r["count"]
            total_pnl = r["total_pnl"] or 0
            wins = r["wins"] or 0
            wr = f"{wins / count * 100:.0f}%" if count > 0 else "N/A"
            lines.append(
                f"  {regime:12s} {count} trades | {total_pnl:+.2f}% | WR {wr}"
            )

    # Trades por sessao
    by_session = db.get_scalping_trades_by_session(hours=24)
    if by_session:
        lines.append("")
        lines.append("Scalping por Sessao:")
        for s in by_session:
            session = s["session_bucket"] or "N/A"
            count = s["count"]
            total_pnl = s["total_pnl"] or 0
            lines.append(
                f"  {session:12s} {count} trades | {total_pnl:+.2f}%"
            )


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
        "momentum": MOMENTUM_STATE_FILE,
    }
    fallback = {
        "paper": PAPER_INITIAL_CAPITAL,
        "agent": AGENT_INITIAL_CAPITAL,
        "pump": PUMP_INITIAL_CAPITAL,
        "scalping": SCALPING_INITIAL_CAPITAL,
        "momentum": MOMENTUM_INITIAL_CAPITAL,
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
        "momentum": "momentum_trades",
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
        "momentum": MOMENTUM_INITIAL_CAPITAL,
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
        "momentum": "momentum_trades",
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
        "momentum": MOMENTUM_INITIAL_CAPITAL,
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
