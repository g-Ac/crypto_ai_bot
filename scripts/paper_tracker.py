"""Tracker do diario paper manual — cron */15 com flock (padrao k_collector).

Para cada trade aberto em paper_manual_trades, varre candles 15m FECHADOS
desde o ultimo check e aplica as regras da spec (2026-06-10-paper-manual-design.md):
toque de stop/alvo por high/low, candle ambiguo = stop (pessimista), gap = fill
no open, MFE/MAE, primeiro candle valido = boundary 15m apos o registro.
Idempotente: reprocessar a mesma janela e no-op.

Guarda TOCTOU: o UPDATE de fechamento usa WHERE id=? AND status='open';
se rowcount != 1, o trade foi fechado por outra rota (close_manual via Flask)
e o tracker simplesmente ignora sem sobrescrever.

Uso:
    python scripts/paper_tracker.py
Cron:
    */15 * * * * /usr/bin/flock -n /tmp/paper_tracker.lock \
      /home/pi/crypto_ai_bot/.venv/bin/python \
      /home/pi/crypto_ai_bot/scripts/paper_tracker.py \
      >> /home/pi/crypto_ai_bot/logs/paper_tracker.log 2>&1
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import paper_data
from paper_data import CANDLE_S

DB_PATH = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")
MAX_CANDLES = 1000


def _first_boundary(created_at: int) -> int:
    """Primeiro open_time de candle 15m inteiramente APOS o registro."""
    return ((created_at + CANDLE_S - 1) // CANDLE_S) * CANDLE_S


def _check_candle(direction: str, open_p: float, high: float, low: float,
                  stop: float, target: float):
    """Retorna (exit_reason, exit_price) ou None. Ambiguo => stop (pessimista).

    Gap: se o open ja esta alem do stop/alvo, usa o open como preco de saida.
    """
    if direction == "long":
        hit_stop = low <= stop
        hit_target = high >= target
        if hit_stop:
            # gap de baixa: open < stop => fill no open
            # Ambiguo (open alem do alvo E stop atingido): stop prevalece — decisao
            # pessimista incondicional; open favoreceria alvo mas spec prioriza stop.
            return ("stop", open_p if open_p <= stop else stop)
        if hit_target:
            # gap de alta: open > target => fill no open
            return ("target", open_p if open_p >= target else target)
    else:
        hit_stop = high >= stop
        hit_target = low <= target
        if hit_stop:
            # gap de alta: open > stop => fill no open
            # Ambiguo (open alem do alvo E stop atingido): stop prevalece — decisao
            # pessimista incondicional; open favoreceria alvo mas spec prioriza stop.
            return ("stop", open_p if open_p >= stop else stop)
        if hit_target:
            # gap de baixa: open < target => fill no open
            return ("target", open_p if open_p <= target else target)
    return None


def _process_trade(conn: sqlite3.Connection, get_candles_fn, now_s: int, row) -> bool:
    """Processa 1 trade aberto; retorna True se fechou (e fechamento foi aceito pelo BD).

    Guarda TOCTOU:
    - UPDATE de fechamento: WHERE id=? AND status='open'; se rowcount != 1,
      trade foi fechado por outra rota simultaneamente — nao conta como fechado.
    - UPDATE de MFE/MAE: WHERE id=? AND status='open'; se rowcount == 0, ignora.
    """
    start = (row["last_checked_ts"] + CANDLE_S if row["last_checked_ts"] is not None
             else _first_boundary(row["created_at"]))
    if start + CANDLE_S > now_s:
        return False                       # nenhum candle fechado novo

    try:
        need = min(MAX_CANDLES, (now_s - start) // CANDLE_S + 2)
        df = get_candles_fn(row["symbol"], "15m", int(need))
    except Exception as exc:
        print(f"[paper_tracker] WARN trade={row['id']} sym={row['symbol']}"
              f" get_candles falhou: {exc}")
        return False
    if df is None or len(df) == 0:
        print(f"[paper_tracker] WARN trade={row['id']} sym={row['symbol']}"
              f" df None ou vazio")
        return False

    mfe, mae = row["mfe_price"], row["mae_price"]
    direction = row["direction"]
    closed = False
    last_processed = row["last_checked_ts"]

    # Fix 1: verifica se a janela alcanca `start`
    sorted_df = df.sort_values("time")
    eligible = sorted_df[
        sorted_df["time"].apply(lambda t: int(t.timestamp()) >= start
                                and int(t.timestamp()) + CANDLE_S <= now_s)]
    if len(eligible) > 0:
        first_eligible_ts = int(eligible.iloc[0]["time"].timestamp())
        if first_eligible_ts > start:
            skipped = (first_eligible_ts - start) // CANDLE_S
            print(f"[paper_tracker] WARN trade={row['id']} sym={row['symbol']}"
                  f" janela nao alcanca start={start}:"
                  f" primeiro elegivel={first_eligible_ts}"
                  f" candles_pulados={skipped} — trade mantido aberto")
            return False

    for _, c in sorted_df.iterrows():
        open_time = int(c["time"].timestamp())
        # Ignorar candles fora da janela ou ainda abertos
        if open_time < start or open_time + CANDLE_S > now_s:
            continue
        high, low, open_p = float(c["high"]), float(c["low"]), float(c["open"])
        # Atualizar MFE/MAE por direcao
        if direction == "long":
            mfe, mae = max(mfe, high), min(mae, low)
        else:
            mfe, mae = min(mfe, low), max(mae, high)
        last_processed = open_time
        hit = _check_candle(direction, open_p, high, low,
                            row["stop_price"], row["target_price"])
        if hit is not None:
            cur = conn.execute(
                "UPDATE paper_manual_trades SET status='closed', exit_reason=?,"
                " exit_price=?, exit_ts=?, mfe_price=?, mae_price=?, last_checked_ts=?"
                " WHERE id=? AND status='open'",
                (hit[0], hit[1], open_time, mfe, mae, open_time, row["id"]))
            if cur.rowcount == 1:
                closed = True
            # Com ou sem rowcount, parar de processar este trade
            conn.commit()
            return closed

    # Sem fechamento — atualizar MFE/MAE se houve progresso
    if last_processed != row["last_checked_ts"]:
        cur = conn.execute(
            "UPDATE paper_manual_trades SET mfe_price=?, mae_price=?, last_checked_ts=?"
            " WHERE id=? AND status='open'",
            (mfe, mae, last_processed, row["id"]))
        # Se rowcount == 0, trade foi fechado em paralelo; ignora silenciosamente
        conn.commit()
    return False


def process_open_trades(conn: sqlite3.Connection, get_candles_fn, now_s: int) -> dict:
    """Processa todos os trades abertos. Retorna {checked, closed}."""
    paper_data.ensure_schema(conn)
    rows = conn.execute(
        "SELECT * FROM paper_manual_trades WHERE status='open'").fetchall()
    closed = 0
    for r in rows:
        try:
            if _process_trade(conn, get_candles_fn, now_s, r):
                closed += 1
        except Exception as exc:
            print(f"[paper_tracker] ERROR trade={r['id']} sym={r['symbol']}"
                  f" excecao inesperada: {exc}")
    return {"checked": len(rows), "closed": closed}


def main() -> int:
    import market
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        out = process_open_trades(conn, market.get_candles, int(time.time()))
        print(f"[paper_tracker] {time.strftime('%Y-%m-%d %H:%M:%S')} "
              f"checked={out['checked']} closed={out['closed']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
