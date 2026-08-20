"""Integration tests for momentum paper trading DB + circuit breaker."""
import os
import sqlite3
import tempfile

import pytest


@pytest.fixture
def tmp_db(monkeypatch):
    """Create a temp DB file and point database.py at it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("database.DB_FILE", path)
    import database as db
    db.init_db()
    yield path
    os.unlink(path)


class TestMomentumTradeInsert:
    def test_insert_and_retrieve(self, tmp_db):
        import database as db

        trade = {
            "timestamp": "2026-04-15T12:00:00",
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "regime": "TRENDING",
            "entry_price": 85000.0,
            "exit_price": 86000.0,
            "sl_price": 84500.0,
            "tp1_price": 85800.0,
            "tp2_price": 86500.0,
            "pnl_pct": 1.18,
            "pnl_usd": 11.80,
            "exit_reason": "tp1_hit",
            "capital_after": 1011.80,
            "param_version": "momentum-pullback-v1.1",
            "duration_candles": 8,
            "mfe_pct": 1.5,
            "mae_pct": -0.3,
        }
        db.insert_momentum_trade(trade)

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM momentum_trades").fetchone()
        conn.close()

        assert row is not None
        assert row["symbol"] == "BTCUSDT"
        assert row["direction"] == "LONG"
        assert row["pnl_pct"] == 1.18
        assert row["exit_reason"] == "tp1_hit"
        assert row["param_version"] == "momentum-pullback-v1.1"


class TestMomentumDecisionInsert:
    def test_insert_and_retrieve(self, tmp_db):
        import database as db

        decision = {
            "timestamp": "2026-04-15T12:00:00",
            "cycle_id": "20260415_120000",
            "symbol": "BTCUSDT",
            "regime": "TRENDING",
            "outcome": "trade",
            "direction": "LONG",
            "blocked_by": "none",
            "ema_fast_value": 85100.0,
            "ema_slow_value": 84800.0,
            "retracement_pct": 42.5,
            "param_version": "momentum-pullback-v1.1",
        }
        db.insert_momentum_decision(decision)

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM momentum_decisions").fetchone()
        conn.close()

        assert row is not None
        assert row["outcome"] == "trade"
        assert row["blocked_by"] == "none"
        assert row["retracement_pct"] == 42.5


class TestCircuitBreakerMomentum:
    def test_momentum_in_table_map(self, tmp_db):
        """Circuit breaker functions should recognize 'momentum' system."""
        from daily_report import check_circuit_breaker
        result = check_circuit_breaker("momentum")
        assert result is False or result is True

    def test_momentum_not_unknown(self):
        """'momentum' should be a known system, not silently ignored."""
        import daily_report
        import inspect
        source = inspect.getsource(daily_report.check_circuit_breaker)
        assert "momentum" in source


class TestMomentumTradeNetFields:
    """Custo de execucao: gross -> net por trade fechado. v1.1 intocada."""

    NET_COLS = [
        "gross_pnl_pct", "gross_pnl_usd",
        "entry_fee_rate", "exit_fee_rate",
        "fee_entry_usd", "fee_exit_usd",
        "fee_entry_bps", "fee_exit_bps",
        "total_fee_usd", "total_cost_bps",
        "net_pnl_pct", "net_pnl_usd",
        "fee_model",
        "entry_liquidity_assumption", "exit_liquidity_assumption",
    ]

    def _columns(self, db_path):
        conn = sqlite3.connect(db_path)
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(momentum_trades)").fetchall()}
        conn.close()
        return cols

    def test_migration_adiciona_colunas_net(self, tmp_db):
        cols = self._columns(tmp_db)
        for c in self.NET_COLS:
            assert c in cols, f"coluna faltando: {c}"

    def test_insert_grava_campos_net(self, tmp_db):
        import database as db
        db.insert_momentum_trade({
            "timestamp": "2026-06-08T12:00:00",
            "symbol": "ETHUSDT", "direction": "SHORT",
            "entry_price": 3000.0, "exit_price": 2970.0,
            "pnl_pct": 1.0, "pnl_usd": 10.0, "position_size_usd": 1000.0,
            "gross_pnl_pct": 1.0, "gross_pnl_usd": 10.0,
            "entry_fee_rate": 0.04, "exit_fee_rate": 0.04,
            "fee_entry_usd": 0.4, "fee_exit_usd": 0.4,
            "fee_entry_bps": 4.0, "fee_exit_bps": 4.0,
            "total_fee_usd": 0.8, "total_cost_bps": 8.0,
            "net_pnl_pct": 0.92, "net_pnl_usd": 9.2,
            "fee_model": "flat_taker_v1",
            "entry_liquidity_assumption": "taker",
            "exit_liquidity_assumption": "taker",
        })
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM momentum_trades").fetchone()
        conn.close()
        assert row["gross_pnl_usd"] == 10.0
        assert row["total_fee_usd"] == 0.8
        assert row["net_pnl_usd"] == 9.2
        assert row["net_pnl_pct"] == 0.92
        assert row["fee_model"] == "flat_taker_v1"
        assert row["entry_liquidity_assumption"] == "taker"
        assert row["exit_liquidity_assumption"] == "taker"

    def test_insert_backward_compat_sem_campos_net(self, tmp_db):
        """Trade legado (sem fee) ainda insere; campos novos ficam NULL."""
        import database as db
        db.insert_momentum_trade({
            "timestamp": "2026-04-15T12:00:00",
            "symbol": "BTCUSDT", "direction": "LONG",
            "entry_price": 85000.0, "exit_price": 86000.0,
            "pnl_pct": 1.18, "pnl_usd": 11.80,
            "exit_reason": "tp1_hit", "capital_after": 1011.80,
        })
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM momentum_trades").fetchone()
        conn.close()
        assert row["pnl_usd"] == 11.80      # campo legado intacto
        assert row["net_pnl_usd"] is None   # nao medido -> NULL
        assert row["total_fee_usd"] is None
        assert row["fee_model"] is None
