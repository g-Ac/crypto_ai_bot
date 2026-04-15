"""Tests for backtest/report.py — report builder."""
import pytest

from backtest.metrics import compute_metrics
from backtest.report import _build_funnel, _verdict, build_report
from defensive.enums import (
    Direction,
    ExitReason,
    Outcome,
    Regime,
    Session,
    Strategy,
)
from defensive.models import BacktestRunMeta, ClosedTrade, TradeDecision


def _trade(pnl_pct: float = 0.5, **kwargs) -> ClosedTrade:
    defaults = dict(
        symbol="BTCUSDT",
        strategy=Strategy.CFER_BASELINE,
        direction=Direction.LONG,
        entry_price=100.0,
        exit_price=100.5,
        position_size_usd=1000.0,
        pnl_pct=pnl_pct,
        pnl_usd=pnl_pct * 10,
        exit_reason=ExitReason.TP1,
        duration_candles=5,
        regime=Regime.RANGING,
        session=Session.US,
    )
    defaults.update(kwargs)
    return ClosedTrade(**defaults)


def _decision(outcome: Outcome = Outcome.NO_COMPRESSION) -> TradeDecision:
    return TradeDecision(outcome=outcome, regime=Regime.RANGING)


class TestVerdict:
    def test_pass(self):
        trades = [_trade(pnl_pct=2.0)] * 8 + [_trade(pnl_pct=-1.0)] * 5
        m = compute_metrics(trades)
        v = _verdict(m)
        assert "PASS" in v

    def test_fail(self):
        trades = [_trade(pnl_pct=-1.0)] * 10
        m = compute_metrics(trades)
        v = _verdict(m)
        assert "FAIL" in v

    def test_review_small_sample(self):
        trades = [_trade(pnl_pct=1.0)] * 3
        m = compute_metrics(trades)
        v = _verdict(m)
        assert "REVIEW" in v


class TestBuildFunnel:
    def test_funnel_counts(self):
        decisions = [
            _decision(Outcome.TRADE),
            _decision(Outcome.NO_COMPRESSION),
            _decision(Outcome.REGIME_BLOCKED),
            _decision(Outcome.NO_COMPRESSION),
        ]
        funnel = _build_funnel(decisions)
        assert funnel.total_cycles == 4
        assert funnel.trades_opened == 1
        assert funnel.blocked_by["no_compression"] == 2
        assert funnel.blocked_by["regime_blocked"] == 1

    def test_conversion_rate(self):
        decisions = [_decision(Outcome.TRADE)] * 2 + [_decision(Outcome.NO_BREAKOUT)] * 8
        funnel = _build_funnel(decisions)
        assert funnel.conversion_rate == pytest.approx(0.2, abs=0.01)


class TestBuildReport:
    def test_report_has_all_sections(self):
        meta = BacktestRunMeta(
            run_id="test123",
            strategy=Strategy.CFER_BASELINE,
            period_start="2025-01-01",
            period_end="2025-06-01",
            candles_total=1000,
            config_hash="abc12345",
            param_version="v0.1",
        )
        trades = [
            _trade(pnl_pct=1.5, exit_reason=ExitReason.TP1),
            _trade(pnl_pct=2.0, exit_reason=ExitReason.TP2),
            _trade(pnl_pct=-0.8, exit_reason=ExitReason.STOP_LOSS),
        ]
        decisions = [
            _decision(Outcome.TRADE),
            _decision(Outcome.TRADE),
            _decision(Outcome.TRADE),
            _decision(Outcome.NO_COMPRESSION),
            _decision(Outcome.REGIME_BLOCKED),
        ]

        report = build_report(meta, trades, decisions)

        assert "## 1. Resumo Executivo" in report
        assert "## 3. Breakdowns" in report
        assert "## 4. Distribuicao de Trades" in report
        assert "## 6. Funil de Decisao" in report
        assert "## 7. Metadados" in report
        assert "test123" in report

    def test_report_empty_trades(self):
        meta = BacktestRunMeta(run_id="empty", strategy=Strategy.CFER_BASELINE)
        report = build_report(meta, [], [])
        assert "Resumo Executivo" in report
        assert "0" in report

    def test_report_with_comparison(self):
        meta = BacktestRunMeta(run_id="cmp", strategy=Strategy.CFER_BASELINE)
        trades = [_trade(pnl_pct=1.0)]
        ravr_trades = [_trade(pnl_pct=0.5, strategy=Strategy.RAVR)]

        report = build_report(
            meta, trades, [_decision(Outcome.TRADE)],
            compare_trades={"RAVR": ravr_trades},
        )
        assert "## 2. Comparativo" in report
        assert "RAVR" in report
