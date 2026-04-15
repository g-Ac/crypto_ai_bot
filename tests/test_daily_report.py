"""Tests for daily_report.py — stats calculation and circuit breaker."""

import os
import json
import tempfile
from unittest.mock import patch, MagicMock
from daily_report import calc_daily_stats, check_circuit_breaker


def test_calc_daily_stats_empty():
    result = calc_daily_stats([])
    assert result["count"] == 0
    assert result["pnl_pct"] == 0
    assert result["pnl_usd"] == 0


def test_calc_daily_stats_filters_open():
    """Trades with exit_reason='open' should be excluded."""
    trades = [
        {"pnl_pct": 1.5, "pnl_usd": 15.0, "exit_reason": "tp"},
        {"pnl_pct": 0.0, "pnl_usd": 0.0, "exit_reason": "open"},
    ]
    result = calc_daily_stats(trades)
    assert result["count"] == 1
    assert result["pnl_pct"] == 1.5


def test_calc_daily_stats_wins_losses():
    trades = [
        {"pnl_pct": 2.0, "pnl_usd": 20.0, "exit_reason": "tp"},
        {"pnl_pct": -1.0, "pnl_usd": -10.0, "exit_reason": "sl"},
        {"pnl_pct": 0.5, "pnl_usd": 5.0, "exit_reason": "tp1"},
    ]
    result = calc_daily_stats(trades)
    assert result["count"] == 3
    assert result["wins"] == 2
    assert result["losses"] == 1
    assert result["pnl_pct"] == 1.5
    assert result["pnl_usd"] == 15.0


def test_calc_daily_stats_none_values():
    """Trades with None pnl should be treated as 0."""
    trades = [
        {"pnl_pct": None, "pnl_usd": None, "exit_reason": "tp"},
    ]
    result = calc_daily_stats(trades)
    assert result["count"] == 1
    assert result["pnl_pct"] == 0
    assert result["wins"] == 0
    assert result["losses"] == 0


@patch("daily_report.db")
def test_circuit_breaker_max_trades(mock_db):
    """Circuit breaker triggers on max trades."""
    mock_db.get_trades_today.return_value = [
        {"pnl_pct": 0.1, "pnl_usd": 1.0, "exit_reason": "tp"}
        for _ in range(25)
    ]
    with patch("daily_report.DAILY_MAX_TRADES", 20):
        assert check_circuit_breaker("scalping") is True


@patch("daily_report.db")
def test_circuit_breaker_not_triggered(mock_db):
    """Under limits should not trigger."""
    mock_db.get_trades_today.return_value = [
        {"pnl_pct": 0.1, "pnl_usd": 1.0, "exit_reason": "tp"}
        for _ in range(3)
    ]
    assert check_circuit_breaker("scalping") is False


@patch("daily_report.db")
@patch("daily_report._get_current_capital", return_value=10000)
def test_circuit_breaker_loss_limit(mock_capital, mock_db):
    """Circuit breaker triggers on daily loss > limit."""
    mock_db.get_trades_today.return_value = [
        {"pnl_pct": -3.0, "pnl_usd": -600.0, "exit_reason": "sl"}
    ]
    with patch("daily_report.DAILY_LOSS_LIMIT_PCT", 5):
        assert check_circuit_breaker("scalping") is True


def test_circuit_breaker_invalid_system():
    assert check_circuit_breaker("nonexistent") is False


