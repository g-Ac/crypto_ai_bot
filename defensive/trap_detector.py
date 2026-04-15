"""Layer 3: Trap confirmation via microstructure (Enhanced only).

Detects evidence that real money entered during the breakout
and is now trapped after the reclaim.

This module is ONLY used when enhanced_enabled=True.
The baseline pipeline skips it entirely.
"""

from __future__ import annotations

from typing import Dict, Optional

from defensive.config import DefensiveConfig
from defensive.enums import Direction, Feature, TrapEvidence
from defensive.models import BreakoutEvent, FeatureAvailability, TrapResult


def detect_trap(
    breakout: BreakoutEvent,
    micro_at_breakout: Optional[Dict],
    micro_after_reclaim: Optional[Dict],
    features: FeatureAvailability,
    config: DefensiveConfig,
) -> TrapResult:
    """Evaluate trap evidence from microstructure data.

    Args:
        breakout: The detected breakout event.
        micro_at_breakout: Microstructure snapshot during/near breakout.
        micro_after_reclaim: Microstructure snapshot after reclaim.
        features: Which data sources are available.
        config: DefensiveConfig.

    Returns:
        TrapResult with score, evidence, and availability info.
    """
    if not breakout.detected:
        return TrapResult()

    result = TrapResult(
        available_evidence=features.available_list,
        missing_evidence=features.missing_list,
        degraded=not features.min_viable,
    )

    if micro_at_breakout is None or micro_after_reclaim is None:
        result.degraded = True
        return result

    score = 0
    evidence = []
    is_long_breakout = breakout.direction == Direction.LONG

    # --- Trap A: OI Trap (primary, weight=35) ---
    if features.oi:
        oi_at = micro_at_breakout.get("oi_change_1h_pct", 0.0) or 0.0
        oi_after = micro_after_reclaim.get("oi_change_1h_pct", 0.0) or 0.0

        oi_expanded = oi_at > config.trap_oi_expand_threshold_pct
        oi_declining = oi_after < 0

        result.oi_expanded = oi_expanded
        result.oi_declining = oi_declining

        if oi_expanded and oi_declining:
            score += config.trap_weight_oi
            evidence.append(TrapEvidence.OI_TRAP)

    # --- Trap B: Liquidation Trap (primary, weight=30) ---
    if features.liquidations:
        liq_long = micro_after_reclaim.get("liquidation_vol_long", 0.0) or 0.0
        liq_short = micro_after_reclaim.get("liquidation_vol_short", 0.0) or 0.0

        # Liquidations in the breakout direction = trapped traders getting liquidated
        if is_long_breakout:
            liq_in_dir = liq_long
        else:
            liq_in_dir = liq_short

        result.liq_in_breakout_dir = liq_in_dir

        liq_is_proxy = micro_after_reclaim.get("liquidation_is_proxy", True)
        threshold = config.trap_liq_threshold_usd

        if liq_in_dir >= threshold:
            weight = config.trap_weight_liq
            if liq_is_proxy:
                weight = min(weight, 20)  # Cap proxy data at 20
            score += weight
            evidence.append(TrapEvidence.LIQUIDATION_TRAP)

    # --- Trap C: Crowding Trap (secondary, weight=25) ---
    crowding_hit = False
    if features.funding:
        funding = micro_after_reclaim.get("funding_rate", 0.0) or 0.0
        if is_long_breakout and funding > config.trap_funding_threshold:
            crowding_hit = True
            result.funding_crowded = True
        elif not is_long_breakout and funding < -config.trap_funding_threshold:
            crowding_hit = True
            result.funding_crowded = True

    if features.ls_ratio:
        ls = micro_after_reclaim.get("ls_ratio_top", 1.0) or 1.0
        if is_long_breakout and ls > config.trap_ls_ratio_long_threshold:
            crowding_hit = True
            result.funding_crowded = True
        elif not is_long_breakout and ls < config.trap_ls_ratio_short_threshold:
            crowding_hit = True
            result.funding_crowded = True

    if crowding_hit:
        score += config.trap_weight_crowding
        evidence.append(TrapEvidence.CROWDING_TRAP)

    # --- Trap D: Basis Divergence (secondary, weight=15) ---
    if features.basis:
        basis_at = micro_at_breakout.get("basis_spread_pct", 0.0) or 0.0
        basis_after = micro_after_reclaim.get("basis_spread_pct", 0.0) or 0.0

        if is_long_breakout:
            # Basis expanded on long breakout (FOMO) then reverted
            diverged = basis_at > 0.03 and basis_after < basis_at
        else:
            # Basis contracted on short breakout then reverted
            diverged = basis_at < -0.02 and basis_after > basis_at

        if diverged:
            result.basis_diverged = True
            score += config.trap_weight_basis
            evidence.append(TrapEvidence.BASIS_TRAP)

    # --- Confirmation logic ---
    result.score = score
    result.evidence = evidence

    has_primary = (TrapEvidence.OI_TRAP in evidence
                   or TrapEvidence.LIQUIDATION_TRAP in evidence)

    if score >= 60:
        result.confirmed = True
    elif score >= config.trap_min_score and has_primary:
        result.confirmed = True
    elif score >= config.trap_min_score_no_primary and not has_primary:
        result.confirmed = True
    else:
        result.confirmed = False

    return result
