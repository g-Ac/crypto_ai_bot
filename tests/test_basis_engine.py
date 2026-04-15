"""Testes unitarios para o Motor 3 — Basis Spread + Session Timing."""
import pytest
from datetime import datetime, timezone

from signal_types import Direction
from basis_engine import BasisEngine


def _make_market_data(
    basis_pct: float = 0.0,
    funding_rate: float = 0.0001,
    session: str = "us",
    futures_price: float = 70000.0,
    spot_price: float = 69965.0,
) -> dict:
    """Helper: cria dict no formato de collect_microstructure()."""
    return {
        "timestamp": "2026-04-08 15:00:00",
        "symbol": "BTCUSDT",
        "funding_rate": funding_rate,
        "funding_rate_prev1": 0.0001,
        "funding_rate_prev2": 0.0001,
        "ls_ratio_top": 1.0,
        "ls_ratio_global": 1.0,
        "liquidation_vol_long": 0.0,
        "liquidation_vol_short": 0.0,
        "liquidation_is_proxy": True,
        "open_interest": 100000.0,
        "oi_change_1h_pct": 0.0,
        "oi_change_4h_pct": 0.0,
        "basis_spread_pct": basis_pct,
        "session": session,
        "futures_price": futures_price,
        "spot_price": spot_price,
    }


@pytest.fixture
def engine():
    return BasisEngine()


# ── Basis alto (euforia) -> SHORT ───────────────────────────────────────

class TestBasisHighShort:
    """Basis > 0.05% com sessao ativa deve gerar sinal SHORT."""

    def test_basis_high_active_session(self, engine):
        data = _make_market_data(basis_pct=0.10, session="us")
        # 15:30 UTC = US session, 30min before 16:00 funding
        now = datetime(2026, 4, 8, 15, 30, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)

        assert sig.valid is True
        assert sig.direction == Direction.SHORT
        assert sig.strength > 0.5
        assert sig.metadata["score_magnitude"] > 0
        assert sig.metadata["score_session"] == 20  # US is active for BTC

    def test_basis_extreme_high_score(self, engine):
        data = _make_market_data(basis_pct=0.20, session="us")
        now = datetime(2026, 4, 8, 15, 50, tzinfo=timezone.utc)  # 10min to funding
        sig = engine.analyze(
            "BTCUSDT", data, regime="TRENDING", now_utc=now, prev_basis_pct=0.15,
        )

        assert sig.valid is True
        assert sig.direction == Direction.SHORT
        # Extreme basis + expanding + active session + near funding -> high score
        assert sig.metadata["score_total"] >= 60
        assert sig.metadata["score_magnitude"] == 35  # max
        assert sig.metadata["score_funding"] == 20     # <= 15min

    def test_basis_at_threshold(self, engine):
        data = _make_market_data(basis_pct=0.05, session="europe")
        now = datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)

        assert sig.valid is True
        assert sig.direction == Direction.SHORT
        assert sig.metadata["score_magnitude"] == 10  # at threshold = min score


# ── Basis negativo (panico) -> LONG ─────────────────────────────────────

class TestBasisNegativeLong:
    """Basis < -0.03% deve gerar sinal LONG."""

    def test_basis_negative_active_session(self, engine):
        data = _make_market_data(basis_pct=-0.05, session="us")
        now = datetime(2026, 4, 8, 16, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)

        assert sig.valid is True
        assert sig.direction == Direction.LONG
        assert sig.strength > 0.3

    def test_basis_contracting_increases_score(self, engine):
        """Basis subindo de -0.08 para -0.05 = contraindo = bom para LONG."""
        data = _make_market_data(basis_pct=-0.05, session="us")
        now = datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc)

        sig_no_prev = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)
        sig_with_prev = engine.analyze(
            "BTCUSDT", data, regime="TRENDING", now_utc=now, prev_basis_pct=-0.08,
        )

        assert sig_with_prev.metadata["score_velocity"] > 0
        assert sig_no_prev.metadata["score_velocity"] == 0
        assert sig_with_prev.metadata["score_total"] > sig_no_prev.metadata["score_total"]

    def test_basis_extreme_backwardation(self, engine):
        data = _make_market_data(basis_pct=-0.15, session="europe")
        now = datetime(2026, 4, 8, 8, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)

        assert sig.valid is True
        assert sig.direction == Direction.LONG
        assert sig.metadata["score_magnitude"] == 35  # max


