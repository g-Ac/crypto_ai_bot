"""
Módulo central de banco de dados (SQLite).
Substitui todos os arquivos CSV de histórico.

WAL mode + timeout=30 permite que main.py e pump_scanner.py
gravem ao mesmo tempo sem conflitos.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta
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
    "ai_decisions",
    "market_microstructure",
    "momentum_trades",
    "momentum_decisions",
    "breakout_trades",
    "breakout_decisions",
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

        -- V2.1b paper side-by-side: tabelas espelho para comparacao
        CREATE TABLE IF NOT EXISTS scalping_trades_v2_1b (
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

        CREATE TABLE IF NOT EXISTS scalping_decisions_v2_1b (
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

        CREATE INDEX IF NOT EXISTS idx_scalping_v2_1b_trades_ts ON scalping_trades_v2_1b(timestamp);
        CREATE INDEX IF NOT EXISTS idx_scalping_v2_1b_decisions_ts ON scalping_decisions_v2_1b(timestamp);

        CREATE TABLE IF NOT EXISTS market_microstructure (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp               TEXT,
            symbol                  TEXT,
            funding_rate            REAL,
            funding_rate_prev1      REAL,
            funding_rate_prev2      REAL,
            ls_ratio_top            REAL,
            ls_ratio_global         REAL,
            liquidation_vol_long    REAL,
            liquidation_vol_short   REAL,
            open_interest           REAL,
            oi_change_1h_pct        REAL,
            oi_change_4h_pct        REAL,
            basis_spread_pct        REAL,
            session                 TEXT
        );

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

        CREATE INDEX IF NOT EXISTS idx_microstructure_ts ON market_microstructure(timestamp);
        CREATE INDEX IF NOT EXISTS idx_microstructure_symbol ON market_microstructure(symbol);

        CREATE INDEX IF NOT EXISTS idx_ai_decisions_ts ON ai_decisions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_ai_decisions_symbol ON ai_decisions(symbol);
        CREATE INDEX IF NOT EXISTS idx_ai_decisions_system ON ai_decisions(system);
    """)
    conn.commit()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS momentum_trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT,
            symbol              TEXT,
            direction           TEXT,
            regime              TEXT,
            entry_price         REAL,
            exit_price          REAL,
            sl_price            REAL,
            tp1_price           REAL,
            tp2_price           REAL,
            position_size_usd   REAL,
            pnl_pct             REAL,
            pnl_usd             REAL,
            exit_reason         TEXT,
            capital_after       REAL,
            param_version       TEXT,
            duration_candles    INTEGER,
            mfe_pct             REAL DEFAULT 0,
            mae_pct             REAL DEFAULT 0,
            session_bucket      TEXT DEFAULT '',
            asset_bucket        TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS momentum_decisions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT,
            cycle_id            TEXT,
            symbol              TEXT,
            regime              TEXT,
            outcome             TEXT,
            direction           TEXT,
            blocked_by          TEXT DEFAULT 'none',
            ema_fast_value      REAL DEFAULT 0,
            ema_slow_value      REAL DEFAULT 0,
            ema_gap_pct         REAL DEFAULT 0,
            retracement_pct     REAL DEFAULT 0,
            impulse_start_price REAL DEFAULT 0,
            impulse_end_price   REAL DEFAULT 0,
            pullback_rejection  TEXT DEFAULT '',
            param_version       TEXT DEFAULT '',
            session_bucket      TEXT DEFAULT '',
            asset_bucket        TEXT DEFAULT '',
            adx_slope_3         REAL DEFAULT 0,
            di_spread           REAL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_momentum_trades_ts ON momentum_trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_momentum_trades_symbol ON momentum_trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_momentum_decisions_ts ON momentum_decisions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_momentum_decisions_cycle ON momentum_decisions(cycle_id);
        CREATE INDEX IF NOT EXISTS idx_momentum_decisions_outcome ON momentum_decisions(outcome);
    """)
    conn.commit()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS breakout_trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT,
            symbol              TEXT,
            direction           TEXT,
            entry_price         REAL,
            exit_price          REAL,
            sl_price            REAL,
            tp1_price           REAL,
            tp2_price           REAL,
            position_size_usd   REAL,
            pnl_pct             REAL,
            pnl_usd             REAL,
            exit_reason         TEXT,
            capital_after       REAL,
            param_version       TEXT,
            duration_candles    INTEGER DEFAULT 0,
            mfe_pct             REAL DEFAULT 0,
            mae_pct             REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS breakout_decisions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT,
            cycle_id            TEXT,
            symbol              TEXT,
            direction           TEXT,
            blocked_by          TEXT DEFAULT 'none',
            range_pct           REAL DEFAULT 0,
            bb_bandwidth        REAL DEFAULT 0,
            vol_ratio           REAL DEFAULT 0,
            body_ratio          REAL DEFAULT 0,
            lookback            INTEGER DEFAULT 0,
            param_version       TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_breakout_trades_ts ON breakout_trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_breakout_trades_symbol ON breakout_trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_breakout_decisions_ts ON breakout_decisions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_breakout_decisions_cycle ON breakout_decisions(cycle_id);
    """)
    conn.commit()

    # Migração: adiciona colunas novas em tabelas já existentes
    for col, coltype in [("sl_price", "REAL"), ("tp_price", "REAL")]:
        try:
            conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass  # coluna já existe

    # Migração: agent_trades ganha execution_mode, lifecycle_id, recommended_mode
    for col, coltype in [("execution_mode", "TEXT"), ("lifecycle_id", "TEXT"), ("recommended_mode", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE agent_trades ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass  # coluna já existe

    # Migração: market_microstructure funding_rate_predicted -> funding_rate_prev1 + prev2
    for col, coltype in [("funding_rate_prev1", "REAL"), ("funding_rate_prev2", "REAL")]:
        try:
            conn.execute(f"ALTER TABLE market_microstructure ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass  # coluna já existe ou tabela ainda não criada

    # Migração: market_microstructure — colunas extras de collect_microstructure
    for col, coltype in [
        ("next_funding_time", "TEXT"),
        ("liquidation_count", "INTEGER DEFAULT 0"),
        ("liquidation_is_proxy", "INTEGER DEFAULT 0"),
        ("futures_price", "REAL"),
        ("spot_price", "REAL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE market_microstructure ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass  # coluna já existe

    # Índice composto para queries historicas eficientes (symbol+time range)
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_microstructure_sym_ts "
            "ON market_microstructure(symbol, timestamp)"
        )
        conn.commit()
    except Exception:
        pass

    # Migração: signal_subtype em scalping_decisions e scalping_trades (V2.1b observabilidade)
    for table in ["scalping_decisions", "scalping_trades"]:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN signal_subtype TEXT DEFAULT 'unknown'")
            conn.commit()
        except Exception:
            pass  # coluna já existe

    # ── Migração: Auditoria Operacional (edge-validator) ─────────────────────
    # Campos novos em scalping_trades e scalping_trades_v2_1b
    _audit_trade_cols = [
        ("signal_price", "REAL"),
        ("expected_entry_price", "REAL"),
        ("realized_entry_price", "REAL"),
        ("entry_slippage_bps", "REAL DEFAULT 0"),
        ("expected_exit_price", "REAL"),
        ("realized_exit_price", "REAL"),
        ("exit_slippage_bps", "REAL DEFAULT 0"),
        ("spread_bps_est", "REAL DEFAULT 0"),
        ("signal_to_order_ms", "REAL DEFAULT 0"),
        ("fill_model", "TEXT DEFAULT 'paper_close'"),
        ("capital_before", "REAL"),
        ("param_version", "TEXT DEFAULT 'unknown'"),
        ("git_sha", "TEXT DEFAULT 'unknown'"),
        ("risk_amount_usd", "REAL DEFAULT 0"),
        ("tp1_price", "REAL"),
        ("sl_distance_pct", "REAL"),
        ("rr_ratio_planned", "REAL"),
        ("gross_pnl_pct", "REAL"),
        ("gross_pnl_usd", "REAL"),
        ("fee_entry_bps", "REAL DEFAULT 0"),
        ("fee_exit_bps", "REAL DEFAULT 0"),
        ("funding_cost_bps", "REAL DEFAULT 0"),
        ("total_cost_bps", "REAL DEFAULT 0"),
        ("net_pnl_pct", "REAL"),
        ("net_pnl_usd", "REAL"),
        ("market_regime", "TEXT"),
        ("session_bucket", "TEXT"),
        ("hour_bucket", "INTEGER"),
        ("weekday_bucket", "INTEGER"),
        ("event_bucket", "TEXT DEFAULT 'none'"),
        ("asset_bucket", "TEXT"),
        ("strategy_family", "TEXT DEFAULT 'microstructure'"),
        ("ai_gate_used", "INTEGER DEFAULT 0"),
        ("ai_gate_approved", "INTEGER DEFAULT 0"),
        ("forced_entry", "INTEGER DEFAULT 0"),
    ]
    for table in ["scalping_trades", "scalping_trades_v2_1b"]:
        for col, coltype in _audit_trade_cols:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
                conn.commit()
            except Exception:
                pass

    # Campos novos em scalping_decisions e scalping_decisions_v2_1b
    _audit_decision_cols = [
        ("param_version", "TEXT DEFAULT 'unknown'"),
        ("git_sha", "TEXT DEFAULT 'unknown'"),
        ("market_regime", "TEXT"),
        ("session_bucket", "TEXT"),
        ("hour_bucket", "INTEGER"),
        ("expected_entry_price", "REAL"),
        ("signal_price", "REAL"),
        ("asset_bucket", "TEXT"),
        ("final_outcome", "TEXT"),
        ("blocked_by", "TEXT DEFAULT 'none'"),
        ("ablation_without_ai", "INTEGER DEFAULT 0"),
        ("ablation_without_funding", "INTEGER DEFAULT 0"),
        ("ablation_without_basis", "INTEGER DEFAULT 0"),
        ("ablation_without_liquidation", "INTEGER DEFAULT 0"),
        ("ablation_primary_only", "INTEGER DEFAULT 0"),
        ("funding_rate", "REAL"),
        ("basis_spread_pct", "REAL"),
        ("oi_change_1h_pct", "REAL"),
    ]
    for table in ["scalping_decisions", "scalping_decisions_v2_1b"]:
        for col, coltype in _audit_decision_cols:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
                conn.commit()
            except Exception:
                pass

    # ── Migração: custo de execucao (fee) em momentum_trades ─────────────────
    # Transforma PnL bruto em liquido. Colunas SEM default de proposito:
    # linhas antigas (trades pre-fee) ficam NULL = "nao medido", nunca
    # 0 = "fee zero". Nao altera a logica nem os params congelados da v1.1.
    _momentum_fee_cols = [
        ("gross_pnl_pct", "REAL"),
        ("gross_pnl_usd", "REAL"),
        ("entry_fee_rate", "REAL"),
        ("exit_fee_rate", "REAL"),
        ("fee_entry_usd", "REAL"),
        ("fee_exit_usd", "REAL"),
        ("fee_entry_bps", "REAL"),
        ("fee_exit_bps", "REAL"),
        ("total_fee_usd", "REAL"),
        ("total_cost_bps", "REAL"),
        ("net_pnl_pct", "REAL"),
        ("net_pnl_usd", "REAL"),
        ("fee_model", "TEXT"),
        ("entry_liquidity_assumption", "TEXT"),
        ("exit_liquidity_assumption", "TEXT"),
    ]
    for col, coltype in _momentum_fee_cols:
        try:
            conn.execute(f"ALTER TABLE momentum_trades ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass  # coluna já existe

    conn.close()


# ── INSERT FUNCTIONS ──────────────────────────────────────────────────────────

def insert_analysis_log(data: dict):
    conn = _get_conn()
    try:
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
    finally:
        conn.close()


def insert_alert(data: dict, alert_type: str):
    conn = _get_conn()
    try:
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
    finally:
        conn.close()


def insert_paper_trade(trade: dict):
    conn = _get_conn()
    try:
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
    finally:
        conn.close()


def insert_agent_trade(trade: dict):
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO agent_trades (
                timestamp, symbol, type, entry_price, sl_price, tp_price,
                position_size_usd, exit_price, pnl_pct, pnl_usd,
                exit_reason, analyst_confidence, capital_after,
                execution_mode, lifecycle_id, recommended_mode
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            trade.get("execution_mode", "paper"),
            trade.get("lifecycle_id"),
            trade.get("recommended_mode", "paper"),
        ))
        conn.commit()
    finally:
        conn.close()


def insert_pump_trade(trade: dict):
    conn = _get_conn()
    try:
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
    finally:
        conn.close()


def insert_momentum_trade(trade: dict):
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO momentum_trades (
                timestamp, symbol, direction, regime,
                entry_price, exit_price, sl_price, tp1_price, tp2_price,
                position_size_usd, pnl_pct, pnl_usd,
                exit_reason, capital_after, param_version,
                duration_candles, mfe_pct, mae_pct,
                session_bucket, asset_bucket,
                gross_pnl_pct, gross_pnl_usd,
                entry_fee_rate, exit_fee_rate,
                fee_entry_usd, fee_exit_usd,
                fee_entry_bps, fee_exit_bps,
                total_fee_usd, total_cost_bps,
                net_pnl_pct, net_pnl_usd,
                fee_model, entry_liquidity_assumption, exit_liquidity_assumption
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            trade["timestamp"],
            trade["symbol"],
            trade["direction"],
            trade.get("regime", ""),
            trade["entry_price"],
            trade.get("exit_price"),
            trade.get("sl_price"),
            trade.get("tp1_price"),
            trade.get("tp2_price"),
            trade.get("position_size_usd"),
            trade.get("pnl_pct"),
            round(trade.get("pnl_usd", 0), 2),
            trade.get("exit_reason", "open"),
            round(trade.get("capital_after", 0), 2),
            trade.get("param_version", "momentum-pullback-v1.1"),
            trade.get("duration_candles"),
            trade.get("mfe_pct", 0),
            trade.get("mae_pct", 0),
            trade.get("session_bucket", ""),
            trade.get("asset_bucket", ""),
            # Custo de execucao (gross -> net). Ausente => NULL = nao medido.
            trade.get("gross_pnl_pct"),
            trade.get("gross_pnl_usd"),
            trade.get("entry_fee_rate"),
            trade.get("exit_fee_rate"),
            trade.get("fee_entry_usd"),
            trade.get("fee_exit_usd"),
            trade.get("fee_entry_bps"),
            trade.get("fee_exit_bps"),
            trade.get("total_fee_usd"),
            trade.get("total_cost_bps"),
            trade.get("net_pnl_pct"),
            trade.get("net_pnl_usd"),
            trade.get("fee_model"),
            trade.get("entry_liquidity_assumption"),
            trade.get("exit_liquidity_assumption"),
        ))
        conn.commit()
    finally:
        conn.close()


def insert_momentum_decision(decision: dict):
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO momentum_decisions (
                timestamp, cycle_id, symbol, regime,
                outcome, direction, blocked_by,
                ema_fast_value, ema_slow_value, ema_gap_pct,
                retracement_pct, impulse_start_price, impulse_end_price,
                pullback_rejection, param_version,
                session_bucket, asset_bucket,
                adx_slope_3, di_spread
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            decision["timestamp"],
            decision.get("cycle_id", ""),
            decision["symbol"],
            decision.get("regime", ""),
            decision["outcome"],
            decision.get("direction", ""),
            decision.get("blocked_by", "none"),
            decision.get("ema_fast_value", 0),
            decision.get("ema_slow_value", 0),
            decision.get("ema_gap_pct", 0),
            decision.get("retracement_pct", 0),
            decision.get("impulse_start_price", 0),
            decision.get("impulse_end_price", 0),
            decision.get("pullback_rejection", ""),
            decision.get("param_version", "momentum-pullback-v1.1"),
            decision.get("session_bucket", ""),
            decision.get("asset_bucket", ""),
            decision.get("adx_slope_3", 0.0),
            decision.get("di_spread", 0.0),
        ))
        conn.commit()
    finally:
        conn.close()


def insert_breakout_trade(trade: dict):
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO breakout_trades (
                timestamp, symbol, direction,
                entry_price, exit_price, sl_price, tp1_price, tp2_price,
                position_size_usd, pnl_pct, pnl_usd,
                exit_reason, capital_after, param_version,
                duration_candles, mfe_pct, mae_pct
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            trade["timestamp"],
            trade["symbol"],
            trade["direction"],
            trade["entry_price"],
            trade.get("exit_price"),
            trade.get("sl_price"),
            trade.get("tp1_price"),
            trade.get("tp2_price"),
            trade.get("position_size_usd"),
            trade.get("pnl_pct"),
            round(trade.get("pnl_usd", 0), 2),
            trade.get("exit_reason", "open"),
            round(trade.get("capital_after", 0), 2),
            trade.get("param_version", "breakout-5m-v1.0"),
            trade.get("duration_candles"),
            trade.get("mfe_pct", 0),
            trade.get("mae_pct", 0),
        ))
        conn.commit()
    finally:
        conn.close()


def insert_breakout_decision(decision: dict):
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO breakout_decisions (
                timestamp, cycle_id, symbol, direction, blocked_by,
                range_pct, bb_bandwidth, vol_ratio, body_ratio,
                lookback, param_version
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            decision["timestamp"],
            decision.get("cycle_id", ""),
            decision["symbol"],
            decision.get("direction", ""),
            decision.get("blocked_by", "none"),
            decision.get("range_pct", 0),
            decision.get("bb_bandwidth", 0),
            decision.get("vol_ratio", 0),
            decision.get("body_ratio", 0),
            decision.get("lookback", 0),
            decision.get("param_version", "breakout-5m-v1.0"),
        ))
        conn.commit()
    finally:
        conn.close()


