"""Tests for historical_data — uses mocked HTTP."""
from unittest.mock import patch, MagicMock

import pytest

from pair_trading.historical_data import (
    fetch_klines,
    fetch_synced_pair,
    klines_to_arrays,
)


_SAMPLE_KLINE = [
    1700000000000,  # open_time ms
    "50000.0",      # open
    "50100.0",      # high
    "49900.0",      # low
    "50050.0",      # close
    "123.45",       # volume
    1700000899999,  # close_time ms
    "6175500.0",    # quote_volume
    100,            # trades
    "60.0",         # taker_buy_base
    "3000000.0",    # taker_buy_quote
    "0",
]


def _mock_response(klines):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = klines
    m.raise_for_status.return_value = None
    return m


def test_fetch_klines_single_page():
    klines = [_SAMPLE_KLINE for _ in range(200)]
    with patch("pair_trading.historical_data.requests.get") as g:
        g.return_value = _mock_response(klines)
        result = fetch_klines("BTCUSDT", "15m", limit=200)
    assert len(result) == 200
    assert result[0][0] == 1700000000000


def test_fetch_klines_pagination_for_large_range():
    # 2500 candles requires 3 pages (1000 + 1000 + 500)
    page1 = [[(1_700_000_000 + i) * 1000, "1", "1", "1", "1", "1",
              (1_700_000_000 + i) * 1000 + 899999, "1", 1, "1", "1", "0"]
             for i in range(1000)]
    page2 = [[(1_700_001_000 + i) * 1000, "1", "1", "1", "1", "1",
              (1_700_001_000 + i) * 1000 + 899999, "1", 1, "1", "1", "0"]
             for i in range(1000)]
    page3 = [[(1_700_002_000 + i) * 1000, "1", "1", "1", "1", "1",
              (1_700_002_000 + i) * 1000 + 899999, "1", 1, "1", "1", "0"]
             for i in range(500)]
    with patch("pair_trading.historical_data.requests.get") as g:
        g.side_effect = [_mock_response(page1), _mock_response(page2), _mock_response(page3)]
        result = fetch_klines("BTCUSDT", "15m", limit=2500)
    assert len(result) == 2500


def test_klines_to_arrays_extracts_close_and_close_time():
    klines = [_SAMPLE_KLINE, _SAMPLE_KLINE]
    close, close_time = klines_to_arrays(klines)
    assert close.tolist() == [50050.0, 50050.0]
    assert close_time.tolist() == [1700000899999, 1700000899999]


def test_fetch_synced_pair_aligns_by_close_time():
    # BTC has 3 candles (t=100, 200, 300)
    btc_k = [
        [100, "1", "1", "1", "1", "1", 199, "1", 1, "1", "1", "0"],
        [200, "1", "1", "1", "2", "1", 299, "1", 1, "1", "1", "0"],
        [300, "1", "1", "1", "3", "1", 399, "1", 1, "1", "1", "0"],
    ]
    # ETH missing t=200 (only t=100, 300)
    eth_k = [
        [100, "1", "1", "1", "10", "1", 199, "1", 1, "1", "1", "0"],
        [300, "1", "1", "1", "30", "1", 399, "1", 1, "1", "1", "0"],
    ]
    with patch("pair_trading.historical_data.fetch_klines") as fk:
        fk.side_effect = [btc_k, eth_k]
        btc_close, eth_close, close_times = fetch_synced_pair(
            "BTCUSDT", "ETHUSDT", "15m", limit=10
        )
    assert btc_close.tolist() == [1.0, 3.0]
    assert eth_close.tolist() == [10.0, 30.0]
    assert close_times.tolist() == [199, 399]
