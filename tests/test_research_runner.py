"""Tests for momentum/research_runner.py.

All tests use injectable candle_fn / regime_fn — no network calls.
check_exit is tested exhaustively as a pure function.
Integration tests use SQLite in tmp_path.
"""

import numpy as np
import pandas as pd
import pytest

from momentum.config import MomentumConfig
from momentum.research_db import (
    ensure_tables,
    get_decisions,
    get_open_trades,
    get_trades,
)
from momentum.research_runner import (
    check_exit,
    run_research_cycle,
    _compute_duration,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test_research.db"
    ensure_tables(path)
    return path


def _build_trend_pullback_candles(
    direction: str = "LONG",
    confirm: bool = True,
    n_trend: int = 55,
    n_pullback: int = 10,
) -> pd.DataFrame:
    """Minimal candle builder that produces a TRADE signal.

    Same logic as test_momentum_trader.py helper: uptrend with mid-dip
    to create detectable swing, pullback, and confirmation candle.
    """
    data = {"high": [], "low": [], "close": [], "timestamp": []}

    if direction == "LONG":
        base, slope = 100.0, 0.5
        mid = n_trend // 2
        for i in range(n_trend):
            c = base + slope * i
            if i == mid:
                c -= 6.0
            data["close"].append(c)
            data["high"].append(c + 0.5)
            data["low"].append(c - 0.5)
            data["timestamp"].append(f"2026-04-15T{10 + i // 4:02d}:{(i % 4) * 15:02d}:00")

        peak = base + slope * (n_trend - 1)
        impulse_range = peak - base
        pullback_close = peak - 0.50 * impulse_range

        for i in range(n_pullback):
            frac = (i + 1) / n_pullback
            c = peak - (peak - pullback_close) * frac
            data["close"].append(c)
            data["high"].append(c + 0.5)
            data["low"].append(c - 0.5)
            idx = n_trend + i
            data["timestamp"].append(f"2026-04-16T{idx // 4:02d}:{(idx % 4) * 15:02d}:00")

        if confirm:
            ema20_approx = peak - 0.25 * impulse_range
            c = ema20_approx + 1.0
            data["close"].append(c)
            data["high"].append(c + 0.5)
            data["low"].append(c - 0.5)
            idx = n_trend + n_pullback
            data["timestamp"].append(f"2026-04-16T{idx // 4:02d}:{(idx % 4) * 15:02d}:00")

    else:  # SHORT
        base, slope = 120.0, -0.5
        mid = n_trend // 2
        for i in range(n_trend):
            c = base + slope * i
            if i == mid:
                c += 6.0
            data["close"].append(c)
            data["high"].append(c + 0.5)
            data["low"].append(c - 0.5)
            data["timestamp"].append(f"2026-04-15T{10 + i // 4:02d}:{(i % 4) * 15:02d}:00")

        valley = base + slope * (n_trend - 1)
        impulse_range = base - valley
        pullback_close = valley + 0.50 * impulse_range

        for i in range(n_pullback):
            frac = (i + 1) / n_pullback
            c = valley + (pullback_close - valley) * frac
            data["close"].append(c)
            data["high"].append(c + 0.5)
            data["low"].append(c - 0.5)
            idx = n_trend + i
            data["timestamp"].append(f"2026-04-16T{idx // 4:02d}:{(idx % 4) * 15:02d}:00")

        if confirm:
            ema20_approx = valley + 0.25 * impulse_range
            c = ema20_approx - 1.0
            data["close"].append(c)
            data["high"].append(c + 0.5)
            data["low"].append(c - 0.5)
            idx = n_trend + n_pullback
            data["timestamp"].append(f"2026-04-16T{idx // 4:02d}:{(idx % 4) * 15:02d}:00")

    return pd.DataFrame(data)


def _flat_candles(price: float = 100.0, n: int = 70) -> pd.DataFrame:
    """Flat market — produces NO_TREND or similar rejection."""
    return pd.DataFrame({
        "high": [price + 0.1] * n,
        "low": [price - 0.1] * n,
        "close": [price] * n,
        "timestamp": [f"2026-04-15T12:{i:02d}:00" for i in range(n)],
    })


# ---------------------------------------------------------------------------
# 1. check_exit — SL
# ---------------------------------------------------------------------------

class TestCheckExitSL:
    def test_sl_hit_long(self):
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=101.0, candle_low=94.0, candle_close=94.5,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=3, timeout_candles=16,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "sl_hit"
        assert r["exit_price"] == pytest.approx(95.0)
        assert r["pnl_pct"] == pytest.approx(-5.0)
        assert r["lost_pullback_extreme"] is True

    def test_sl_hit_short(self):
        r = check_exit(
            direction="SHORT", entry_price=100.0,
            sl_price=105.0, tp1_price=90.0, tp2_price=85.0,
            candle_high=106.0, candle_low=99.0, candle_close=105.5,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=3, timeout_candles=16,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "sl_hit"
        assert r["exit_price"] == pytest.approx(105.0)
        assert r["pnl_pct"] == pytest.approx(-5.0)
        assert r["lost_pullback_extreme"] is True

    def test_sl_exact_boundary_long(self):
        """Low exactly at SL → sl_hit (<=, not <)."""
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=101.0, candle_low=95.0, candle_close=96.0,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=3, timeout_candles=16,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "sl_hit"


# ---------------------------------------------------------------------------
# 2. check_exit — TP1
# ---------------------------------------------------------------------------

class TestCheckExitTP1:
    def test_tp1_hit_long(self):
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=111.0, candle_low=99.0, candle_close=110.5,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=3, timeout_candles=16,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "tp1_hit"
        assert r["exit_price"] == pytest.approx(110.0)
        assert r["pnl_pct"] == pytest.approx(10.0)
        assert r["retested_impulse_end"] is True
        assert r["lost_pullback_extreme"] is False

    def test_tp1_hit_short(self):
        r = check_exit(
            direction="SHORT", entry_price=100.0,
            sl_price=105.0, tp1_price=90.0, tp2_price=85.0,
            candle_high=101.0, candle_low=89.0, candle_close=89.5,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=3, timeout_candles=16,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "tp1_hit"
        assert r["exit_price"] == pytest.approx(90.0)
        assert r["pnl_pct"] == pytest.approx(10.0)
        assert r["retested_impulse_end"] is True


# ---------------------------------------------------------------------------
# 3. check_exit — TP2
# ---------------------------------------------------------------------------

class TestCheckExitTP2:
    def test_tp2_hit_long(self):
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=116.0, candle_low=109.0, candle_close=115.5,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=3, timeout_candles=16,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "tp2_hit"
        assert r["exit_price"] == pytest.approx(115.0)
        assert r["pnl_pct"] == pytest.approx(15.0)
        assert r["retested_impulse_end"] is True  # TP2 > TP1

    def test_tp2_hit_short(self):
        r = check_exit(
            direction="SHORT", entry_price=100.0,
            sl_price=105.0, tp1_price=90.0, tp2_price=85.0,
            candle_high=91.0, candle_low=84.0, candle_close=84.5,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=3, timeout_candles=16,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "tp2_hit"
        assert r["pnl_pct"] == pytest.approx(15.0)
        assert r["retested_impulse_end"] is True


# ---------------------------------------------------------------------------
# 4. check_exit — timeout
# ---------------------------------------------------------------------------

class TestCheckExitTimeout:
    def test_timeout_long_profit(self):
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=103.0, candle_low=99.0, candle_close=102.0,
            current_mfe=2.5, current_mae=-1.5,
            duration_candles=16, timeout_candles=16,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "timeout"
        assert r["exit_price"] == pytest.approx(102.0)
        assert r["pnl_pct"] == pytest.approx(2.0)
        assert r["retested_impulse_end"] is False
        assert r["lost_pullback_extreme"] is False

    def test_timeout_short_loss(self):
        r = check_exit(
            direction="SHORT", entry_price=100.0,
            sl_price=105.0, tp1_price=90.0, tp2_price=85.0,
            candle_high=103.0, candle_low=101.0, candle_close=102.0,
            current_mfe=0.5, current_mae=-2.0,
            duration_candles=20, timeout_candles=16,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "timeout"
        assert r["pnl_pct"] == pytest.approx(-2.0)

    def test_not_yet_timeout(self):
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=103.0, candle_low=99.0, candle_close=102.0,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=15, timeout_candles=16,
        )
        assert r["closed"] is False


# ---------------------------------------------------------------------------
# 5. check_exit — priority
# ---------------------------------------------------------------------------

class TestCheckExitPriority:
    def test_sl_beats_tp_same_candle(self):
        """Candle spans both SL and TP1 → SL wins (conservative)."""
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=111.0, candle_low=94.0, candle_close=96.0,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=3, timeout_candles=16,
        )
        assert r["exit_reason"] == "sl_hit"
        assert r["retested_impulse_end"] is True  # TP1 also touched

    def test_tp2_beats_tp1(self):
        """Candle reaches both TP1 and TP2 → TP2 wins."""
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=116.0, candle_low=108.0, candle_close=115.0,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=3, timeout_candles=16,
        )
        assert r["exit_reason"] == "tp2_hit"

    def test_tp1_beats_timeout(self):
        """TP1 hit on timeout candle → TP1 wins."""
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=111.0, candle_low=99.0, candle_close=110.5,
            current_mfe=0.0, current_mae=0.0,
            duration_candles=16, timeout_candles=16,
        )
        assert r["exit_reason"] == "tp1_hit"


# ---------------------------------------------------------------------------
# 6. check_exit — MFE / MAE
# ---------------------------------------------------------------------------

class TestCheckExitMfeMae:
    def test_mfe_mae_long_no_exit(self):
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=103.0, candle_low=98.0, candle_close=102.0,
            current_mfe=1.0, current_mae=-1.0,
            duration_candles=3, timeout_candles=16,
        )
        assert r["closed"] is False
        assert r["mfe_pct"] == pytest.approx(3.0)  # max(1.0, (103-100)/100*100)
        assert r["mae_pct"] == pytest.approx(-2.0)  # min(-1.0, (98-100)/100*100)

    def test_mfe_mae_short_no_exit(self):
        r = check_exit(
            direction="SHORT", entry_price=100.0,
            sl_price=105.0, tp1_price=90.0, tp2_price=85.0,
            candle_high=101.0, candle_low=96.0, candle_close=97.0,
            current_mfe=2.0, current_mae=-0.5,
            duration_candles=3, timeout_candles=16,
        )
        assert r["closed"] is False
        assert r["mfe_pct"] == pytest.approx(4.0)  # max(2.0, (100-96)/100*100)
        assert r["mae_pct"] == pytest.approx(-1.0)  # min(-0.5, (100-101)/100*100)

    def test_mfe_preserved_from_prior_candles(self):
        """Prior MFE was higher than current candle → keep prior."""
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=101.0, candle_low=99.5, candle_close=100.5,
            current_mfe=5.0, current_mae=-0.3,
            duration_candles=3, timeout_candles=16,
        )
        assert r["mfe_pct"] == pytest.approx(5.0)  # preserved
        assert r["mae_pct"] == pytest.approx(-0.5)  # updated: (99.5-100)/100 = -0.5

    def test_mfe_mae_on_sl_exit(self):
        """MFE/MAE include the exit candle."""
        r = check_exit(
            direction="LONG", entry_price=100.0,
            sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
            candle_high=102.0, candle_low=94.0, candle_close=94.5,
            current_mfe=3.0, current_mae=-1.0,
            duration_candles=5, timeout_candles=16,
        )
        assert r["closed"] is True
        assert r["mfe_pct"] == pytest.approx(3.0)  # prior was higher
        assert r["mae_pct"] == pytest.approx(-6.0)  # (94-100)/100*100 = -6