def insert_scalping_trade(trade: dict):
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO scalping_trades (
                timestamp, symbol, type, entry_price, exit_price,
                sl_price, tp_price, position_size_usd, leverage,
                confluence_score, source, pnl_pct, pnl_usd,
                exit_reason, capital_after, signal_subtype,
                signal_price, expected_entry_price, realized_entry_price,
                entry_slippage_bps, expected_exit_price, realized_exit_price,
                exit_slippage_bps, spread_bps_est, signal_to_order_ms,
                fill_model, capital_before, param_version, git_sha,
                risk_amount_usd, tp1_price, sl_distance_pct, rr_ratio_planned,
                gross_pnl_pct, gross_pnl_usd, fee_entry_bps, fee_exit_bps,
                funding_cost_bps, total_cost_bps, net_pnl_pct, net_pnl_usd,
                market_regime, session_bucket, hour_bucket, weekday_bucket,
                event_bucket, asset_bucket, strategy_family,
                ai_gate_used, ai_gate_approved, forced_entry
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            trade.get("signal_subtype", "unknown"),
            trade.get("signal_price"),
            trade.get("expected_entry_price"),
            trade.get("realized_entry_price"),
            trade.get("entry_slippage_bps", 0),
            trade.get("expected_exit_price"),
            trade.get("realized_exit_price"),
            trade.get("exit_slippage_bps", 0),
            trade.get("spread_bps_est", 0),
            trade.get("signal_to_order_ms", 0),
            trade.get("fill_model", "paper_close"),
            trade.get("capital_before"),
            trade.get("param_version", "unknown"),
            trade.get("git_sha", "unknown"),
            trade.get("risk_amount_usd", 0),
            trade.get("tp1_price"),
            trade.get("sl_distance_pct"),
            trade.get("rr_ratio_planned"),
            trade.get("gross_pnl_pct"),
            trade.get("gross_pnl_usd"),
            trade.get("fee_entry_bps", 0),
            trade.get("fee_exit_bps", 0),
            trade.get("funding_cost_bps", 0),
            trade.get("total_cost_bps", 0),
            trade.get("net_pnl_pct"),
            trade.get("net_pnl_usd"),
            trade.get("market_regime"),
            trade.get("session_bucket"),
            trade.get("hour_bucket"),
            trade.get("weekday_bucket"),
            trade.get("event_bucket", "none"),
            trade.get("asset_bucket"),
            trade.get("strategy_family", "microstructure"),
            int(bool(trade.get("ai_gate_used", False))),
            int(bool(trade.get("ai_gate_approved", False))),
            int(bool(trade.get("forced_entry", False))),
        ))
        conn.commit()
    finally:
        conn.close()


