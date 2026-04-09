"""
Testes unitarios para Motor 1 — Funding Rate + Long/Short Ratio.

Cobre:
- Funding extremo positivo (crowded long) -> sinal SHORT
- Funding extremo negativo (crowded short) -> sinal LONG
- Zona neutra -> sem sinal
- Proximo ao pagamento de funding -> filtrado
- L/S ratio desequilibrado -> boost de score
- Tendencia de crowding (3 periodos) -> boost de score
- Regimes diferentes -> score de regime correto
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime, timezone

from signal_types import Direction
from funding_engine import FundingEngine


def _base_market_data(**overrides) -> dict:
    """Helper: dados de microestrutura com defaults razoaveis."""
    data = {
        "timestamp": "2026-04-08 10:00:00",
        "symbol": "BTCUSDT",
        "funding_rate": 0.0005,       # 0.05% — extremo positivo
        "funding_rate_prev1": 0.0004,
        "funding_rate_prev2": 0.0003,
        "ls_ratio_top": 2.0,          # crowded long
        "ls_ratio_global": 1.3,
        "liquidation_vol_long": 0.0,
        "liquidation_vol_short": 0.0,
        "liquidation_is_proxy": True,
        "open_interest": 100000.0,
        "oi_change_1h_pct": 0.0,
        "oi_change_4h_pct": 0.0,
        "basis_spread_pct": 0.03,
        "session": "europe",
        "futures_price": 70000.0,
        "spot_price": 69979.0,
    }
    data.update(overrides)
    return data


@pytest.fixture
def engine():
    return FundingEngine()


# Far from funding payment: 10:00 UTC (next funding at 16:00 = 6h away)
FAR_FROM_FUNDING = datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc)

# Close to funding payment: 15:30 UTC (next funding at 16:00 = 30min away)
CLOSE_TO_FUNDING = datetime(2026, 4, 8, 15, 30, tzinfo=timezone.utc)


class TestFundingShort:
    """Funding extremo positivo + crowded long -> sinal SHORT."""

    def test_strong_short_signal(self, engine):
        data = _base_market_data(funding_rate=0.0005, ls_ratio_top=2.0)
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.direction == Direction.SHORT
        assert sig.valid is True
        assert sig.metadata["score_total"] >= 40

    def test_short_direction_above_threshold(self, engine):
        data = _base_market_data(funding_rate=0.0003)  # exactly at threshold
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.direction == Direction.SHORT

    def test_higher_funding_higher_score(self, engine):
        data_low = _base_market_data(funding_rate=0.0004)
        data_high = _base_market_data(funding_rate=0.001)  # 0.10%
        sig_low = engine.analyze("BTCUSDT", data_low, "RANGING", FAR_FROM_FUNDING)
        sig_high = engine.analyze("BTCUSDT", data_high, "RANGING", FAR_FROM_FUNDING)
        assert sig_high.metadata["score_total"] > sig_low.metadata["score_total"]


class TestFundingLong:
    """Funding extremo negativo + crowded short -> sinal LONG."""

    def test_strong_long_signal(self, engine):
        data = _base_market_data(
            funding_rate=-0.0005,
            funding_rate_prev1=-0.0004,
            funding_rate_prev2=-0.0003,
            ls_ratio_top=0.5,
            ls_ratio_global=0.7,
        )
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.direction == Direction.LONG
        assert sig.valid is True

    def test_long_direction_below_threshold(self, engine):
        data = _base_market_data(
            funding_rate=-0.0002,  # exactly at threshold
            ls_ratio_top=0.8,
            ls_ratio_global=0.9,
        )
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.direction == Direction.LONG


class TestNeutralZone:
    """Funding em zona neutra -> sem sinal."""

    def test_neutral_positive(self, engine):
        data = _base_market_data(funding_rate=0.0001)  # 0.01%
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.direction == Direction.NEUTRAL
        assert sig.valid is False

    def test_neutral_negative(self, engine):
        data = _base_market_data(funding_rate=-0.00005)  # -0.005%
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.direction == Direction.NEUTRAL
        assert sig.valid is False

    def test_neutral_zero(self, engine):
        data = _base_market_data(funding_rate=0.0)
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.direction == Direction.NEUTRAL


class TestFundingProximityFilter:
    """Proximo ao pagamento de funding -> filtrado."""

    def test_filtered_30min_before(self, engine):
        data = _base_market_data(funding_rate=0.0005)
        sig = engine.analyze("BTCUSDT", data, "RANGING", CLOSE_TO_FUNDING)
        assert sig.direction == Direction.NEUTRAL
        assert sig.valid is False
        assert "proximo" in sig.reason.lower() or "pagamento" in sig.reason.lower()

    def test_not_filtered_3h_before(self, engine):
        far = datetime(2026, 4, 8, 5, 0, tzinfo=timezone.utc)  # 3h before 08:00
        data = _base_market_data(funding_rate=0.0005)
        sig = engine.analyze("BTCUSDT", data, "RANGING", far)
        assert sig.direction == Direction.SHORT


class TestCrowdingTrend:
    """Tendencia de crowding nos 3 periodos afeta score."""

    def test_3_periods_increasing_short(self, engine):
        data = _base_market_data(
            funding_rate=0.0006,
            funding_rate_prev1=0.0005,
            funding_rate_prev2=0.0004,
        )
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.metadata["score_crowding"] == 20

    def test_2_periods_increasing_short(self, engine):
        data = _base_market_data(
            funding_rate=0.0006,
            funding_rate_prev1=0.0005,
            funding_rate_prev2=0.0006,  # not monotonically increasing
        )
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.metadata["score_crowding"] == 12

    def test_no_trend(self, engine):
        data = _base_market_data(
            funding_rate=0.0005,
            funding_rate_prev1=0.0006,  # decreasing
            funding_rate_prev2=0.0005,
        )
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.metadata["score_crowding"] == 5  # positive but no trend


class TestRegimeScore:
    """Score de regime varia conforme regime."""

    def test_ranging_gives_max_regime(self, engine):
        data = _base_market_data()
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.metadata["score_regime"] == 10

    def test_volatile_gives_max_regime(self, engine):
        data = _base_market_data()
        sig = engine.analyze("BTCUSDT", data, "VOLATILE", FAR_FROM_FUNDING)
        assert sig.metadata["score_regime"] == 10

    def test_trending_gives_low_regime(self, engine):
        data = _base_market_data()
        sig = engine.analyze("BTCUSDT", data, "TRENDING", FAR_FROM_FUNDING)
        assert sig.metadata["score_regime"] == 3

    def test_weak_trend_gives_mid_regime(self, engine):
        data = _base_market_data()
        sig = engine.analyze("BTCUSDT", data, "WEAK_TREND", FAR_FROM_FUNDING)
        assert sig.metadata["score_regime"] == 7


class TestLSRatioScoring:
    """L/S ratio afeta score corretamente."""

    def test_high_ls_boosts_short(self, engine):
        data = _base_market_data(ls_ratio_top=2.0, ls_ratio_global=1.3)
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.metadata["score_ls_ratio"] >= 20

    def test_neutral_ls_no_boost(self, engine):
        data = _base_market_data(ls_ratio_top=1.0, ls_ratio_global=1.0)
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.metadata["score_ls_ratio"] == 0

    def test_low_ls_boosts_long(self, engine):
        data = _base_market_data(
            funding_rate=-0.0005,
            funding_rate_prev1=-0.0004,
            funding_rate_prev2=-0.0003,
            ls_ratio_top=0.5,
            ls_ratio_global=0.7,
        )
        sig = engine.analyze("BTCUSDT", data, "RANGING", FAR_FROM_FUNDING)
        assert sig.metadata["score_ls_ratio"] >= 15


class TestMinutesToFunding:
    """Helper _minutes_to_next_funding calcula corretamente."""

    def test_before_first_funding(self, engine):
        # 23:30 UTC -> next funding at 00:00 = 30min
        t = datetime(2026, 4, 8, 23, 30, tzinfo=timezone.utc)
        assert engine._minutes_to_next_funding(t) == 30

    def test_between_fundings(self, engine):
        # 10:00 UTC -> next funding at 16:00 = 360min
        t = datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc)
        assert engine._minutes_to_next_funding(t) == 360

    def test_right_after_funding(self, engine):
        # 00:01 UTC -> next funding at 08:00 = 479min
        t = datetime(2026, 4, 8, 0, 1, tzinfo=timezone.utc)
        assert engine._minutes_to_next_funding(t) == 479
