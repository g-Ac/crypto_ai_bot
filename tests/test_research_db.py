"""Tests for momentum/research_db.py.

All tests use a temporary SQLite database — no network, no shared state.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from momentum.research_db import (
    close_trade,
    ensure_tables,
    get_decisions,
    get_open_trades,
    get_trades,
    insert_decision,
    insert_trade,
    update_decision_forward,
    update_trade_mfe_mae,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Temporary DB with schema already created."""
    path = tmp_path / "test_momentum.db"
    ensure_tables(path)
    return path


def _sample_decision(**overrides) -> dict:
    base = {
        "timestamp": "2026-04-15T12:00:00",
        "symbol": "BTCUSDT",
        "regime": "TRENDING",
        "session_bucket": "us",
        "asset_bucket": "btc",
        "outcome": "trade",
        "direction": "LONG",
        "ema_fast_value": 105000.0,
        "ema_slow_value": 104500.0,
        "ema_gap_pct": 0.48,
        "retracement_pct": 42.5,
        "impulse_start_price": 103000.0,
        "impulse_end_price": 106000.0,
        "pullback_rejection": "",
        "param_version": "momentum-pullback-v1",
    }
    base.update(overrides)
    return base


def _sample_trade(decision_id: int, **overrides) -> dict:
    base = {
        "decision_id": decision_id,
        "timestamp": "2026-04-15T12:00:00",
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "regime": "TRENDING",
        "session_bucket": "us",
        "entry_price": 104800.0,
        "sl_price": 103000.0,
        "tp1_price": 106000.0,
        "tp2_price": 107500.0,
        "param_version": "momentum-pullback-v1",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_ensure_tables_creates_both_tables(self, db_path):
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()

        table_names = [t[0] for t in tables]
        assert "momentum_decisions" in table_names
        assert "momentum_trades" in table_names

    def test_ensure_tables_idempotent(self, db_path):
        # Call again — must not raise
        ensure_tables(db_path)
        ensure_tables(db_path)

        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'momentum_%'"
        ).fetchone()[0]
        conn.close()
        assert count == 2

    def test_wal_mode_enabled(self, db_path):
        conn = sqlite3.connect(str(db_path))
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_indexes_created(self, db_path):
        conn = sqlite3.connect(str(db_path))
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_m%'"
        ).fetchall()
        conn.close()

        idx_names = [i[0] for i in indexes]
        assert "idx_mdec_ts" in idx_names
        assert "idx_mdec_symbol" in idx_names
        assert "idx_mdec_outcome" in idx_names
        assert "idx_mtrade_ts" in idx_names
        assert "idx_mtrade_symbol" in idx_names
        assert "idx_mtrade_open" in idx_names


# ---------------------------------------------------------------------------
# 2. Decisions — insert / query
# ---------------------------------------------------------------------------

class TestDecisionInsert:
    def test_insert_returns_id(self, db_path):
        row_id = insert_decision(db_path, _sample_decision())
        assert row_id == 1

    def test_insert_roundtrip(self, db_path):
        d = _sample_decision()
        row_id = insert_decision(db_path, d)

        rows = get_decisions(db_path)
        assert len(rows) == 1

        row = rows[0]
        assert row["id"] == row_id
        assert row["symbol"] == "BTCUSDT"
        assert row["outcome"] == "trade"
        assert row["direction"] == "LONG"
        assert row["regime"] == "TRENDING"
        assert row["ema_gap_pct"] == pytest.approx(0.48)
        assert row["retracement_pct"] == pytest.approx(42.5)
        assert row["param_version"] == "momentum-pullback-v1"
        assert row["forward_mfe_pct"] is None
        assert row["forward_mae_pct"] is None

    def test_insert_rejected_decision(self, db_path):
        d = _sample_decision(
            outcome="no_valid_pullback",
            pullback_rejection="retracement_too_shallow",
            retracement_pct=12.3,
        )
        insert_decision(db_path, d)
        rows = get_decisions(db_path)
        assert rows[0]["pullback_rejection"] == "retracement_too_shallow"

    def test_insert_minimal_fields(self, db_path):
        """Only required fields — defaults fill the rest."""
        d = {
            "timestamp": "2026-04-15T00:00:00",
            "symbol": "ETHUSDT",
            "regime": "WEAK_TREND",
            "outcome": "no_trend",
            "direction": "NEUTRAL",
        }
        row_id = insert_decision(db_path, d)
        row = get_decisions(db_path)[0]
        assert row["id"] == row_id
        assert row["ema_fast_value"] == 0  # default
        assert row["session_bucket"] == ""  # default

    def test_autoincrement(self, db_path):
        id1 = insert_decision(db_path, _sample_decision())
        id2 = insert_decision(db_path, _sample_decision(symbol="ETHUSDT"))
        assert id2 == id1 + 1