def insert_scalping_decision(decision: dict):
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO scalping_decisions (
                timestamp, cycle_id, symbol, outcome, reason,
                confluence_score, confluence_direction, best_signal_source,
                ai_used, ai_approved, risk_approved, rr_ratio, sl_distance_pct,
                signal_subtype,
                param_version, git_sha, market_regime, session_bucket,
                hour_bucket, expected_entry_price, signal_price, asset_bucket,
                final_outcome, blocked_by,
                ablation_without_ai, ablation_without_funding,
                ablation_without_basis, ablation_without_liquidation,
                ablation_primary_only,
                funding_rate, basis_spread_pct, oi_change_1h_pct
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            decision.get("signal_subtype", "unknown"),
            decision.get("param_version", "unknown"),
            decision.get("git_sha", "unknown"),
            decision.get("market_regime"),
            decision.get("session_bucket"),
            decision.get("hour_bucket"),
            decision.get("expected_entry_price"),
            decision.get("signal_price"),
            decision.get("asset_bucket"),
            decision.get("final_outcome"),
            decision.get("blocked_by", "none"),
            int(bool(decision.get("ablation_without_ai", False))),
            int(bool(decision.get("ablation_without_funding", False))),
            int(bool(decision.get("ablation_without_basis", False))),
            int(bool(decision.get("ablation_without_liquidation", False))),
            int(bool(decision.get("ablation_primary_only", False))),
            decision.get("funding_rate"),
            decision.get("basis_spread_pct"),
            decision.get("oi_change_1h_pct"),
        ))
        conn.commit()
    finally:
        conn.close()


