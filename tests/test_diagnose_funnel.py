"""Testes para diagnose_funnel.py — funil de decisoes do scalping."""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

from diagnose_funnel import get_funnel_data, get_funnel_json


def _mock_conn_with_data():
    """Cria mock de conexao com dados de teste."""
    conn = MagicMock()

    # Mock fetchall para cada query (chamadas sequenciais)
    blocked_rows = [
        {"blocked_by": "confluence", "count": 100},
        {"blocked_by": "none", "count": 10},
        {"blocked_by": "risk", "count": 30},
    ]
    regime_rows = [
        {"market_regime": "RANGING", "count": 80},
        {"market_regime": "TRENDING", "count": 60},
    ]
    session_rows = [
        {"session_bucket": "us", "count": 50},
        {"session_bucket": "europe", "count": 40},
        {"session_bucket": "asia", "count": 30},
        {"session_bucket": "dead", "count": 20},
    ]
    score_rows = [
        {"confluence_score": 0, "count": 90},
        {"confluence_score": 1, "count": 30},
        {"confluence_score": 2, "count": 15},
        {"confluence_score": 3, "count": 5},
    ]
    reason_rows = [
        {"reason": "Confluencia insuficiente", "count": 80},
        {"reason": "Risk blocked", "count": 20},
    ]
    regime_trade_rows = [
        {"market_regime": "RANGING", "trades": 5, "wins": 3, "pnl": 0.02},
        {"market_regime": "TRENDING", "trades": 3, "wins": 2, "pnl": 0.01},
    ]
    session_trade_rows = [
        {"session_bucket": "us", "trades": 4, "wins": 2, "pnl": 0.015},
        {"session_bucket": "europe", "trades": 2, "wins": 1, "pnl": 0.005},
    ]

    # Cada chamada a execute().fetchall() retorna o proximo conjunto
    conn.execute.return_value.fetchall.side_effect = [
        [MagicMock(**{"__getitem__": lambda s, k, r=r: r[k]}) for r in blocked_rows],
        [MagicMock(**{"__getitem__": lambda s, k, r=r: r[k]}) for r in regime_rows],
        [MagicMock(**{"__getitem__": lambda s, k, r=r: r[k]}) for r in regime_trade_rows],
        [MagicMock(**{"__getitem__": lambda s, k, r=r: r[k]}) for r in session_rows],
        [MagicMock(**{"__getitem__": lambda s, k, r=r: r[k]}) for r in session_trade_rows],
        [MagicMock(**{"__getitem__": lambda s, k, r=r: r[k]}) for r in score_rows],
        [MagicMock(**{"__getitem__": lambda s, k, r=r: r[k]}) for r in reason_rows],
    ]
    return conn


class TestGetFunnelData:
    """get_funnel_data retorna estrutura correta."""

    @patch("diagnose_funnel.db._get_conn")
    def test_returns_correct_structure(self, mock_get_conn):
        mock_get_conn.return_value = _mock_conn_with_data()
        data = get_funnel_data(hours=24)

        assert "total_decisions" in data
        assert "passed" in data
        assert "pass_rate_pct" in data
        assert "funnel" in data
        assert "by_regime" in data
        assert "by_session" in data
        assert "top_block_reasons" in data
        assert data["period_hours"] == 24

    @patch("diagnose_funnel.db._get_conn")
    def test_pass_rate_calculated(self, mock_get_conn):
        mock_get_conn.return_value = _mock_conn_with_data()
        data = get_funnel_data(hours=24)

        # 10 passed out of 140 total = 7.1%
        assert data["total_decisions"] == 140
        assert data["passed"] == 10
        assert 7.0 <= data["pass_rate_pct"] <= 7.2

    @patch("diagnose_funnel.db._get_conn")
    def test_empty_data(self, mock_get_conn):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        mock_get_conn.return_value = conn
        data = get_funnel_data(hours=24)

        assert data["total_decisions"] == 0
        assert data["passed"] == 0
        assert data["pass_rate_pct"] == 0


class TestGetFunnelJson:
    """get_funnel_json retorna JSON valido."""

    @patch("diagnose_funnel.db._get_conn")
    def test_returns_valid_json(self, mock_get_conn):
        mock_get_conn.return_value = _mock_conn_with_data()
        result = get_funnel_json(hours=24)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "funnel" in parsed
