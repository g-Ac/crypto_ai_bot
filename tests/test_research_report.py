"""Tests for momentum/research_report.py.

All tests use a temporary SQLite database seeded with known data.
"""

import pytest

from momentum.research_db import (
    close_trade,
    ensure_tables,
    insert_decision,
    insert_trade,
)
from momentum.research_report import format_report, generate_report


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test_report.db"
    ensure_tables(path)
    return path


def _decision(**overrides) -> dict:
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
        "retracement_pct": 45.0,
        "impulse_start_price": 103000.0,
        "impulse_end_price": 106000.0,
        "pullback_rejection": "",
        "param_version": "momentum-pullback-v1",
    }
    base.update(overrides)
    return base


def _trade(decision_id: int, **overrides) -> dict:
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


def _close(db_path, trade_id, **overrides):
    """Close a trade with sensible defaults."""
    defaults = {
        "exit_price": 106000.0,
        "exit_reason": "tp1_hit",
        "exit_timestamp": "2026-04-15T16:00:00",
        "pnl_pct": 1.15,
        "duration_candles": 8,
        "mfe_pct": 1.3,
        "mae_pct": -0.2,
        "retested_impulse_end": True,
        "lost_pullback_extreme": False,
    }
    defaults.update(overrides)
    close_trade(db_path, trade_id, **defaults)


# ---------------------------------------------------------------------------
# 1. Empty database
# ---------------------------------------------------------------------------

class TestEmptyReport:
    def test_empty_overview(self, db_path):
        r = generate_report(db_path)
        o = r["overview"]
        assert o["total_decisions"] == 0
        assert o["total_trades"] == 0
        assert o["closed_trades"] == 0
        assert o["open_trades"] == 0

    def test_empty_funnel(self, db_path):
        r = generate_report(db_path)
        assert r["funnel"]["total"] == 0
        assert r["funnel"]["counts"] == {}

    def test_empty_trades(self, db_path):
        r = generate_report(db_path)
        t = r["trades"]
        assert t["count"] == 0
        assert t["win_rate"] == 0.0
        assert t["profit_factor"] == 0.0

    def test_empty_retracement(self, db_path):
        r = generate_report(db_path)
        ret = r["retracement"]
        assert ret["count"] == 0
        assert ret["mean"] == 0.0

    def test_empty_format_no_crash(self, db_path):
        r = generate_report(db_path)
        text = format_report(r)
        assert "RESEARCH REPORT" in text
        assert "(sem dados)" in text


# ---------------------------------------------------------------------------
# 2. Decision funnel
# ---------------------------------------------------------------------------

class TestFunnel:
    def test_funnel_counts(self, db_path):
        insert_decision(db_path, _decision(outcome="trade"))
        insert_decision(db_path, _decision(outcome="trade"))
        insert_decision(db_path, _decision(outcome="no_trend"))
        insert_decision(db_path, _decision(outcome="no_valid_pullback"))
        insert_decision(db_path, _decision(outcome="no_confirmation"))

        r = generate_report(db_path)
        f = r["funnel"]
        assert f["total"] == 5
        assert f["counts"]["trade"] == 2
        assert f["counts"]["no_trend"] == 1
        assert f["counts"]["no_valid_pullback"] == 1
        assert f["counts"]["no_confirmation"] == 1

    def test_funnel_percentages(self, db_path):
        for _ in range(3):
            insert_decision(db_path, _decision(outcome="trade"))
        insert_decision(db_path, _decision(outcome="no_trend"))

        r = generate_report(db_path)
        assert r["funnel"]["percentages"]["trade"] == 75.0
        assert r["funnel"]["percentages"]["no_trend"] == 25.0


# ---------------------------------------------------------------------------
# 3. Trade stats
# ---------------------------------------------------------------------------

