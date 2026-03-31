"""
Listener de comandos Telegram (bidirecional).
Executa em thread daemon dentro do main.py.

Comandos disponiveis:
  /status      - resumo de capital e trades de todos os sistemas
  /posicoes    - posicoes abertas no momento
  /capital     - capital detalhado de todos os sistemas
  /performance - win rate, melhor/pior trade, streak
  /saude       - saude do sistema (CPU, RAM, disco, temp)
  /pausar      - pausa abertura de novos trades
  /retomar     - retoma operacao normal
  /relatorio   - envia o relatorio diario agora
  /ajuda       - lista de comandos
"""
import json
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime
import requests
from telegram_notifier import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, send_telegram_message

CONTROL_FILE = "bot_control.json"
_last_update_id = 0


# ── PAUSE CONTROL ─────────────────────────────────────────────────────────────

def is_paused() -> bool:
    """Retorna True se o bot esta pausado via /pausar."""
    try:
        if os.path.isfile(CONTROL_FILE):
            with open(CONTROL_FILE, "r") as f:
                return json.load(f).get("paused", False)
    except Exception:
        pass
    return False


def _set_paused(value: bool):
    data = json.dumps({"paused": value}, indent=2)
    dir_name = os.path.dirname(os.path.abspath(CONTROL_FILE)) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as f:
        f.write(data)
        tmp = f.name
    os.replace(tmp, CONTROL_FILE)


# ── COMMAND HANDLERS ──────────────────────────────────────────────────────────

def _cmd_status():
    from paper_trader import get_status as paper_status
    from trade_agents import get_agent_status
    from pump_trader import get_status as pump_status
    from scalping_trader import get_scalping_status

    paused_tag = "\U0001f7e1 <b>PAUSADO</b>\n\n" if is_paused() else ""
    lines = [
        f"{paused_tag}\U0001f916 <b>Status do Bot</b>",
        "",
        "\U0001f4c4 <b>Paper Trading</b>",
        f"<code>{paper_status()}</code>",
        "",
        "\U0001f916 <b>Multi-Agent</b>",
        f"<code>{get_agent_status()}</code>",
        "",
        "\U0001f680 <b>Pump Scanner</b>",
        f"<code>{pump_status()}</code>",
        "",
        "\u26a1 <b>Scalping</b>",
        f"<code>{get_scalping_status()}</code>",
    ]
    return "\n".join(lines)


def _cmd_posicoes():
    from daily_report import get_open_positions
    positions = get_open_positions()
    if not positions:
        return "\U0001f4cd Nenhuma posicao aberta no momento."
    lines = [f"\U0001f4cd <b>Posicoes Abertas ({len(positions)}):</b>\n"]
    for p in positions:
        lines.append(f"<code>{p.strip()}</code>")
    return "\n".join(lines)


def _cmd_capital():
    from daily_report import get_capital_status
    from config import PAPER_INITIAL_CAPITAL, AGENT_INITIAL_CAPITAL, PUMP_INITIAL_CAPITAL

    capitals = get_capital_status()
    initials = {
        "Paper": PAPER_INITIAL_CAPITAL,
        "Agent": AGENT_INITIAL_CAPITAL,
        "Pump": PUMP_INITIAL_CAPITAL,
    }

    lines = ["\U0001f4b0 <b>Capital por Sistema</b>\n"]
    total_current = 0
    total_initial = 0

    for name, current in capitals.items():
        initial = initials.get(name, current)
        change = ((current - initial) / initial * 100) if initial > 0 else 0
        emoji = "\U0001f7e2" if change >= 0 else "\U0001f534"
        lines.append(
            f"{emoji} <b>{name}:</b> <code>${current:.2f}</code> "
            f"({change:+.2f}% desde inicio)"
        )
        total_current += current
        total_initial += initial

    total_change = ((total_current - total_initial) / total_initial * 100) if total_initial > 0 else 0
    lines.append(f"\n\U0001f4b5 <b>Total:</b> <code>${total_current:.2f}</code> ({total_change:+.2f}%)")

    return "\n".join(lines)


