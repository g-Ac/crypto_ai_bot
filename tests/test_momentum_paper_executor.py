"""Tests for momentum paper executor."""
import json
import os
import sqlite3
import tempfile
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from momentum.config import MomentumConfig, MomentumOutcome, MomentumDirection
from momentum.momentum_trader import MomentumSignal


@pytest.fixture
def state_file(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    # Remove so load_state creates fresh
    os.unlink(path)
    monkeypatch.setattr("momentum.paper_executor.MOMENTUM_STATE_FILE", path)
    monkeypatch.setattr("momentum.paper_executor.MOMENTUM_INITIAL_CAPITAL", 1000.0)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("database.DB_FILE", path)
    import database as db
    db.init_db()
    yield path
    os.unlink(path)


def _make_trade_signal(symbol="BTCUSDT", direction="LONG",
                       entry=85000.0, sl=84500.0,
                       tp1=85800.0, tp2=86500.0):
    return MomentumSignal(
        outcome=MomentumOutcome.TRADE,
        direction=MomentumDirection(direction),
        entry_price=entry,
        sl_price=sl,
        tp1_price=tp1,
        tp2_price=tp2,
        ema_fast_value=85100.0,
        ema_slow_value=84800.0,
        ema_gap_pct=0.35,
        retracement_pct=42.5,
        impulse_start_price=84000.0,
        impulse_end_price=86000.0,
        symbol=symbol,
        regime="TRENDING",
        timestamp="2026-04-15T12:00:00",
        param_version="momentum-pullback-v1.1",
    )


def _make_reject_signal(symbol="BTCUSDT", outcome=MomentumOutcome.NO_TREND):
    return MomentumSignal(
        outcome=outcome,
        direction=MomentumDirection.NEUTRAL,
        symbol=symbol,
        regime="TRENDING",
        timestamp="2026-04-15T12:00:00",
        param_version="momentum-pullback-v1.1",
    )


class TestOpenPosition:
    def test_opens_position_on_trade_signal(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position

        state = load_state()
        signal = _make_trade_signal()
        msgs = open_position(state, signal, "20260415_120000")
        save_state(state)

        assert "BTCUSDT" in state["positions"]
        pos = state["positions"]["BTCUSDT"]
        assert pos["direction"] == "LONG"
        assert pos["entry_price"] == 85000.0
        assert pos["sl_price"] == 84500.0
        assert pos["position_size_usd"] > 0
        assert len(msgs) > 0

    def test_respects_max_positions(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position

        state = load_state()
        signal1 = _make_trade_signal(symbol="BTCUSDT")
        open_position(state, signal1, "cycle1")

        signal2 = _make_trade_signal(symbol="ETHUSDT", entry=3200.0,
                                     sl=3150.0, tp1=3280.0, tp2=3350.0)
        msgs = open_position(state, signal2, "cycle1")
        save_state(state)

        assert "ETHUSDT" not in state["positions"]
        assert len(state["positions"]) == 1

    def test_skips_duplicate_symbol(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")
        msgs = open_position(state, signal, "cycle2")
        save_state(state)

        assert len(state["positions"]) == 1

    def test_position_size_within_capital(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, open_position

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")

        pos = state["positions"]["BTCUSDT"]
        assert pos["position_size_usd"] <= state["capital"]


class TestStateManagement:
    def test_load_fresh_state(self, state_file):
        from momentum.paper_executor import load_state

        state = load_state()
        assert state["capital"] == 1000.0
        assert state["positions"] == {}
        assert state["cooldowns"] == {}
        assert state["total_trades"] == 0
        assert state["wins"] == 0
        assert state["losses"] == 0
        assert state["total_pnl_usd"] == 0.0
        assert state["hwm"] == 1000.0

    def test_save_and_reload(self, state_file):
        from momentum.paper_executor import load_state, save_state

        state = load_state()
        state["capital"] = 1050.0
        state["hwm"] = 1050.0
        state["total_trades"] = 3
        save_state(state)

        reloaded = load_state()
        assert reloaded["capital"] == 1050.0
        assert reloaded["hwm"] == 1050.0
        assert reloaded["total_trades"] == 3

    def test_save_is_atomic(self, state_file):
        from momentum.paper_executor import load_state, save_state

        state = load_state()
        save_state(state)

        # File exists and is valid JSON
        with open(state_file) as f:
            data = json.load(f)
        assert data["capital"] == 1000.0

    def test_get_status_no_positions(self, state_file):
        from momentum.paper_executor import load_state, get_momentum_status

        load_state()  # ensure state file exists
        status = get_momentum_status()
        assert "MOMENTUM" in status
        assert "$1000.00" in status
        assert "0W" in status


class TestClosePosition:
    def test_sl_hit_closes_position(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()  # LONG @ 85000, SL 84500
        open_position(state, signal, "cycle1")

        # Simulate candle that hits SL
        candle = {"high": 85100.0, "low": 84400.0, "close": 84450.0}
        msgs = manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert "BTCUSDT" not in state["positions"]
        assert state["losses"] == 1
        assert state["total_trades"] == 1
        assert state["capital"] < 1000.0
        assert len(msgs) > 0

    def test_tp1_hit_closes_position(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()  # LONG @ 85000, TP1 85800
        open_position(state, signal, "cycle1")

        candle = {"high": 85900.0, "low": 85000.0, "close": 85850.0}
        msgs = manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert "BTCUSDT" not in state["positions"]
        assert state["wins"] == 1
        assert state["capital"] > 1000.0

    def test_timeout_closes_position(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")

        # Simulate 16 candles elapsed (timeout)
        state["positions"]["BTCUSDT"]["candles_elapsed"] = 16

        candle = {"high": 85100.0, "low": 84900.0, "close": 85050.0}
        msgs = manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert "BTCUSDT" not in state["positions"]
        assert state["total_trades"] == 1

    def test_no_exit_when_no_hit(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")

        # Normal candle, no SL/TP hit
        candle = {"high": 85200.0, "low": 84900.0, "close": 85100.0}
        msgs = manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert "BTCUSDT" in state["positions"]
        assert state["total_trades"] == 0
        assert state["positions"]["BTCUSDT"]["candles_elapsed"] == 1

    def test_hwm_updates_on_profit(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")

        candle = {"high": 85900.0, "low": 85000.0, "close": 85850.0}
        manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert state["hwm"] >= state["capital"]
        assert state["hwm"] > 1000.0


class TestExecutionCost:
    """Fee: gross -> net. Capital bruto governa o sizing v1.1 (intocado)."""

    def test_fee_acumula_sem_tocar_capital_bruto(self, state_file, tmp_db):
        from momentum.paper_executor import (
            load_state, open_position, manage_positions,
        )
        from config import (
            MOMENTUM_PAPER_ENTRY_FEE_RATE, MOMENTUM_PAPER_EXIT_FEE_RATE,
        )

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")
        size = state["positions"]["BTCUSDT"]["position_size_usd"]

        candle = {"high": 85900.0, "low": 85000.0, "close": 85850.0}  # bate TP1
        manage_positions(state, {"BTCUSDT": candle})

        # Capital BRUTO = inicial + pnl bruto; a fee NAO o reduz (sizing intocado)
        assert state["capital"] == pytest.approx(1000.0 + state["total_pnl_usd"])

        # Fee acumulada a parte = notional * (entry+exit)/100, independe do pnl
        expected_fee = size * (
            MOMENTUM_PAPER_ENTRY_FEE_RATE + MOMENTUM_PAPER_EXIT_FEE_RATE
        ) / 100.0
        assert state["total_fee_usd"] == pytest.approx(expected_fee)
        assert state["total_fee_usd"] > 0

        # Net acumulado = bruto - fee
        assert state["total_net_pnl_usd"] == pytest.approx(
            state["total_pnl_usd"] - state["total_fee_usd"]
        )

    def test_close_grava_campos_net_no_db(self, state_file, tmp_db):
        from momentum.paper_executor import (
            load_state, open_position, manage_positions,
        )

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")
        candle = {"high": 85900.0, "low": 85000.0, "close": 85850.0}
        manage_positions(state, {"BTCUSDT": candle})

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM momentum_trades").fetchone()
        conn.close()

        assert row["total_fee_usd"] is not None and row["total_fee_usd"] > 0
        assert row["gross_pnl_usd"] is not None
        assert row["net_pnl_usd"] is not None
        assert row["net_pnl_usd"] == pytest.approx(
            row["gross_pnl_usd"] - row["total_fee_usd"], abs=0.02
        )
        assert row["fee_model"] is not None
        assert row["entry_liquidity_assumption"] is not None
        # Campo legado (bruto) preservado e coerente com gross
        assert row["pnl_usd"] == pytest.approx(row["gross_pnl_usd"], abs=0.02)

    def test_status_mostra_capital_liquido(self, state_file, tmp_db):
        from momentum.paper_executor import (
            load_state, save_state, open_position, manage_positions,
            get_momentum_status,
        )

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")
        candle = {"high": 85900.0, "low": 85000.0, "close": 85850.0}
        manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        status = get_momentum_status()
        assert "Net" in status


class TestProcessCycle:
    def test_logs_reject_decision(self, state_file, tmp_db):
        from momentum.paper_executor import process_momentum_cycle

        def mock_candle_fn(symbol, interval, limit):
            n = 100
            data = {
                "time": pd.date_range("2026-01-01", periods=n, freq="15min"),
                "open": np.full(n, 85000.0),
                "high": np.full(n, 85100.0),
                "low": np.full(n, 84900.0),
                "close": np.full(n, 85000.0),
                "volume": np.full(n, 100.0),
            }
            return pd.DataFrame(data)

        def mock_regime_fn(symbol):
            return {"regime_label": "TRENDING"}

        msgs = process_momentum_cycle(
            symbols=["BTCUSDT"],
            open_new=True,
            candle_fn=mock_candle_fn,
            regime_fn=mock_regime_fn,
        )

        # Should have logged a decision (rejection) to the DB
        import sqlite3
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM momentum_decisions").fetchall()
        conn.close()
        assert len(rows) >= 1
        # The flat candles should produce a reject (no trend)
        assert rows[0]["outcome"] != "trade" or rows[0]["blocked_by"] != "none"

    def test_logs_adx_slope_and_di_spread_from_regime_data(self, state_file, tmp_db):
        """Regime Gate v2 fields (adx_slope_3, di_spread) must be persisted in momentum_decisions."""
        from momentum.paper_executor import process_momentum_cycle

        def mock_candle_fn(symbol, interval, limit):
            n = 100
            data = {
                "time": pd.date_range("2026-01-01", periods=n, freq="15min"),
                "open": np.full(n, 85000.0),
                "high": np.full(n, 85100.0),
                "low": np.full(n, 84900.0),
                "close": np.full(n, 85000.0),
                "volume": np.full(n, 100.0),
            }
            return pd.DataFrame(data)

        def mock_regime_fn(symbol):
            return {
                "regime_label": "TRENDING",
                "adx_slope_3": 5.2,
                "di_spread": 18.5,
            }

        process_momentum_cycle(
            symbols=["BTCUSDT"],
            open_new=True,
            candle_fn=mock_candle_fn,
            regime_fn=mock_regime_fn,
        )

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT adx_slope_3, di_spread FROM momentum_decisions LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["adx_slope_3"] == 5.2
        assert row["di_spread"] == 18.5

    def test_logs_regime_v2_fields_default_zero_when_missing(self, state_file, tmp_db):
        """If regime_fn returns dict without v2 fields, persist zeros (backward compat)."""
        from momentum.paper_executor import process_momentum_cycle

        def mock_candle_fn(symbol, interval, limit):
            n = 100
            data = {
                "time": pd.date_range("2026-01-01", periods=n, freq="15min"),
                "open": np.full(n, 85000.0),
                "high": np.full(n, 85100.0),
                "low": np.full(n, 84900.0),
                "close": np.full(n, 85000.0),
                "volume": np.full(n, 100.0),
            }
            return pd.DataFrame(data)

        def mock_regime_fn(symbol):
            return {"regime_label": "TRENDING"}

        process_momentum_cycle(
            symbols=["BTCUSDT"],
            open_new=True,
            candle_fn=mock_candle_fn,
            regime_fn=mock_regime_fn,
        )

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT adx_slope_3, di_spread FROM momentum_decisions LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["adx_slope_3"] == 0.0
        assert row["di_spread"] == 0.0

    def test_same_15m_candle_does_not_duplicate_decision_log(self, state_file, tmp_db):
        from momentum.paper_executor import process_momentum_cycle

        def mock_candle_fn(symbol, interval, limit):
            n = 100
            data = {
                "time": pd.date_range("2026-01-01", periods=n, freq="15min"),
                "open": np.full(n, 85000.0),
                "high": np.full(n, 85100.0),
                "low": np.full(n, 84900.0),
                "close": np.full(n, 85000.0),
                "volume": np.full(n, 100.0),
            }
            return pd.DataFrame(data)

        def mock_regime_fn(symbol):
            return {"regime_label": "TRENDING"}

        process_momentum_cycle(
            symbols=["BTCUSDT"],
            open_new=True,
            candle_fn=mock_candle_fn,
            regime_fn=mock_regime_fn,
        )
        process_momentum_cycle(
            symbols=["BTCUSDT"],
            open_new=True,
            candle_fn=mock_candle_fn,
            regime_fn=mock_regime_fn,
        )

        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT COUNT(*) FROM momentum_decisions").fetchone()[0]
        conn.close()
        assert rows == 1


class TestCandleTracking15m:
    """candles_elapsed must only increment on new 15m candles, not every 5m cycle."""

    def test_same_candle_does_not_increment(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")

        candle = {"high": 85200.0, "low": 84900.0, "close": 85100.0}
        # First call: new candle → should increment
        manage_positions(state, {"BTCUSDT": candle}, new_candle_symbols={"BTCUSDT"})
        assert state["positions"]["BTCUSDT"]["candles_elapsed"] == 1

        # Second call: same candle (5m later) → should NOT increment
        manage_positions(state, {"BTCUSDT": candle}, new_candle_symbols=set())
        assert state["positions"]["BTCUSDT"]["candles_elapsed"] == 1

        # Third call: still same candle → still 1
        manage_positions(state, {"BTCUSDT": candle}, new_candle_symbols=set())
        assert state["positions"]["BTCUSDT"]["candles_elapsed"] == 1

        # Fourth call: new candle arrives → increments to 2
        manage_positions(state, {"BTCUSDT": candle}, new_candle_symbols={"BTCUSDT"})
        assert state["positions"]["BTCUSDT"]["candles_elapsed"] == 2
        save_state(state)


class TestCooldown:
    def test_cooldown_blocks_entry(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position

        state = load_state()
        # Manually set cooldown for BTCUSDT
        state["cooldowns"] = {"BTCUSDT": 2}

        signal = _make_trade_signal(symbol="BTCUSDT")
        msgs = open_position(state, signal, "cycle1")
        save_state(state)

        assert "BTCUSDT" not in state["positions"]
        assert msgs == []

    def test_cooldown_ticks_and_expires(self, state_file):
        from momentum.paper_executor import load_state, save_state, _tick_cooldowns

        state = load_state()
        state["cooldowns"] = {"BTCUSDT": 2, "ETHUSDT": 1}

        _tick_cooldowns(state)
        # BTCUSDT: 2 → 1, ETHUSDT: 1 → expired
        assert state["cooldowns"] == {"BTCUSDT": 1}

        _tick_cooldowns(state)
        # BTCUSDT: 1 → expired
        assert state["cooldowns"] == {}
        save_state(state)


class TestShortDirection:
    def test_short_position_sl_hit(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        # SHORT @ 85000, SL 85500 (above entry), TP1 84200, TP2 83500
        signal = _make_trade_signal(
            direction="SHORT", entry=85000.0, sl=85500.0,
            tp1=84200.0, tp2=83500.0,
        )
        open_position(state, signal, "cycle1")

        assert "BTCUSDT" in state["positions"]
        assert state["positions"]["BTCUSDT"]["direction"] == "SHORT"

        # Candle hits SL (high goes above 85500)
        candle = {"high": 85600.0, "low": 84900.0, "close": 85550.0}
        msgs = manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert "BTCUSDT" not in state["positions"]
        assert state["losses"] == 1
        assert state["capital"] < 1000.0

    def test_short_position_tp1_hit(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal(
            direction="SHORT", entry=85000.0, sl=85500.0,
            tp1=84200.0, tp2=83500.0,
        )
        open_position(state, signal, "cycle1")

        # Candle hits TP1 (low goes below 84200)
        candle = {"high": 85000.0, "low": 84100.0, "close": 84150.0}
        msgs = manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert "BTCUSDT" not in state["positions"]
        assert state["wins"] == 1
        assert state["capital"] > 1000.0