class TestTradeStats:
    def _seed_trades(self, db_path):
        """Seed 4 closed trades: 3 wins, 1 loss."""
        # Win 1: tp1_hit +1.15%
        d1 = insert_decision(db_path, _decision())
        t1 = insert_trade(db_path, _trade(d1))
        _close(db_path, t1, pnl_pct=1.15, exit_reason="tp1_hit",
               mfe_pct=1.3, mae_pct=-0.2, duration_candles=8)

        # Win 2: tp2_hit +2.50%
        d2 = insert_decision(db_path, _decision())
        t2 = insert_trade(db_path, _trade(d2))
        _close(db_path, t2, pnl_pct=2.50, exit_reason="tp2_hit",
               mfe_pct=2.6, mae_pct=-0.1, duration_candles=12)

        # Win 3: timeout +0.30%
        d3 = insert_decision(db_path, _decision())
        t3 = insert_trade(db_path, _trade(d3))
        _close(db_path, t3, pnl_pct=0.30, exit_reason="timeout",
               mfe_pct=0.8, mae_pct=-0.5, duration_candles=16)

        # Loss: sl_hit -1.72%
        d4 = insert_decision(db_path, _decision())
        t4 = insert_trade(db_path, _trade(d4))
        _close(db_path, t4, pnl_pct=-1.72, exit_reason="sl_hit",
               mfe_pct=0.2, mae_pct=-1.8, duration_candles=4,
               retested_impulse_end=False, lost_pullback_extreme=True)

    def test_win_rate(self, db_path):
        self._seed_trades(db_path)
        r = generate_report(db_path)
        assert r["trades"]["wins"] == 3
        assert r["trades"]["losses"] == 1
        assert r["trades"]["win_rate"] == 75.0

    def test_pnl_totals(self, db_path):
        self._seed_trades(db_path)
        r = generate_report(db_path)
        # total = 1.15 + 2.50 + 0.30 + (-1.72) = 2.23
        assert r["trades"]["total_pnl"] == pytest.approx(2.23, abs=0.01)

    def test_avg_pnl(self, db_path):
        self._seed_trades(db_path)
        r = generate_report(db_path)
        assert r["trades"]["avg_pnl"] == pytest.approx(2.23 / 4, abs=0.01)

    def test_avg_win_loss(self, db_path):
        self._seed_trades(db_path)
        r = generate_report(db_path)
        # avg win = (1.15 + 2.50 + 0.30) / 3 = 1.3167
        assert r["trades"]["avg_win"] == pytest.approx(1.3167, abs=0.01)
        assert r["trades"]["avg_loss"] == pytest.approx(-1.72, abs=0.01)

    def test_profit_factor(self, db_path):
        self._seed_trades(db_path)
        r = generate_report(db_path)
        # gross_profit = 3.95, gross_loss = 1.72 → PF = 2.30
        assert r["trades"]["profit_factor"] == pytest.approx(2.30, abs=0.05)

    def test_avg_duration(self, db_path):
        self._seed_trades(db_path)
        r = generate_report(db_path)
        # (8 + 12 + 16 + 4) / 4 = 10.0
        assert r["trades"]["avg_duration"] == 10.0

    def test_all_losses_profit_factor(self, db_path):
        """All losing trades → profit factor = 0."""
        d = insert_decision(db_path, _decision())
        t = insert_trade(db_path, _trade(d))
        _close(db_path, t, pnl_pct=-1.0, exit_reason="sl_hit")

        r = generate_report(db_path)
        assert r["trades"]["profit_factor"] == 0.0

    def test_all_wins_profit_factor(self, db_path):
        """All winning trades → profit factor = inf."""
        d = insert_decision(db_path, _decision())
        t = insert_trade(db_path, _trade(d))
        _close(db_path, t, pnl_pct=1.0, exit_reason="tp1_hit")

        r = generate_report(db_path)
        assert r["trades"]["profit_factor"] == float("inf")


# ---------------------------------------------------------------------------
# 4. Exit breakdown
# ---------------------------------------------------------------------------

class TestExitBreakdown:
    def test_exit_reasons_counted(self, db_path):
        for reason, pnl in [
            ("tp1_hit", 1.15), ("tp1_hit", 1.20),
            ("sl_hit", -1.72), ("timeout", 0.10),
        ]:
            d = insert_decision(db_path, _decision())
            t = insert_trade(db_path, _trade(d))
            _close(db_path, t, pnl_pct=pnl, exit_reason=reason)

        r = generate_report(db_path)
        exits = r["exits"]
        assert exits["tp1_hit"]["count"] == 2
        assert exits["sl_hit"]["count"] == 1
        assert exits["timeout"]["count"] == 1

    def test_exit_avg_pnl(self, db_path):
        for pnl in [1.0, 1.4]:
            d = insert_decision(db_path, _decision())
            t = insert_trade(db_path, _trade(d))
            _close(db_path, t, pnl_pct=pnl, exit_reason="tp1_hit")

        r = generate_report(db_path)
        assert r["exits"]["tp1_hit"]["avg_pnl"] == pytest.approx(1.2, abs=0.01)


# ---------------------------------------------------------------------------
# 5. MFE / MAE
# ---------------------------------------------------------------------------