def _cmd_performance():
    import database as db
    from daily_report import calc_daily_stats

    lines = ["\U0001f4ca <b>Performance do Dia</b>\n"]

    systems = {
        "Paper": "paper_trades",
        "Agent": "agent_trades",
        "Pump": "pump_trades",
    }

    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_pnl = 0

    for name, table in systems.items():
        trades = db.get_trades_today(table)
        stats = calc_daily_stats(trades)
        total_trades += stats["count"]
        total_wins += stats["wins"]
        total_losses += stats["losses"]
        total_pnl += stats["pnl_usd"]

        if stats["count"] > 0:
            wr = (stats["wins"] / stats["count"]) * 100
            emoji = "\u2705" if stats["pnl_usd"] >= 0 else "\u274c"
            lines.append(
                f"{emoji} <b>{name}:</b> {stats['count']} trades | "
                f"WR: <code>{wr:.0f}%</code> | "
                f"P&amp;L: <code>${stats['pnl_usd']:+.2f}</code>"
            )
        else:
            lines.append(f"\u2796 <b>{name}:</b> Sem trades hoje")

    if total_trades > 0:
        total_wr = (total_wins / total_trades) * 100
        lines.append(
            f"\n\U0001f3af <b>Total:</b> {total_trades} trades | "
            f"WR: <code>{total_wr:.0f}%</code> | "
            f"P&amp;L: <code>${total_pnl:+.2f}</code> | "
            f"W:{total_wins} L:{total_losses}"
        )
    else:
        lines.append("\nNenhum trade executado hoje.")

    return "\n".join(lines)


