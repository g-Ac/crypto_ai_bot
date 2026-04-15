"""Tests for momentum/robustness_check.py.

Covers: compute_stats, analyze_monthly, analyze_regime, format_robustness_report.
Holdout replay is not tested here (requires Binance data).
"""

import pytest

from momentum.robustness_check import (
    analyze_monthly,
    analyze_regime,
    compute_stats,
    format_robustness_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _trade(pnl: float, month: str = "2026-02", regime: str = "TRENDING"):
    """Minimal closed-trade dict for testing."""
    return {
        "pnl_pct": pnl,
        "timestamp": f"{month}-15 12:00:00",
        "regime": regime,
        "exit_price": 100.0,
    }


# ---------------------------------------------------------------------------
# compute_stats
# ---------------------------------------------------------------------------

class TestComputeStats:

    def test_empty(self):
        s = compute_stats([])
        assert s["count"] == 0
        assert s["win_rate"] == 0.0
        assert s["profit_factor"] == 0.0

    def test_all_wins(self):
        trades = [_trade(1.0), _trade(2.0), _trade(0.5)]
        s = compute_stats(trades)
        assert s["count"] == 3
        assert s["wins"] == 3
        assert s["losses"] == 0
        assert s["win_rate"] == 100.0
        assert s["profit_factor"] == float("inf")
        assert s["total_pnl"] == 3.5

    def test_mixed(self):
        trades = [_trade(2.0), _trade(-1.0), _trade(1.0), _trade(-0.5)]
        s = compute_stats(trades)
        assert s["count"] == 4
        assert s["wins"] == 2
        assert s["losses"] == 2
        assert s["win_rate"] == 50.0
        assert s["profit_factor"] == 2.0  # 3.0 / 1.5
        assert s["total_pnl"] == 1.5

    def test_all_losses(self):
        trades = [_trade(-1.0), _trade(-2.0)]
        s = compute_stats(trades)
        assert s["wins"] == 0
        assert s["profit_factor"] == 0.0  # 0 / 3.0 → 0 (guarded)
        assert s["total_pnl"] == -3.0

    def test_zero_pnl_counts_as_loss(self):
        trades = [_trade(0.0)]
        s = compute_stats(trades)
        assert s["losses"] == 1
        assert s["wins"] == 0


# ---------------------------------------------------------------------------
# analyze_monthly
# ---------------------------------------------------------------------------

class TestAnalyzeMonthly:

    def test_v11_wins_all_months(self):
        v10 = [_trade(-1.0, "2026-01"), _trade(1.0, "2026-02"), _trade(0.5, "2026-03")]
        v11 = [_trade(-0.5, "2026-01"), _trade(1.5, "2026-02"), _trade(1.0, "2026-03")]
        result = analyze_monthly(v10, v11)
        assert result["v11_wins"] == 3
        assert result["total_months"] == 3
        assert result["conclusion"] == "consistente"
        for data in result["months"].values():
            assert data["winner"] == "v1.1"

    def test_v11_loses_majority(self):
        v10 = [_trade(2.0, "2026-01"), _trade(2.0, "2026-02"), _trade(2.0, "2026-03")]
        v11 = [_trade(1.0, "2026-01"), _trade(1.0, "2026-02"), _trade(3.0, "2026-03")]
        result = analyze_monthly(v10, v11)
        assert result["v11_wins"] == 1
        assert result["conclusion"] == "fragil"

    def test_tie_goes_to_v11(self):
        """Equal PnL in a month → v1.1 wins that month."""
        v10 = [_trade(1.0, "2026-01")]
        v11 = [_trade(1.0, "2026-01")]
        result = analyze_monthly(v10, v11)
        assert result["months"]["2026-01"]["winner"] == "v1.1"

    def test_empty_trades(self):
        result = analyze_monthly([], [])
        assert result["total_months"] == 0
        assert result["conclusion"] == "sem dados"

    def test_disjoint_months(self):
        """v1.0 has month A, v1.1 has month B."""
        v10 = [_trade(1.0, "2026-01")]
        v11 = [_trade(2.0, "2026-02")]
        result = analyze_monthly(v10, v11)
        assert result["total_months"] == 2
        # 2026-01: v1.0 has trades, v1.1 has 0 → v1.0 wins
        assert result["months"]["2026-01"]["winner"] == "v1.0"
        # 2026-02: v1.1 has trades, v1.0 has 0 → v1.1 wins
        assert result["months"]["2026-02"]["winner"] == "v1.1"

    def test_partial_majority(self):
        """v1.1 wins 2 of 4 months → parcial."""
        v10 = [
            _trade(2.0, "2026-01"), _trade(2.0, "2026-02"),
            _trade(0.5, "2026-03"), _trade(0.5, "2026-04"),
        ]
        v11 = [
            _trade(1.0, "2026-01"), _trade(1.0, "2026-02"),
            _trade(1.0, "2026-03"), _trade(1.0, "2026-04"),
        ]
        result = analyze_monthly(v10, v11)
        assert result["v11_wins"] == 2
        assert result["conclusion"] == "parcial"


# ---------------------------------------------------------------------------
# analyze_regime
# ---------------------------------------------------------------------------

class TestAnalyzeRegime:

    def test_both_regimes_improve(self):
        v10 = [
            _trade(1.0, regime="TRENDING"),
            _trade(0.5, regime="WEAK_TREND"),
        ]
        v11 = [
            _trade(2.0, regime="TRENDING"),
            _trade(1.0, regime="WEAK_TREND"),
        ]
        result = analyze_regime(v10, v11)
        assert result["regimes_improved"] == 2
        assert result["conclusion"] == "generalizada"

    def test_one_regime_worse(self):
        v10 = [
            _trade(2.0, regime="TRENDING"),
            _trade(0.5, regime="WEAK_TREND"),
        ]
        v11 = [
            _trade(1.0, regime="TRENDING"),
            _trade(1.0, regime="WEAK_TREND"),
        ]
        result = analyze_regime(v10, v11)
        assert result["regimes_improved"] == 1
        assert result["conclusion"] == "parcial"

    def test_all_worse(self):
        v10 = [_trade(2.0, regime="TRENDING"), _trade(2.0, regime="WEAK_TREND")]
        v11 = [_trade(0.5, regime="TRENDING"), _trade(0.5, regime="WEAK_TREND")]
        result = analyze_regime(v10, v11)
        assert result["regimes_improved"] == 0
        assert result["conclusion"] == "regime-especifica"

    def test_pnl_delta(self):
        v10 = [_trade(1.0, regime="TRENDING")]
        v11 = [_trade(1.5, regime="TRENDING")]
        result = analyze_regime(v10, v11)
        assert result["regimes"]["TRENDING"]["pnl_delta"] == 0.5

    def test_empty(self):
        result = analyze_regime([], [])
        assert result["conclusion"] == "sem dados"


# ---------------------------------------------------------------------------
# format_robustness_report
# ---------------------------------------------------------------------------

class TestFormatReport:

    def _basic_data(self):
        monthly = {
            "months": {
                "2026-01": {
                    "v1.0": compute_stats([_trade(-1.0, "2026-01")]),
                    "v1.1": compute_stats([_trade(-0.5, "2026-01")]),
                    "winner": "v1.1",
                },
            },
            "v11_wins": 1,
            "total_months": 1,
            "conclusion": "consistente",
        }
        holdout = {
            "period": "2025-12-17 → 2026-01-16",
            "steps": 2000,
            "v1.0": compute_stats([_trade(1.0)]),
            "v1.1": compute_stats([_trade(1.5)]),
            "conclusion": "reforça",
        }
        regime = {
            "regimes": {
                "TRENDING": {
                    "v1.0": compute_stats([_trade(1.0, regime="TRENDING")]),
                    "v1.1": compute_stats([_trade(1.5, regime="TRENDING")]),
                    "pnl_delta": 0.5,
                    "wr_delta": 0.0,
                },
            },
            "regimes_improved": 1,
            "total_regimes": 1,
            "conclusion": "generalizada",
        }
        return monthly, holdout, regime

    def test_contains_all_sections(self):
        monthly, holdout, regime = self._basic_data()
        text = format_robustness_report(monthly, holdout, regime)
        assert "CONSISTENCIA MENSAL" in text
        assert "HOLDOUT OUT-OF-SAMPLE" in text
        assert "BREAKDOWN POR REGIME" in text
        assert "VEREDICTO FINAL" in text

    def test_robusta_verdict(self):
        monthly, holdout, regime = self._basic_data()
        text = format_robustness_report(monthly, holdout, regime)
        assert "ROBUSTA" in text

    def test_fragil_verdict(self):
        monthly, holdout, regime = self._basic_data()
        monthly["conclusion"] = "fragil"
        holdout["conclusion"] = "alerta"
        text = format_robustness_report(monthly, holdout, regime)
        assert "FRAGIL" in text

    def test_holdout_error(self):
        monthly, _, regime = self._basic_data()
        holdout = {"error": "Not enough candles"}
        text = format_robustness_report(monthly, holdout, regime)
        assert "ERRO" in text
        assert "Not enough candles" in text

    def test_inconclusiva_verdict(self):
        monthly, holdout, regime = self._basic_data()
        monthly["conclusion"] = "fragil"
        holdout["conclusion"] = "reforça"
        regime["conclusion"] = "generalizada"
        text = format_robustness_report(monthly, holdout, regime)
        assert "INCONCLUSIVA" in text
