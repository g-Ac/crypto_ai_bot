"""Tests for 1-minute market data fetching."""
import pandas as pd
import pytest
import requests
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from market_1m import fetch_1m_candles_live, fetch_1m_historical


class TestFetchLive:
    def _mock_binance_response(self, n=5):
        base_ts = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        rows = []
        for i in range(n):
            ts = base_ts + i * 60_000
            rows.append([
                ts, "100.0", "101.0", "99.0", "100.5", "1000.0",
                ts + 59999, "100500.0", "50", "500.0", "50250.0", "0"
            ])
        return rows

    @patch("market_1m.requests.get")
    def test_returns_dataframe_with_ohlcv(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._mock_binance_response(10)
        mock_get.return_value = mock_resp
        df = fetch_1m_candles_live("BTCUSDT", limit=10)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 10
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in df.columns
            assert df[col].dtype == float

    @patch("market_1m.requests.get")
    def test_uses_futures_endpoint(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._mock_binance_response(5)
        mock_get.return_value = mock_resp
        fetch_1m_candles_live("BTCUSDT", limit=5)
        call_url = mock_get.call_args[0][0] if mock_get.call_args[0] else mock_get.call_args[1].get("url", "")
        # Could also be passed as positional or keyword - check the actual call
        args, kwargs = mock_get.call_args
        actual_url = args[0] if args else kwargs.get("url", "")
        assert "fapi.binance.com" in actual_url

    @patch("market_1m.requests.get")
    def test_api_failure_raises(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("Network error")
        with pytest.raises(requests.exceptions.ConnectionError):
            fetch_1m_candles_live("BTCUSDT", limit=5)


class TestFetchHistorical:
    @patch("market_1m.fetch_and_cache")
    def test_delegates_to_data_fetcher(self, mock_fetch):
        mock_fetch.return_value = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=100, freq="1min", tz="UTC"),
            "open": [100.0] * 100, "high": [101.0] * 100,
            "low": [99.0] * 100, "close": [100.5] * 100,
            "volume": [1000.0] * 100,
        })
        df = fetch_1m_historical("BTCUSDT", days=1)
        mock_fetch.assert_called_once_with("BTCUSDT", "1m", days=1, force=False)
        assert len(df) == 100

    @patch("market_1m.fetch_and_cache")
    def test_force_redownload(self, mock_fetch):
        mock_fetch.return_value = pd.DataFrame()
        fetch_1m_historical("BTCUSDT", days=30, force=True)
        mock_fetch.assert_called_once_with("BTCUSDT", "1m", days=30, force=True)