def _cmd_saude():
    """Saude do sistema (funciona em Linux/Raspberry Pi e Windows)."""
    health = {}

    # CPU
    try:
        with open("/proc/stat", "r") as f:
            parts = f.readline().split()
        idle = int(parts[4])
        total = sum(int(p) for p in parts[1:])
        health["cpu"] = f"{(1 - idle / total) * 100:.1f}%" if total > 0 else "N/A"
    except Exception:
        health["cpu"] = "N/A"

    health["cpu_cores"] = os.cpu_count() or "N/A"

    # RAM
    try:
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split()
                meminfo[parts[0].rstrip(":")] = int(parts[1])
        total_mb = meminfo.get("MemTotal", 0) / 1024
        avail_mb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / 1024
        used_mb = total_mb - avail_mb
        pct = (used_mb / total_mb * 100) if total_mb > 0 else 0
        health["ram"] = f"{used_mb:.0f}/{total_mb:.0f} MB ({pct:.0f}%)"
    except Exception:
        health["ram"] = "N/A"

    # Disco
    try:
        usage = shutil.disk_usage("/")
        total_gb = usage.total / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        pct = (used_gb / total_gb * 100) if total_gb > 0 else 0
        health["disco"] = f"{used_gb:.1f}/{total_gb:.1f} GB ({pct:.0f}%) | Livre: {free_gb:.1f} GB"
    except Exception:
        health["disco"] = "N/A"

    # Temperatura (Raspberry Pi)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = int(f.read().strip()) / 1000
        temp_emoji = "\U0001f525" if temp > 70 else ("\U0001f7e1" if temp > 60 else "\U0001f7e2")
        health["temp"] = f"{temp_emoji} {temp:.1f}C"
    except Exception:
        health["temp"] = "N/A"

    # Uptime
    try:
        with open("/proc/uptime", "r") as f:
            secs = float(f.read().split()[0])
        days = int(secs // 86400)
        hours = int((secs % 86400) // 3600)
        mins = int((secs % 3600) // 60)
        health["uptime"] = f"{days}d {hours}h {mins}m"
    except Exception:
        health["uptime"] = "N/A"

    # Bot uptime (tempo desde inicio do processo)
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        bot_secs = time.time() - proc.create_time()
        b_hours = int(bot_secs // 3600)
        b_mins = int((bot_secs % 3600) // 60)
        health["bot_uptime"] = f"{b_hours}h {b_mins}m"
    except Exception:
        health["bot_uptime"] = "N/A"

    # DB size
    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.db")
        if os.path.isfile(db_path):
            size_mb = os.path.getsize(db_path) / (1024 * 1024)
            health["db"] = f"{size_mb:.1f} MB"
        else:
            health["db"] = "N/A"
    except Exception:
        health["db"] = "N/A"

    lines = [
        "\U0001f3e5 <b>Saude do Sistema</b>\n",
        f"\U0001f5a5 <b>CPU:</b> {health['cpu']} ({health['cpu_cores']} cores)",
        f"\U0001f4be <b>RAM:</b> {health['ram']}",
        f"\U0001f4bf <b>Disco:</b> {health['disco']}",
        f"\U0001f321 <b>Temperatura:</b> {health['temp']}",
        f"\u23f1 <b>Uptime Sistema:</b> {health['uptime']}",
        f"\U0001f916 <b>Uptime Bot:</b> {health['bot_uptime']}",
        f"\U0001f4c1 <b>Database:</b> {health['db']}",
    ]

    return "\n".join(lines)


def _cmd_pausar():
    _set_paused(True)
    return (
        "\u23f8 <b>Bot PAUSADO</b>\n\n"
        "Posicoes abertas continuam gerenciadas (stop/timeout).\n"
        "Nenhuma nova posicao sera aberta.\n\n"
        "Use /retomar para voltar ao normal."
    )


def _cmd_retomar():
    _set_paused(False)
    return "\u25b6\ufe0f <b>Bot RETOMADO</b>\n\nOperacao normal restaurada."


def _cmd_relatorio():
    from daily_report import generate_report
    return generate_report()


def _cmd_ajuda():
    return (
        "\U0001f4cb <b>Comandos Disponiveis</b>\n\n"
        "/status - capital e trades de todos os sistemas\n"
        "/posicoes - posicoes abertas agora\n"
        "/capital - capital detalhado por sistema\n"
        "/performance - win rate e P&amp;L do dia\n"
        "/saude - CPU, RAM, disco, temperatura\n"
        "/pausar - pausa novos trades\n"
        "/retomar - retoma operacao normal\n"
        "/relatorio - relatorio diario completo\n"
        "/ajuda - esta mensagem"
    )


_HANDLERS = {
    "/status": _cmd_status,
    "/posicoes": _cmd_posicoes,
    "/capital": _cmd_capital,
    "/performance": _cmd_performance,
    "/saude": _cmd_saude,
    "/pausar": _cmd_pausar,
    "/retomar": _cmd_retomar,
    "/relatorio": _cmd_relatorio,
    "/ajuda": _cmd_ajuda,
    "/help": _cmd_ajuda,
}


def _handle_command(text: str):
    cmd = text.strip().lower().split()[0]
    # Remove @botname suffix (ex: /status@MyBot)
    if "@" in cmd:
        cmd = cmd.split("@")[0]
    handler = _HANDLERS.get(cmd)
    if not handler:
        return None  # comando desconhecido - ignora silenciosamente
    try:
        return handler()
    except Exception as e:
        return f"\u274c <b>Erro ao executar {cmd}:</b>\n<code>{e}</code>"


# ── POLLING LOOP ──────────────────────────────────────────────────────────────

def _poll_loop():
    global _last_update_id

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM CMD] Token/chat_id nao configurados, listener inativo.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"

    # Primeiro poll: descarta mensagens acumuladas antes do start (evita spam no restart)
    try:
        resp = requests.get(url, params={"offset": -1, "limit": 1}, timeout=10)
        if resp.status_code == 200:
            updates = resp.json().get("result", [])
            if updates:
                _last_update_id = updates[-1]["update_id"]
    except Exception:
        pass

    while True:
        try:
            params = {
                "offset": _last_update_id + 1,
                "timeout": 25,
                "allowed_updates": ["message"],
            }
            resp = requests.get(url, params=params, timeout=35)

            if resp.status_code != 200:
                time.sleep(5)
                continue

            updates = resp.json().get("result", [])
            for update in updates:
                _last_update_id = update["update_id"]
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")

                # Apenas responde ao chat configurado (seguranca)
                if chat_id != str(TELEGRAM_CHAT_ID):
                    continue

                if text.startswith("/"):
                    response = _handle_command(text)
                    if response:
                        send_telegram_message(response)

        except requests.exceptions.Timeout:
            pass  # normal em long polling
        except Exception as e:
            print(f"[TELEGRAM CMD] Erro no poll: {e}")
            time.sleep(10)


def start_command_listener():
    """Inicia o listener de comandos em thread daemon. Chamar uma vez no inicio do main.py."""
    t = threading.Thread(target=_poll_loop, daemon=True, name="telegram-cmd")
    t.start()
    print("[TELEGRAM CMD] Listener de comandos iniciado.")


# ── SELF-TEST ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testando importacao do telegram_commands...")
    print(f"is_paused() = {is_paused()}")
    print("Comandos registrados:", list(_HANDLERS.keys()))
    print("OK.")
