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
            sl_price      REAL,
            tp_price      REAL,
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

    # Migração: adiciona colunas novas em tabelas já existentes
    for col, coltype in [("sl_price", "REAL"), ("tp_price", "REAL")]:
        try:
            conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass  # coluna já existe

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
            sl_price, tp_price, pnl_pct, pnl_usd, exit_reason, capital_after
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        trade["timestamp"],
        trade["symbol"],
        trade["type"],
        trade["entry_price"],
        trade["exit_price"],
        trade.get("sl_price"),
        trade.get("tp_price"),
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


def get_all_time_stats(table: str, days: int = 30) -> dict:
    """Metricas avancadas: win rate, profit factor, drawdown, melhor/pior trade."""
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    rows = [dict(r) for r in conn.execute(
        f"SELECT pnl_pct, pnl_usd, capital_after FROM {table} "
        f"WHERE timestamp >= ? AND pnl_pct IS NOT NULL AND exit_reason != 'open' "
        f"ORDER BY id",
        (cutoff,)
    ).fetchall()]
    conn.close()

    if not rows:
        return {
            "total_trades": 0, "win_rate": 0, "avg_pnl_pct": 0,
            "largest_win": 0, "largest_loss": 0, "profit_factor": 0,
            "max_drawdown_pct": 0,
        }

    wins = [r for r in rows if float(r["pnl_pct"] or 0) > 0]
    losses = [r for r in rows if float(r["pnl_pct"] or 0) < 0]
    total = len(rows)
    win_rate = (len(wins) / total * 100) if total > 0 else 0

    sum_wins = sum(float(r["pnl_usd"] or 0) for r in wins)
    sum_losses = abs(sum(float(r["pnl_usd"] or 0) for r in losses))
    profit_factor = (sum_wins / sum_losses) if sum_losses > 0 else (99.0 if sum_wins > 0 else 0)

    all_pnl_pct = [float(r["pnl_pct"] or 0) for r in rows]
    largest_win = max(all_pnl_pct) if all_pnl_pct else 0
    largest_loss = min(all_pnl_pct) if all_pnl_pct else 0
    avg_pnl = sum(all_pnl_pct) / len(all_pnl_pct) if all_pnl_pct else 0

    # Max drawdown from capital_after series
    max_drawdown_pct = 0
    capitals = [float(r["capital_after"] or 0) for r in rows if r["capital_after"]]
    if capitals:
        peak = capitals[0]
        for c in capitals:
            if c > peak:
                peak = c
            dd = ((peak - c) / peak * 100) if peak > 0 else 0
            if dd > max_drawdown_pct:
                max_drawdown_pct = dd

    return {
        "total_trades": total,
        "win_rate": round(win_rate, 1),
        "avg_pnl_pct": round(avg_pnl, 2),
        "largest_win": round(largest_win, 2),
        "largest_loss": round(largest_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
    }


def get_stats_by_symbol(table: str, days: int = 30) -> list:
    """Performance agrupada por simbolo."""
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    rows = [dict(r) for r in conn.execute(
        f"SELECT symbol, COUNT(*) as trades, "
        f"SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins, "
        f"SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losses, "
        f"ROUND(SUM(pnl_usd), 2) as total_pnl, "
        f"ROUND(AVG(pnl_pct), 2) as avg_pnl_pct "
        f"FROM {table} WHERE timestamp >= ? AND pnl_pct IS NOT NULL AND exit_reason != 'open' "
        f"GROUP BY symbol ORDER BY total_pnl DESC",
        (cutoff,)
    ).fetchall()]
    conn.close()
    return rows


def get_trades_range(table: str, days: int = 7, limit: int = 100) -> list:
    """Trades dos ultimos N dias, limitado a N registros."""
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM {table} WHERE timestamp >= ? ORDER BY id DESC LIMIT ?",
        (cutoff, limit)
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
