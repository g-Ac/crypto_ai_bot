"""
Listener de comandos Telegram (bidirecional).
Executa em thread daemon dentro do main.py.

Comandos disponiveis:
  /status    - resumo de capital e trades de todos os sistemas
  /posicoes  - posicoes abertas no momento
  /pausar    - pausa abertura de novos trades
  /retomar   - retoma operacao normal
  /relatorio - envia o relatorio diario agora
  /ajuda     - lista de comandos
"""
import json
import os
import tempfile
import threading
import time
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

    paused_tag = "[PAUSADO] " if is_paused() else ""
    lines = [
        f"{paused_tag}Status do Bot",
        "",
        "--- Paper Trading ---",
        paper_status(),
        "",
        "--- Multi-Agent ---",
        get_agent_status(),
        "",
        "--- Pump Scanner ---",
        pump_status(),
    ]
    return "\n".join(lines)


def _cmd_posicoes():
    from daily_report import get_open_positions
    positions = get_open_positions()
    if not positions:
        return "Nenhuma posicao aberta no momento."
    lines = [f"Posicoes abertas ({len(positions)}):"]
    lines.extend(positions)
    return "\n".join(lines)


def _cmd_pausar():
    _set_paused(True)
    return (
        "Bot PAUSADO.\n"
        "Posicoes abertas continuam gerenciadas (stop/timeout).\n"
        "Nenhuma nova posicao sera aberta.\n"
        "Use /retomar para voltar ao normal."
    )


def _cmd_retomar():
    _set_paused(False)
    return "Bot RETOMADO. Operacao normal restaurada."


def _cmd_relatorio():
    from daily_report import generate_report
    return generate_report()


def _cmd_ajuda():
    return (
        "Comandos disponiveis:\n"
        "/status    - capital e trades de todos os sistemas\n"
        "/posicoes  - posicoes abertas agora\n"
        "/pausar    - pausa novos trades\n"
        "/retomar   - retoma operacao normal\n"
        "/relatorio - relatorio diario agora\n"
        "/ajuda     - esta mensagem"
    )


_HANDLERS = {
    "/status": _cmd_status,
    "/posicoes": _cmd_posicoes,
    "/pausar": _cmd_pausar,
    "/retomar": _cmd_retomar,
    "/relatorio": _cmd_relatorio,
    "/ajuda": _cmd_ajuda,
    "/help": _cmd_ajuda,
}


def _handle_command(text: str):
    cmd = text.strip().lower().split()[0]
    handler = _HANDLERS.get(cmd)
    if not handler:
        return None  # comando desconhecido - ignora silenciosamente
    try:
        return handler()
    except Exception as e:
        return f"Erro ao executar {cmd}: {e}"


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
