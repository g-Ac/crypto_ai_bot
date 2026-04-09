"""
Testes unitarios para o sistema de confluencia V2.

Cobre:
- VOLATILE com M2 forte (score >= 60) -> permite trade (SOLO)
- VOLATILE com M2 fraco (score < 60) -> bloqueia
- 2 motores (WEAK_TREND) com 2/2 confirmacao -> permite
- 2 motores (WEAK_TREND) com 1/2 confirmacao -> bloqueia
- 3 motores (TRENDING) com 2/3 e 3/3 -> permite
- 3 motores (TRENDING) com 1/3 -> bloqueia
- Sinais opostos -> bloqueia
- CHOPPY -> nenhum motor, bloqueia
- _get_prev_basis retorna penultimo registro
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from signal_types import Direction, Signal, ConfluenceResult, ScalpingConfig
from confluence import analyze


def _make_signal(direction: Direction, valid: bool, score: int = 50, source: str = "test") -> Signal:
    return Signal(
        direction=direction,
        strength=score / 100.0,
        timestamp="2026-04-08T10:00:00",
        source=source,
        symbol="BTCUSDT",
        price=70000.0,
        valid=valid,
        reason="test signal",
        metadata={"score_total": score},
    )


@pytest.fixture
def config():
    return ScalpingConfig(min_confluence_score=2)


# ── VOLATILE (1 motor: M2) ──────────────────────────────────────────────

class TestVolatileSingleMotor:
    """VOLATILE regime: only M2 runs. Allow if score >= 60."""

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_volatile_strong_m2_allows_trade(self, mock_basis, mock_funding, mock_liq, config):
        mock_liq.analyze.return_value = _make_signal(Direction.LONG, valid=True, score=70, source="liquidation")
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data={"some": "data"},
            regime="VOLATILE",
        )
        assert result.direction == Direction.LONG
        assert result.score == 1
        assert result.meets_threshold is True
        assert result.position_size_pct == 30.0
        assert result.leverage == 2
        assert "SOLO" in result.reason

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_volatile_weak_m2_blocked(self, mock_basis, mock_funding, mock_liq, config):
        mock_liq.analyze.return_value = _make_signal(Direction.LONG, valid=True, score=45, source="liquidation")
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data={"some": "data"},
            regime="VOLATILE",
        )
        assert result.meets_threshold is False
        assert result.direction == Direction.NEUTRAL
        assert "continuous_score" in result.reason

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_volatile_invalid_m2_no_signal(self, mock_basis, mock_funding, mock_liq, config):
        mock_liq.analyze.return_value = _make_signal(Direction.NEUTRAL, valid=False, score=0, source="liquidation")
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data={"some": "data"},
            regime="VOLATILE",
        )
        assert result.direction == Direction.NEUTRAL
        assert result.meets_threshold is False


# ── 2 motors (WEAK_TREND: M1 + M3) ─────────────────────────────────────

class TestTwoMotorRegime:
    """WEAK_TREND: M1 + M3. Need 2/2 to pass."""

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_two_motors_both_agree(self, mock_basis, mock_funding, mock_liq, config):
        mock_funding.analyze.return_value = _make_signal(Direction.SHORT, valid=True, score=60, source="funding")
        mock_basis.analyze.return_value = _make_signal(Direction.SHORT, valid=True, score=55, source="basis")
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data={"some": "data"},
            regime="WEAK_TREND",
        )
        assert result.direction == Direction.SHORT
        assert result.score == 2
        assert result.position_size_pct == 50.0
        assert result.leverage == 3

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_two_motors_only_one_valid(self, mock_basis, mock_funding, mock_liq, config):
        mock_funding.analyze.return_value = _make_signal(Direction.SHORT, valid=True, score=60, source="funding")
        mock_basis.analyze.return_value = _make_signal(Direction.NEUTRAL, valid=False, score=0, source="basis")
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data={"some": "data"},
            regime="WEAK_TREND",
        )
        assert result.meets_threshold is False
        assert "insuficiente" in result.reason

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_two_motors_opposite_signals(self, mock_basis, mock_funding, mock_liq, config):
        mock_funding.analyze.return_value = _make_signal(Direction.SHORT, valid=True, score=60, source="funding")
        mock_basis.analyze.return_value = _make_signal(Direction.LONG, valid=True, score=55, source="basis")
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data={"some": "data"},
            regime="WEAK_TREND",
        )
        assert result.direction == Direction.NEUTRAL
        assert "opostos" in result.reason.lower()


# ── 3 motors (TRENDING: M1 + M2 + M3) ──────────────────────────────────

class TestThreeMotorRegime:
    """TRENDING: M1 + M2 + M3. Need 2/3 minimum."""

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_three_motors_all_agree(self, mock_basis, mock_funding, mock_liq, config):
        mock_funding.analyze.return_value = _make_signal(Direction.LONG, valid=True, score=70, source="funding")
        mock_liq.analyze.return_value = _make_signal(Direction.LONG, valid=True, score=65, source="liquidation")
        mock_basis.analyze.return_value = _make_signal(Direction.LONG, valid=True, score=60, source="basis")
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data={"some": "data"},
            regime="TRENDING",
        )
        assert result.direction == Direction.LONG
        assert result.score == 3
        assert result.position_size_pct == 100.0
        assert result.leverage == 5
        assert "ALTO" in result.reason

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_three_motors_two_agree(self, mock_basis, mock_funding, mock_liq, config):
        mock_funding.analyze.return_value = _make_signal(Direction.LONG, valid=True, score=70, source="funding")
        mock_liq.analyze.return_value = _make_signal(Direction.LONG, valid=True, score=65, source="liquidation")
        mock_basis.analyze.return_value = _make_signal(Direction.NEUTRAL, valid=False, score=0, source="basis")
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data={"some": "data"},
            regime="TRENDING",
        )
        assert result.direction == Direction.LONG
        assert result.score == 2
        assert result.position_size_pct == 50.0

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_three_motors_only_one_valid(self, mock_basis, mock_funding, mock_liq, config):
        mock_funding.analyze.return_value = _make_signal(Direction.LONG, valid=True, score=70, source="funding")
        mock_liq.analyze.return_value = _make_signal(Direction.NEUTRAL, valid=False, score=0, source="liquidation")
        mock_basis.analyze.return_value = _make_signal(Direction.NEUTRAL, valid=False, score=0, source="basis")
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data={"some": "data"},
            regime="TRENDING",
        )
        assert result.meets_threshold is False
        assert "insuficiente" in result.reason


# ── CHOPPY (no motors) ──────────────────────────────────────────────────

class TestChoppyRegime:
    """CHOPPY: no motors allowed."""

    def test_choppy_blocked(self, config):
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data={"some": "data"},
            regime="CHOPPY",
        )
        assert result.direction == Direction.NEUTRAL
        assert result.meets_threshold is False
        assert "nenhum motor" in result.reason.lower()


# ── No market data ──────────────────────────────────────────────────────

class TestNoMarketData:
    """Missing market_data -> safe fallback."""

    def test_no_data(self, config):
        result = analyze(
            symbol="BTCUSDT",
            config=config,
            market_data=None,
            regime="TRENDING",
        )
        assert result.direction == Direction.NEUTRAL
        assert result.meets_threshold is False


# ── _get_prev_basis (penultimate record) ────────────────────────────────

class TestGetPrevBasis:
    """_get_prev_basis must return the penultimate record, not the latest."""

    @patch("scalping_trader.db")
    def test_returns_penultimate(self, mock_db):
        from scalping_trader import _get_prev_basis

        mock_conn = MagicMock()
        mock_db._get_conn.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = (0.045,)

        result = _get_prev_basis("BTCUSDT")

        assert result == 0.045
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        assert "OFFSET 1" in sql

    @patch("scalping_trader.db")
    def test_returns_none_if_no_penultimate(self, mock_db):
        from scalping_trader import _get_prev_basis

        mock_conn = MagicMock()
        mock_db._get_conn.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None

        result = _get_prev_basis("BTCUSDT")
        assert result is None

    @patch("scalping_trader.db")
    def test_returns_none_on_exception(self, mock_db):
        from scalping_trader import _get_prev_basis

        mock_db._get_conn.side_effect = Exception("DB error")
        result = _get_prev_basis("BTCUSDT")
        assert result is None


# ── Integration: SOLO gate nao bloqueia a si mesmo ──────────────────────

class TestSoloGateIntegration:
    """Verifica que a regra SOLO nao e bloqueada pelo proprio meets_threshold."""

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_solo_trade_not_blocked_by_own_gate(self, mock_basis, mock_funding, mock_liq, config):
        """Simula o fluxo completo: VOLATILE + M2 forte deve produzir
        meets_threshold=True para que scalping_trader nao bloqueie."""
        mock_liq.analyze.return_value = _make_signal(
            Direction.SHORT, valid=True, score=75, source="liquidation",
        )
        result = analyze(
            symbol="ETHUSDT",
            config=config,
            market_data={"some": "data"},
            regime="VOLATILE",
        )
        # O trade deve estar aprovado de ponta a ponta
        assert result.direction == Direction.SHORT
        assert result.score == 1
        assert result.meets_threshold is True
        assert result.position_size_pct > 0
        assert result.leverage > 0
        # scalping_trader checa `if not confluence.meets_threshold` —
        # com meets_threshold=True, o trade nao sera bloqueado

    @patch("confluence._liquidation_engine")
    @patch("confluence._funding_engine")
    @patch("confluence._basis_engine")
    def test_solo_weak_correctly_rejected(self, mock_basis, mock_funding, mock_liq, config):
        """M2 fraco no VOLATILE: meets_threshold deve ser False."""
        mock_liq.analyze.return_value = _make_signal(
            Direction.SHORT, valid=True, score=40, source="liquidation",
        )
        result = analyze(
            symbol="ETHUSDT",
            config=config,
            market_data={"some": "data"},
            regime="VOLATILE",
        )
        assert result.meets_threshold is False
        assert result.position_size_pct == 0
