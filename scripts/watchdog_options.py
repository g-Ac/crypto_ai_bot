"""Watchdog ATIVO do options_collector (EXP-019) — pega 'travado mas não crashado'.

A cadeia de opções da Deribit é PERECÍVEL e IRRECUPERÁVEL (sem backfill, exceto DVOL).
O collector roda via cron no minuto :10 (flock). Se travar silenciosamente (exceção
não-fatal, Deribit fora por horas, rede caída em várias rodadas, disco/DB lock, crontab
perdido), `k_options_features` para de crescer e ninguém percebe — comprometendo o
veredito forward do EXP-019 (≥2026-09-01, exige ≥10 semanas e cobertura ≥90%).

Este watchdog detecta staleness pela idade da última feature gravada (MAX(bucket_ts),
ts da Deribit) e:
  - re-dispara o collector — recovery;
  - alerta no Telegram (parou / não conseguiu / nunca coletou / DB ausente).

Espelha scripts/watchdog_k_collector.py: o options_collector é CRON-based (não é systemd
service), então o recovery RE-RODA o script — não há `systemctl restart` nem sudoers.
Diferente do k_collector, NÃO há `--backfill` (cadeia irrecuperável): o recovery captura o
snapshot da hora corrente e retoma a cadência; horas já perdidas não voltam. O valor
principal é o ALERTA.

Rodado por systemd timer a cada 1h (:40, defasado do cron :10 pra dar tempo da rodada
terminar). Idempotente — se saudável, sai silencioso.

Threshold default = 2h: o collector é hourly, então 2h tolera 1 falha transitória e só
dispara após ~2 rodadas perdidas. Override via env `OPTIONS_COLLECTOR_STALE_HOURS`.

Uso:
    python watchdog_options.py             # check + recovery se stale
    python watchdog_options.py --check     # só reporta, não dispara recovery
    python watchdog_options.py --notify    # força alerta mesmo se OK (teste de canal)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# Importa configs e helpers do collector (mesmo diretório)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import options_collector as oc  # noqa: E402

# Defaults — overridable via env
DB_PATH = oc.DB_PATH
SYMBOLS = oc.SYMBOLS
STALE_HOURS_THRESHOLD = float(os.getenv("OPTIONS_COLLECTOR_STALE_HOURS", "2"))
COLLECTOR_SCRIPT = Path(__file__).resolve().parent / "options_collector.py"
PYTHON_BIN = "/home/pi/crypto_ai_bot/.venv/bin/python"
SUBPROCESS_TIMEOUT_SECONDS = 120   # ~2 chamadas públicas/símbolo; coleta leve
LOG_PATH = Path("/home/pi/crypto_ai_bot/logs/watchdog_options.log")


# ─── Telegram (fallback do CHAT principal se OPTIONS_TELEGRAM_CHAT_ID vazio) ───
def _telegram_chat_id() -> str | None:
    return os.getenv("OPTIONS_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")


def telegram_alert(text: str) -> bool:
    """Envia mensagem Telegram. Não levanta exceção (watchdog não pode crashar).

    Usa urllib puro de propósito: o watchdog roda como oneshot systemd isolado e não
    importa o stack do bot (telegram_notifier/runtime_config). Sempre tenta enviar —
    NÃO respeita ENABLE_TELEGRAM_NOTIFICATIONS (um alerta de saúde não pode ser silenciado).
    """
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


# ─── Lógica pura de classificação (testável, sem banco) ──────────────────────
def classify(age_seconds: float | None, threshold_hours: float) -> tuple[str, float | None]:
    """Classifica a idade (s) da última feature. status ∈ {ok, stale, never}.

    Usa '>' estrito: exatamente no threshold ainda é 'ok'.
    """
    if age_seconds is None:
        return ("never", None)
    gap_h = age_seconds / 3600.0
    if gap_h > threshold_hours:
        return ("stale", gap_h)
    return ("ok", gap_h)


# ─── Acesso ao banco (testável com :memory:) ─────────────────────────────────
def feature_age_seconds(conn: sqlite3.Connection, now: int, symbols) -> dict:
    """Idade (s) da feature mais recente por símbolo, via MAX(bucket_ts).

    None = símbolo nunca coletado. max(0, ...) protege contra relógio do Pi atrasado
    (sem RTC; trava após power-loss — pi_power_loss_recovery).
    """
    out = {}
    for sym in symbols:
        try:
            row = conn.execute(
                "SELECT MAX(bucket_ts) FROM k_options_features WHERE symbol=?", (sym,)
            ).fetchone()
        except sqlite3.OperationalError:
            out[sym] = None
            continue
        ts = row[0] if row else None
        out[sym] = None if ts is None else max(0, now - int(ts))
    return out


def worst(ages: dict, threshold_hours: float) -> tuple[str, str | None, float | None]:
    """Combina o estado por símbolo. Retorna (status, symbol, gap_hours).

    'never' DOMINA: qualquer símbolo esperado sem dado é problema (BTC é canônico do
    EXP-019, mas perder ETH também conta). Senão, classifica o símbolo MAIS DEFASADO.
    """
    if not ages:
        return ("never", None, None)
    nevers = [s for s, a in ages.items() if a is None]
    if nevers:
        return ("never", sorted(nevers)[0], None)
    sym = max(ages, key=lambda s: ages[s])  # maior idade = mais defasado
    status, gap = classify(ages[sym], threshold_hours)
    return (status, sym, gap)


# ─── Ação de recuperação ─────────────────────────────────────────────────────
def try_recovery() -> tuple[bool, str]:
    """Re-roda options_collector.py (SEM --backfill — cadeia irrecuperável).

    Captura o snapshot da hora corrente e retoma a cadência. Retorna (ok, stdout).
    """
    try:
        result = subprocess.run(
            [PYTHON_BIN, str(COLLECTOR_SCRIPT)],
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        ok = result.returncode == 0
        out = (result.stdout or "")[-1000:]
        if result.stderr:
            out += f"\n[stderr] {result.stderr[-500:]}"
        return ok, out
    except subprocess.TimeoutExpired:
        return False, f"timeout após {SUBPROCESS_TIMEOUT_SECONDS}s"
    except Exception as e:  # noqa: BLE001 - boundary, watchdog não pode crashar
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
    parser = argparse.ArgumentParser(description="Watchdog ativo do options_collector (EXP-019)")
    parser.add_argument("--check", action="store_true",
                        help="só reporta staleness, não dispara recovery")
    parser.add_argument("--notify", action="store_true",
                        help="força envio Telegram mesmo se OK (teste de canal)")
    parser.add_argument("--threshold-hours", type=float,
                        default=STALE_HOURS_THRESHOLD,
                        help=f"threshold de staleness em h (default={STALE_HOURS_THRESHOLD})")
    args = parser.parse_args()

    if not DB_PATH.exists():
        msg = f"DB ausente: {DB_PATH}"
        log_event(f"FATAL {msg}")
        telegram_alert(f"⚠️ <b>options watchdog</b>\n{msg}")
        return 2

    now = int(time.time())
    conn = sqlite3.connect(str(DB_PATH))
    try:
        ages = feature_age_seconds(conn, now, SYMBOLS)
    finally:
        conn.close()

    status, sym, gap = worst(ages, args.threshold_hours)
    gap_txt = "n/a" if gap is None else f"{gap:.1f}h"

    if status == "ok":
        log_event(f"OK gap={gap_txt} ({sym})")
        if args.notify:
            telegram_alert(
                f"🟢 <b>options watchdog</b> (notify teste)\n"
                f"Coleta saudável — feature mais defasada ({sym}) há {gap_txt}."
            )
        print(f"[ok] coleta saudável, feature mais defasada {sym} há {gap_txt} "
              f"(threshold {args.threshold_hours}h)")
        return 0

    # status in {stale, never}
    headline = (f"k_options_features SEM {sym} (nunca coletado)"
                if status == "never"
                else f"coleta de {sym} PARADA há {gap_txt} (> {args.threshold_hours}h)")
    log_event(f"STALE status={status} sym={sym} gap={gap_txt}")

    if args.check:
        print(f"[check-only] {headline}")
        return 1

    ok, recovery_log = try_recovery()
    log_event(f"RECOVERY ok={ok} status={status} sym={sym} gap={gap_txt}")
    emoji = "🟡" if ok else "🔴"
    recovery_status = "re-disparei o collector (OK)" if ok else "re-disparo FALHOU"
    text = (f"{emoji} <b>options watchdog</b>\n"
            f"{headline}\n\n"
            f"<b>Recovery:</b> {recovery_status}\n"
            f"<i>(cadeia é perecível; horas perdidas não voltam)</i>\n"
            f"<pre>{recovery_log[-400:]}</pre>")
    telegram_alert(text)
    print(text.replace("<b>", "").replace("</b>", "")
          .replace("<i>", "").replace("</i>", "")
          .replace("<pre>", "").replace("</pre>", ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