# ---------------------------------------------------------------------------
# 3. Decisions — forward labels
# ---------------------------------------------------------------------------

class TestDecisionForward:
    def test_update_forward_labels(self, db_path):
        row_id = insert_decision(db_path, _sample_decision(outcome="no_confirmation"))

        update_decision_forward(db_path, row_id, forward_mfe_pct=1.2, forward_mae_pct=-0.5)

        row = get_decisions(db_path)[0]
        assert row["forward_mfe_pct"] == pytest.approx(1.2)
        assert row["forward_mae_pct"] == pytest.approx(-0.5)

    def test_update_only_target_row(self, db_path):
        id1 = insert_decision(db_path, _sample_decision())
        id2 = insert_decision(db_path, _sample_decision(symbol="ETHUSDT"))

        update_decision_forward(db_path, id1, forward_mfe_pct=2.0, forward_mae_pct=-1.0)

        rows = get_decisions(db_path)
        assert rows[0]["forward_mfe_pct"] == pytest.approx(2.0)
        assert rows[1]["forward_mfe_pct"] is None  # untouched


# ---------------------------------------------------------------------------
# 4. Decisions — query filters
# ---------------------------------------------------------------------------

class TestDecisionFilters:
    def test_filter_by_symbol(self, db_path):
        insert_decision(db_path, _sample_decision(symbol="BTCUSDT"))
        insert_decision(db_path, _sample_decision(symbol="ETHUSDT"))
        insert_decision(db_path, _sample_decision(symbol="BTCUSDT"))

        rows = get_decisions(db_path, symbol="ETHUSDT")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "ETHUSDT"

    def test_filter_by_outcome(self, db_path):
        insert_decision(db_path, _sample_decision(outcome="trade"))
        insert_decision(db_path, _sample_decision(outcome="no_trend"))
        insert_decision(db_path, _sample_decision(outcome="trade"))

        rows = get_decisions(db_path, outcome="trade")
        assert len(rows) == 2

    def test_no_filters_returns_all(self, db_path):
        for i in range(5):
            insert_decision(db_path, _sample_decision())
        assert len(get_decisions(db_path)) == 5

    def test_combined_filters(self, db_path):
        insert_decision(db_path, _sample_decision(symbol="BTCUSDT", outcome="trade"))
        insert_decision(db_path, _sample_decision(symbol="BTCUSDT", outcome="no_trend"))
        insert_decision(db_path, _sample_decision(symbol="ETHUSDT", outcome="trade"))

        rows = get_decisions(db_path, symbol="BTCUSDT", outcome="trade")
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# 5. Trades — insert / query
# ---------------------------------------------------------------------------

class TestTradeInsert:
    def test_insert_returns_id(self, db_path):
        dec_id = insert_decision(db_path, _sample_decision())
        trade_id = insert_trade(db_path, _sample_trade(dec_id))
        assert trade_id == 1

    def test_insert_roundtrip(self, db_path):
        dec_id = insert_decision(db_path, _sample_decision())
        trade_id = insert_trade(db_path, _sample_trade(dec_id))

        rows = get_trades(db_path)
        assert len(rows) == 1

        row = rows[0]
        assert row["id"] == trade_id
        assert row["decision_id"] == dec_id
        assert row["entry_price"] == pytest.approx(104800.0)
        assert row["sl_price"] == pytest.approx(103000.0)
        assert row["tp1_price"] == pytest.approx(106000.0)
        assert row["exit_price"] is None  # open
        assert row["exit_reason"] is None
        assert row["mfe_pct"] == 0
        assert row["mae_pct"] == 0
        assert row["retested_impulse_end"] == 0
        assert row["lost_pullback_extreme"] == 0


# ---------------------------------------------------------------------------
# 6. Trades — close
# ---------------------------------------------------------------------------

