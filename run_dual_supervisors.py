"""
Launcher para subir baseline e v2 em paralelo com runtime isolado.

Uso:
    python run_dual_supervisors.py
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from runtime_config import PYTHON_EXECUTABLE


APP_DIR = Path(__file__).resolve().parent

INSTANCES = [
    {
        "bot_id": "baseline",
        "bot_label": "BASELINE",
        "dashboard_port": "5000",
        "telegram_instance_tag": "BASELINE",
        "enable_telegram_commands": os.getenv("BASELINE_TELEGRAM_COMMANDS", "0"),
        "enable_telegram_notifications": os.getenv("BASELINE_TELEGRAM_NOTIFICATIONS", "0"),
    },
    {
        "bot_id": "v2",
        "bot_label": "V2",
        "dashboard_port": "5001",
        "portfolio_target_capital": os.getenv("V2_PORTFOLIO_TARGET_CAPITAL", "1000"),
        "scalping_experimental_force_entries": os.getenv("V2_SCALPING_EXPERIMENTAL_FORCE_ENTRIES", "1"),
        "scalping_ignore_risk_filters": os.getenv("V2_SCALPING_IGNORE_RISK_FILTERS", "1"),
        "scalping_disable_ai_gate": os.getenv("V2_SCALPING_DISABLE_AI_GATE", "1"),
        "scalping_disable_cooldown": os.getenv("V2_SCALPING_DISABLE_COOLDOWN", "1"),
        "scalping_audit_enabled": os.getenv("V2_SCALPING_AUDIT_ENABLED", "1"),
        "scalping_max_positions": os.getenv("V2_SCALPING_MAX_POSITIONS", "10"),
        "scalping_force_position_size_pct": os.getenv("V2_SCALPING_FORCE_POSITION_SIZE_PCT", "100"),
        "scalping_force_leverage": os.getenv("V2_SCALPING_FORCE_LEVERAGE", "1"),
        "telegram_instance_tag": "V2",
        "enable_telegram_commands": "0",
        "enable_telegram_notifications": os.getenv("V2_TELEGRAM_NOTIFICATIONS", "0"),
    },
]


def launch_instance(instance: dict) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "BOT_ID": instance["bot_id"],
            "BOT_LABEL": instance["bot_label"],
            "DASHBOARD_PORT": instance["dashboard_port"],
            "BOT_PORTFOLIO_TARGET_CAPITAL": instance.get("portfolio_target_capital", ""),
            "SCALPING_EXPERIMENTAL_FORCE_ENTRIES": instance.get("scalping_experimental_force_entries", ""),
            "SCALPING_IGNORE_RISK_FILTERS": instance.get("scalping_ignore_risk_filters", ""),
            "SCALPING_DISABLE_AI_GATE": instance.get("scalping_disable_ai_gate", ""),
            "SCALPING_DISABLE_COOLDOWN": instance.get("scalping_disable_cooldown", ""),
            "SCALPING_AUDIT_ENABLED": instance.get("scalping_audit_enabled", ""),
            "SCALPING_MAX_POSITIONS": instance.get("scalping_max_positions", ""),
            "SCALPING_FORCE_POSITION_SIZE_PCT": instance.get("scalping_force_position_size_pct", ""),
            "SCALPING_FORCE_LEVERAGE": instance.get("scalping_force_leverage", ""),
            "TELEGRAM_INSTANCE_TAG": instance["telegram_instance_tag"],
            "ENABLE_TELEGRAM_COMMANDS": instance["enable_telegram_commands"],
            "ENABLE_TELEGRAM_NOTIFICATIONS": instance["enable_telegram_notifications"],
        }
    )

    process = subprocess.Popen(
        [PYTHON_EXECUTABLE, "-u", "supervisor.py"],
        cwd=str(APP_DIR),
        env=env,
    )
    print(
        f"[LAUNCHER] {instance['bot_id']} iniciado "
        f"(PID {process.pid}) na porta {instance['dashboard_port']}"
    )
    return process


def main() -> None:
    processes = {}

    try:
        for instance in INSTANCES:
            processes[instance["bot_id"]] = launch_instance(instance)

        print("[LAUNCHER] Duas instancias ativas. Ctrl+C para encerrar.")
        print("[LAUNCHER] Dashboards: http://127.0.0.1:5000 | http://127.0.0.1:5001")
        print("[LAUNCHER] Comparacao: http://127.0.0.1:5000/comparison?left=baseline&right=v2&days=1")

        while True:
            for bot_id, process in list(processes.items()):
                ret = process.poll()
                if ret is not None:
                    print(f"[LAUNCHER] {bot_id} encerrou com codigo {ret}.")
                    del processes[bot_id]

            if not processes:
                print("[LAUNCHER] Nenhuma instancia ativa. Encerrando launcher.")
                return

            time.sleep(3)

    except KeyboardInterrupt:
        print("\n[LAUNCHER] Encerrando instancias...")
    finally:
        for bot_id, process in processes.items():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                print(f"[LAUNCHER] {bot_id} encerrado.")


if __name__ == "__main__":
    main()
