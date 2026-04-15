"""Tests for backtest/metrics.py — PF, expectancy, DD, breakdowns."""
import pytest

from backtest.metrics import (
    FunnelStats,
    MetricsSummary,
    breakdown_by_direction,
    breakdown_by_exit_reason,
    breakdown_by_regime,
    breakdown_by_symbol,
    breakdown_by_trap_evidence,
    compute_equity_curve,
    compute_max_drawdown,
    compute_metrics,
)
from defensive.enums import Direction, ExitReason, Regime, Session, Strategy, TrapEvidence
from defensive.models import ClosedTrade


def _trade(pnl_pct: float = 0.5, pnl_usd: float = 5.0, **kwargs) -> ClosedTrade:
    """Helper: create a trade with defaults."""
    defaults = dict(
        symbol="BTCUSDT",
        strategy=Strategy.CFER_BASELINE,
        direction=Direction.LONG,
        entry_price=100.0,
        exit_price=100.5,
        position_size_usd=1000.0,
        pnl_pct=pnl_pct,
        pnl_usd=pnl_usd,
        exit_reason=ExitReason.TP1,
        duration_candles=5,
        regime=Regime.RANGING,
        session=Session.US,
        mae_pct=-0.3,
        mfe_pct=0.8,
    )
    defaults.update(kwargs)
    return ClosedTrade(**defaults)


class TestComputeMetrics:
    def test_empty_trades(self):
        m = compute_metrics([])
        assert m.total_trades == 0
        assert m.profit_factor == 0.0

    def test_all_winners(self):
        trades = [_trade(pnl_pct=1.0, pnl_usd=10)] * 5
        m = compute_metrics(trades)
        assert m.total_trades == 5
        assert m.wins == 5
        assert m.losses == 0
        assert m.win_rate == 1.0
        assert m.profit_factor == float("inf")
        assert m.total_pnl_pct == 5.0

    def test_all_losers(self):
        trades = [_trade(pnl_pct=-1.0, pnl_usd=-10)] * 3
        m = compute_metrics(trades)
        assert m.wins == 0
        assert m.losses == 3
        assert m.win_rate == 0.0
        assert m.profit_factor == 0.0

    def test_mixed_trades(self):
        trades = [
            _trade(pnl_pct=2.0, pnl_usd=20),
            _trade(pnl_pct=1.5, pnl_usd=15),
            _trade(pnl_pct=-1.0, pnl_usd=-10),
        ]
        m = compute_metrics(trades)
        assert m.total_trades == 3
        assert m.wins == 2
        assert m.losses == 1
        assert m.profit_factor == pytest.approx(3.5, abs=0.01)  # 3.5/1.0
        assert m.total_pnl_pct == pytest.approx(2.5, abs=0.01)

    def test_expectancy_formula(self):
        """expectancy = (WR * avg_win) - ((1-WR) * avg_loss)."""
        trades = [
            _trade(pnl_pct=3.0), _trade(pnl_pct=3.0),  # 2 wins
            _trade(pnl_pct=-1.0),                          # 1 loss
        ]
        m = compute_metrics(trades)
        expected = (2 / 3 * 3.0) - (1 / 3 * 1.0)
        assert m.expectancy == pytest.approx(expected, abs=0.01)

    def test_avg_rr_realized(self):
        trades = [
            _trade(pnl_pct=2.0),
            _trade(pnl_pct=-1.0),
        ]
        m = compute_metrics(trades)
        assert m.avg_rr_realized == pytest.approx(2.0, abs=0.01)

    def test_mae_mfe_averaged(self):
        trades = [
            _trade(mae_pct=-0.5, mfe_pct=1.0),
            _trade(mae_pct=-1.0, mfe_pct=2.0),
        ]
        m = compute_metrics(trades)
        assert m.avg_mae_pct == pytest.approx(-0.75, abs=0.01)
        assert m.avg_mfe_pct == pytest.approx(1.5, abs=0.01)


class TestMaxDrawdown:
    def test_no_drawdown(self):
        trades = [_trade(pnl_pct=1.0)] * 5
        dd = compute_max_drawdown(trades)
        assert dd == 0.0

    def test_simple_drawdown(self):
        trades = [
            _trade(pnl_pct=3.0),
            _trade(pnl_pct=-1.0),
            _trade(pnl_pct=-1.0),
            _trade(pnl_pct=2.0),
        ]
        dd = compute_max_drawdown(trades)
        assert dd == pytest.approx(2.0, abs=0.01)

    def test_empty(self):
        assert compute_max_drawdown([]) == 0.0


class TestEquityCurve:
    def test_initial_equity(self):
        curve = compute_equity_curve([], initial_capital=1000.0)
        assert len(curve) == 1
        assert curve[0]["equity"] == 1000.0

    def test_equity_progression(self):
        trades = [
            _trade(pnl_usd=50),
            _trade(pnl_usd=-20),
        ]
        curve = compute_equity_curve(trades, initial_capital=1000.0)
        assert len(curve) == 3
        assert curve[1]["equity"] == 1050.0
        assert curve[2]["equity"] == 1030.0


class TestBreakdowns:
    def test_breakdown_by_symbol(self):
        trades = [
            _trade(symbol="BTCUSDT", pnl_pct=1.0),
            _trade(symbol="ETHUSDT", pnl_pct=-0.5),
            _trade(symbol="BTCUSDT", pnl_pct=0.5),
        ]
        by_sym = breakdown_by_symbol(trades)
        assert "BTCUSDT" in by_sym
        assert "ETHUSDT" in by_sym
        assert by_sym["BTCUSDT"].total_trades == 2
        assert by_sym["ETHUSDT"].total_trades == 1

    def test_breakdown_by_regime(self):
        trades = [
            _trade(regime=Regime.RANGING, pnl_pct=1.0),
            _trade(regime=Regime.WEAK_TREND, pnl_pct=0.5),
        ]
        by_reg = breakdown_by_regime(trades)
        assert len(by_reg) == 2

    def test_breakdown_by_direction(self):
        trades = [
            _trade(direction=Direction.LONG, pnl_pct=1.0),
            _trade(direction=Direction.SHORT, pnl_pct=-0.5),
        ]
        by_dir = breakdown_by_direction(trades)
        assert Direction.LONG.value in by_dir or "Direction.LONG" in by_dir

    def test_breakdown_by_exit_reason(self):
        trades = [
            _trade(exit_reason=ExitReason.TP1),
            _trade(exit_reason=ExitReason.STOP_LOSS, pnl_pct=-1.0),
        ]
        by_exit = breakdown_by_exit_reason(trades)
        assert len(by_exit) == 2

    def test_breakdown_by_trap_evidence(self):
        trades = [
            _trade(trap_evidence=[TrapEvidence.OI_TRAP], pnl_pct=1.0),
            _trade(trap_evidence=[], pnl_pct=-0.5),
        ]
        by_trap = breakdown_by_trap_evidence(trades)
        assert "oi_trap" in by_trap
        assert by_trap["oi_trap"]["with"].total_trades == 1
        assert by_trap["oi_trap"]["without"].total_trades == 1


class TestFunnelStats:
    def test_conversion_rate(self):
        f = FunnelStats(total_cycles=100, trades_opened=5)
        f.compute_conversion()
        assert f.conversion_rate == pytest.approx(0.05, abs=0.001)

    def test_zero_cycles(self):
        f = FunnelStats(total_cycles=0, trades_opened=0)
        f.compute_conversion()
        assert f.conversion_rate == 0.0
