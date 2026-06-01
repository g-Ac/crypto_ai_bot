"""Watchdog ATIVO do k_collector — pega o caso 'travado mas não crashado'.

Diferente do `Restart=always` (que só resolve crash), este watchdog detecta:
  - Última coleta com staleness > THRESHOLD horas (collector silenciosamente parado,
    rede caiu por longo período, lock órfão no flock).
  - Dispara ação de recuperação: roda `k_collector.py --backfill` SINCRONAMENTE
    (timeout protegido), e alerta Telegram independentemente do resultado.

Rodado por systemd timer separado a cada 1h. Idempotente — se collector está saudável,
sai silencioso.

Uso:
    python watchdog_k_collector.py             # check + ação se stale
    python watchdog_k_collector.py --check     # só reporta, não age
    python watchdog_k_collector.py --notify    # força alerta mesmo se ok (teste)
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
import k_collector as kc  # noqa: E402

# Defaults — overridable via env
DB_PATH = kc.DB_PATH
STALE_HOURS_THRESHOLD = int(os.getenv("K_COLLECTOR_STALE_HOURS", "2"))
COLLECTOR_SCRIPT = Path(__file__).resolve().parent / "k_collector.py"
PYTHON_BIN = "/home/pi/crypto_ai_bot/.venv/bin/python"
SUBPROCESS_TIMEOUT_SECONDS = 300   # 5 min — tempo razoável p/ backfill de 14 símbolos
LOG_PATH = Path("/home/pi/crypto_ai_bot/logs/watchdog_k_collector.log")


# ─── Telegram (fallback do CHAT principal se K_COLLECTOR_TELEGRAM_CHAT_ID vazio) ───
def _telegram_chat_id() -> str | None:
    return (os.getenv("K_COLLECTOR_TELEGRAM_CHAT_ID")
            or os.getenv("TELEGRAM_CHAT_ID"))


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


# ─── Staleness por tabela (lógica pura, testável) ────────────────────────────
def collect_staleness(conn: sqlite3.Connection, now: int) -> dict:
    """Retorna staleness por tabela usando o símbolo MAIS DEFASADO de cada uma.

    Estrutura: {tabela: {oldest_last_ts, gap_hours, never_collected}}
    """
    tables = [
        ("k_ratios", "bucket_ts"),
        ("k_prices", "bucket_ts"),
        ("k_open_interest", "bucket_ts"),
        ("k_funding_rates", "funding_time"),
    ]
    out = {}
    for tbl, col in tables:
        oldest = None
        for sym in kc.SYMBOLS:
            ts = kc.last_bucket_ts(conn, tbl, sym, col)
            if ts is None:
                continue
            if oldest is None or ts < oldest:
                oldest = ts
        if oldest is None:
            out[tbl] = {"never_collected": True}
        else:
            gap_h = max(0, now - oldest) // 3600
            out[tbl] = {"oldest_last_ts": int(oldest), "gap_hours": int(gap_h)}
    return out


def is_stale(staleness: dict, threshold_hours: int) -> tuple[bool, list[str]]:
    """Avalia se algum item ultrapassa threshold. Funding tem cadência 8h, então
    aplicamos threshold X4 pra ele (32h se threshold=8h, evita falso alarme).

    Retorna (stale, lista de tabelas que dispararam).
    """
    stale_tables = []
    for tbl, info in staleness.items():
        if info.get("never_collected"):
            stale_tables.append(f"{tbl}=never")
            continue
        # funding rate liquida a cada 8h, então tolerância é 4x maior
        effective_threshold = threshold_hours * 4 if tbl == "k_funding_rates" else threshold_hours
        if info["gap_hours"] > effective_threshold:
            stale_tables.append(
                f"{tbl}={info['gap_hours']}h>{effective_threshold}h"
            )
    return len(stale_tables) > 0, stale_tables


def format_staleness_report(staleness: dict) -> str:
    """Formata staleness pra mensagem Telegram."""
    parts = []
    for tbl, info in staleness.items():
        if info.get("never_collected"):
            parts.append(f"  - {tbl}: <i>NUNCA coletado</i>")
        else:
            parts.append(f"  - {tbl}: gap=<b>{info['gap_hours']}h</b>")
    return "\n".join(parts)


# ─── Ação de recuperação ─────────────────────────────────────────────────────
def try_recovery() -> tuple[bool, str]:
    """Roda `k_collector --backfill` sincronamente com timeout. Retorna (ok, stdout)."""
    try:
        result = subprocess.run(
            [PYTHON_BIN, str(COLLECTOR_SCRIPT), "--backfill"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        ok = result.returncode == 0
        out = (result.stdout or "")[-1000:]
        if result.stderr:
            out += f"\n[stderr] {result.stderr[-500:]}"
        return ok, out
    except subprocess.TimeoutExpired:
        return False, f"timeout após {SUBPROCESS_TIMEOUT_SECONDS}s"
    except Exception as e:
        return False, f"exceção: {type(e).__name__}: {e}"


# ─── Log local ────────────────────────────────────────────────────────────────
def log_event(message: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    line = f"{ts} {message}\n"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(line)
    except OSError:
        pass


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Watchdog ativo do k_collector")
    parser.add_argument("--check", action="store_true",
                        help="só reporta staleness, não dispara recovery")
    parser.add_argument("--notify", action="store_true",
                        help="força envio Telegram mesmo se OK (teste de canal)")
    parser.add_argument("--threshold-hours", type=int,
                        default=STALE_HOURS_THRESHOLD,
                        help=f"threshold de staleness (default={STALE_HOURS_THRESHOLD}h)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        msg = f"DB ausente: {DB_PATH}"
        log_event(f"FATAL {msg}")
        telegram_alert(f"⚠️ <b>k_collector watchdog</b>\n{msg}")
        return 2

    now = int(time.time())
    conn = sqlite3.connect(str(DB_PATH))
    try:
        staleness = collect_staleness(conn, now)
    finally:
        conn.close()

    stale, stale_tables = is_stale(staleness, args.threshold_hours)
    report = format_staleness_report(staleness)

    if stale:
        log_event(f"STALE {stale_tables}")
        if args.check:
            print(f"[check-only] STALE: {stale_tables}\n{report}")
            return 1

        ok, recovery_log = try_recovery()
        log_event(f"RECOVERY ok={ok} stale={stale_tables}")
        emoji = "🟡" if ok else "🔴"
        recovery_status = "backfill OK" if ok else "backfill FALHOU"
        text = (f"{emoji} <b>k_collector watchdog</b>\n"
                f"staleness > {args.threshold_hours}h em: {', '.join(stale_tables)}\n"
                f"\n<b>Staleness atual:</b>\n{report}\n"
                f"\n<b>Recovery:</b> {recovery_status}\n"
                f"<pre>{recovery_log[-400:]}</pre>")
        telegram_alert(text)
        print(text.replace("<b>", "").replace("</b>", "")
              .replace("<i>", "").replace("</i>", "")
              .replace("<pre>", "").replace("</pre>", ""))
        return 0 if ok else 1

    # Saudável
    log_event(f"OK staleness={ {k: v.get('gap_hours') for k, v in staleness.items()} }")
    if args.notify:
        telegram_alert(
            f"🟢 <b>k_collector watchdog</b> (notify teste)\n"
            f"Tudo saudável.\n{report}"
        )
    plain_report = (report.replace("<b>", "").replace("</b>", "")
                    .replace("<i>", "").replace("</i>", ""))
    print(f"[ok] no staleness > {args.threshold_hours}h\n{plain_report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