# ---------------------------------------------------------------------------
# 7. _compute_duration
# ---------------------------------------------------------------------------

class TestComputeDuration:
    def test_exact_candles(self):
        assert _compute_duration("2026-04-15T12:00:00", "2026-04-15T13:00:00") == 4

    def test_zero_duration(self):
        assert _compute_duration("2026-04-15T12:00:00", "2026-04-15T12:00:00") == 0

    def test_partial_candle(self):
        # 20 minutes = 1 full 15m candle (int truncation)
        assert _compute_duration("2026-04-15T12:00:00", "2026-04-15T12:20:00") == 1

    def test_bad_timestamp(self):
        assert _compute_duration("not-a-time", "also-bad") == 0


# ---------------------------------------------------------------------------
# 8. Integration — cycle records decision
# ---------------------------------------------------------------------------

class TestCycleDecisions:
    def test_records_decision_for_each_symbol(self, db_path):
        calls = {}

        def candle_fn(symbol, interval, limit):
            calls[symbol] = True
            return _flat_candles()

        def regime_fn(symbol):
            return {"regime_label": "TRENDING"}

        config = MomentumConfig()
        result = run_research_cycle(
            ["BTCUSDT", "ETHUSDT"], db_path, config,
            candle_fn=candle_fn, regime_fn=regime_fn,
        )

        assert result["decisions_recorded"] == 2
        decisions = get_decisions(db_path)
        assert len(decisions) == 2
        symbols = {d["symbol"] for d in decisions}
        assert symbols == {"BTCUSDT", "ETHUSDT"}

    def test_rejected_signal_no_trade(self, db_path):
        """Flat market → rejection → decision recorded, no trade."""
        result = run_research_cycle(
            ["BTCUSDT"], db_path, MomentumConfig(),
            candle_fn=lambda s, i, l: _flat_candles(),
            regime_fn=lambda s: {"regime_label": "TRENDING"},
        )

        assert result["decisions_recorded"] == 1
        assert result["trades_opened"] == 0
        assert get_trades(db_path) == []