class TestTradeClose:
    def test_close_trade_fills_exit(self, db_path):
        dec_id = insert_decision(db_path, _sample_decision())
        trade_id = insert_trade(db_path, _sample_trade(dec_id))

        close_trade(
            db_path, trade_id,
            exit_price=106000.0,
            exit_reason="tp1_hit",
            exit_timestamp="2026-04-15T16:00:00",
            pnl_pct=1.15,
            duration_candles=8,
            mfe_pct=1.3,
            mae_pct=-0.2,
            retested_impulse_end=True,
            lost_pullback_extreme=False,
        )

        row = get_trades(db_path)[0]
        assert row["exit_price"] == pytest.approx(106000.0)
        assert row["exit_reason"] == "tp1_hit"
        assert row["exit_timestamp"] == "2026-04-15T16:00:00"
        assert row["pnl_pct"] == pytest.approx(1.15)
        assert row["duration_candles"] == 8
        assert row["mfe_pct"] == pytest.approx(1.3)
        assert row["mae_pct"] == pytest.approx(-0.2)
        assert row["retested_impulse_end"] == 1
        assert row["lost_pullback_extreme"] == 0

    def test_close_only_target_trade(self, db_path):
        dec_id = insert_decision(db_path, _sample_decision())
        t1 = insert_trade(db_path, _sample_trade(dec_id))
        t2 = insert_trade(db_path, _sample_trade(dec_id, symbol="ETHUSDT"))

        close_trade(
            db_path, t1,
            exit_price=103000.0, exit_reason="sl_hit",
            exit_timestamp="2026-04-15T14:00:00",
            pnl_pct=-1.72, duration_candles=4,
            mfe_pct=0.1, mae_pct=-1.8,
        )

        rows = get_trades(db_path)
        assert rows[0]["exit_price"] is not None  # t1 closed
        assert rows[1]["exit_price"] is None  # t2 still open


# ---------------------------------------------------------------------------
# 7. Trades — MFE/MAE running update
# ---------------------------------------------------------------------------

class TestTradeMfeMae:
    def test_update_running_mfe_mae(self, db_path):
        dec_id = insert_decision(db_path, _sample_decision())
        trade_id = insert_trade(db_path, _sample_trade(dec_id))

        update_trade_mfe_mae(db_path, trade_id, mfe_pct=0.8, mae_pct=-0.3)

        row = get_trades(db_path)[0]
        assert row["mfe_pct"] == pytest.approx(0.8)
        assert row["mae_pct"] == pytest.approx(-0.3)

        # Update again — higher MFE
        update_trade_mfe_mae(db_path, trade_id, mfe_pct=1.5, mae_pct=-0.3)
        row = get_trades(db_path)[0]
        assert row["mfe_pct"] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# 8. Trades — open positions filter
# ---------------------------------------------------------------------------

class TestOpenTrades:
    def test_get_open_trades_excludes_closed(self, db_path):
        dec_id = insert_decision(db_path, _sample_decision())
        t1 = insert_trade(db_path, _sample_trade(dec_id))
        t2 = insert_trade(db_path, _sample_trade(dec_id, symbol="ETHUSDT"))

        close_trade(
            db_path, t1,
            exit_price=106000.0, exit_reason="tp1_hit",
            exit_timestamp="2026-04-15T16:00:00",
            pnl_pct=1.15, duration_candles=8,
            mfe_pct=1.3, mae_pct=-0.2,
        )

        open_trades = get_open_trades(db_path)
        assert len(open_trades) == 1
        assert open_trades[0]["id"] == t2

    def test_get_open_trades_empty(self, db_path):
        assert get_open_trades(db_path) == []


# ---------------------------------------------------------------------------
# 9. Trades — query filters
# ---------------------------------------------------------------------------

class TestTradeFilters:
    def test_filter_by_symbol(self, db_path):
        dec_id = insert_decision(db_path, _sample_decision())
        insert_trade(db_path, _sample_trade(dec_id, symbol="BTCUSDT"))
        insert_trade(db_path, _sample_trade(dec_id, symbol="ETHUSDT"))

        rows = get_trades(db_path, symbol="ETHUSDT")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "ETHUSDT"

    def test_closed_only_filter(self, db_path):
        dec_id = insert_decision(db_path, _sample_decision())
        t1 = insert_trade(db_path, _sample_trade(dec_id))
        t2 = insert_trade(db_path, _sample_trade(dec_id, symbol="ETHUSDT"))

        close_trade(
            db_path, t1,
            exit_price=106000.0, exit_reason="tp1_hit",
            exit_timestamp="2026-04-15T16:00:00",
            pnl_pct=1.15, duration_candles=8,
            mfe_pct=1.3, mae_pct=-0.2,
        )

        all_trades = get_trades(db_path)
        assert len(all_trades) == 2

        closed = get_trades(db_path, closed_only=True)
        assert len(closed) == 1
        assert closed[0]["id"] == t1


# ---------------------------------------------------------------------------
# 10. Empty DB edge cases
# ---------------------------------------------------------------------------

class TestEmptyDB:
    def test_get_decisions_empty(self, db_path):
        assert get_decisions(db_path) == []

    def test_get_trades_empty(self, db_path):
        assert get_trades(db_path) == []

    def test_get_open_trades_empty(self, db_path):
        assert get_open_trades(db_path) == []
