"""Shadow simulator: simula outcome de decisoes momentum bloqueadas.

Pra cada decisao em momentum_decisions com impulse valido (impulse_start_price > 0
AND impulse_end_price > 0), busca candles forward da Binance e simula o que teria
acontecido se a trade tivesse aberto. Resultado vai pra momentum_shadow_outcomes.

Idempotente: pula decisoes ja simuladas. Pode rodar quantas vezes precisar.

Reusa logica pura do momentum:
- check_exit (research_runner): SL/TP/timeout walk forward
- _compute_sl/_compute_tp1/_compute_tp2 (momentum_trader): niveis de saida
- MomentumConfig: parametros v1.1 congelados (sl_floor=0.5, tp1_factor=1.0, rr=1.5, timeout=16)

Uso:
    python shadow_simulator.py --dry-run --limit 5    # teste
    python shadow_simulator.py --limit 50             # processa 50
    python shadow_simulator.py                        # tudo pendente
    python shadow_simulator.py --analyze              # relatorio
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from momentum.config import MomentumConfig  # noqa: E402
from momentum.research_runner import check_exit  # noqa: E402
from momentum.robustness_check import fetch_candles  # noqa: E402

DB = PROJECT_ROOT / "runtime" / "baseline" / "bot.db"

CANDLE_INTERVAL = "15m"
CANDLE_INTERVAL_MS = 15 * 60 * 1000

SCHEMA = """
CREATE TABLE IF NOT EXISTS momentum_shadow_outcomes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id         INTEGER NOT NULL UNIQUE,
    simulated_at        TEXT NOT NULL,
    symbol              TEXT,
    direction           TEXT,
    blocked_by          TEXT,
    regime              TEXT,
    decision_timestamp  TEXT,
    entry_price         REAL,
    sl_price            REAL,
    tp1_price           REAL,
    tp2_price           REAL,
    exit_price          REAL,
    exit_reason         TEXT,
    pnl_pct             REAL,
    mfe_pct             REAL,
    mae_pct             REAL,
    duration_candles    INTEGER,
    candles_analyzed    INTEGER,
    complete            INTEGER,
    FOREIGN KEY(decision_id) REFERENCES momentum_decisions(id)
);
CREATE INDEX IF NOT EXISTS idx_shadow_decision ON momentum_shadow_outcomes(decision_id);
CREATE INDEX IF NOT EXISTS idx_shadow_blocked_by ON momentum_shadow_outcomes(blocked_by);
CREATE INDEX IF NOT EXISTS idx_shadow_complete ON momentum_shadow_outcomes(complete);
"""


def init_db() -> None:
    conn = sqlite3.connect(str(DB))
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def parse_ts_to_ms(ts: str) -> int:
    """Convert various timestamp formats to milliseconds since epoch."""
    if not ts:
        return 0
    s = ts.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return 0


def compute_levels(
    direction: str,
    impulse_start_price: float,
    impulse_end_price: float,
    entry_price: float,
    cfg: MomentumConfig,
) -> tuple[float, float, float]:
    """Compute SL, TP1, TP2 mirroring momentum_trader logic.

    LONG: SL below impulse start, floor enforced.
    SHORT: SL above impulse start, floor enforced.
    TP1 = impulse_end (factor 1.0) or interpolated.
    TP2 = entry +/- rr_mult * |entry - sl|.
    """
    floor = entry_price * cfg.sl_floor_pct / 100

    if direction == "LONG":
        max_sl = entry_price - floor
        sl = min(impulse_start_price, max_sl)
    else:
        min_sl = entry_price + floor
        sl = max(impulse_start_price, min_sl)

    if cfg.tp1_factor >= 1.0:
        tp1 = impulse_end_price
    elif direction == "LONG":
        tp1 = entry_price + cfg.tp1_factor * (impulse_end_price - entry_price)
    else:
        tp1 = entry_price - cfg.tp1_factor * (entry_price - impulse_end_price)

    sl_distance = abs(entry_price - sl)
    if direction == "LONG":
        tp2 = entry_price + cfg.tp2_rr_mult * sl_distance
    else:
        tp2 = entry_price - cfg.tp2_rr_mult * sl_distance

    return sl, tp1, tp2


def simulate_decision(
    direction: str,
    impulse_start_price: float,
    impulse_end_price: float,
    candles_forward: pd.DataFrame,
    cfg: MomentumConfig,
) -> dict:
    """Simulate forward outcome for one decision.

    Entry = close of first candle (the candle of the decision).
    Then walk forward checking exit on each subsequent candle.
    """
    if candles_forward.empty or len(candles_forward) < 2:
        return {
            "entry_price": 0.0, "sl_price": 0.0, "tp1_price": 0.0, "tp2_price": 0.0,
            "exit_price": 0.0, "exit_reason": "no_candles",
            "pnl_pct": 0.0, "mfe_pct": 0.0, "mae_pct": 0.0,
            "duration_candles": 0, "candles_analyzed": len(candles_forward),
            "complete": 0,
        }

    entry = float(candles_forward.iloc[0]["close"])
    sl, tp1, tp2 = compute_levels(direction, impulse_start_price, impulse_end_price, entry, cfg)

    mfe, mae = 0.0, 0.0
    forward = candles_forward.iloc[1:]

    for i, row in enumerate(forward.itertuples(index=False), start=1):
        result = check_exit(
            direction=direction,
            entry_price=entry,
            sl_price=sl, tp1_price=tp1, tp2_price=tp2,
            candle_high=float(row.high),
            candle_low=float(row.low),
            candle_close=float(row.close),
            current_mfe=mfe, current_mae=mae,
            duration_candles=i,
            timeout_candles=cfg.timeout_candles,
            breakeven_trigger_pct=0.0,
        )
        mfe = result["mfe_pct"]
        mae = result["mae_pct"]
        if result["closed"]:
            return {
                "entry_price": entry, "sl_price": sl, "tp1_price": tp1, "tp2_price": tp2,
                "exit_price": result["exit_price"],
                "exit_reason": result["exit_reason"],
                "pnl_pct": result["pnl_pct"],
                "mfe_pct": result["mfe_pct"],
                "mae_pct": result["mae_pct"],
                "duration_candles": i,
                "candles_analyzed": i,
                "complete": 1,
            }

    return {
        "entry_price": entry, "sl_price": sl, "tp1_price": tp1, "tp2_price": tp2,
        "exit_price": 0.0, "exit_reason": "incomplete",
        "pnl_pct": 0.0, "mfe_pct": mfe, "mae_pct": mae,
        "duration_candles": len(forward),
        "candles_analyzed": len(forward),
        "complete": 0,
    }


# Apenas blocked_by onde o sinal era valido (passou pullback + confirmacao):
#  - none: entrou de verdade (benchmark)
#  - max_positions: foi bloqueado APENAS por limite de posicoes
#  - no_confirmation: pullback foi valido, faltou confirmacao final
#
# Excluidos (entry nao tem significado coerente):
#  - no_valid_pullback: o sinal nao tinha pullback valido por definicao
#  - regime_blocked, trend_too_young, trend_exhaustion: bloqueados antes de calcular impulse
SIMULABLE_BLOCKED_BY = ("none", "max_positions", "no_confirmation")


def get_pending_decisions(conn: sqlite3.Connection, limit: int | None = None) -> list:
    placeholders = ",".join("?" * len(SIMULABLE_BLOCKED_BY))
    sql = f"""
        SELECT d.id, d.timestamp, d.symbol, d.direction, d.regime, d.blocked_by,
               d.impulse_start_price, d.impulse_end_price
        FROM momentum_decisions d
        LEFT JOIN momentum_shadow_outcomes s ON s.decision_id = d.id
        WHERE s.id IS NULL
          AND d.impulse_start_price > 0
          AND d.impulse_end_price > 0
          AND d.direction IN ('LONG', 'SHORT')
          AND d.blocked_by IN ({placeholders})
        ORDER BY d.id ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, SIMULABLE_BLOCKED_BY).fetchall()