# ---------------------------------------------------------------------------
# 9. Integration — cycle opens trade
# ---------------------------------------------------------------------------

class TestCycleOpensTrade:
    def test_trade_signal_opens_position(self, db_path):
        result = run_research_cycle(
            ["BTCUSDT"], db_path, MomentumConfig(),
            candle_fn=lambda s, i, l: _build_trend_pullback_candles("LONG"),
            regime_fn=lambda s: {"regime_label": "TRENDING"},
        )

        assert result["trades_opened"] == 1
        trades = get_open_trades(db_path)
        assert len(trades) == 1
        assert trades[0]["symbol"] == "BTCUSDT"
        assert trades[0]["direction"] == "LONG"
        assert trades[0]["entry_price"] > 0
        assert trades[0]["sl_price"] > 0
        assert trades[0]["tp1_price"] > trades[0]["entry_price"]

    def test_no_duplicate_position(self, db_path):
        """Two cycles with TRADE signal → only one open position."""
        candle_fn = lambda s, i, l: _build_trend_pullback_candles("LONG")
        regime_fn = lambda s: {"regime_label": "TRENDING"}
        config = MomentumConfig()

        run_research_cycle(["BTCUSDT"], db_path, config,
                           candle_fn=candle_fn, regime_fn=regime_fn)
        run_research_cycle(["BTCUSDT"], db_path, config,
                           candle_fn=candle_fn, regime_fn=regime_fn)

        assert len(get_open_trades(db_path)) == 1
        # But 2 decisions recorded
        assert len(get_decisions(db_path)) == 2


