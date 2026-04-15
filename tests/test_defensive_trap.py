"""Tests for defensive/trap_detector.py — Enhanced only."""
import pytest

from defensive.config import DefensiveConfig
from defensive.enums import Direction, Feature, TrapEvidence
from defensive.models import BreakoutEvent, FeatureAvailability, TrapResult
from defensive.trap_detector import detect_trap


def _full_features() -> FeatureAvailability:
    return FeatureAvailability(
        oi=True, liquidations=True, funding=True,
        ls_ratio=True, basis=True, candles_15m=True,
        candles_1h=True, regime=True,
    )


def _micro_at_breakout(**overrides) -> dict:
    base = {
        "oi_change_1h_pct": 0.0,
        "basis_spread_pct": 0.0,
    }
    base.update(overrides)
    return base


def _micro_after_reclaim(**overrides) -> dict:
    base = {
        "oi_change_1h_pct": 0.0,
        "funding_rate": 0.0,
        "ls_ratio_top": 1.0,
        "liquidation_vol_long": 0.0,
        "liquidation_vol_short": 0.0,
        "liquidation_is_proxy": False,
        "basis_spread_pct": 0.0,
    }
    base.update(overrides)
    return base


@pytest.fixture
def config():
    return DefensiveConfig()


@pytest.fixture
def long_breakout():
    return BreakoutEvent(detected=True, direction=Direction.LONG, price=101.0)


@pytest.fixture
def short_breakout():
    return BreakoutEvent(detected=True, direction=Direction.SHORT, price=99.0)


class TestDetectTrap:
    def test_no_breakout_returns_empty(self, config):
        result = detect_trap(
            BreakoutEvent(detected=False), None, None,
            _full_features(), config,
        )
        assert result.confirmed is False
        assert result.score == 0

    def test_no_micro_data_returns_degraded(self, config, long_breakout):
        result = detect_trap(
            long_breakout, None, None,
            _full_features(), config,
        )
        assert result.degraded is True
        assert result.confirmed is False

    def test_oi_trap_scores_35(self, config, long_breakout):
        """OI expanded at breakout then declining after reclaim → OI trap."""
        micro_at = _micro_at_breakout(oi_change_1h_pct=0.5)  # > 0.3 threshold
        micro_after = _micro_after_reclaim(oi_change_1h_pct=-0.2)  # declining

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert TrapEvidence.OI_TRAP in result.evidence
        assert result.oi_expanded is True
        assert result.oi_declining is True

    def test_liquidation_trap_scores_30(self, config, long_breakout):
        """Liquidations in breakout direction after reclaim → liq trap."""
        micro_at = _micro_at_breakout()
        micro_after = _micro_after_reclaim(
            liquidation_vol_long=60_000,  # > 50k threshold
            liquidation_is_proxy=False,
        )

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert TrapEvidence.LIQUIDATION_TRAP in result.evidence

    def test_proxy_liq_capped_at_20(self, config, long_breakout):
        """Proxy liquidation data caps weight at 20, not 30."""
        micro_at = _micro_at_breakout()
        micro_after = _micro_after_reclaim(
            liquidation_vol_long=60_000,
            liquidation_is_proxy=True,
        )

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert TrapEvidence.LIQUIDATION_TRAP in result.evidence
        # Only proxy liq (20) — not enough for confirmation by itself
        assert result.score == 20

    def test_crowding_trap_via_funding(self, config, long_breakout):
        """High funding on long breakout = crowding."""
        micro_at = _micro_at_breakout()
        micro_after = _micro_after_reclaim(funding_rate=0.0005)  # >> 0.0001

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert TrapEvidence.CROWDING_TRAP in result.evidence
        assert result.funding_crowded is True

    def test_crowding_trap_via_ls_ratio(self, config, long_breakout):
        """High LS ratio on long breakout = crowding."""
        features = _full_features()
        features.funding = False  # Disable funding to isolate LS
        micro_at = _micro_at_breakout()
        micro_after = _micro_after_reclaim(ls_ratio_top=2.0)  # > 1.5

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            features, config,
        )
        assert TrapEvidence.CROWDING_TRAP in result.evidence

    def test_basis_trap_long(self, config, long_breakout):
        """Basis expanded on long breakout then reverted → basis trap."""
        micro_at = _micro_at_breakout(basis_spread_pct=0.05)  # > 0.03
        micro_after = _micro_after_reclaim(basis_spread_pct=0.01)  # < 0.05

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert TrapEvidence.BASIS_TRAP in result.evidence
        assert result.basis_diverged is True

    def test_full_trap_confirmation_score_ge_60(self, config, long_breakout):
        """OI(35) + Liq(30) = 65 → confirmed regardless."""
        micro_at = _micro_at_breakout(oi_change_1h_pct=0.5)
        micro_after = _micro_after_reclaim(
            oi_change_1h_pct=-0.2,
            liquidation_vol_long=60_000,
            liquidation_is_proxy=False,
        )

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert result.confirmed is True
        assert result.score >= 60

    def test_primary_plus_score_ge_30_confirms(self, config, long_breakout):
        """OI(35) alone = score 35 with primary → confirmed."""
        micro_at = _micro_at_breakout(oi_change_1h_pct=0.5)
        micro_after = _micro_after_reclaim(oi_change_1h_pct=-0.2)

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert result.confirmed is True
        assert TrapEvidence.OI_TRAP in result.evidence

    def test_no_primary_needs_higher_score(self, config, long_breakout):
        """Crowding(25) alone = 25 < 40 (no primary threshold) → NOT confirmed."""
        micro_at = _micro_at_breakout()
        micro_after = _micro_after_reclaim(funding_rate=0.0005)

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert result.confirmed is False
        assert result.score == 25

    def test_no_primary_with_enough_score_confirms(self, config, long_breakout):
        """Crowding(25) + Basis(15) = 40 without primary → confirmed."""
        micro_at = _micro_at_breakout(basis_spread_pct=0.05)
        micro_after = _micro_after_reclaim(
            funding_rate=0.0005,
            basis_spread_pct=0.01,
        )

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert result.confirmed is True
        assert result.score >= 40

    def test_short_breakout_uses_short_liq(self, config, short_breakout):
        """Short breakout should check short-side liquidations."""
        micro_at = _micro_at_breakout()
        micro_after = _micro_after_reclaim(
            liquidation_vol_short=60_000,
            liquidation_is_proxy=False,
        )

        result = detect_trap(
            short_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert TrapEvidence.LIQUIDATION_TRAP in result.evidence

    def test_short_breakout_crowding_negative_funding(self, config, short_breakout):
        """Negative funding on short breakout = crowding."""
        micro_at = _micro_at_breakout()
        micro_after = _micro_after_reclaim(funding_rate=-0.0005)

        result = detect_trap(
            short_breakout, micro_at, micro_after,
            _full_features(), config,
        )
        assert TrapEvidence.CROWDING_TRAP in result.evidence

    def test_missing_features_tracked(self, config, long_breakout):
        """Features not available should be in missing_evidence."""
        features = FeatureAvailability(
            oi=True, liquidations=False, funding=False,
            candles_15m=True, regime=True,
        )
        micro_at = _micro_at_breakout(oi_change_1h_pct=0.5)
        micro_after = _micro_after_reclaim(oi_change_1h_pct=-0.2)

        result = detect_trap(
            long_breakout, micro_at, micro_after,
            features, config,
        )
        assert Feature.LIQUIDATIONS in result.missing_evidence
        assert Feature.FUNDING in result.missing_evidence
        assert Feature.OI in result.available_evidence