def insert_scalping_audit_log(audit: dict):
    details_json = audit.get("details_json", "")
    if isinstance(details_json, (dict, list)):
        details_json = json.dumps(details_json, ensure_ascii=False)

    conn = _get_conn()
    try:
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
    finally:
        conn.close()


def insert_scalping_trade_v2_1b(trade: dict):
    """Insere trade na tabela V2.1b (espelho de scalping_trades)."""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO scalping_trades_v2_1b (
                timestamp, symbol, type, entry_price, exit_price,
                sl_price, tp_price, position_size_usd, leverage,
                confluence_score, source, pnl_pct, pnl_usd,
                exit_reason, capital_after,
                signal_price, expected_entry_price, realized_entry_price,
                entry_slippage_bps, expected_exit_price, realized_exit_price,
                exit_slippage_bps, spread_bps_est, signal_to_order_ms,
                fill_model, capital_before, param_version, git_sha,
                risk_amount_usd, tp1_price, sl_distance_pct, rr_ratio_planned,
                gross_pnl_pct, gross_pnl_usd, fee_entry_bps, fee_exit_bps,
                funding_cost_bps, total_cost_bps, net_pnl_pct, net_pnl_usd,
                market_regime, session_bucket, hour_bucket, weekday_bucket,
                event_bucket, asset_bucket, strategy_family,
                ai_gate_used, ai_gate_approved, forced_entry
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            trade.get("signal_price"),
            trade.get("expected_entry_price"),
            trade.get("realized_entry_price"),
            trade.get("entry_slippage_bps", 0),
            trade.get("expected_exit_price"),
            trade.get("realized_exit_price"),
            trade.get("exit_slippage_bps", 0),
            trade.get("spread_bps_est", 0),
            trade.get("signal_to_order_ms", 0),
            trade.get("fill_model", "paper_close"),
            trade.get("capital_before"),
            trade.get("param_version", "unknown"),
            trade.get("git_sha", "unknown"),
            trade.get("risk_amount_usd", 0),
            trade.get("tp1_price"),
            trade.get("sl_distance_pct"),
            trade.get("rr_ratio_planned"),
            trade.get("gross_pnl_pct"),
            trade.get("gross_pnl_usd"),
            trade.get("fee_entry_bps", 0),
            trade.get("fee_exit_bps", 0),
            trade.get("funding_cost_bps", 0),
            trade.get("total_cost_bps", 0),
            trade.get("net_pnl_pct"),
            trade.get("net_pnl_usd"),
            trade.get("market_regime"),
            trade.get("session_bucket"),
            trade.get("hour_bucket"),
            trade.get("weekday_bucket"),
            trade.get("event_bucket", "none"),
            trade.get("asset_bucket"),
            trade.get("strategy_family", "microstructure"),
            int(bool(trade.get("ai_gate_used", False))),
            int(bool(trade.get("ai_gate_approved", False))),
            int(bool(trade.get("forced_entry", False))),
        ))
        conn.commit()
    finally:
        conn.close()


