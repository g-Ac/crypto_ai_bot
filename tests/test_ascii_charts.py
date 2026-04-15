"""Tests for ascii_charts module."""
import pytest
from ascii_charts import render_equity_curve, render_daily_pnl


class TestRenderEquityCurve:
    def test_empty_data_returns_no_data_message(self):
        result = render_equity_curve([])
        assert "NO DATA" in result

    def test_single_point(self):
        data = [{"day": "2025-01-01", "pnl": 100.0}]
        result = render_equity_curve(data, width=20)
        assert "100" in result

    def test_multiple_points_has_axes(self):
        data = [
            {"day": "2025-01-01", "pnl": 0},
            {"day": "2025-01-02", "pnl": 50},
            {"day": "2025-01-03", "pnl": 100},
            {"day": "2025-01-04", "pnl": 75},
        ]
        result = render_equity_curve(data, width=30)
        lines = result.strip().split("\n")
        assert len(lines) >= 3
        assert any("|" in line for line in lines)

    def test_negative_values(self):
        data = [
            {"day": "2025-01-01", "pnl": -50},
            {"day": "2025-01-02", "pnl": -100},
            {"day": "2025-01-03", "pnl": -25},
        ]
        result = render_equity_curve(data, width=30)
        assert "-" in result

    def test_width_respected(self):
        data = [{"day": f"2025-01-{i:02d}", "pnl": i * 10} for i in range(1, 15)]
        result = render_equity_curve(data, width=40)
        lines = result.strip().split("\n")
        for line in lines:
            assert len(line) <= 55


class TestRenderDailyPnl:
    def test_empty_data(self):
        result = render_daily_pnl([])
        assert "NO DATA" in result

    def test_positive_bars(self):
        data = [
            {"day": "2025-01-01", "pnl": 50},
            {"day": "2025-01-02", "pnl": 100},
        ]
        result = render_daily_pnl(data, width=20)
        assert "\u2588" in result

    def test_mixed_positive_negative(self):
        data = [
            {"day": "2025-01-01", "pnl": 50},
            {"day": "2025-01-02", "pnl": -30},
            {"day": "2025-01-03", "pnl": 80},
        ]
        result = render_daily_pnl(data, width=20)
        lines = result.strip().split("\n")
        assert len(lines) >= 2

    def test_summary_line(self):
        data = [
            {"day": "2025-01-01", "pnl": 50},
            {"day": "2025-01-02", "pnl": -30},
        ]
        result = render_daily_pnl(data, width=20)
        assert "AVG" in result.upper() or "W" in result.upper()