# ── Dead zone (21:00-00:00 UTC) ────────────────────────────────────────

class TestDeadZone:
    """Dead zone filtra sinais com score < 60."""

    def test_dead_zone_low_score_filtered(self, engine):
        data = _make_market_data(basis_pct=0.06, session="dead")
        now = datetime(2026, 4, 8, 22, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)

        # Basis just above threshold + dead zone session score = 0 -> low total
        assert sig.metadata["score_session"] == 0
        # Should be filtered because score < 60 in dead zone
        assert sig.valid is False
        assert "Dead zone" in sig.metadata["filter_reason"]

    def test_dead_zone_moderate_score_passes(self, engine):
        """Moderate basis in dead zone passes with score >= 60."""
        data = _make_market_data(basis_pct=0.15, session="dead")
        # 15:50 UTC -> 10min to 16:00 funding
        now = datetime(2026, 4, 8, 15, 50, tzinfo=timezone.utc)
        sig = engine.analyze(
            "BTCUSDT", data, regime="TRENDING", now_utc=now, prev_basis_pct=0.10,
        )

        # mag~28 + velocity=25 + session=0 + funding=20 = ~73 >= 60
        assert sig.metadata["score_total"] >= 60
        assert sig.valid is True

    def test_dead_zone_high_score_passes(self, engine):
        """Extreme basis in dead zone passes with score >= 60."""
        data = _make_market_data(basis_pct=0.20, session="dead")
        # 23:50 UTC -> 10min to midnight funding
        now = datetime(2026, 4, 8, 23, 50, tzinfo=timezone.utc)
        sig = engine.analyze(
            "BTCUSDT", data, regime="TRENDING", now_utc=now, prev_basis_pct=0.15,
        )

        # mag=35 + velocity=25 + session=0 + funding=20 = 80 >= 60
        assert sig.metadata["score_total"] >= 60
        assert sig.valid is True

    def test_session_classification(self, engine):
        dead = datetime(2026, 4, 8, 22, 30, tzinfo=timezone.utc)
        assert engine._classify_session(dead) == "dead"

        asia = datetime(2026, 4, 8, 3, 0, tzinfo=timezone.utc)
        assert engine._classify_session(asia) == "asia"

        europe = datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc)
        assert engine._classify_session(europe) == "europe"

        us = datetime(2026, 4, 8, 17, 0, tzinfo=timezone.utc)
        assert engine._classify_session(us) == "us"


# ── Basis neutro -> sem sinal ───────────────────────────────────────────

class TestBasisNeutral:
    """Basis entre -0.02% e 0.03% e zona neutra."""

    def test_basis_zero(self, engine):
        data = _make_market_data(basis_pct=0.0, session="us")
        now = datetime(2026, 4, 8, 16, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)

        assert sig.valid is False
        assert sig.direction == Direction.NEUTRAL

    def test_basis_slightly_positive(self, engine):
        data = _make_market_data(basis_pct=0.02, session="us")
        now = datetime(2026, 4, 8, 16, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)

        assert sig.valid is False

    def test_basis_slightly_negative(self, engine):
        data = _make_market_data(basis_pct=-0.01, session="us")
        now = datetime(2026, 4, 8, 16, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)

        assert sig.valid is False

    def test_basis_at_neutral_boundary_high(self, engine):
        """0.03% is still neutral (inclusive upper bound)."""
        data = _make_market_data(basis_pct=0.03, session="us")
        now = datetime(2026, 4, 8, 16, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)

        assert sig.valid is False

    def test_basis_at_neutral_boundary_low(self, engine):
        """-0.02% is still neutral (inclusive lower bound)."""
        data = _make_market_data(basis_pct=-0.02, session="us")
        now = datetime(2026, 4, 8, 16, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=now)

        assert sig.valid is False


# ── Proximidade ao funding -> score aumentado ───────────────────────────