def insert_outcome(conn: sqlite3.Connection, decision_id: int, decision_ts: str,
                   symbol: str, direction: str, blocked_by: str, regime: str,
                   outcome: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT OR REPLACE INTO momentum_shadow_outcomes
        (decision_id, simulated_at, symbol, direction, blocked_by, regime, decision_timestamp,
         entry_price, sl_price, tp1_price, tp2_price, exit_price, exit_reason,
         pnl_pct, mfe_pct, mae_pct, duration_candles, candles_analyzed, complete)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id, now, symbol, direction, blocked_by, regime, decision_ts,
            outcome["entry_price"], outcome["sl_price"], outcome["tp1_price"], outcome["tp2_price"],
            outcome["exit_price"], outcome["exit_reason"],
            outcome["pnl_pct"], outcome["mfe_pct"], outcome["mae_pct"],
            outcome["duration_candles"], outcome["candles_analyzed"], outcome["complete"],
        ),
    )


def run(limit: int | None = None, dry_run: bool = False, verbose: bool = False) -> int:
    init_db()
    cfg = MomentumConfig()

    conn = sqlite3.connect(str(DB))
    try:
        pending = get_pending_decisions(conn, limit=limit)
    finally:
        conn.close()

    if not pending:
        print("Nenhuma decisao pendente.")
        return 0

    print(f"Processando {len(pending)} decisoes pendentes (limit={limit})...")

    processed = 0
    skipped = 0
    errors = 0

    # Buffer: timeout + 8 candles extra pra garantir exit
    buffer_candles = cfg.timeout_candles + 8

    for row in pending:
        decision_id, ts, symbol, direction, regime, blocked_by, imp_start, imp_end = row

        start_ms = parse_ts_to_ms(ts)
        if start_ms == 0:
            if verbose:
                print(f"  [{decision_id}] timestamp invalido: '{ts}'")
            skipped += 1
            continue

        end_ms = start_ms + buffer_candles * CANDLE_INTERVAL_MS

        try:
            candles = fetch_candles(symbol, CANDLE_INTERVAL, start_ms, end_ms)
        except Exception as e:
            if verbose:
                print(f"  [{decision_id}] erro fetch: {e}")
            errors += 1
            time.sleep(1)
            continue

        if candles.empty or len(candles) < 2:
            if verbose:
                print(f"  [{decision_id}] sem candles forward (recente?)")
            skipped += 1
            continue

        outcome = simulate_decision(direction, imp_start, imp_end, candles, cfg)

        if verbose or dry_run:
            print(
                f"  [{decision_id}] {symbol} {direction} bb={blocked_by} reg={regime}: "
                f"entry={outcome['entry_price']:.2f} sl={outcome['sl_price']:.2f} "
                f"tp1={outcome['tp1_price']:.2f} → {outcome['exit_reason']} "
                f"pnl={outcome['pnl_pct']:+.3f}% (mfe={outcome['mfe_pct']:.2f} mae={outcome['mae_pct']:.2f}) "
                f"in {outcome['duration_candles']}c"
            )

        if not dry_run:
            conn = sqlite3.connect(str(DB))
            try:
                insert_outcome(conn, decision_id, ts, symbol, direction, blocked_by, regime, outcome)
                conn.commit()
            finally:
                conn.close()

        processed += 1
        time.sleep(0.3)  # rate limit Binance

    print(f"\nProcessadas: {processed} | Skipped: {skipped} | Errors: {errors}")
    return 0