def insert_scalping_decision_v2_1b(decision: dict):
    """Insere decisao na tabela V2.1b (espelho de scalping_decisions)."""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO scalping_decisions_v2_1b (
                timestamp, cycle_id, symbol, outcome, reason,
                confluence_score, confluence_direction, best_signal_source,
                ai_used, ai_approved, risk_approved, rr_ratio, sl_distance_pct,
                param_version, git_sha, market_regime, session_bucket,
                hour_bucket, expected_entry_price, signal_price, asset_bucket,
                final_outcome, blocked_by,
                ablation_without_ai, ablation_without_funding,
                ablation_without_basis, ablation_without_liquidation,
                ablation_primary_only,
                funding_rate, basis_spread_pct, oi_change_1h_pct
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            decision.get("param_version", "unknown"),
            decision.get("git_sha", "unknown"),
            decision.get("market_regime"),
            decision.get("session_bucket"),
            decision.get("hour_bucket"),
            decision.get("expected_entry_price"),
            decision.get("signal_price"),
            decision.get("asset_bucket"),
            decision.get("final_outcome"),
            decision.get("blocked_by", "none"),
            int(bool(decision.get("ablation_without_ai", False))),
            int(bool(decision.get("ablation_without_funding", False))),
            int(bool(decision.get("ablation_without_basis", False))),
            int(bool(decision.get("ablation_without_liquidation", False))),
            int(bool(decision.get("ablation_primary_only", False))),
            decision.get("funding_rate"),
            decision.get("basis_spread_pct"),
            decision.get("oi_change_1h_pct"),
        ))
        conn.commit()
    finally:
        conn.close()


