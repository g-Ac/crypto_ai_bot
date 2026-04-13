#!/usr/bin/env python3
"""
Etapa 1 — Auditoria de dados de microestrutura em producao.

Verifica:
  1. Rows por simbolo nas ultimas 24h e 7d
  2. % de liquidacoes reais (is_proxy=0) vs proxy
  3. % de basis_spread_pct preenchido (NOT NULL)
  4. Atraso entre ultimo registro e hora actual
  5. Campos NULL criticos (funding_rate, open_interest, oi_change)
  6. Resumo de trades e decisoes do scalping (V2 + V2.1b)

Uso:
    python audit_data.py                   # audita todas as instancias
    python audit_data.py baseline          # audita so a instancia baseline
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
RUNTIME_BASE = APP_DIR / "runtime"


def _find_dbs(instance: str | None = None) -> list[tuple[str, str]]:
    """Retorna [(instance_name, db_path), ...]."""
    if instance:
        db = RUNTIME_BASE / instance / "bot.db"
        if db.exists():
            return [(instance, str(db))]
        print(f"[ERRO] DB nao encontrado: {db}")
        return []

    results = []
    if RUNTIME_BASE.exists():
        for d in sorted(RUNTIME_BASE.iterdir()):
            db = d / "bot.db"
            if db.is_file():
                results.append((d.name, str(db)))
    if not results:
        print(f"[ERRO] Nenhum DB encontrado em {RUNTIME_BASE}/*/bot.db")
    return results


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def audit_microstructure(conn: sqlite3.Connection):
    if not _table_exists(conn, "market_microstructure"):
        print("  [!] Tabela market_microstructure NAO existe")
        return

    now = datetime.now()
    t_1h = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    t_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    t_7d = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    # --- Total rows ---
    total = conn.execute("SELECT COUNT(*) FROM market_microstructure").fetchone()[0]
    print(f"\n  Total de registos: {total}")
    if total == 0:
        print("  [!] ZERO registos — bot nao esta a gravar microestrutura")
        return

    # --- Rows por simbolo: 1h, 24h e 7d ---
    print("\n  Rows por simbolo (1h / 24h / 7d / total):")
    rows = conn.execute("""
        SELECT
            symbol,
            SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS cnt_1h,
            SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS cnt_24h,
            SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS cnt_7d,
            COUNT(*) AS cnt_total
        FROM market_microstructure
        GROUP BY symbol
        ORDER BY cnt_24h DESC
    """, (t_1h, t_24h, t_7d)).fetchall()

    for r in rows:
        cycles_24h = r["cnt_24h"]
        expected_24h = 288  # 24h / 5min = 288 ciclos
        pct = (cycles_24h / expected_24h * 100) if expected_24h else 0
        status = "OK" if pct >= 80 else "BAIXO" if pct >= 50 else "CRITICO"
        print(f"    {r['symbol']:>10s}  {r['cnt_1h']:>3d} / {cycles_24h:>4d} / {r['cnt_7d']:>5d} / {r['cnt_total']:>6d}  "
              f"({pct:.0f}% do esperado 24h) [{status}]")

    # --- Atraso do ultimo registro ---
    last_ts_row = conn.execute(
        "SELECT MAX(timestamp) AS last_ts FROM market_microstructure"
    ).fetchone()
    if last_ts_row and last_ts_row["last_ts"]:
        try:
            last_ts = datetime.strptime(last_ts_row["last_ts"], "%Y-%m-%d %H:%M:%S")
            delay = now - last_ts
            delay_min = delay.total_seconds() / 60
            status = "OK" if delay_min < 10 else "ATRASADO" if delay_min < 30 else "PARADO"
            print(f"\n  Ultimo registo: {last_ts_row['last_ts']} ({delay_min:.0f}min atras) [{status}]")
        except ValueError:
            print(f"\n  Ultimo registo: {last_ts_row['last_ts']} (formato nao reconhecido)")

    # --- Liquidacoes: real vs proxy (1h + 24h) ---
    print("\n  Liquidacoes real vs proxy (1h):")
    liq_1h = conn.execute("""
        SELECT
            symbol,
            SUM(CASE WHEN liquidation_is_proxy = 0 THEN 1 ELSE 0 END) AS real_cnt,
            SUM(CASE WHEN liquidation_is_proxy = 1 THEN 1 ELSE 0 END) AS proxy_cnt,
            COUNT(*) AS total
        FROM market_microstructure
        WHERE timestamp >= ?
        GROUP BY symbol
        ORDER BY symbol
    """, (t_1h,)).fetchall()

    for r in liq_1h:
        pct = (r["real_cnt"] / r["total"] * 100) if r["total"] else 0
        tag = "REAL" if pct >= 80 else "MISTO" if pct >= 20 else "PROXY"
        print(f"    {r['symbol']:>10s}  real={r['real_cnt']:>3d}  proxy={r['proxy_cnt']:>3d}  ({pct:.0f}% real) [{tag}]")

    print("\n  Liquidacoes real vs proxy (24h):")
    liq_rows = conn.execute("""
        SELECT
            symbol,
            SUM(CASE WHEN liquidation_is_proxy = 0 THEN 1 ELSE 0 END) AS real_24h,
            SUM(CASE WHEN liquidation_is_proxy = 1 THEN 1 ELSE 0 END) AS proxy_24h,
            SUM(CASE WHEN liquidation_is_proxy IS NULL THEN 1 ELSE 0 END) AS null_24h,
            COUNT(*) AS cnt_24h
        FROM market_microstructure
        WHERE timestamp >= ?
        GROUP BY symbol
        ORDER BY symbol
    """, (t_24h,)).fetchall()

    total_real = 0
    total_proxy = 0
    total_null = 0
    for r in liq_rows:
        cnt = r["cnt_24h"]
        real = r["real_24h"]
        proxy = r["proxy_24h"]
        null = r["null_24h"]
        total_real += real
        total_proxy += proxy
        total_null += null
        pct_real = (real / cnt * 100) if cnt else 0
        tag = "REAL" if pct_real >= 80 else "MISTO" if pct_real >= 20 else "PROXY"
        print(f"    {r['symbol']:>10s}  real={real:>3d}  proxy={proxy:>3d}  null={null:>3d}  "
              f"({pct_real:.0f}% real) [{tag}]")

    grand_total = total_real + total_proxy + total_null
    if grand_total:
        print(f"    {'TOTAL':>10s}  real={total_real:>3d}  proxy={total_proxy:>3d}  null={total_null:>3d}  "
              f"({total_real / grand_total * 100:.0f}% real)")

    # --- basis_spread_pct preenchido ---
    print("\n  Basis spread (preenchimento 24h):")
    basis_rows = conn.execute("""
        SELECT
            symbol,
            SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS cnt_24h,
            SUM(CASE WHEN timestamp >= ? AND basis_spread_pct IS NOT NULL THEN 1 ELSE 0 END) AS filled_24h
        FROM market_microstructure
        GROUP BY symbol
        ORDER BY symbol
    """, (t_24h, t_24h)).fetchall()

    for r in basis_rows:
        cnt = r["cnt_24h"]
        filled = r["filled_24h"]
        pct = (filled / cnt * 100) if cnt else 0
        status = "OK" if pct >= 90 else "PARCIAL" if pct >= 50 else "FALHA"
        print(f"    {r['symbol']:>10s}  {filled:>3d}/{cnt:>3d} preenchidos ({pct:.0f}%) [{status}]")

    # --- Campos NULL criticos (24h) ---
    print("\n  Campos NULL criticos (24h):")
    null_checks = conn.execute("""
        SELECT
            SUM(CASE WHEN funding_rate IS NULL THEN 1 ELSE 0 END) AS null_funding,
            SUM(CASE WHEN open_interest IS NULL THEN 1 ELSE 0 END) AS null_oi,
            SUM(CASE WHEN oi_change_1h_pct IS NULL THEN 1 ELSE 0 END) AS null_oi_1h,
            SUM(CASE WHEN oi_change_4h_pct IS NULL THEN 1 ELSE 0 END) AS null_oi_4h,
            SUM(CASE WHEN liquidation_vol_long IS NULL THEN 1 ELSE 0 END) AS null_liq_long,
            SUM(CASE WHEN liquidation_vol_short IS NULL THEN 1 ELSE 0 END) AS null_liq_short,
            COUNT(*) AS total
        FROM market_microstructure
        WHERE timestamp >= ?
    """, (t_24h,)).fetchone()

    total_rows = null_checks["total"]
    for field in ["null_funding", "null_oi", "null_oi_1h", "null_oi_4h", "null_liq_long", "null_liq_short"]:
        val = null_checks[field]
        pct = (val / total_rows * 100) if total_rows else 0
        label = field.replace("null_", "")
        status = "OK" if pct < 5 else "AVISO" if pct < 20 else "PROBLEMA"
        print(f"    {label:>15s}  {val:>3d}/{total_rows:>3d} NULL ({pct:.0f}%) [{status}]")


def audit_scalping(conn: sqlite3.Connection):
    now = datetime.now()
    t_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    t_7d = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    for version, trades_t, decisions_t in [
        ("V2", "scalping_trades", "scalping_decisions"),
        ("V2.1b", "scalping_trades_v2_1b", "scalping_decisions_v2_1b"),
    ]:
        print(f"\n  Scalping {version}:")

        if not _table_exists(conn, trades_t):
            print(f"    [!] Tabela {trades_t} nao existe")
            continue

        # Trades
        trades = conn.execute(f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS t_24h,
                SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS t_7d,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN pnl_usd <= 0 THEN 1 ELSE 0 END) AS losses,
                SUM(pnl_usd) AS total_pnl,
                AVG(pnl_pct) AS avg_pnl_pct
            FROM {trades_t}
        """, (t_24h, t_7d)).fetchone()

        total = trades["total"]
        wins = trades["wins"] or 0
        losses = trades["losses"] or 0
        wr = (wins / total * 100) if total else 0
        pnl = trades["total_pnl"] or 0

        print(f"    Trades: {total} total ({trades['t_24h']} 24h, {trades['t_7d']} 7d)")
        print(f"    Win rate: {wins}W / {losses}L ({wr:.0f}%)")
        print(f"    PnL total: ${pnl:.2f}  |  PnL medio: {(trades['avg_pnl_pct'] or 0):.2f}%")

        # Exit reasons
        if total > 0:
            exits = conn.execute(f"""
                SELECT exit_reason, COUNT(*) AS cnt
                FROM {trades_t}
                WHERE exit_reason IS NOT NULL
                GROUP BY exit_reason
                ORDER BY cnt DESC
            """).fetchall()
            if exits:
                parts = [f"{r['exit_reason']}={r['cnt']}" for r in exits]
                print(f"    Saidas: {', '.join(parts)}")

        # Decisions
        if _table_exists(conn, decisions_t):
            decs = conn.execute(f"""
                SELECT
                    outcome,
                    COUNT(*) AS cnt
                FROM {decisions_t}
                WHERE timestamp >= ?
                GROUP BY outcome
                ORDER BY cnt DESC
            """, (t_24h,)).fetchall()

            if decs:
                parts = [f"{r['outcome']}={r['cnt']}" for r in decs]
                print(f"    Decisoes 24h: {', '.join(parts)}")

            # Top rejection reasons
            rejections = conn.execute(f"""
                SELECT reason, COUNT(*) AS cnt
                FROM {decisions_t}
                WHERE timestamp >= ? AND outcome != 'opened'
                GROUP BY reason
                ORDER BY cnt DESC
                LIMIT 5
            """, (t_24h,)).fetchall()

            if rejections:
                print(f"    Top rejeicoes 24h:")
                for r in rejections:
                    print(f"      {r['cnt']:>3d}x  {r['reason']}")

            # SL distance distribution (para diagnosticar risk gate)
            sl_rows = conn.execute(f"""
                SELECT sl_distance_pct
                FROM {decisions_t}
                WHERE timestamp >= ? AND sl_distance_pct IS NOT NULL AND sl_distance_pct > 0
                ORDER BY sl_distance_pct
            """, (t_24h,)).fetchall()

            if sl_rows:
                vals = [r["sl_distance_pct"] for r in sl_rows]
                n = len(vals)
                p25 = vals[int(n * 0.25)] if n > 4 else vals[0]
                p50 = vals[int(n * 0.50)]
                p75 = vals[int(n * 0.75)] if n > 4 else vals[-1]
                blocked = sum(1 for v in vals if v > 0.8)
                pct_blocked = (blocked / n * 100) if n else 0
                print(f"    SL distance 24h: p25={p25:.2f}% p50={p50:.2f}% p75={p75:.2f}% "
                      f"(>{0.8:.1f}%: {blocked}/{n} = {pct_blocked:.0f}% bloqueados)")


def audit_db_health(db_path: str):
    """Tamanho do ficheiro e integridade basica."""
    size_mb = os.path.getsize(db_path) / (1024 * 1024)
    print(f"\n  DB: {db_path}")
    print(f"  Tamanho: {size_mb:.1f}MB")

    conn = _conn(db_path)
    try:
        result = conn.execute("PRAGMA integrity_check(1)").fetchone()
        status = result[0] if result else "unknown"
        print(f"  Integridade: {status}")
    finally:
        conn.close()


def main():
    instance_filter = sys.argv[1] if len(sys.argv) > 1 else None
    dbs = _find_dbs(instance_filter)

    if not dbs:
        sys.exit(1)

    for name, db_path in dbs:
        print(f"\n{'='*60}")
        print(f"  AUDITORIA: instancia [{name}]")
        print(f"{'='*60}")

        audit_db_health(db_path)

        conn = _conn(db_path)
        try:
            audit_microstructure(conn)
            audit_scalping(conn)
        finally:
            conn.close()

    print(f"\n{'='*60}")
    print(f"  Auditoria concluida: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