# ---------------------------------------------------------------------------
# 10. Integration — position management: SL / TP1 / TP2 / timeout
# ---------------------------------------------------------------------------

class TestCyclePositionManagement:
    """Open a LONG trade on cycle 1, then manage it on cycle 2."""

    def _open_trade(self, db_path) -> dict:
        """Cycle 1: open a LONG position. Returns the trade row."""
        run_research_cycle(
            ["BTCUSDT"], db_path, MomentumConfig(),
            candle_fn=lambda s, i, l: _build_trend_pullback_candles("LONG"),
            regime_fn=lambda s: {"regime_label": "TRENDING"},
        )
        trades = get_open_trades(db_path)
        assert len(trades) == 1
        return trades[0]

    def _candle_fn_with_last(self, high, low, close):
        """Build candle_fn where the last candle has specific H/L/C.

        Timestamps end at 2026-04-16T16:45 (1 candle after trade open)
        so that duration stays well under timeout_candles.
        """
        def fn(symbol, interval, limit):
            n = 70
            base_ts = pd.Timestamp("2026-04-16T16:45:00")
            timestamps = [
                str(base_ts - pd.Timedelta(minutes=15 * (n - 1 - i)))
                for i in range(n)
            ]
            data = {
                "high": [120.0] * (n - 1) + [high],
                "low": [118.0] * (n - 1) + [low],
                "close": [119.0] * (n - 1) + [close],
                "timestamp": timestamps,
            }
            return pd.DataFrame(data)
        return fn

    def test_sl_hit_closes_trade(self, db_path):
        trade = self._open_trade(db_path)
        sl = trade["sl_price"]

        result = run_research_cycle(
            ["BTCUSDT"], db_path, MomentumConfig(),
            candle_fn=self._candle_fn_with_last(
                high=trade["entry_price"] + 1,
                low=sl - 1,
                close=sl,
            ),
            regime_fn=lambda s: {"regime_label": "TRENDING"},
        )

        assert result["trades_closed"] == 1
        closed = get_trades(db_path, closed_only=True)
        assert len(closed) == 1
        assert closed[0]["exit_reason"] == "sl_hit"
        assert closed[0]["pnl_pct"] < 0

    def test_tp1_hit_closes_trade(self, db_path):
        trade = self._open_trade(db_path)
        tp1 = trade["tp1_price"]

        result = run_research_cycle(
            ["BTCUSDT"], db_path, MomentumConfig(),
            candle_fn=self._candle_fn_with_last(
                high=tp1 + 1,
                low=trade["entry_price"] - 0.5,
                close=tp1,
            ),
            regime_fn=lambda s: {"regime_label": "TRENDING"},
        )

        assert result["trades_closed"] == 1
        closed = get_trades(db_path, closed_only=True)
        assert closed[0]["exit_reason"] == "tp1_hit"
        assert closed[0]["pnl_pct"] > 0
        assert closed[0]["retested_impulse_end"] == 1

    def test_tp2_hit_closes_trade(self, db_path):
        trade = self._open_trade(db_path)
        tp2 = trade["tp2_price"]

        result = run_research_cycle(
            ["BTCUSDT"], db_path, MomentumConfig(),
            candle_fn=self._candle_fn_with_last(
                high=tp2 + 1,
                low=trade["entry_price"] - 0.5,
                close=tp2,
            ),
            regime_fn=lambda s: {"regime_label": "TRENDING"},
        )

        assert result["trades_closed"] == 1
        closed = get_trades(db_path, closed_only=True)
        assert closed[0]["exit_reason"] == "tp2_hit"
        assert closed[0]["pnl_pct"] > 0

    def test_timeout_closes_trade(self, db_path):
        trade = self._open_trade(db_path)
        config = MomentumConfig()

        # Build candles with timestamps far enough for timeout
        hours_needed = (config.timeout_candles * 15) // 60 + 1

        def timeout_candle_fn(symbol, interval, limit):
            n = 70
            data = {
                "high": [trade["entry_price"] + 1] * n,
                "low": [trade["entry_price"] - 1] * n,
                "close": [trade["entry_price"] + 0.5] * n,
                "timestamp": [
                    f"2026-04-18T{i // 4:02d}:{(i % 4) * 15:02d}:00"
                    for i in range(n)
                ],
            }
            return pd.DataFrame(data)

        result = run_research_cycle(
            ["BTCUSDT"], db_path, config,
            candle_fn=timeout_candle_fn,
            regime_fn=lambda s: {"regime_label": "TRENDING"},
        )

        assert result["trades_closed"] == 1
        closed = get_trades(db_path, closed_only=True)
        assert closed[0]["exit_reason"] == "timeout"

    def test_mfe_mae_updated_while_open(self, db_path):
        trade = self._open_trade(db_path)
        entry = trade["entry_price"]

        # Cycle 2: price moves favorably but doesn't hit TP1
        tp1 = trade["tp1_price"]
        favorable_high = entry + (tp1 - entry) * 0.5  # halfway to TP1

        result = run_research_cycle(
            ["BTCUSDT"], db_path, MomentumConfig(),
            candle_fn=self._candle_fn_with_last(
                high=favorable_high,
                low=entry - 0.5,
                close=favorable_high - 0.3,
            ),
            regime_fn=lambda s: {"regime_label": "TRENDING"},
        )

        assert result["trades_closed"] == 0
        open_trades = get_open_trades(db_path)
        assert len(open_trades) == 1
        assert open_trades[0]["mfe_pct"] > 0
        assert open_trades[0]["mae_pct"] <= 0