def upsert_scalping_outcome_label(label: dict):
    details_json = label.get("details_json", "")
    if isinstance(details_json, (dict, list)):
        details_json = json.dumps(details_json, ensure_ascii=False)

    conn = _get_conn()
    try:
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
    finally:
        conn.close()


def insert_ai_decision(decision: dict):
    """Registra uma decisão de IA (modelo, latência, fallback, resultado)."""
    conn = _get_conn()
    try:
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
    finally:
        conn.close()


def insert_market_microstructure(data: dict):
    """Insere snapshot de microestrutura de mercado."""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO market_microstructure (
                timestamp, symbol, funding_rate, funding_rate_prev1,
                funding_rate_prev2, ls_ratio_top, ls_ratio_global,
                liquidation_vol_long, liquidation_vol_short,
                open_interest, oi_change_1h_pct, oi_change_4h_pct,
                basis_spread_pct, session,
                next_funding_time, liquidation_count, liquidation_is_proxy,
                futures_price, spot_price
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            data.get("symbol", ""),
            data.get("funding_rate"),
            data.get("funding_rate_prev1"),
            data.get("funding_rate_prev2"),
            data.get("ls_ratio_top"),
            data.get("ls_ratio_global"),
            data.get("liquidation_vol_long"),
            data.get("liquidation_vol_short"),
            data.get("open_interest"),
            data.get("oi_change_1h_pct"),
            data.get("oi_change_4h_pct"),
            data.get("basis_spread_pct"),
            data.get("session", ""),
            data.get("next_funding_time"),
            data.get("liquidation_count", 0),
            1 if data.get("liquidation_is_proxy") else 0,
            data.get("futures_price"),
            data.get("spot_price"),
        ))
        conn.commit()
    finally:
        conn.close()


