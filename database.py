"""
Módulo central de banco de dados (SQLite).
Substitui todos os arquivos CSV de histórico.

WAL mode + timeout=30 permite que main.py e pump_scanner.py
gravem ao mesmo tempo sem conflitos.
"""
import json
import sqlite3
from datetime import date, datetime
from runtime_config import DB_FILE, ensure_runtime_dirs

# Whitelist de tabelas válidas para queries dinâmicas (B10).
# Impede uso de nomes arbitrários em f-strings SQL.
VALID_TABLES = frozenset({
    "paper_trades",
    "agent_trades",
    "pump_trades",
    "scalping_trades",
    "analysis_log",
    "alerts",
    "scalping_decisions",
    "scalping_audit_log",
    "scalping_outcome_labels",
})


def _validate_table(table: str) -> str:
    """Valida nome de tabela contra whitelist. Levanta ValueError se inválido."""
    if table not in VALID_TABLES:
        raise ValueError(
            f"Tabela '{table}' não é permitida. "
            f"Tabelas válidas: {sorted(VALID_TABLES)}"
        )

ensure_runtime_dirs()


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

        CREATE TABLE IF NOT EXISTS scalping_trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT,
            symbol              TEXT,
            type                TEXT,
            entry_price         REAL,
            exit_price          REAL,
            sl_price            REAL,
            tp_price            REAL,
            position_size_usd   REAL,
            leverage            INTEGER,
            confluence_score    INTEGER,
            source              TEXT,
            pnl_pct             REAL,
            pnl_usd             REAL,
            exit_reason         TEXT,
            capital_after       REAL
        );

        CREATE TABLE IF NOT EXISTS scalping_decisions (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp            TEXT,
            cycle_id             TEXT,
            symbol               TEXT,
            outcome              TEXT,
            reason               TEXT,
            confluence_score     INTEGER,
            confluence_direction TEXT,
            best_signal_source   TEXT,
            ai_used              INTEGER,
            ai_approved          INTEGER,
            risk_approved        INTEGER,
            rr_ratio             REAL,
            sl_distance_pct      REAL
        );

        CREATE TABLE IF NOT EXISTS scalping_audit_log (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp             TEXT,
            cycle_id              TEXT,
            symbol                TEXT,
            outcome               TEXT,
            reason                TEXT,
            opportunity_detected  INTEGER,
            force_entry_enabled   INTEGER,
            force_entry_applied   INTEGER,
            ai_used               INTEGER,
            ai_approved           INTEGER,
            risk_approved         INTEGER,
            pnl_pct               REAL,
            pnl_usd               REAL,
            details_json          TEXT
        );

        CREATE TABLE IF NOT EXISTS scalping_outcome_labels (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id              INTEGER NOT NULL UNIQUE,
            labeled_at            TEXT,
            audit_timestamp       TEXT,
            symbol                TEXT,
            scenario_type         TEXT,
            event_outcome         TEXT,
            verdict               TEXT,
            reason                TEXT,
            force_entry_applied   INTEGER,
            is_actionable         INTEGER,
            direction             TEXT,
            reference_price       REAL,
            entry_price           REAL,
            sl_price              REAL,
            tp1_price             REAL,
            tp2_price             REAL,
            first_touch           TEXT,
            first_touch_minutes   REAL,
            time_to_tp1_minutes   REAL,
            time_to_tp2_minutes   REAL,
            time_to_sl_minutes    REAL,
            winner_flag           INTEGER,
            loser_flag            INTEGER,
            max_labeled_horizon   INTEGER,
            label_status          TEXT,
            details_json          TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_analysis_log_ts  ON analysis_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_paper_trades_ts  ON paper_trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_agent_trades_ts  ON agent_trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_pump_trades_ts   ON pump_trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_alerts_ts        ON alerts(timestamp);
        CREATE INDEX IF NOT EXISTS idx_scalping_trades_ts ON scalping_trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_scalping_trades_symbol ON scalping_trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_scalping_decisions_ts ON scalping_decisions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_scalping_decisions_cycle ON scalping_decisions(cycle_id);
        CREATE INDEX IF NOT EXISTS idx_scalping_decisions_outcome ON scalping_decisions(outcome);
        CREATE INDEX IF NOT EXISTS idx_scalping_audit_ts ON scalping_audit_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_scalping_audit_cycle ON scalping_audit_log(cycle_id);
        CREATE INDEX IF NOT EXISTS idx_scalping_audit_symbol ON scalping_audit_log(symbol);
        CREATE INDEX IF NOT EXISTS idx_scalping_audit_outcome ON scalping_audit_log(outcome);
        CREATE INDEX IF NOT EXISTS idx_scalping_outcome_ts ON scalping_outcome_labels(audit_timestamp);
        CREATE INDEX IF NOT EXISTS idx_scalping_outcome_symbol ON scalping_outcome_labels(symbol);
        CREATE INDEX IF NOT EXISTS idx_scalping_outcome_scenario ON scalping_outcome_labels(scenario_type);
        CREATE INDEX IF NOT EXISTS idx_scalping_outcome_verdict ON scalping_outcome_labels(verdict);

        CREATE TABLE IF NOT EXISTS ai_decisions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT,
            symbol          TEXT,
            system          TEXT,
            model           TEXT,
            prompt_version  TEXT,
            latency_ms      REAL,
            fallback_used   INTEGER,
            parse_success   INTEGER,
            approved        INTEGER,
            confidence      INTEGER,
            reasoning       TEXT,
            trade_result    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ai_decisions_ts ON ai_decisions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_ai_decisions_symbol ON ai_decisions(symbol);
        CREATE INDEX IF NOT EXISTS idx_ai_decisions_system ON ai_decisions(system);
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


def insert_scalping_trade(trade: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO scalping_trades (
            timestamp, symbol, type, entry_price, exit_price,
            sl_price, tp_price, position_size_usd, leverage,
            confluence_score, source, pnl_pct, pnl_usd,
            exit_reason, capital_after
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        trade["timestamp"],
        trade["symbol"],
        trade["type"],
        trade["entry_price"],
        trade.get("exit_price"),
        trade.get("sl_price"),
        trade.get("tp_price"),
        trade.get("position_size_usd"),
        trade.get("leverage"),
        trade.get("confluence_score"),
        trade.get("source"),
        trade.get("pnl_pct"),
        round(trade.get("pnl_usd", 0), 2),
        trade.get("exit_reason", "open"),
        round(trade.get("capital_after", 0), 2),
    ))
    conn.commit()
    conn.close()


def insert_scalping_decision(decision: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO scalping_decisions (
            timestamp, cycle_id, symbol, outcome, reason,
            confluence_score, confluence_direction, best_signal_source,
            ai_used, ai_approved, risk_approved, rr_ratio, sl_distance_pct
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        decision.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        decision.get("cycle_id", ""),
        decision.get("symbol", ""),
        decision.get("outcome", ""),
        decision.get("reason", ""),
        decision.get("confluence_score"),
        decision.get("confluence_direction"),
        decision.get("best_signal_source"),
        int(bool(decision.get("ai_used", False))),
        int(bool(decision.get("ai_approved", False))),
        int(bool(decision.get("risk_approved", False))),
        decision.get("rr_ratio"),
        decision.get("sl_distance_pct"),
    ))
    conn.commit()
    conn.close()


def insert_scalping_audit_log(audit: dict):
    details_json = audit.get("details_json", "")
    if isinstance(details_json, (dict, list)):
        details_json = json.dumps(details_json, ensure_ascii=False)

    conn = _get_conn()
    conn.execute("""
        INSERT INTO scalping_audit_log (
            timestamp, cycle_id, symbol, outcome, reason,
            opportunity_detected, force_entry_enabled, force_entry_applied,
            ai_used, ai_approved, risk_approved,
            pnl_pct, pnl_usd, details_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        audit.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        audit.get("cycle_id", ""),
        audit.get("symbol", ""),
        audit.get("outcome", ""),
        audit.get("reason", ""),
        int(bool(audit.get("opportunity_detected", False))),
        int(bool(audit.get("force_entry_enabled", False))),
        int(bool(audit.get("force_entry_applied", False))),
        int(bool(audit.get("ai_used", False))),
        int(bool(audit.get("ai_approved", False))),
        int(bool(audit.get("risk_approved", False))),
        audit.get("pnl_pct"),
        audit.get("pnl_usd"),
        details_json,
    ))
    conn.commit()
    conn.close()


def upsert_scalping_outcome_label(label: dict):
    details_json = label.get("details_json", "")
    if isinstance(details_json, (dict, list)):
        details_json = json.dumps(details_json, ensure_ascii=False)

    conn = _get_conn()
    conn.execute("""
        INSERT INTO scalping_outcome_labels (
            audit_id, labeled_at, audit_timestamp, symbol,
            scenario_type, event_outcome, verdict, reason,
            force_entry_applied, is_actionable, direction,
            reference_price, entry_price, sl_price, tp1_price, tp2_price,
            first_touch, first_touch_minutes,
            time_to_tp1_minutes, time_to_tp2_minutes, time_to_sl_minutes,
            winner_flag, loser_flag,
            max_labeled_horizon, label_status, details_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(audit_id) DO UPDATE SET
            labeled_at=excluded.labeled_at,
            audit_timestamp=excluded.audit_timestamp,
            symbol=excluded.symbol,
            scenario_type=excluded.scenario_type,
            event_outcome=excluded.event_outcome,
            verdict=excluded.verdict,
            reason=excluded.reason,
            force_entry_applied=excluded.force_entry_applied,
            is_actionable=excluded.is_actionable,
            direction=excluded.direction,
            reference_price=excluded.reference_price,
            entry_price=excluded.entry_price,
            sl_price=excluded.sl_price,
            tp1_price=excluded.tp1_price,
            tp2_price=excluded.tp2_price,
            first_touch=excluded.first_touch,
            first_touch_minutes=excluded.first_touch_minutes,
            time_to_tp1_minutes=excluded.time_to_tp1_minutes,
            time_to_tp2_minutes=excluded.time_to_tp2_minutes,
            time_to_sl_minutes=excluded.time_to_sl_minutes,
            winner_flag=excluded.winner_flag,
            loser_flag=excluded.loser_flag,
            max_labeled_horizon=excluded.max_labeled_horizon,
            label_status=excluded.label_status,
            details_json=excluded.details_json
    """, (
        int(label.get("audit_id", 0)),
        label.get("labeled_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        label.get("audit_timestamp", ""),
        label.get("symbol", ""),
        label.get("scenario_type", ""),
        label.get("event_outcome", ""),
        label.get("verdict", ""),
        label.get("reason", ""),
        int(bool(label.get("force_entry_applied", False))),
        int(bool(label.get("is_actionable", False))),
        label.get("direction", ""),
        label.get("reference_price"),
        label.get("entry_price"),
        label.get("sl_price"),
        label.get("tp1_price"),
        label.get("tp2_price"),
        label.get("first_touch", ""),
        label.get("first_touch_minutes"),
        label.get("time_to_tp1_minutes"),
        label.get("time_to_tp2_minutes"),
        label.get("time_to_sl_minutes"),
        int(bool(label.get("winner_flag", False))),
        int(bool(label.get("loser_flag", False))),
        int(label.get("max_labeled_horizon", 0)),
        label.get("label_status", "pending"),
        details_json,
    ))
    conn.commit()
    conn.close()


def insert_ai_decision(decision: dict):
    """Registra uma decisão de IA (modelo, latência, fallback, resultado)."""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO ai_decisions (
            timestamp, symbol, system, model, prompt_version,
            latency_ms, fallback_used, parse_success,
            approved, confidence, reasoning, trade_result
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        decision.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        decision.get("symbol", ""),
        decision.get("system", ""),
        decision.get("model", ""),
        decision.get("prompt_version", ""),
        decision.get("latency_ms"),
        int(bool(decision.get("fallback_used", False))),
        int(bool(decision.get("parse_success", True))),
        int(bool(decision.get("approved", False))),
        decision.get("confidence"),
        decision.get("reasoning", ""),
        decision.get("trade_result"),
    ))
    conn.commit()
    conn.close()


# ── QUERY FUNCTIONS ───────────────────────────────────────────────────────────

def get_trades_today(table: str) -> list:
    """Retorna trades do dia atual como lista de dicts. Substitui read_trades_today()."""
    _validate_table(table)
    today = date.today().isoformat()
    conn = _get_conn()
    try:
        cursor = conn.execute(
            f"SELECT * FROM {table} WHERE timestamp LIKE ?",
            (f"{today}%",)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_recent_trades(table: str, limit: int = 50) -> list:
    """Retorna os N trades mais recentes de uma tabela (para o dashboard)."""
    _validate_table(table)
    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()]
    finally:
        conn.close()


def get_cumulative_pnl(table: str, days: int = 30) -> list:
    """P&L diario agrupado por data. Usado no grafico do dashboard."""
    _validate_table(table)
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT date(timestamp) as day, SUM(pnl_usd) as daily_pnl "
            f"FROM {table} WHERE timestamp >= ? GROUP BY day ORDER BY day",
            (cutoff,)
        ).fetchall()]
    finally:
        conn.close()


def get_all_time_stats(table: str, days: int = 30) -> dict:
    """Metricas avancadas: win rate, profit factor, drawdown, melhor/pior trade."""
    _validate_table(table)
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    try:
        rows = [dict(r) for r in conn.execute(
            f"SELECT pnl_pct, pnl_usd, capital_after FROM {table} "
            f"WHERE timestamp >= ? AND pnl_pct IS NOT NULL AND exit_reason != 'open' "
            f"ORDER BY id",
            (cutoff,)
        ).fetchall()]
    finally:
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
    _validate_table(table)
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT symbol, COUNT(*) as trades, "
            f"SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins, "
            f"SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losses, "
            f"ROUND(SUM(pnl_usd), 2) as total_pnl, "
            f"ROUND(AVG(pnl_pct), 2) as avg_pnl_pct "
            f"FROM {table} WHERE timestamp >= ? AND pnl_pct IS NOT NULL AND exit_reason != 'open' "
            f"GROUP BY symbol ORDER BY total_pnl DESC",
            (cutoff,)
        ).fetchall()]
    finally:
        conn.close()


def get_scalping_funnel_stats(days: int = 1) -> dict:
    """Resumo do funil de decisao do scalping por outcome."""
    from datetime import timedelta

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    rows = [dict(r) for r in conn.execute(
        """
        SELECT outcome, COUNT(*) as count
        FROM scalping_decisions
        WHERE timestamp >= ?
        GROUP BY outcome
        ORDER BY outcome
        """,
        (cutoff,),
    ).fetchall()]
    conn.close()

    breakdown = {row["outcome"]: int(row["count"]) for row in rows}
    ordered_keys = [
        "opened",
        "risk_blocked",
        "ai_rejected",
        "confluence_block",
        "cooldown",
        "in_position",
        "error",
    ]

    return {
        "days": days,
        "total": sum(breakdown.values()),
        "breakdown": {key: breakdown.get(key, 0) for key in ordered_keys},
        "raw_breakdown": breakdown,
    }


def get_scalping_trades(days: int = 1, limit: int = 100) -> list:
    """Retorna trades de scalping dos ultimos N dias."""
    from datetime import timedelta

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM scalping_trades WHERE timestamp >= ? "
            "ORDER BY id DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()]
    finally:
        conn.close()


def get_scalping_audit_log(limit: int = 100, days: int = 1, outcome: str = "") -> list:
    """Historico detalhado de observacoes e execucoes do scalping."""
    from datetime import timedelta

    cutoff = (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
    query = """
        SELECT timestamp, cycle_id, symbol, outcome, reason,
               opportunity_detected, force_entry_enabled, force_entry_applied,
               ai_used, ai_approved, risk_approved,
               pnl_pct, pnl_usd, details_json
        FROM scalping_audit_log
        WHERE timestamp >= ?
    """
    params = [cutoff]

    if outcome:
        query += " AND outcome = ?"
        params.append(outcome)

    query += " ORDER BY timestamp DESC, id DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))

    conn = _get_conn()
    rows = [dict(r) for r in conn.execute(query, tuple(params)).fetchall()]
    conn.close()

    for row in rows:
        details = row.get("details_json")
        if details:
            try:
                row["details"] = json.loads(details)
            except Exception:
                row["details"] = {"raw": details}
        else:
            row["details"] = {}
        row.pop("details_json", None)

    return rows


def get_scalping_audits_for_outcome_labeling(limit: int = 200, days: int = 7) -> list:
    """Auditorias que ainda nao chegaram em rotulagem completa."""
    from datetime import timedelta

    cutoff = (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
    conn = _get_conn()
    rows = [dict(r) for r in conn.execute("""
        SELECT
            a.id,
            a.timestamp,
            a.cycle_id,
            a.symbol,
            a.outcome,
            a.reason,
            a.opportunity_detected,
            a.force_entry_enabled,
            a.force_entry_applied,
            a.ai_used,
            a.ai_approved,
            a.risk_approved,
            a.pnl_pct,
            a.pnl_usd,
            a.details_json,
            COALESCE(l.max_labeled_horizon, 0) AS current_max_labeled_horizon,
            COALESCE(l.label_status, 'pending') AS current_label_status
        FROM scalping_audit_log a
        LEFT JOIN scalping_outcome_labels l ON l.audit_id = a.id
        WHERE a.timestamp >= ?
          AND COALESCE(l.max_labeled_horizon, 0) < 60
        ORDER BY a.timestamp DESC, a.id DESC
        LIMIT ?
    """, (cutoff, max(1, min(limit, 1000)))).fetchall()]
    conn.close()

    for row in rows:
        details = row.get("details_json")
        if details:
            try:
                row["details"] = json.loads(details)
            except Exception:
                row["details"] = {"raw": details}
        else:
            row["details"] = {}
        row.pop("details_json", None)

    return rows


def get_scalping_outcome_labels(
    limit: int = 100,
    days: int = 7,
    scenario_type: str = "",
    verdict: str = "",
) -> list:
    """Historico de labels forward do scalping."""
    from datetime import timedelta

    cutoff = (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
    query = """
        SELECT
            id, audit_id, labeled_at, audit_timestamp, symbol,
            scenario_type, event_outcome, verdict, reason,
            force_entry_applied, is_actionable, direction,
            reference_price, entry_price, sl_price, tp1_price, tp2_price,
            first_touch, first_touch_minutes,
            time_to_tp1_minutes, time_to_tp2_minutes, time_to_sl_minutes,
            winner_flag, loser_flag,
            max_labeled_horizon, label_status, details_json
        FROM scalping_outcome_labels
        WHERE audit_timestamp >= ?
    """
    params = [cutoff]

    if scenario_type:
        query += " AND scenario_type = ?"
        params.append(scenario_type)

    if verdict:
        query += " AND verdict = ?"
        params.append(verdict)

    query += " ORDER BY audit_timestamp DESC, id DESC LIMIT ?"
    params.append(max(1, min(limit, 20000)))

    conn = _get_conn()
    rows = [dict(r) for r in conn.execute(query, tuple(params)).fetchall()]
    conn.close()

    for row in rows:
        details = row.get("details_json")
        if details:
            try:
                row["details"] = json.loads(details)
            except Exception:
                row["details"] = {"raw": details}
        else:
            row["details"] = {}
        row.pop("details_json", None)

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