class TestFundingProximity:
    """Score de funding sobe conforme se aproxima do horario de pagamento."""

    def test_far_from_funding(self, engine):
        # 12:00 -> 4h to 16:00 funding
        now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
        assert engine._minutes_to_next_funding(now) == 240
        assert engine._score_funding_proximity(now) == 0

    def test_60min_from_funding(self, engine):
        # 15:00 -> 60min to 16:00
        now = datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc)
        assert engine._minutes_to_next_funding(now) == 60
        assert engine._score_funding_proximity(now) == 10

    def test_30min_from_funding(self, engine):
        # 15:30 -> 30min to 16:00
        now = datetime(2026, 4, 8, 15, 30, tzinfo=timezone.utc)
        assert engine._minutes_to_next_funding(now) == 30
        assert engine._score_funding_proximity(now) == 15

    def test_15min_from_funding(self, engine):
        # 15:45 -> 15min to 16:00
        now = datetime(2026, 4, 8, 15, 45, tzinfo=timezone.utc)
        assert engine._minutes_to_next_funding(now) == 15
        assert engine._score_funding_proximity(now) == 20

    def test_5min_from_funding(self, engine):
        # 15:55 -> 5min to 16:00
        now = datetime(2026, 4, 8, 15, 55, tzinfo=timezone.utc)
        assert engine._minutes_to_next_funding(now) == 5
        assert engine._score_funding_proximity(now) == 20

    def test_wraps_around_midnight(self, engine):
        # 23:30 -> 30min to 00:00 funding
        now = datetime(2026, 4, 8, 23, 30, tzinfo=timezone.utc)
        assert engine._minutes_to_next_funding(now) == 30
        assert engine._score_funding_proximity(now) == 15

    def test_funding_score_in_full_signal(self, engine):
        """Verify funding proximity increases total score in a real signal."""
        data = _make_market_data(basis_pct=0.10, session="us")

        far = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
        near = datetime(2026, 4, 8, 15, 50, tzinfo=timezone.utc)

        sig_far = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=far)
        sig_near = engine.analyze("BTCUSDT", data, regime="TRENDING", now_utc=near)

        assert sig_near.metadata["score_funding"] > sig_far.metadata["score_funding"]
        assert sig_near.metadata["score_total"] > sig_far.metadata["score_total"]


# ── Session scoring ─────────────────────────────────────────────────────

class TestSessionScoring:
    """Session score depends on asset-session alignment."""

    def test_btc_in_us_session(self, engine):
        data = _make_market_data(basis_pct=0.10, session="us")
        now = datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, now_utc=now)

        assert sig.metadata["score_session"] == 20  # US is primary for BTC

    def test_btc_in_asia_session(self, engine):
        data = _make_market_data(basis_pct=0.10, session="asia")
        now = datetime(2026, 4, 8, 3, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, now_utc=now)

        assert sig.metadata["score_session"] == 10  # Asia is non-primary for BTC

    def test_bnb_in_asia_session(self, engine):
        data = _make_market_data(basis_pct=0.10, session="asia")
        now = datetime(2026, 4, 8, 3, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BNBUSDT", data, now_utc=now)

        assert sig.metadata["score_session"] == 20  # Asia is primary for BNB

    def test_dead_session_zero(self, engine):
        data = _make_market_data(basis_pct=0.10, session="dead")
        now = datetime(2026, 4, 8, 22, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, now_utc=now)

        assert sig.metadata["score_session"] == 0


# ── Edge cases ──────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_missing_basis_returns_neutral(self, engine):
        data = _make_market_data(basis_pct=0.0)
        now = datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, now_utc=now)

        assert sig.valid is False
        assert sig.direction == Direction.NEUTRAL

    def test_unknown_symbol_uses_default_sessions(self, engine):
        data = _make_market_data(basis_pct=0.10, session="us")
        now = datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc)
        sig = engine.analyze("NEWCOINUSDT", data, now_utc=now)

        assert sig.metadata["score_session"] == 20  # default includes "us"

    def test_signal_source_is_basis_engine(self, engine):
        data = _make_market_data(basis_pct=0.10, session="us")
        now = datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc)
        sig = engine.analyze("BTCUSDT", data, now_utc=now)

        assert sig.source == "basis_engine"

    def test_velocity_negative_delta_short_zero(self, engine):
        """Basis shrinking when SHORT expected = velocity 0."""
        data = _make_market_data(basis_pct=0.06, session="us")
        now = datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc)
        sig = engine.analyze(
            "BTCUSDT", data, now_utc=now, prev_basis_pct=0.10,
        )

        assert sig.metadata["score_velocity"] == 0
