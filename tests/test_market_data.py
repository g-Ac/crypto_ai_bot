"""
Testes para market_data.py — Fase 0.1 do Roadmap V1.

Cobre:
- _get_proxy_liquidations: m=True → vol_short (taker sold), m=False → vol_long (taker bought)
- Threshold filtering (trades < 10x avg são ignorados)
- Retorno default quando dados insuficientes
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch

from market_data import _get_proxy_liquidations


def _make_agg_trades(trades_spec, normal_count=30):
    """Helper: gera lista de aggTrades com trades normais + extremos.

    trades_spec: list of (qty, price, is_maker_buyer) for extreme trades.
    normal_count: number of normal (below-threshold) trades to pad.
    """
    # Normal trades: qty=1.0, price=100, so avg_qty ~ 1.0
    # Threshold = avg_qty * 10 = ~10. Extreme trades need qty >= 10.
    data = []
    for _ in range(normal_count):
        data.append({"q": "1.0", "p": "100.0", "m": False})

    for qty, price, is_maker in trades_spec:
        data.append({"q": str(qty), "p": str(price), "m": is_maker})

    return data


class TestProxyLiquidations:
    """Testa a lógica de classificação long/short das proxy liquidations."""

    @patch("market_data._api_get")
    def test_maker_buyer_goes_to_vol_short(self, mock_api):
        """m=True → maker was buyer → taker SOLD → vol_short."""
        mock_api.return_value = _make_agg_trades([
            (50.0, 100.0, True),  # extreme trade, maker=buyer → taker sold
        ])

        result = _get_proxy_liquidations("BTCUSDT")

        assert result["liquidation_vol_short"] == 5000.0  # 50 * 100
        assert result["liquidation_vol_long"] == 0.0
        assert result["count"] == 1
        assert result["is_proxy"] is True

    @patch("market_data._api_get")
    def test_maker_seller_goes_to_vol_long(self, mock_api):
        """m=False → maker was seller → taker BOUGHT → vol_long."""
        mock_api.return_value = _make_agg_trades([
            (50.0, 100.0, False),  # extreme trade, maker=seller → taker bought
        ])

        result = _get_proxy_liquidations("BTCUSDT")

        assert result["liquidation_vol_long"] == 5000.0  # 50 * 100
        assert result["liquidation_vol_short"] == 0.0
        assert result["count"] == 1

    @patch("market_data._api_get")
    def test_mixed_trades_split_correctly(self, mock_api):
        """Múltiplos trades extremos classificados corretamente."""
        # Com 100 trades normais (qty=1), avg~1, threshold~10.
        # Extreme trades com qty=50+ passam facilmente.
        mock_api.return_value = _make_agg_trades([
            (50.0, 100.0, True),   # taker sold → vol_short = 5000
            (60.0, 100.0, True),   # taker sold → vol_short = 6000
            (70.0, 200.0, False),  # taker bought → vol_long = 14000
        ], normal_count=100)

        result = _get_proxy_liquidations("BTCUSDT")

        assert result["liquidation_vol_short"] == 11000.0  # 5000 + 6000
        assert result["liquidation_vol_long"] == 14000.0
        assert result["count"] == 3

    @patch("market_data._api_get")
    def test_below_threshold_trades_ignored(self, mock_api):
        """Trades com qty < 10x a média são ignorados."""
        mock_api.return_value = _make_agg_trades([
            (5.0, 100.0, True),  # 5 < ~10 threshold → ignorado
        ])

        result = _get_proxy_liquidations("BTCUSDT")

        assert result["count"] == 0
        assert result["liquidation_vol_long"] == 0.0
        assert result["liquidation_vol_short"] == 0.0

    @patch("market_data._api_get")
    def test_insufficient_data_returns_default(self, mock_api):
        """Menos de 20 trades retorna default vazio."""
        mock_api.return_value = [{"q": "1.0", "p": "100.0", "m": False}] * 10

        result = _get_proxy_liquidations("BTCUSDT")

        assert result["count"] == 0
        assert result["is_proxy"] is True

    @patch("market_data._api_get")
    def test_api_failure_returns_default(self, mock_api):
        """API retornando None → default seguro."""
        mock_api.return_value = None

        result = _get_proxy_liquidations("BTCUSDT")

        assert result == {
            "liquidation_vol_long": 0.0,
            "liquidation_vol_short": 0.0,
            "count": 0,
            "is_proxy": True,
        }