def analyze() -> None:
    """Compara shadow outcomes vs trades reais."""
    conn = sqlite3.connect(str(DB))
    try:
        print("=" * 75)
        print("SHADOW OUTCOMES por blocked_by (somente complete=1)")
        print("=" * 75)
        rows = conn.execute(
            """
            SELECT blocked_by, COUNT(*) as n,
                   SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                   ROUND(AVG(pnl_pct), 3) as avg_pnl,
                   ROUND(SUM(pnl_pct), 2) as total_pnl,
                   ROUND(MAX(pnl_pct), 2) as best,
                   ROUND(MIN(pnl_pct), 2) as worst
            FROM momentum_shadow_outcomes
            WHERE complete = 1
            GROUP BY blocked_by
            ORDER BY total_pnl DESC
            """
        ).fetchall()
        if not rows:
            print("(sem outcomes simulados ainda)")
        else:
            print(f"{'blocked_by':<25} {'N':>5} {'WR':>5} {'AvgPnL':>9} {'TotPnL':>9} {'Best':>7} {'Worst':>7}")
            print("-" * 75)
            for r in rows:
                wr = (r[2] / r[1] * 100) if r[1] else 0
                print(f"{r[0]:<25} {r[1]:>5} {wr:>4.0f}% {r[3]:>+8.3f}% {r[4]:>+8.2f}% {r[5]:>+6.2f}% {r[6]:>+6.2f}%")

        print("\n" + "=" * 75)
        print("TRADES REAIS (para comparacao)")
        print("=" * 75)
        real = conn.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END),
                   ROUND(AVG(pnl_pct), 3),
                   ROUND(SUM(pnl_pct), 2),
                   ROUND(MAX(pnl_pct), 2),
                   ROUND(MIN(pnl_pct), 2)
            FROM momentum_trades WHERE exit_price IS NOT NULL
            """
        ).fetchone()
        if real and real[0]:
            wr = (real[1] / real[0] * 100) if real[0] else 0
            print(f"{'real (none)':<25} {real[0]:>5} {wr:>4.0f}% {real[2]:>+8.3f}% {real[3]:>+8.2f}% {real[4]:>+6.2f}% {real[5]:>+6.2f}%")

        print("\n" + "=" * 75)
        print("EXIT REASONS por blocked_by")
        print("=" * 75)
        exit_rows = conn.execute(
            """
            SELECT blocked_by, exit_reason, COUNT(*)
            FROM momentum_shadow_outcomes
            WHERE complete = 1
            GROUP BY blocked_by, exit_reason
            ORDER BY blocked_by, COUNT(*) DESC
            """
        ).fetchall()
        current_bb = None
        for bb, er, n in exit_rows:
            if bb != current_bb:
                print(f"\n  {bb}:")
                current_bb = bb
            print(f"    {er}: {n}")

        print("\n" + "=" * 75)
        print("REGIME × blocked_by (PnL medio)")
        print("=" * 75)
        regime_rows = conn.execute(
            """
            SELECT regime, blocked_by, COUNT(*) as n, ROUND(AVG(pnl_pct), 3) as avg_pnl
            FROM momentum_shadow_outcomes
            WHERE complete = 1 AND regime != ''
            GROUP BY regime, blocked_by
            HAVING COUNT(*) >= 3
            ORDER BY regime, avg_pnl DESC
            """
        ).fetchall()
        if regime_rows:
            current_reg = None
            for reg, bb, n, avg in regime_rows:
                if reg != current_reg:
                    print(f"\n  {reg}:")
                    current_reg = reg
                print(f"    {bb:<25} N={n:>3} AvgPnL={avg:+.3f}%")
    finally:
        conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Shadow simulator do momentum")
    p.add_argument("--limit", type=int, default=None, help="processa N decisoes")
    p.add_argument("--dry-run", action="store_true", help="nao salva no DB")
    p.add_argument("--verbose", action="store_true", help="log detalhado")
    p.add_argument("--analyze", action="store_true", help="apenas relatorio (sem simular)")
    args = p.parse_args()

    if args.analyze:
        analyze()
        return 0
    return run(limit=args.limit, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
