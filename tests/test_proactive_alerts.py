"""Testes para alertas proativos."""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

import proactive_alerts as pa


@pytest.fixture(autouse=True)
def reset_cooldowns():
    """Limpa state de dedup entre testes."""
    pa._last_alert.clear()
    yield
    pa._last_alert.clear()


class TestCooldown:
    """Dedup in-memory funciona corretamente."""

    def test_first_call_allowed(self):
        assert pa._cooldown_ok("test_key", 60) is True

    def test_second_call_blocked_after_mark(self):
        pa._cooldown_ok("test_key", 60)
        pa._mark_sent("test_key")
        assert pa._cooldown_ok("test_key", 60) is False

    def test_after_cooldown_allowed(self):
        pa._mark_sent("test_key")
        pa._last_alert["test_key"] = time.time() - 2  # simula cooldown expirado
        assert pa._cooldown_ok("test_key", 1) is True

    def test_different_keys_independent(self):
        pa._cooldown_ok("key_a", 60)
        assert pa._cooldown_ok("key_b", 60) is True


class TestDrawdownCheck:
    """Drawdown warning dispara corretamente."""

    @patch("proactive_alerts.send_system_alert")
    @patch("proactive_alerts._get_current_capital", return_value=10000)
    @patch("proactive_alerts.db.get_trades_today")
    def test_drawdown_triggers_alert(self, mock_trades, mock_cap, mock_alert):
        """Perda >= 3% deve disparar alerta (pode disparar para ambos sistemas)."""
        mock_trades.return_value = [
            {"pnl_pct": -2.0, "pnl_usd": -200, "exit_reason": "sl"},
            {"pnl_pct": -1.5, "pnl_usd": -150, "exit_reason": "sl"},
        ]
        pa._check_drawdown()
        assert mock_alert.call_count >= 1
        assert "Drawdown" in mock_alert.call_args_list[0][0][0]

    @patch("proactive_alerts.send_system_alert")
    @patch("proactive_alerts._get_current_capital", return_value=10000)
    @patch("proactive_alerts.db.get_trades_today")
    def test_small_loss_no_alert(self, mock_trades, mock_cap, mock_alert):
        """Perda < 3% nao dispara."""
        mock_trades.return_value = [
            {"pnl_pct": -0.5, "pnl_usd": -50, "exit_reason": "sl"},
        ]
        pa._check_drawdown()
        mock_alert.assert_not_called()

    @patch("proactive_alerts.send_system_alert")
    @patch("proactive_alerts._get_current_capital", return_value=10000)
    @patch("proactive_alerts.db.get_trades_today")
    def test_no_trades_no_alert(self, mock_trades, mock_cap, mock_alert):
        """Sem trades nao dispara."""
        mock_trades.return_value = []
        pa._check_drawdown()
        mock_alert.assert_not_called()

    @patch("proactive_alerts.send_system_alert")
    @patch("proactive_alerts._get_current_capital", return_value=10000)
    @patch("proactive_alerts.db.get_trades_today")
    def test_drawdown_dedup(self, mock_trades, mock_cap, mock_alert):
        """Segundo alerta dentro do cooldown nao dispara."""
        mock_alert.return_value = True  # simula envio bem-sucedido
        mock_trades.return_value = [
            {"pnl_pct": -4.0, "pnl_usd": -400, "exit_reason": "sl"},
        ]
        pa._check_drawdown()
        first_count = mock_alert.call_count
        assert first_count >= 1  # pelo menos 1 sistema alertou
        # Reset mock mas nao o cooldown (mark_sent foi chamado)
        mock_alert.reset_mock()
        pa._check_drawdown()
        mock_alert.assert_not_called()  # dedup bloqueou


class TestZeroTradesCheck:
    """Zero trades 24h funciona corretamente."""

    @patch("proactive_alerts.send_system_alert")
    @patch("proactive_alerts.db._get_conn")
    def test_zero_trades_triggers_alert(self, mock_conn, mock_alert):
        """0 trades em 24h dispara alerta."""
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (0,)
        mock_conn.return_value = conn
        pa._check_zero_trades()
        mock_alert.assert_called_once()
        assert "Zero Trades" in mock_alert.call_args[0][0]

    @patch("proactive_alerts.send_system_alert")
    @patch("proactive_alerts.db._get_conn")
    def test_has_trades_no_alert(self, mock_conn, mock_alert):
        """Com trades nao dispara."""
        conn = MagicMock()
        # Primeira chamada: scalping_trades = 3
        conn.execute.return_value.fetchone.return_value = (3,)
        mock_conn.return_value = conn
        pa._check_zero_trades()
        mock_alert.assert_not_called()


class TestRepeatedErrorsCheck:
    """Erros repetidos funciona corretamente."""

    @patch("proactive_alerts.send_system_alert")
    @patch("proactive_alerts.db._get_conn")
    def test_many_errors_triggers_alert(self, mock_conn, mock_alert):
        """>=5 erros na hora dispara alerta."""
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (7,)
        mock_conn.return_value = conn
        pa._check_repeated_errors()
        mock_alert.assert_called_once()
        assert "Erros" in mock_alert.call_args[0][0]
        # critical=True
        assert mock_alert.call_args[1].get("critical") is True or mock_alert.call_args[0][2] is True

    @patch("proactive_alerts.send_system_alert")
    @patch("proactive_alerts.db._get_conn")
    def test_few_errors_no_alert(self, mock_conn, mock_alert):
        """<5 erros nao dispara."""
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (2,)
        mock_conn.return_value = conn
        pa._check_repeated_errors()
        mock_alert.assert_not_called()


class TestCheckAll:
    """check_proactive_alerts() executa todos os checks."""

    @patch("proactive_alerts._check_repeated_errors")
    @patch("proactive_alerts._check_zero_trades")
    @patch("proactive_alerts._check_drawdown")
    def test_calls_all_checks(self, mock_dd, mock_zt, mock_re):
        pa.check_proactive_alerts()
        mock_dd.assert_called_once()
        mock_zt.assert_called_once()
        mock_re.assert_called_once()
