"""Watchdog ATIVO do liquidation_collector — pega o caso 'feed travado mas processo vivo'.

O `liquidation-collector.service` tem `Restart=always`, que cobre CRASH do processo.
Mas NÃO cobre o feed WebSocket (Bybit) conectar e parar de receber (socket zumbi,
reconnect em loop): o processo segue vivo, `k_liquidations` para de crescer, e
ninguém percebe. Foi o tipo de buraco silencioso que o apagão de 12-15/06 expôs.

Este watchdog detecta staleness pela idade da última liquidação gravada e:
  - reinicia o serviço (`sudo systemctl restart liquidation-collector`) — recovery;
  - alerta no Telegram (reiniciou / não conseguiu / nunca coletou / DB ausente).

Rodado por systemd timer a cada 30min. Idempotente — se saudável, sai silencioso.

Threshold default = 90min: calibrado empiricamente. O maior silêncio NORMAL entre
liquidações nos 14 símbolos foi ~52min (mercado calmo); 90min dá margem contra
falso-positivo. Um feed realmente morto fica mudo por horas. Override via env
`LIQUIDATION_STALE_MINUTES`.

Uso:
    python watchdog_liquidation.py             # check + recovery se stale
    python watchdog_liquidation.py --check     # só reporta, não reinicia
    python watchdog_liquidation.py --notify    # força alerta mesmo se OK (teste de canal)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# raiz do projeto no path (este script vive em scripts/)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from liquidation_store import last_event_age_seconds  # noqa: E402

# Defaults — overridable via env
DB_PATH = Path(os.getenv("LIQUIDATION_DB", "/home/pi/crypto_ai_bot/runtime/baseline/bot.db"))
STALE_MINUTES_THRESHOLD = int(os.getenv("LIQUIDATION_STALE_MINUTES", "90"))
SOURCE = os.getenv("LIQUIDATION_SOURCE", "bybit")
SERVICE = os.getenv("LIQUIDATION_SERVICE", "liquidation-collector.service")
SUBPROCESS_TIMEOUT_SECONDS = 30
LOG_PATH = Path("/home/pi/crypto_ai_bot/logs/watchdog_liquidation.log")


# ─── Telegram (fallback do CHAT principal se LIQUIDATION_TELEGRAM_CHAT_ID vazio) ───
def _telegram_chat_id() -> str | None:
    return os.getenv("LIQUIDATION_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")


def telegram_alert(text: str) -> bool:
    """Envia mensagem Telegram. Não levanta exceção (watchdog não pode crashar)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = _telegram_chat_id()
    if not token or not chat_id:
        return False
    try:
        import urllib.parse
        import urllib.request
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }).encode()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


# ─── Avaliação (lógica pura, testável) ───────────────────────────────────────
def evaluate(age_seconds: float | None, threshold_minutes: int) -> tuple[str, float | None]:
    """Classifica o estado do feed pela idade (s) da última liquidação.

    Retorna (status, gap_min) com status in {'ok', 'stale', 'never'}.
    Usa '>' estrito: exatamente no threshold ainda é 'ok'.
    """
    if age_seconds is None:
        return ("never", None)
    gap_min = age_seconds / 60.0
    if gap_min > threshold_minutes:
        return ("stale", gap_min)
    return ("ok", gap_min)


# ─── Ação de recuperação ─────────────────────────────────────────────────────
def try_restart() -> tuple[bool, str]:
    """Reinicia o serviço via sudo non-interactive (regra sudoers NOPASSWD específica).

    `sudo -n` falha na hora se não houver a regra (em vez de travar pedindo senha).
    Retorna (ok, detalhe).
    """
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", SERVICE],
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        ok = result.returncode == 0
        detail = "restart ok" if ok else f"rc={result.returncode}: {(result.stderr or '').strip()[:200]}"
        return ok, detail
    except subprocess.TimeoutExpired:
        return False, f"timeout após {SUBPROCESS_TIMEOUT_SECONDS}s"
    except Exception as e:
        return False, f"exceção: {type(e).__name__}: {e}"


# ─── Log local ────────────────────────────────────────────────────────────────
def log_event(message: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(f"{ts} {message}\n")
    except OSError:
        pass


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Watchdog ativo do liquidation_collector")
    parser.add_argument("--check", action="store_true",
                        help="só reporta staleness, não reinicia")
    parser.add_argument("--notify", action="store_true",
                        help="força envio Telegram mesmo se OK (teste de canal)")
    parser.add_argument("--threshold-minutes", type=int,
                        default=STALE_MINUTES_THRESHOLD,
                        help=f"threshold de staleness em min (default={STALE_MINUTES_THRESHOLD})")
    args = parser.parse_args()

    if not DB_PATH.exists():
        msg = f"DB ausente: {DB_PATH}"
        log_event(f"FATAL {msg}")
        telegram_alert(f"⚠️ <b>liquidation watchdog</b>\n{msg}")
        return 2

    now = int(time.time())
    conn = sqlite3.connect(str(DB_PATH))
    try:
        age = last_event_age_seconds(conn, now, source=SOURCE)
    finally:
        conn.close()

    status, gap_min = evaluate(age, args.threshold_minutes)
    gap_txt = "n/a" if gap_min is None else f"{gap_min:.0f}min"

    if status == "ok":
        log_event(f"OK gap={gap_txt}")
        if args.notify:
            telegram_alert(
                f"🟢 <b>liquidation watchdog</b> (notify teste)\n"
                f"Feed Bybit saudável — última liquidação há {gap_txt}."
            )
        print(f"[ok] feed saudável, última liquidação há {gap_txt} "
              f"(threshold {args.threshold_minutes}min)")
        return 0

    # status in {stale, never}
    headline = ("k_liquidations VAZIA (source=%s nunca coletou)" % SOURCE
                if status == "never"
                else f"feed Bybit MUDO há {gap_txt} (> {args.threshold_minutes}min)")
    log_event(f"STALE status={status} gap={gap_txt}")

    if args.check:
        print(f"[check-only] {headline}")
        return 1

    ok, detail = try_restart()
    log_event(f"RECOVERY restart ok={ok} ({detail}) status={status} gap={gap_txt}")
    emoji = "🟡" if ok else "🔴"
    recovery_status = (f"reiniciei o serviço ({detail})" if ok
                       else f"NÃO consegui reiniciar — {detail}")
    text = (f"{emoji} <b>liquidation watchdog</b>\n"
            f"{headline}\n\n"
            f"<b>Ação:</b> {recovery_status}")
    telegram_alert(text)
    print(text.replace("<b>", "").replace("</b>", ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