class TestMfeMae:
    def test_mfe_mae_averages(self, db_path):
        for mfe, mae in [(1.0, -0.5), (2.0, -1.0), (3.0, -0.3)]:
            d = insert_decision(db_path, _decision())
            t = insert_trade(db_path, _trade(d))
            _close(db_path, t, mfe_pct=mfe, mae_pct=mae)

        r = generate_report(db_path)
        assert r["mfe_mae"]["avg_mfe"] == pytest.approx(2.0, abs=0.01)
        assert r["mfe_mae"]["avg_mae"] == pytest.approx(-0.6, abs=0.01)
        assert r["mfe_mae"]["max_mfe"] == pytest.approx(3.0)
        assert r["mfe_mae"]["worst_mae"] == pytest.approx(-1.0)

    def test_edge_ratio(self, db_path):
        # avg_mfe=2.0, avg_mae=-0.5 → edge = 2.0/0.5 = 4.0
        for mfe, mae in [(2.0, -0.5), (2.0, -0.5)]:
            d = insert_decision(db_path, _decision())
            t = insert_trade(db_path, _trade(d))
            _close(db_path, t, mfe_pct=mfe, mae_pct=mae)

        r = generate_report(db_path)
        assert r["mfe_mae"]["edge_ratio"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# 6. Retracement distribution — core of user request
# ---------------------------------------------------------------------------

class TestRetracementDistribution:
    def _seed_retracements(self, db_path, values: list):
        """Insert TRADE decisions with specific retracement_pct values."""
        for v in values:
            insert_decision(db_path, _decision(
                outcome="trade", retracement_pct=v,
            ))

    def test_mean_and_median(self, db_path):
        self._seed_retracements(db_path, [35.0, 45.0, 50.0, 55.0, 65.0])
        r = generate_report(db_path)["retracement"]
        assert r["mean"] == pytest.approx(50.0)
        assert r["median"] == pytest.approx(50.0)

    def test_median_even_count(self, db_path):
        self._seed_retracements(db_path, [40.0, 50.0, 55.0, 60.0])
        r = generate_report(db_path)["retracement"]
        # Median of [40, 50, 55, 60] = (50+55)/2 = 52.5
        assert r["median"] == pytest.approx(52.5)

    def test_buckets(self, db_path):
        # 2 in 30-40, 3 in 40-50, 1 in 50-60, 2 in 60-70
        values = [32.0, 38.0, 42.0, 45.0, 49.0, 55.0, 65.0, 68.0]
        self._seed_retracements(db_path, values)
        r = generate_report(db_path)["retracement"]
        assert r["buckets"]["30-40"] == 2
        assert r["buckets"]["40-50"] == 3
        assert r["buckets"]["50-60"] == 1
        assert r["buckets"]["60-70"] == 2

    def test_near_boundaries(self, db_path):
        # Near 30%: 30.5, 33.0, 35.0 → 3 signals <=35
        # Near 70%: 65.0, 67.0, 69.5 → 3 signals >=65
        # Middle: 50.0
        values = [30.5, 33.0, 35.0, 50.0, 65.0, 67.0, 69.5]
        self._seed_retracements(db_path, values)
        r = generate_report(db_path)["retracement"]
        assert r["near_30_count"] == 3
        assert r["near_70_count"] == 3

    def test_min_max(self, db_path):
        self._seed_retracements(db_path, [31.0, 50.0, 69.0])
        r = generate_report(db_path)["retracement"]
        assert r["min"] == pytest.approx(31.0)
        assert r["max"] == pytest.approx(69.0)

    def test_ignores_non_trade_decisions(self, db_path):
        # Rejected decisions should not appear in retracement
        insert_decision(db_path, _decision(
            outcome="no_valid_pullback", retracement_pct=25.0,
        ))
        insert_decision(db_path, _decision(
            outcome="trade", retracement_pct=50.0,
        ))
        r = generate_report(db_path)["retracement"]
        assert r["count"] == 1
        assert r["mean"] == pytest.approx(50.0)

    def test_single_value(self, db_path):
        self._seed_retracements(db_path, [48.0])
        r = generate_report(db_path)["retracement"]
        assert r["count"] == 1
        assert r["mean"] == pytest.approx(48.0)
        assert r["median"] == pytest.approx(48.0)


# ---------------------------------------------------------------------------
# 7. Breakdowns
# ---------------------------------------------------------------------------

class TestBreakdowns:
    def _seed_varied(self, db_path):
        """Seed trades with different regimes, sessions, directions."""
        specs = [
            ("TRENDING", "us", "LONG", 1.0),
            ("TRENDING", "us", "LONG", -0.5),
            ("TRENDING", "europe", "SHORT", 0.8),
            ("WEAK_TREND", "asia", "LONG", -1.2),
            ("WEAK_TREND", "asia", "SHORT", 1.5),
        ]
        for regime, session, direction, pnl in specs:
            d = insert_decision(db_path, _decision(
                regime=regime, session_bucket=session, direction=direction,
            ))
            t = insert_trade(db_path, _trade(
                d, regime=regime, session_bucket=session, direction=direction,
            ))
            _close(db_path, t, pnl_pct=pnl, exit_reason="tp1_hit")

    def test_by_regime(self, db_path):
        self._seed_varied(db_path)
        r = generate_report(db_path)["breakdowns"]["by_regime"]
        assert "TRENDING" in r
        assert "WEAK_TREND" in r
        assert r["TRENDING"]["count"] == 3
        assert r["WEAK_TREND"]["count"] == 2

    def test_by_session(self, db_path):
        self._seed_varied(db_path)
        r = generate_report(db_path)["breakdowns"]["by_session"]
        assert r["us"]["count"] == 2
        assert r["europe"]["count"] == 1
        assert r["asia"]["count"] == 2

    def test_by_direction(self, db_path):
        self._seed_varied(db_path)
        r = generate_report(db_path)["breakdowns"]["by_direction"]
        assert r["LONG"]["count"] == 3
        assert r["SHORT"]["count"] == 2

    def test_win_rate_per_group(self, db_path):
        self._seed_varied(db_path)
        r = generate_report(db_path)["breakdowns"]["by_regime"]
        # TRENDING: 2 wins (1.0, 0.8), 1 loss (-0.5) → 66.7%
        assert r["TRENDING"]["win_rate"] == pytest.approx(66.7, abs=0.1)


# ---------------------------------------------------------------------------
# 8. Research flags
# ---------------------------------------------------------------------------

class TestResearchFlags:
    def test_flag_counts(self, db_path):
        d = insert_decision(db_path, _decision())

        t1 = insert_trade(db_path, _trade(d))
        _close(db_path, t1, retested_impulse_end=True, lost_pullback_extreme=False)

        t2 = insert_trade(db_path, _trade(d, symbol="ETHUSDT"))
        _close(db_path, t2, retested_impulse_end=True, lost_pullback_extreme=True)

        t3 = insert_trade(db_path, _trade(d, symbol="SOLUSDT"))
        _close(db_path, t3, retested_impulse_end=False, lost_pullback_extreme=False)

        r = generate_report(db_path)["research_flags"]
        assert r["retested_impulse_end"] == 2
        assert r["retested_pct"] == pytest.approx(66.7, abs=0.1)
        assert r["lost_pullback_extreme"] == 1
        assert r["lost_pct"] == pytest.approx(33.3, abs=0.1)


# ---------------------------------------------------------------------------
# 9. format_report — text output
# ---------------------------------------------------------------------------

class TestFormatReport:
    def _seed_full(self, db_path):
        """Seed enough data for a complete report."""
        for outcome in ["trade", "trade", "no_trend", "no_valid_pullback"]:
            insert_decision(db_path, _decision(
                outcome=outcome, retracement_pct=45.0 if outcome == "trade" else 0.0,
            ))

        decisions = [1, 2]  # trade decisions
        for i, dec_id in enumerate(decisions):
            t = insert_trade(db_path, _trade(dec_id))
            pnl = 1.0 if i == 0 else -0.5
            reason = "tp1_hit" if i == 0 else "sl_hit"
            _close(db_path, t, pnl_pct=pnl, exit_reason=reason,
                   mfe_pct=1.2, mae_pct=-0.3,
                   retested_impulse_end=(i == 0),
                   lost_pullback_extreme=(i == 1))

    def test_contains_all_sections(self, db_path):
        self._seed_full(db_path)
        text = format_report(generate_report(db_path))
        assert "RESEARCH REPORT" in text
        assert "FUNIL DE DECISOES" in text
        assert "PERFORMANCE" in text
        assert "SAIDAS POR MOTIVO" in text
        assert "MFE / MAE" in text
        assert "DISTRIBUICAO RETRACEMENT" in text
        assert "BREAKDOWN POR REGIME" in text
        assert "BREAKDOWN POR SESSAO" in text
        assert "BREAKDOWN POR DIRECAO" in text
        assert "RESEARCH FLAGS" in text

    def test_win_rate_appears(self, db_path):
        self._seed_full(db_path)
        text = format_report(generate_report(db_path))
        assert "Win rate:" in text
        assert "50.0%" in text  # 1W / 1L

    def test_retracement_buckets_appear(self, db_path):
        self._seed_full(db_path)
        text = format_report(generate_report(db_path))
        assert "40-50%" in text

    def test_format_is_string(self, db_path):
        self._seed_full(db_path)
        text = format_report(generate_report(db_path))
        assert isinstance(text, str)
        assert len(text) > 100


# ---------------------------------------------------------------------------
# 10. Open trades excluded from stats
# ---------------------------------------------------------------------------

class TestOpenTradesExcluded:
    def test_open_trade_not_in_stats(self, db_path):
        """Open trades should appear in overview but not in trade stats."""
        d = insert_decision(db_path, _decision())
        insert_trade(db_path, _trade(d))  # not closed

        r = generate_report(db_path)
        assert r["overview"]["open_trades"] == 1
        assert r["overview"]["total_trades"] == 1
        assert r["trades"]["count"] == 0  # no closed trades
