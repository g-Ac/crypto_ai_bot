"""
Supervisor - gerencia main.py e pump_scanner.py.
Reinicia automaticamente se um dos bots crashar.
Grava logs em arquivo. Notifica via Telegram.
"""
import subprocess
import sys
import os
import time
from datetime import datetime
from runtime_config import APP_DIR, BOT_ID, BOT_LABEL, LOG_DIR, PYTHON_EXECUTABLE, ensure_runtime_dirs

BOT_DIR = str(APP_DIR)
ensure_runtime_dirs()

# Adiciona BOT_DIR ao path para imports
sys.path.insert(0, BOT_DIR)

BOTS = [
    {"name": "main_bot",    "script": "main.py"},
    {"name": "pump_scanner","script": "pump_scanner.py"},
    {"name": "dashboard",   "script": "dashboard_server.py"},
]

MAX_RESTARTS = 10   # maximo de restarts por bot antes de parar
BACKOFF_STEPS = [10, 30, 60, 120, 300]  # backoff exponencial em segundos (cap 5min)
STABLE_THRESHOLD = 300  # segundos rodando sem crash para resetar contador (5min)
ALERT_COOLDOWN = 600  # segundos entre alertas Telegram por bot (10 min)


def get_log_path(name):
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOG_DIR, f"{name}_{today}.log")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{BOT_ID}] {msg}"
    print(line)
    with open(os.path.join(LOG_DIR, "supervisor.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


_last_alert_time = {}  # {bot_name: timestamp} — rate-limit por bot


def notify_telegram(title, message, critical=False, bot_name=None):
    """Envia notificacao ao Telegram via telegram_notifier.

    Rate-limit: no maximo 1 alerta a cada ALERT_COOLDOWN segundos por bot,
    exceto alertas criticos (critical=True) que sempre passam.
    """
    if bot_name and not critical:
        now = time.time()
        last = _last_alert_time.get(bot_name, 0)
        if now - last < ALERT_COOLDOWN:
            log(f"Alerta suprimido para {bot_name} (cooldown {ALERT_COOLDOWN}s, faltam {int(ALERT_COOLDOWN - (now - last))}s)")
            return
        _last_alert_time[bot_name] = now
    try:
        from telegram_notifier import send_system_alert
        send_system_alert(title, message, critical=critical)
    except Exception as e:
        log(f"Falha ao notificar Telegram: {e}")


def run_bot(bot):
    script = os.path.join(BOT_DIR, bot["script"])
    log_path = get_log_path(bot["name"])

    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(f"\n{'='*50}\n")
    log_file.write(f"Iniciado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log_file.write(f"{'='*50}\n\n")
    log_file.flush()

    process = subprocess.Popen(
        [PYTHON_EXECUTABLE, "-u", script],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=BOT_DIR,
        env=os.environ.copy(),
    )
    return process, log_file


def _get_backoff_delay(restart_count):
    """Retorna delay de backoff baseado no numero de restarts (cap em 5min)."""
    idx = min(restart_count - 1, len(BACKOFF_STEPS) - 1)
    idx = max(idx, 0)
    return BACKOFF_STEPS[idx]


def main():
    log("=" * 50)
    log(f"SUPERVISOR INICIADO ({BOT_LABEL})")
    log(f"Diretorio: {BOT_DIR}")
    log(f"Runtime logs: {LOG_DIR}")
    log(f"Python: {PYTHON_EXECUTABLE}")
    log(f"Bots: {', '.join(b['name'] for b in BOTS)}")
    log(f"Max restarts: {MAX_RESTARTS} | Backoff: {BACKOFF_STEPS}s | Stable after: {STABLE_THRESHOLD}s | Alert cooldown: {ALERT_COOLDOWN}s")
    log("=" * 50)

    processes = {}
    log_files = {}
    restart_counts = {}
    start_times = {}  # quando cada processo foi iniciado (para detectar estabilidade)

    # Iniciar todos os bots
    for bot in BOTS:
        proc, lf = run_bot(bot)
        processes[bot["name"]] = proc
        log_files[bot["name"]] = lf
        restart_counts[bot["name"]] = 0
        start_times[bot["name"]] = time.time()
        log(f"{bot['name']} iniciado (PID: {proc.pid})")

    # Notificar inicio do supervisor
    bot_names = ", ".join(b["name"] for b in BOTS)
    notify_telegram(
        "Supervisor Iniciado",
        f"Todos os bots iniciados com sucesso.\n<b>Bots:</b> {bot_names}",
    )

    # Loop de monitoramento
    try:
        while True:
            for bot in BOTS:
                name = bot["name"]
                proc = processes[name]

                # Resetar contador se processo esta rodando estavelmente
                if proc.poll() is None and restart_counts[name] > 0:
                    uptime = time.time() - start_times[name]
                    if uptime >= STABLE_THRESHOLD:
                        log(f"{name} estavel por {int(uptime)}s - resetando contador de restarts ({restart_counts[name]} -> 0)")
                        restart_counts[name] = 0

                # Verificar se o processo ainda esta rodando
                ret = proc.poll()
                if ret is not None:
                    log_files[name].close()
                    restart_counts[name] += 1

                    if restart_counts[name] > MAX_RESTARTS:
                        log(f"{name} atingiu {MAX_RESTARTS} restarts. Parando.")
                        notify_telegram(
                            f"{name} - Limite de Restarts",
                            f"<b>{name}</b> atingiu <code>{MAX_RESTARTS}</code> restarts e foi parado.\n"
                            f"Intervencao manual necessaria.",
                            critical=True,
                            bot_name=name,
                        )
                        continue

                    delay = _get_backoff_delay(restart_counts[name])
                    log(f"{name} parou (codigo: {ret}). Reiniciando em {delay}s... (restart #{restart_counts[name]}/{MAX_RESTARTS})")
                    notify_telegram(
                        f"{name} Crashou",
                        f"<b>{name}</b> parou com codigo <code>{ret}</code>.\n"
                        f"Reiniciando em {delay}s (backoff)... (restart #{restart_counts[name]}/{MAX_RESTARTS})",
                        critical=restart_counts[name] >= 3,
                        bot_name=name,
                    )
                    time.sleep(delay)

                    proc, lf = run_bot(bot)
                    processes[name] = proc
                    log_files[name] = lf
                    start_times[name] = time.time()
                    log(f"{name} reiniciado (PID: {proc.pid})")

            time.sleep(5)  # Verificar a cada 5 segundos

    except KeyboardInterrupt:
        log("Parando todos os bots...")
        notify_telegram("Supervisor Encerrado", "Todos os bots estao sendo parados.")
        for name, proc in processes.items():
            proc.terminate()
            log(f"{name} parado")
        for lf in log_files.values():
            lf.close()
        log("Supervisor encerrado.")


if __name__ == "__main__":
    main()