def get_microstructure_history(symbol: str, hours: int = 24, resolution_minutes: int = 1) -> list:
    """Retorna historico de microestrutura com agregacao temporal.

    Args:
        symbol: Par de trading (ex: BTCUSDT)
        hours: Quantas horas de historico (default 24)
        resolution_minutes: Resolucao em minutos (1=granular, 5=5min, 60=1h)

    Returns:
        Lista de dicts com medias por bucket temporal (ou rows raw se resolution=1)
    """
    conn = _get_conn()
    try:
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

        if resolution_minutes <= 1:
            # Dados granulares — retorna tudo
            cursor = conn.execute("""
                SELECT * FROM market_microstructure
                WHERE symbol = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (symbol, since))
        else:
            # Agregacao por bucket de N minutos
            cursor = conn.execute("""
                SELECT
                    strftime('%Y-%m-%d %H:', timestamp) ||
                        printf('%02d', (CAST(strftime('%M', timestamp) AS INTEGER) / ?) * ?)
                        || ':00' AS bucket,
                    symbol,
                    AVG(funding_rate) AS funding_rate,
                    AVG(funding_rate_prev1) AS funding_rate_prev1,
                    AVG(funding_rate_prev2) AS funding_rate_prev2,
                    AVG(ls_ratio_top) AS ls_ratio_top,
                    AVG(ls_ratio_global) AS ls_ratio_global,
                    SUM(liquidation_vol_long) AS liquidation_vol_long,
                    SUM(liquidation_vol_short) AS liquidation_vol_short,
                    AVG(open_interest) AS open_interest,
                    AVG(oi_change_1h_pct) AS oi_change_1h_pct,
                    AVG(oi_change_4h_pct) AS oi_change_4h_pct,
                    AVG(basis_spread_pct) AS basis_spread_pct,
                    AVG(futures_price) AS futures_price,
                    AVG(spot_price) AS spot_price,
                    COUNT(*) AS sample_count
                FROM market_microstructure
                WHERE symbol = ? AND timestamp >= ?
                GROUP BY bucket, symbol
                ORDER BY bucket ASC
            """, (resolution_minutes, resolution_minutes, symbol, since))

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def prune_microstructure(keep_days: int = 60) -> int:
    """Remove registos de microestrutura mais antigos que keep_days.

    Returns:
        Numero de registos removidos.
    """
    conn = _get_conn()
    try:
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            "DELETE FROM market_microstructure WHERE timestamp < ?",
            (cutoff,),
        )
        removed = cursor.rowcount
        conn.commit()
        if removed > 0:
            # VACUUM periodico para recuperar espaco no SD card
            conn.execute("VACUUM")
        return removed
    finally:
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


def get_recent_trades_by_symbol(table: str, symbol: str,
                                limit: int = 10) -> list:
    """Fetch the N most recent trades for a specific symbol. Read-only."""
    _validate_table(table)
    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} WHERE symbol = ? ORDER BY id DESC LIMIT ?",
            (symbol, limit),
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
    _validate_table(table)
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM {table} WHERE timestamp >= ? ORDER BY id DESC LIMIT ?",
        (cutoff, limit)
    ).fetchall()]
    conn.close()
    return rows


def get_scalping_decisions_summary(hours: int = 24) -> dict:
    """Resumo de decisoes do scalping agrupado por blocked_by."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT blocked_by, COUNT(*) as count "
            "FROM scalping_decisions "
            "WHERE timestamp > datetime('now', ?)"
            "GROUP BY blocked_by ORDER BY count DESC",
            (f"-{hours} hours",),
        ).fetchall()
        return {row["blocked_by"] or "none": int(row["count"]) for row in rows}
    finally:
        conn.close()


def get_scalping_trades_by_regime(hours: int = 24) -> list:
    """Trades do scalping agrupados por regime com stats (janela rolante)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT market_regime, COUNT(*) as count, "
            "ROUND(AVG(pnl_pct), 4) as avg_pnl, "
            "ROUND(SUM(pnl_pct), 4) as total_pnl, "
            "SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losses "
            "FROM scalping_trades WHERE timestamp > datetime('now', ?) "
            "AND exit_reason != 'open' "
            "GROUP BY market_regime ORDER BY count DESC",
            (f"-{hours} hours",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_scalping_trades_by_session(hours: int = 24) -> list:
    """Trades do scalping agrupados por sessao com stats (janela rolante)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT session_bucket, COUNT(*) as count, "
            "ROUND(AVG(pnl_pct), 4) as avg_pnl, "
            "ROUND(SUM(pnl_pct), 4) as total_pnl, "
            "SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losses "
            "FROM scalping_trades WHERE timestamp > datetime('now', ?) "
            "AND exit_reason != 'open' "
            "GROUP BY session_bucket ORDER BY count DESC",
            (f"-{hours} hours",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_closed_trades_in_period(table: str, days: int = 30) -> list:
    """Todos os trades fechados (com PnL) no periodo, sem limite artificial.

    Read-only.  Usado pelo auditor offline para garantir que expectancy,
    churn, concentration e verdict usem a mesma base completa.
    """
    _validate_table(table)
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} "
            f"WHERE timestamp >= ? AND pnl_pct IS NOT NULL AND exit_reason != 'open' "
            f"ORDER BY id",
            (cutoff,),
        ).fetchall()]
    finally:
        conn.close()


