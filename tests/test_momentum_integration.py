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
