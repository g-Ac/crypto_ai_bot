"""Coletor maker-shadow Fase F (PREREG_maker_fill_v11 §5; spec 2026-06-10).

Registra, para cada trade taker real aberto pelo paper executor, uma ordem
limit maker hipotetica e resolve fill/desfecho forward com 3 invariantes:

1. signal_ts REAL: a sombra nasce no instante do open_position (now), nao
   reconstruida depois.
2. Nenhum dado anterior ao nascimento conta para fill: o candle onde a ordem
   nasceu NUNCA usa wick — so ticks observados nos ciclos (~5min, sempre
   pos-nascimento); candles que ABRIRAM apos o sinal usam wick ao fechar.
   Forward e deliberadamente mais conservador que o replay otimista.
3. Snapshot de book (bookTicker) no nascimento como diagnostico de
   marketability (would_post / post_only_reject_hypothetical); falha de
   fetch nunca bloqueia.

A sombra NUNCA altera estrategia/executor; todos os hooks chamam este modulo
em try/except. Desfecho pos-fill espelha a regra selada: candle do fill
avalia SO o SL; seguintes usam check_exit (SL > TP2 > TP1 > timeout) com
duration ancorada no candle do sinal; fees maker 0.02 (entrada/TP) e
taker 0.05 (SL/timeout).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from momentum.maker_shadow import MAKER_FEE_RATE, TAKER_FEE_RATE, _pnl
from momentum.research_runner import check_exit

logger = logging.getLogger(__name__)

_M15_S = 15 * 60
FILL_WINDOW_CANDLES = 2   # resto do candle N + candle N+1
TIMEOUT_CANDLES = 16

_SCHEMA = """
CREATE TABLE IF NOT EXISTS momentum_maker_shadow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    signal_ts TEXT NOT NULL,
    candle_open_ts INTEGER NOT NULL,
    expiry_ts INTEGER NOT NULL,
    limit_price REAL NOT NULL,
    sl_price REAL NOT NULL,
    tp1_price REAL NOT NULL,
    tp2_price REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    fill_ts TEXT,
    fill_source TEXT,
    fill_candle_open_ts INTEGER,
    exit_reason TEXT,
    exit_price REAL,
    exit_ts TEXT,
    gross_pnl_pct REAL,
    net_pnl_pct REAL,
    entry_fee_rate REAL,
    exit_fee_rate REAL,
    mfe_pct REAL DEFAULT 0,
    mae_pct REAL DEFAULT 0,
    duration_candles INTEGER DEFAULT 0,
    best_bid_at_signal REAL,
    best_ask_at_signal REAL,
    spread_bps REAL,
    would_post INTEGER,
    post_only_reject_hypothetical INTEGER,
    taker_net_pnl_pct REAL,
    created_at TEXT NOT NULL
);
"""


def _to_epoch_s(ts: str) -> int:
    dt = datetime.fromisoformat(str(ts))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _default_book_fn(symbol: str) -> Optional[Dict[str, float]]:
    """Snapshot best bid/ask spot. None em qualquer falha (nunca bloqueia)."""
    try:
        import requests
        resp = requests.get(
            "https://api.binance.com/api/v3/ticker/bookTicker",
            params={"symbol": symbol}, timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"bid": float(data["bidPrice"]), "ask": float(data["askPrice"])}
    except Exception as e:
        logger.warning("maker_shadow book fetch failed for %s: %s", symbol, e)
        return None


class MakerShadowCollector:
    def __init__(
        self,
        db_path: Optional[str] = None,
        book_fn: Optional[Callable] = None,
        now_fn: Optional[Callable] = None,
    ) -> None:
        if db_path is None:
            from runtime_config import DB_FILE
            db_path = DB_FILE
        self.db_path = str(db_path)
        self.book_fn = book_fn or _default_book_fn
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        with self._conn() as conn:
            conn.execute(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, shadow_id: int) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM momentum_maker_shadow WHERE id=?", (shadow_id,)
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Nascimento (invariantes 1 e 3)
    # ------------------------------------------------------------------
    def on_trade_opened(
        self, *, symbol: str, direction: str, entry_price: float,
        sl_price: float, tp1_price: float, tp2_price: float,
        candle_open_ts: str,
    ) -> int:
        now = self.now_fn()
        candle_open = _to_epoch_s(candle_open_ts)
        expiry = candle_open + FILL_WINDOW_CANDLES * _M15_S

        book = self.book_fn(symbol)
        bid = ask = spread_bps = would_post = reject = None
        if book:
            bid, ask = book["bid"], book["ask"]
            mid = (ask + bid) / 2.0
            spread_bps = round((ask - bid) / mid * 10000.0, 4) if mid else None
            if direction == "LONG":
                would_post = 1 if entry_price < ask else 0
            else:
                would_post = 1 if entry_price > bid else 0
            reject = 1 - would_post

        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO momentum_maker_shadow ("
                " symbol, direction, signal_ts, candle_open_ts, expiry_ts,"
                " limit_price, sl_price, tp1_price, tp2_price, status,"
                " best_bid_at_signal, best_ask_at_signal, spread_bps,"
                " would_post, post_only_reject_hypothetical, created_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?)",
                (symbol, direction, now.strftime("%Y-%m-%d %H:%M:%S"),
                 candle_open, expiry, entry_price, sl_price, tp1_price,
                 tp2_price, bid, ask, spread_bps, would_post, reject,
                 now.isoformat()),
            )
            return int(cur.lastrowid)

    # ------------------------------------------------------------------
    # Pareamento com o trade taker real
    # ------------------------------------------------------------------
    def on_trade_closed(self, shadow_id: int, taker_net_pnl_pct: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE momentum_maker_shadow SET taker_net_pnl_pct=? WHERE id=?",
                (taker_net_pnl_pct, shadow_id),
            )

    # ------------------------------------------------------------------
    # Ciclo (fill + expiry + desfecho)
    # ------------------------------------------------------------------
    def on_cycle(
        self, *, symbol: str, tick_price: float, now_candle_open_ts: str,
        closed_candle: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Avalia sombras do simbolo. Ordem cronologica: wick do candle
        recem-fechado -> tick corrente -> expiry; depois desfecho dos filled."""
        now = self.now_fn()
        now_s = int(now.timestamp())
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM momentum_maker_shadow WHERE symbol=? "
                "AND status IN ('pending','filled')", (symbol,)
            ).fetchall()

        for row in rows:
            if row["status"] == "pending":
                self._advance_pending(dict(row), tick_price,
                                      now_candle_open_ts, closed_candle,
                                      now, now_s)
            else:
                if closed_candle is not None:
                    self._advance_filled(dict(row), closed_candle, now)

    # --- pending ---
    def _advance_pending(self, row, tick_price, now_candle_open_ts,
                         closed_candle, now, now_s) -> None:
        is_long = row["direction"] == "LONG"
        limit = row["limit_price"]

        # 1) wick do candle recem-fechado — so se ABRIU apos o sinal (inv. 2)
        if closed_candle is not None:
            c_open = _to_epoch_s(closed_candle["time"])
            signal_s = _to_epoch_s(row["signal_ts"])
            if c_open >= signal_s and c_open < row["expiry_ts"]:
                through = (closed_candle["low"] < limit) if is_long \
                    else (closed_candle["high"] > limit)
                if through:
                    self._mark_filled(row, "next_candle_wick", c_open, now)
                    # candle do fill avalia SO o SL, com o candle completo
                    self._fill_candle_sl_check(row, closed_candle, c_open, now)
                    return

        # 2) tick corrente (sempre pos-nascimento), valido ate o expiry
        if now_s < row["expiry_ts"]:
            through = (tick_price < limit) if is_long else (tick_price > limit)
            if through:
                self._mark_filled(row, "cycle_tick",
                                  _to_epoch_s(now_candle_open_ts), now)
                return

        # 3) expiry
        if now_s >= row["expiry_ts"]:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE momentum_maker_shadow SET status='no_fill',"
                    " gross_pnl_pct=0, net_pnl_pct=0 WHERE id=?",
                    (row["id"],),
                )

    def _mark_filled(self, row, source, fill_candle_open, now) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE momentum_maker_shadow SET status='filled',"
                " fill_ts=?, fill_source=?, fill_candle_open_ts=?,"
                " entry_fee_rate=? WHERE id=?",
                (now.strftime("%Y-%m-%d %H:%M:%S"), source,
                 fill_candle_open, MAKER_FEE_RATE, row["id"]),
            )
        row["status"] = "filled"
        row["fill_candle_open_ts"] = fill_candle_open

    # --- filled ---
    def _fill_candle_sl_check(self, row, candle, c_open, now) -> None:
        """Candle do fill: avalia so o SL e faz seed de MFE/MAE."""
        is_long = row["direction"] == "LONG"
        entry = row["limit_price"]
        if is_long:
            mfe = max((candle["high"] - entry) / entry * 100, 0.0)
            mae = min((candle["low"] - entry) / entry * 100, 0.0)
            sl_hit = candle["low"] <= row["sl_price"]
        else:
            mfe = max((entry - candle["low"]) / entry * 100, 0.0)
            mae = min((entry - candle["high"]) / entry * 100, 0.0)
            sl_hit = candle["high"] >= row["sl_price"]

        duration = max((c_open - row["candle_open_ts"]) // _M15_S, 0)
        if sl_hit:
            gross = _pnl(is_long, entry, row["sl_price"])
            self._close(row, "sl_hit", row["sl_price"], gross,
                        TAKER_FEE_RATE, mfe, mae, duration, now)
        else:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE momentum_maker_shadow SET mfe_pct=?, mae_pct=?,"
                    " duration_candles=? WHERE id=?",
                    (round(mfe, 4), round(mae, 4), duration, row["id"]),
                )

    def _advance_filled(self, row, closed_candle, now) -> None:
        c_open = _to_epoch_s(closed_candle["time"])
        if row["fill_candle_open_ts"] is not None \
                and c_open <= row["fill_candle_open_ts"]:
            if c_open == row["fill_candle_open_ts"]:
                # o candle do fill (tick) acabou de fechar: so SL + seed
                self._fill_candle_sl_check(row, closed_candle, c_open, now)
            return

        k = (c_open - row["candle_open_ts"]) // _M15_S
        result = check_exit(
            direction=row["direction"],
            entry_price=row["limit_price"],
            sl_price=row["sl_price"],
            tp1_price=row["tp1_price"],
            tp2_price=row["tp2_price"],
            candle_high=closed_candle["high"],
            candle_low=closed_candle["low"],
            candle_close=closed_candle["close"],
            current_mfe=row["mfe_pct"] or 0.0,
            current_mae=row["mae_pct"] or 0.0,
            duration_candles=int(k - 1),
            timeout_candles=TIMEOUT_CANDLES,
            breakeven_trigger_pct=0.0,
        )
        if result["closed"]:
            reason = result["exit_reason"]
            exit_fee = MAKER_FEE_RATE if reason in ("tp1_hit", "tp2_hit") \
                else TAKER_FEE_RATE
            self._close(row, reason, result["exit_price"], result["pnl_pct"],
                        exit_fee, result["mfe_pct"], result["mae_pct"],
                        int(k - 1), now)
        else:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE momentum_maker_shadow SET mfe_pct=?, mae_pct=?,"
                    " duration_candles=? WHERE id=?",
                    (round(result["mfe_pct"], 4), round(result["mae_pct"], 4),
                     int(k - 1), row["id"]),
                )

    def _close(self, row, reason, exit_price, gross, exit_fee,
               mfe, mae, duration, now) -> None:
        net = gross - (MAKER_FEE_RATE + exit_fee)
        with self._conn() as conn:
            conn.execute(
                "UPDATE momentum_maker_shadow SET status='closed',"
                " exit_reason=?, exit_price=?, exit_ts=?, gross_pnl_pct=?,"
                " net_pnl_pct=?, entry_fee_rate=?, exit_fee_rate=?,"
                " mfe_pct=?, mae_pct=?, duration_candles=? WHERE id=?",
                (reason, exit_price, now.strftime("%Y-%m-%d %H:%M:%S"),
                 round(gross, 4), round(net, 4), MAKER_FEE_RATE, exit_fee,
                 round(mfe, 4), round(mae, 4), duration, row["id"]),
            )


_collector: Optional[MakerShadowCollector] = None


def get_collector() -> MakerShadowCollector:
    """Singleton para uso pelos hooks do paper executor."""
    global _collector
    if _collector is None:
        _collector = MakerShadowCollector()
    return _collector