def get_ai_decisions_summary(days: int = 30, system: str | None = None) -> dict:
    """Resumo read-only das decisoes de IA no periodo (para auditor offline).

    Se ``system`` for fornecido, filtra apenas registros desse desk
    (ex: "agent").  Caso contrario, retorna o resumo global.
    """
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    where = "WHERE timestamp >= ?"
    params: list = [cutoff]
    if system is not None:
        where += " AND system = ?"
        params.append(system)

    conn = _get_conn()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM ai_decisions {where}", params,
        ).fetchone()["cnt"]

        empty = {
            "total": 0, "by_system": {}, "by_prompt_version": {},
            "fallbacks": 0, "parse_failures": 0, "approvals": 0,
            "approval_rate": 0, "avg_confidence": 0, "avg_latency_ms": 0,
        }
        if total == 0:
            return empty

        versions = [dict(r) for r in conn.execute(
            f"SELECT prompt_version, COUNT(*) as cnt FROM ai_decisions "
            f"{where} GROUP BY prompt_version", params,
        ).fetchall()]

        by_system = [dict(r) for r in conn.execute(
            f"SELECT system, COUNT(*) as cnt FROM ai_decisions "
            f"{where} GROUP BY system", params,
        ).fetchall()]

        agg = conn.execute(
            f"SELECT SUM(fallback_used) as fb, "
            f"SUM(CASE WHEN parse_success = 0 THEN 1 ELSE 0 END) as pf, "
            f"SUM(approved) as ap, AVG(confidence) as ac, AVG(latency_ms) as al "
            f"FROM ai_decisions {where}", params,
        ).fetchone()

        fallbacks = int(agg["fb"] or 0)
        parse_failures = int(agg["pf"] or 0)
        approvals = int(agg["ap"] or 0)
        avg_conf = float(agg["ac"]) if agg["ac"] is not None else 0
        avg_lat = float(agg["al"]) if agg["al"] is not None else 0

        return {
            "total": total,
            "by_system": {r["system"]: r["cnt"] for r in by_system},
            "by_prompt_version": {(r["prompt_version"] or "none"): r["cnt"] for r in versions},
            "fallbacks": fallbacks,
            "parse_failures": parse_failures,
            "approvals": approvals,
            "approval_rate": round(approvals / total * 100, 1),
            "avg_confidence": round(avg_conf, 1),
            "avg_latency_ms": round(avg_lat, 1),
        }
    finally:
        conn.close()


def get_trade_by_id(table: str, trade_id: int) -> dict | None:
    """Fetch a single trade by ID. Read-only."""
    _validate_table(table)
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ?", (trade_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# Whitelist of timestamp column names allowed in get_nearby_records.
_VALID_TS_COLS = frozenset({"timestamp", "audit_timestamp", "labeled_at"})


def get_nearby_records(table: str, timestamp: str, symbol: str | None = None,
                       window_minutes: int = 60, limit: int = 20,
                       timestamp_col: str = "timestamp") -> list:
    """Fetch records near a timestamp from any valid table. Read-only.

    Used by the Trade Review Lab to collect context around a specific trade.
    """
    _validate_table(table)
    if timestamp_col not in _VALID_TS_COLS:
        raise ValueError(
            f"timestamp_col '{timestamp_col}' not allowed. "
            f"Valid: {sorted(_VALID_TS_COLS)}"
        )

    from datetime import timedelta
    try:
        ts = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return []

    start = (ts - timedelta(minutes=window_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    end = (ts + timedelta(minutes=window_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    query = f"SELECT * FROM {table} WHERE {timestamp_col} BETWEEN ? AND ?"
    params: list = [start, end]

    if symbol:
        query += " AND symbol = ?"
        params.append(symbol)

    query += f" ORDER BY {timestamp_col} DESC LIMIT ?"
    params.append(limit)

    conn = _get_conn()
    try:
        rows = [dict(r) for r in conn.execute(query, tuple(params)).fetchall()]
    finally:
        conn.close()

    for row in rows:
        details = row.get("details_json")
        if details:
            try:
                row["details"] = json.loads(details)
            except Exception:
                row["details"] = {"raw": details}
            row.pop("details_json", None)

    return rows


def get_nearby_ai_decisions(timestamp: str, symbol: str | None = None,
                            system: str | None = None,
                            window_minutes: int = 30,
                            limit: int = 10) -> list:
    """Fetch ai_decisions near a timestamp, optionally filtered by system.

    Dedicated helper so the Trade Review Lab can request only decisions
    from a specific desk (e.g. system="agent").  Read-only.
    """
    from datetime import timedelta
    try:
        ts = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return []

    start = (ts - timedelta(minutes=window_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    end = (ts + timedelta(minutes=window_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    query = "SELECT * FROM ai_decisions WHERE timestamp BETWEEN ? AND ?"
    params: list = [start, end]

    if symbol:
        query += " AND symbol = ?"
        params.append(symbol)

    if system:
        query += " AND system = ?"
        params.append(system)

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


# ── TRADE QUERY HELPERS (used by trade_review_lab.py) ─────────────────────────

def _is_closed_filter() -> str:
    """SQL fragment that matches only closed trades."""
    return "exit_reason IS NOT NULL AND exit_reason != '' AND exit_reason != 'open'"


def get_closed_trade_by_id(table: str, trade_id: int) -> dict | None:
    """Fetch a single trade by ID only if it is closed. Read-only.

    A trade is considered closed when exit_reason is present and not
    empty/'open'. Returns None if the trade does not exist or is still open.
    """
    _validate_table(table)
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ? AND {_is_closed_filter()}",
            (trade_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_recent_closed_trades(table: str, limit: int = 10) -> list:
    """Fetch the N most recent closed trades from a table. Read-only."""
    _validate_table(table)
    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} WHERE {_is_closed_filter()} "
            f"ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()]
    finally:
        conn.close()


def get_recent_closed_trades_by_symbol(table: str, symbol: str,
                                       limit: int = 10) -> list:
    """Fetch the N most recent closed trades for a symbol. Read-only."""
    _validate_table(table)
    conn = _get_conn()
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} "
            f"WHERE symbol = ? AND {_is_closed_filter()} "
            f"ORDER BY id DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()]
    finally:
        conn.close()
