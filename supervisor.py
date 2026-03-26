"""
Supervisor - gerencia main.py e pump_scanner.py.
Reinicia automaticamente se um dos bots crashar.
Grava logs em arquivo.
"""
import subprocess
import sys
import os
import time
from datetime import datetime

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BOT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

BOTS = [
    {"name": "main_bot",    "script": "main.py"},
    {"name": "pump_scanner","script": "pump_scanner.py"},
    {"name": "dashboard",   "script": "dashboard_server.py"},
]

RESTART_DELAY = 10  # segundos antes de reiniciar um bot que crashou
MAX_RESTARTS = 50   # maximo de restarts por bot antes de parar


def get_log_path(name):
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOG_DIR, f"{name}_{today}.log")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(os.path.join(LOG_DIR, "supervisor.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_bot(bot):
    script = os.path.join(BOT_DIR, bot["script"])
    log_path = get_log_path(bot["name"])

    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(f"\n{'='*50}\n")
    log_file.write(f"Iniciado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log_file.write(f"{'='*50}\n\n")
    log_file.flush()

    process = subprocess.Popen(
        [sys.executable, "-u", script],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=BOT_DIR,
    )
    return process, log_file


def main():
    log("=" * 50)
    log("SUPERVISOR INICIADO")
    log(f"Diretorio: {BOT_DIR}")
    log(f"Python: {sys.executable}")
    log(f"Bots: {', '.join(b['name'] for b in BOTS)}")
    log("=" * 50)

    processes = {}
    log_files = {}
    restart_counts = {}

    # Iniciar todos os bots
    for bot in BOTS:
        proc, lf = run_bot(bot)
        processes[bot["name"]] = proc
        log_files[bot["name"]] = lf
        restart_counts[bot["name"]] = 0
        log(f"{bot['name']} iniciado (PID: {proc.pid})")

    # Loop de monitoramento
    try:
        while True:
            for bot in BOTS:
                name = bot["name"]
                proc = processes[name]

                # Verificar se o processo ainda esta rodando
                ret = proc.poll()
                if ret is not None:
                    log_files[name].close()
                    restart_counts[name] += 1

                    if restart_counts[name] > MAX_RESTARTS:
                        log(f"{name} atingiu {MAX_RESTARTS} restarts. Parando.")
                        continue

                    log(f"{name} parou (codigo: {ret}). Reiniciando em {RESTART_DELAY}s... (restart #{restart_counts[name]})")
                    time.sleep(RESTART_DELAY)

                    proc, lf = run_bot(bot)
                    processes[name] = proc
                    log_files[name] = lf
                    log(f"{name} reiniciado (PID: {proc.pid})")

            time.sleep(5)  # Verificar a cada 5 segundos

    except KeyboardInterrupt:
        log("Parando todos os bots...")
        for name, proc in processes.items():
            proc.terminate()
            log(f"{name} parado")
        for lf in log_files.values():
            lf.close()
        log("Supervisor encerrado.")


if __name__ == "__main__":
    main()
