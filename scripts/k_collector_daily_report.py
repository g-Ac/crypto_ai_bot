"""Relatório diário do k_collector — staleness + gaps + backfill summary 24h.

Envia 1x/dia via Telegram (chat separado pro lab se K_COLLECTOR_TELEGRAM_CHAT_ID
estiver setado; senão fallback pro chat principal).

Reporta:
  - Staleness por tabela (gap horas desde última coleta).
  - Total de runs nas últimas 24h e contagem por status (ok/partial/fail).
  - Rows inseridas em 24h (por tabela).
  - Recuperabilidade dos gaps:
      LSR/OI/prices retention ~30d → recuperável se gap < 720h
      funding retention ~370d → recuperável quase sempre

Uso:
    python k_collector_daily_report.py            # gera e envia
    python k_collector_daily_report.py --stdout   # só imprime, não envia Telegram
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import k_collector as kc  # noqa: E402

DB_PATH = kc.DB_PATH
ONE_DAY_S = 86400


def _telegram_chat_id() -> str | None:
    return (os.getenv("K_COLLECTOR_TELEGRAM_CHAT_ID")
            or os.getenv("TELEGRAM_CHAT_ID"))


def telegram_send(text: str) -> bool:
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
            "disable_web_page_preview": "true",
        }).encode()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def gather_staleness(conn: sqlite3.Connection, now: int) -> dict:
    """Por tabela: oldest_last_ts entre símbolos, gap_hours, classificação retenção."""
    tables = [
        ("k_ratios", "bucket_ts", kc.RETENTION_HOURS_LSR_OI),
        ("k_prices", "bucket_ts", kc.RETENTION_HOURS_LSR_OI),
        ("k_open_interest", "bucket_ts", kc.RETENTION_HOURS_LSR_OI),
        ("k_funding_rates", "funding_time", kc.RETENTION_HOURS_FUNDING),
    ]
    out = {}
    for tbl, col, retention_h in tables:
        oldest = None
        symbols_status = {}
        for sym in kc.SYMBOLS:
            ts = kc.last_bucket_ts(conn, tbl, sym, col)
            symbols_status[sym] = ts
            if ts is None:
                continue
            if oldest is None or ts < oldest:
                oldest = ts
        if oldest is None:
            out[tbl] = {"never_collected": True, "retention_h": retention_h}
            continue
        gap_h = max(0, now - oldest) // 3600
        recoverable = gap_h < retention_h
        # quantos símbolos têm o gap > retenção (dado perdido específico)
        lost = sum(1 for ts in symbols_status.values()
                   if ts is not None and (now - ts) // 3600 > retention_h)
        out[tbl] = {
            "oldest_last_ts": int(oldest),
            "gap_hours": int(gap_h),
            "retention_hours": retention_h,
            "recoverable": bool(recoverable),
            "symbols_lost": int(lost),
        }
    return out


def gather_runs_24h(conn: sqlite3.Connection, now: int) -> dict:
    """Estatísticas dos runs nas últimas 24h da tabela k_collector_runs."""
    cutoff = now - ONE_DAY_S
    cur = conn.execute(
        "SELECT status, COUNT(*), SUM(rows_inserted), SUM(symbols_ok), "
        "SUM(symbols_fail) FROM k_collector_runs "
        "WHERE started_at >= ? GROUP BY status",
        (cutoff,),
    )
    by_status = {}
    total_runs = 0
    total_rows = 0
    for row in cur.fetchall():
        status, count, rows, ok, fail = row
        by_status[status or "unknown"] = {
            "count": int(count),
            "rows_inserted": int(rows or 0),
            "symbols_ok": int(ok or 0),
            "symbols_fail": int(fail or 0),
        }
        total_runs += int(count)
        total_rows += int(rows or 0)

    # Última run
    cur = conn.execute(
        "SELECT started_at, status, rows_inserted, notes "
        "FROM k_collector_runs ORDER BY run_id DESC LIMIT 1"
    )
    last = cur.fetchone()
    last_run = None
    if last:
        last_run = {
            "started_at": int(last[0]),
            "status": last[1],
            "rows_inserted": int(last[2] or 0),
            "notes": (last[3] or "")[:200],
            "age_hours": (now - int(last[0])) // 3600,
        }

    return {
        "total_runs_24h": total_runs,
        "total_rows_inserted_24h": total_rows,
        "by_status": by_status,
        "last_run": last_run,
    }


def gather_rows_inserted_per_table_24h(conn: sqlite3.Connection, now: int) -> dict:
    """Conta rows com collected_at nas últimas 24h por tabela."""
    cutoff = now - ONE_DAY_S
    out = {}
    for tbl in ("k_ratios", "k_prices", "k_open_interest", "k_funding_rates"):
        cur = conn.execute(
            f"SELECT COUNT(*) FROM {tbl} WHERE collected_at >= ?", (cutoff,)
        )
        out[tbl] = int(cur.fetchone()[0])
    return out


def format_report(staleness: dict, runs: dict, inserted_24h: dict) -> str:
    """Mensagem HTML pra Telegram."""
    now_str = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime())
    lines = [
        f"📊 <b>k_collector daily</b> — {now_str}",
        "",
        "<b>Staleness (gap horas desde última coleta)</b>:",
    ]
    for tbl, info in staleness.items():
        if info.get("never_collected"):
            lines.append(f"  • {tbl}: <i>NUNCA coletado</i>")
            continue
        flag = "🟢" if info["gap_hours"] < 4 else ("🟡" if info["gap_hours"] < 24 else "🔴")
        rec = "recuperável" if info["recoverable"] else "<b>PERDIDO</b>"
        lost_part = (f" — {info['symbols_lost']} símbolos com dado perdido"
                     if info["symbols_lost"] > 0 else "")
        lines.append(
            f"  {flag} {tbl}: <b>{info['gap_hours']}h</b> "
            f"(retenção {info['retention_hours'] // 24}d, {rec}){lost_part}"
        )

    lines.append("")
    lines.append("<b>Runs nas últimas 24h</b>:")
    if runs["total_runs_24h"] == 0:
        lines.append("  ⚠️ <b>0 runs</b> — possível parada do agendador")
    else:
        lines.append(
            f"  • total: {runs['total_runs_24h']} runs, "
            f"<b>{runs['total_rows_inserted_24h']}</b> rows inseridas"
        )
        for status, s in sorted(runs["by_status"].items()):
            emoji = {"ok": "🟢", "partial": "🟡", "fail": "🔴"}.get(status, "•")
            lines.append(
                f"  {emoji} {status}: {s['count']} runs, "
                f"{s['rows_inserted']} rows"
            )

    last = runs.get("last_run")
    if last:
        lines.append(
            f"\n<b>Última run</b>: {last['age_hours']}h atrás, "
            f"status=<b>{last['status']}</b>, "
            f"{last['rows_inserted']} rows"
        )
        if last.get("notes"):
            lines.append(f"  notes: <i>{last['notes'][:150]}</i>")

    lines.append("")
    lines.append("<b>Rows novas por tabela (24h)</b>:")
    for tbl, n in inserted_24h.items():
        lines.append(f"  • {tbl}: {n}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Relatório diário do k_collector")
    parser.add_argument("--stdout", action="store_true",
                        help="só imprime, não envia Telegram")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERRO: DB ausente: {DB_PATH}", file=sys.stderr)
        return 1

    now = int(time.time())
    conn = sqlite3.connect(str(DB_PATH))
    try:
        staleness = gather_staleness(conn, now)
        runs = gather_runs_24h(conn, now)
        inserted = gather_rows_inserted_per_table_24h(conn, now)
    finally:
        conn.close()

    text = format_report(staleness, runs, inserted)
    plain = (text.replace("<b>", "").replace("</b>", "")
             .replace("<i>", "").replace("</i>", ""))

    if args.stdout:
        print(plain)
        return 0

    ok = telegram_send(text)
    if not ok:
        print("⚠️ Telegram falhou (token/chat ausente ou rede). Imprimindo local:\n")
        print(plain)
        return 1
    print(plain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
