"""Tests for preflight: mock Binance + eligibility classification."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from momentum.expansion.preflight import PreflightResult, run_preflight


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_eligible_with_long_history():
    today = datetime(2026, 4, 27, tzinfo=timezone.utc)
    # First kline 700d ago — eligible for 455d requirement
    first_kline_ms = _ms(today - timedelta(days=700))

    with patch("momentum.expansion.preflight._fetch_first_kline_time") as mock_fetch:
        mock_fetch.return_value = first_kline_ms
        result = run_preflight(
            symbols=["BTCUSDT"], required_days=455, today=today,
        )
    assert "BTCUSDT" in result.universe
    assert "BTCUSDT" not in result.ineligible


def test_ineligible_with_short_history():
    today = datetime(2026, 4, 27, tzinfo=timezone.utc)
    first_kline_ms = _ms(today - timedelta(days=100))

    with patch("momentum.expansion.preflight._fetch_first_kline_time") as mock_fetch:
        mock_fetch.return_value = first_kline_ms
        result = run_preflight(
            symbols=["NEWCOINUSDT"], required_days=455, today=today,
        )
    assert "NEWCOINUSDT" not in result.universe
    assert "NEWCOINUSDT" in result.ineligible
    assert result.ineligible["NEWCOINUSDT"]["days_available"] == 100


def test_mixed_eligibility():
    today = datetime(2026, 4, 27, tzinfo=timezone.utc)

    def fake_fetch(symbol):
        if symbol == "BTCUSDT":
            return _ms(today - timedelta(days=2000))
        if symbol == "NEWCOINUSDT":
            return _ms(today - timedelta(days=50))
        return _ms(today - timedelta(days=455))  # exactly at threshold

    with patch("momentum.expansion.preflight._fetch_first_kline_time", side_effect=fake_fetch):
        result = run_preflight(
            symbols=["BTCUSDT", "NEWCOINUSDT", "EDGEUSDT"],
            required_days=455, today=today,
        )
    assert "BTCUSDT" in result.universe
    assert "NEWCOINUSDT" in result.ineligible
    # Exactly at threshold = eligible
    assert "EDGEUSDT" in result.universe


def test_preflight_serializes_to_json_dict():
    today = datetime(2026, 4, 27, tzinfo=timezone.utc)
    with patch("momentum.expansion.preflight._fetch_first_kline_time") as mock_fetch:
        mock_fetch.return_value = _ms(today - timedelta(days=700))
        result = run_preflight(symbols=["BTCUSDT"], required_days=455, today=today)
    d = result.to_dict()
    assert d["frozen_at"]
    assert d["required_days"] == 455
    assert d["universe"] == ["BTCUSDT"]
    assert d["candidates_checked"] == 1
    assert d["universe_size"] == 1


def test_preflight_empty_eligible_raises_in_caller():
    today = datetime(2026, 4, 27, tzinfo=timezone.utc)
    with patch("momentum.expansion.preflight._fetch_first_kline_time") as mock_fetch:
        mock_fetch.return_value = _ms(today - timedelta(days=10))
        result = run_preflight(symbols=["NEWUSDT"], required_days=455, today=today)
    # run_preflight returns the result; abort decision is on the CLI
    assert result.universe_size == 0
