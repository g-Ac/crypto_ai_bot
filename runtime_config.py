"""
Configuracao central de runtime por instancia do bot.

Permite subir multiplas instancias a partir do mesmo codigo-base,
isolando banco, arquivos de estado, logs e porta do dashboard.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from config import (
    AGENT_INITIAL_CAPITAL,
    PAPER_INITIAL_CAPITAL,
    PORTFOLIO_INITIAL_CAPITAL,
    PUMP_INITIAL_CAPITAL,
    SCALPING_INITIAL_CAPITAL,
)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    normalized = normalized.strip("-._").lower()
    return normalized or "baseline"


APP_DIR = Path(__file__).resolve().parent
BOT_ID = _slugify(os.getenv("BOT_ID", "baseline"))
BOT_LABEL = os.getenv("BOT_LABEL", BOT_ID.upper())

_default_port_map = {
    "baseline": 5000,
    "v2": 5001,
}

DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", _default_port_map.get(BOT_ID, 5001)))
ENABLE_TELEGRAM_COMMANDS = _bool_env("ENABLE_TELEGRAM_COMMANDS", BOT_ID == "baseline")
ENABLE_TELEGRAM_NOTIFICATIONS = _bool_env("ENABLE_TELEGRAM_NOTIFICATIONS", True)
TELEGRAM_INSTANCE_TAG = os.getenv("TELEGRAM_INSTANCE_TAG", BOT_LABEL)

RUNTIME_BASE_DIR = Path(os.getenv("BOT_RUNTIME_BASE_DIR", APP_DIR / "runtime"))
RUNTIME_DIR = RUNTIME_BASE_DIR / BOT_ID
LOG_DIR = RUNTIME_DIR / "logs"

_venv_python = APP_DIR / ".venv" / "Scripts" / "python.exe"
PYTHON_EXECUTABLE = os.getenv(
    "BOT_PYTHON",
    str(_venv_python if _venv_python.exists() else Path(sys.executable)),
)


def _git_output(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(APP_DIR),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


GIT_SHA = os.getenv("BOT_GIT_SHA", _git_output(["rev-parse", "--short", "HEAD"]) or "unknown")
GIT_BRANCH = os.getenv("BOT_GIT_BRANCH", _git_output(["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown")
GIT_COMMIT_DATE = os.getenv("BOT_GIT_COMMIT_DATE", _git_output(["log", "-1", "--format=%cI"]) or "unknown")
VERSION_TAG = os.getenv("BOT_VERSION_TAG", f"{BOT_ID}:{GIT_SHA}")
SCALPING_EXPERIMENTAL_FORCE_ENTRIES = _bool_env("SCALPING_EXPERIMENTAL_FORCE_ENTRIES", False)
SCALPING_IGNORE_RISK_FILTERS = _bool_env("SCALPING_IGNORE_RISK_FILTERS", SCALPING_EXPERIMENTAL_FORCE_ENTRIES)
SCALPING_DISABLE_AI_GATE = _bool_env("SCALPING_DISABLE_AI_GATE", SCALPING_EXPERIMENTAL_FORCE_ENTRIES)
SCALPING_DISABLE_COOLDOWN = _bool_env("SCALPING_DISABLE_COOLDOWN", SCALPING_EXPERIMENTAL_FORCE_ENTRIES)
SCALPING_AUDIT_ENABLED = _bool_env("SCALPING_AUDIT_ENABLED", True)
SCALPING_MAX_POSITIONS_OVERRIDE = _int_env("SCALPING_MAX_POSITIONS", 0)
SCALPING_FORCE_POSITION_SIZE_PCT = _float_env("SCALPING_FORCE_POSITION_SIZE_PCT", 100.0)
SCALPING_FORCE_LEVERAGE = max(1, _int_env("SCALPING_FORCE_LEVERAGE", 1))


def ensure_runtime_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def runtime_path(filename: str) -> str:
    ensure_runtime_dirs()
    return str(RUNTIME_DIR / filename)


def app_path(filename: str) -> str:
    return str(APP_DIR / filename)


DB_FILE = runtime_path("bot.db")
PAPER_STATE_FILE = runtime_path("paper_state.json")
AGENT_STATE_FILE = runtime_path("agent_state.json")
PUMP_STATE_FILE = runtime_path("pump_positions.json")
SCALPING_STATE_FILE = runtime_path("scalping_state.json")
CONTROL_FILE = runtime_path("bot_control.json")
PUMP_COOLDOWN_FILE = runtime_path("pump_cooldown.json")
LAST_ALERT_FILE = runtime_path("last_alert.json")
LAST_REPORT_FILE = runtime_path("last_report_date.txt")
TECHNICAL_ANALYSIS_FILE = runtime_path("technical_analysis.json")
RELEVANT_OPPORTUNITIES_FILE = runtime_path("relevant_opportunities.json")
RUNTIME_MANIFEST_FILE = runtime_path("runtime_manifest.json")
SCALPING_OUTCOMES_JSON_FILE = runtime_path("scalping_outcomes_dataset.json")
SCALPING_OUTCOMES_JSONL_FILE = runtime_path("scalping_outcomes_dataset.jsonl")
SCALPING_OUTCOMES_CSV_FILE = runtime_path("scalping_outcomes_dataset.csv")
SCALPING_SCORER_REPORT_FILE = runtime_path("scalping_scorer_report.json")


def runtime_metadata() -> dict:
    return {
        "bot_id": BOT_ID,
        "label": BOT_LABEL,
        "dashboard_port": DASHBOARD_PORT,
        "runtime_dir": str(RUNTIME_DIR),
        "logs_dir": str(LOG_DIR),
        "python_executable": PYTHON_EXECUTABLE,
        "git_sha": GIT_SHA,
        "git_branch": GIT_BRANCH,
        "git_commit_date": GIT_COMMIT_DATE,
        "version_tag": VERSION_TAG,
        "portfolio_initial_capital": round(float(PORTFOLIO_INITIAL_CAPITAL), 2),
        "initial_capitals": {
            "paper": round(float(PAPER_INITIAL_CAPITAL), 2),
            "agent": round(float(AGENT_INITIAL_CAPITAL), 2),
            "pump": round(float(PUMP_INITIAL_CAPITAL), 2),
            "scalping": round(float(SCALPING_INITIAL_CAPITAL), 2),
        },
        "scalping_experiment": {
            "force_entries": SCALPING_EXPERIMENTAL_FORCE_ENTRIES,
            "ignore_risk_filters": SCALPING_IGNORE_RISK_FILTERS,
            "disable_ai_gate": SCALPING_DISABLE_AI_GATE,
            "disable_cooldown": SCALPING_DISABLE_COOLDOWN,
            "audit_enabled": SCALPING_AUDIT_ENABLED,
            "max_positions_override": SCALPING_MAX_POSITIONS_OVERRIDE,
            "force_position_size_pct": round(float(SCALPING_FORCE_POSITION_SIZE_PCT), 2),
            "force_leverage": SCALPING_FORCE_LEVERAGE,
        },
        "telegram_commands_enabled": ENABLE_TELEGRAM_COMMANDS,
        "telegram_notifications_enabled": ENABLE_TELEGRAM_NOTIFICATIONS,
    }


def write_runtime_manifest(extra: dict | None = None) -> str:
    """Persiste os metadados da instancia para consumo por comparadores locais."""
    ensure_runtime_dirs()
    payload = runtime_metadata()
    payload["written_at"] = datetime.now().isoformat()
    if extra:
        payload.update(extra)

    content = json.dumps(payload, indent=2, ensure_ascii=False)
    dir_name = os.path.dirname(RUNTIME_MANIFEST_FILE) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp", encoding="utf-8") as handle:
        handle.write(content)
        tmp_path = handle.name
    os.replace(tmp_path, RUNTIME_MANIFEST_FILE)
    return RUNTIME_MANIFEST_FILE


write_runtime_manifest()
