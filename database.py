"""
Módulo central de banco de dados (SQLite).
Substitui todos os arquivos CSV de histórico.

WAL mode + timeout=30 permite que main.py e pump_scanner.py
gravem ao mesmo tempo sem conflitos.
"""
import sqlite3
import os
from datetime import date, datetime

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db")


def _get_conn():
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Cria todas as tabelas se não existirem. Chamar no início de cada processo."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS analysis_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT,
            symbol          TEXT,
            candle_time     TEXT,
            price           REAL,
            sma_9           REAL,
            sma_21          REAL,
            trend           TEXT,
            rsi             REAL,
            rsi_status      TEXT,
            price_position  TEXT,
            sma_9_direction  TEXT,
            sma_21_direction TEXT,
            breakout_status TEXT,
            buy_score       INTEGER,
            sell_score      INTEGER,
            signal_strength TEXT,
            decision        TEXT,
            confidence_score INTEGER,
            reason          TEXT
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT,
            symbol          TEXT,
            alert_type      TEXT,
            price           REAL,
            trend           TEXT,
            rsi             REAL,
            rsi_status      TEXT,
            buy_score       INTEGER,
            sell_score      INTEGER,
            signal_strength TEXT,
            decision        TEXT,
            reason          TEXT
        );

        CREATE TABLE IF NOT EXISTS paper_trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT,
            symbol        TEXT,
            type          TEXT,
            entry_price   REAL,
            exit_price    REAL,
            pnl_pct       REAL,
            pnl_usd       REAL,
            exit_reason   TEXT,
            capital_after REAL
        );

        CREATE TABLE IF NOT EXISTS agent_trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT,
            symbol              TEXT,
            type                TEXT,
            entry_price         REAL,
            sl_price            REAL,
            tp_price            REAL,
            position_size_usd   REAL,
            exit_price          REAL,
            pnl_pct             REAL,
            pnl_usd             REAL,
            exit_reason         TEXT,
            analyst_confidence  INTEGER,
            capital_after       REAL
        );

        CREATE TABLE IF NOT EXISTS pump_trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT,
            symbol        TEXT,
            type          TEXT,
            entry_price   REAL,
            exit_price    REAL,
            pnl_pct       REAL,
            pnl_usd       REAL,
            exit_reason   TEXT,
            duration_min  REAL,
            peak_price    REAL,
            capital_after REAL
        );

        CREATE INDEX IF NOT EXISTS idx_analysis_log_ts  ON analysis_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_paper_trades_ts  ON paper_trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_agent_trades_ts  ON agent_trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_pump_trades_ts   ON pump_trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_alerts_ts        ON alerts(timestamp);
    """)
    conn.commit()
    conn.close()


# ── INSERT FUNCTIONS ──────────────────────────────────────────────────────────

def insert_analysis_log(data: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO analysis_log (
            timestamp, symbol, candle_time, price, sma_9, sma_21, trend,
            rsi, rsi_status, price_position, sma_9_direction, sma_21_direction,
            breakout_status, buy_score, sell_score, signal_strength,
            decision, confidence_score, reason
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data["symbol"],
        str(data["candle_time"]),
        round(data["price"], 2),
        round(data["sma_9"], 2),
        round(data["sma_21"], 2),
        data["trend"],
        round(data["rsi"], 2),
        data["rsi_status"],
        data["price_position"],
        data["sma_9_direction"],
        data["sma_21_direction"],
        data["breakout_status"],
        data["buy_score"],
        data["sell_score"],
        data["signal_strength"],
        data["decision"],
        data["confidence_score"],
        data["reason"],
    ))
    conn.commit()
    conn.close()


def insert_alert(data: dict, alert_type: str):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO alerts (
            timestamp, symbol, alert_type, price, trend, rsi, rsi_status,
            buy_score, sell_score, signal_strength, decision, reason
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data["symbol"],
        alert_type,
        round(data["price"], 2),
        data["trend"],
        round(data["rsi"], 2),
        data["rsi_status"],
        data["buy_score"],
        data["sell_score"],
        data["signal_strength"],
        data["decision"],
        data["reason"],
    ))
    conn.commit()
    conn.close()


def insert_paper_trade(trade: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO paper_trades (
            timestamp, symbol, type, entry_price, exit_price,
            pnl_pct, pnl_usd, exit_reason, capital_after
        ) VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        trade["timestamp"],
        trade["symbol"],
        trade["type"],
        trade["entry_price"],
        trade["exit_price"],
        round(trade["pnl_pct"], 4),
        round(trade["pnl_usd"], 2),
        trade["exit_reason"],
        round(trade["capital_after"], 2),
    ))
    conn.commit()
    conn.close()


def insert_agent_trade(trade: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO agent_trades (
            timestamp, symbol, type, entry_price, sl_price, tp_price,
            position_size_usd, exit_price, pnl_pct, pnl_usd,
            exit_reason, analyst_confidence, capital_after
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        trade["timestamp"],
        trade["symbol"],
        trade["type"],
        trade["entry_price"],
        trade["sl_price"],
        trade["tp_price"],
        round(trade["position_size_usd"], 2),
        trade.get("exit_price", None),
        trade.get("pnl_pct", None),
        round(trade.get("pnl_usd", 0), 2),
        trade.get("exit_reason", "open"),
        trade.get("analyst_confidence", 0),
        round(trade.get("capital_after", 0), 2),
    ))
    conn.commit()
    conn.close()


def insert_pump_trade(trade: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO pump_trades (
            timestamp, symbol, type, entry_price, exit_price,
            pnl_pct, pnl_usd, exit_reason, duration_min,
            peak_price, capital_after
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        trade["timestamp"],
        trade["symbol"],
        trade["type"],
        trade["entry_price"],
        trade["exit_price"],
        round(trade["pnl_pct"], 4),
        round(trade["pnl_usd"], 2),
        trade["exit_reason"],
        trade["duration_min"],
        trade["peak_price"],
        round(trade["capital_after"], 2),
    ))
    conn.commit()
    conn.close()


# ── QUERY FUNCTIONS ───────────────────────────────────────────────────────────

def get_trades_today(table: str) -> list:
    """Retorna trades do dia atual como lista de dicts. Substitui read_trades_today()."""
    today = date.today().isoformat()
    conn = _get_conn()
    cursor = conn.execute(
        f"SELECT * FROM {table} WHERE timestamp LIKE ?",
        (f"{today}%",)
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_recent_trades(table: str, limit: int = 50) -> list:
    """Retorna os N trades mais recentes de uma tabela (para o dashboard)."""
    conn = _get_conn()
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()]
    conn.close()
    return rows


def get_cumulative_pnl(table: str, days: int = 30) -> list:
    """P&L diario agrupado por data. Usado no grafico do dashboard."""
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    rows = [dict(r) for r in conn.execute(
        f"SELECT date(timestamp) as day, SUM(pnl_usd) as daily_pnl "
        f"FROM {table} WHERE timestamp >= ? GROUP BY day ORDER BY day",
        (cutoff,)
    ).fetchall()]
    conn.close()
    return rows


# ── SELF-TEST ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Inicializando banco em: {DB_FILE}")
    init_db()
    print("Tabelas criadas com sucesso.")

    conn = _get_conn()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    conn.close()

    print(f"Tabelas no banco ({len(tables)}):")
    for t in tables:
        print(f"  - {t['name']}")
