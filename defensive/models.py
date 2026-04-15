"""Dataclasses / interfaces for the defensive trading subsystem.

These are the contracts between modules. Every module communicates
through these structures — no raw dicts crossing boundaries.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from defensive.enums import (
    Direction,
    ExitReason,
    Feature,
    Outcome,
    Regime,
    Session,
    Strategy,
    TrapEvidence,
)


# ---------------------------------------------------------------------------
# Pipeline intermediaries
# ---------------------------------------------------------------------------

@dataclass
class CompressionState:
    """Output of compression_detector."""

    active: bool = False
    bb_width_current: float = 0.0
    bb_width_percentile: float = 100.0
    consecutive_decline: int = 0
    atr_declining: bool = False
    volume_stable: bool = False
    since: str = ""  # ISO timestamp when compression started


@dataclass
class BreakoutEvent:
    """Output of breakout_detector."""

    detected: bool = False
    direction: Direction = Direction.NEUTRAL
    price: float = 0.0
    volume_ratio: float = 0.0
    bb_level: float = 0.0  # BB band that was breached
    timestamp: str = ""
    candle_index: int = 0


@dataclass
class TrapResult:
    """Output of trap_detector (Enhanced only)."""

    confirmed: bool = False
    score: int = 0
    evidence: List[TrapEvidence] = field(default_factory=list)
    available_evidence: List[Feature] = field(default_factory=list)
    missing_evidence: List[Feature] = field(default_factory=list)
    degraded: bool = False

    # Individual trap flags
    oi_expanded: bool = False
    oi_declining: bool = False
    liq_in_breakout_dir: float = 0.0
    funding_crowded: bool = False
    basis_diverged: bool = False


@dataclass
class FeatureAvailability:
    """Tracks which data sources are fresh enough to use."""

    oi: bool = False
    liquidations: bool = False
    liq_is_proxy: bool = False
    funding: bool = False
    ls_ratio: bool = False
    basis: bool = False
    candles_15m: bool = False
    candles_5m: bool = False
    candles_1h: bool = False
    regime: bool = False

    @property
    def min_viable(self) -> bool:
        """Minimum for operation: candles + regime + at least 2 micro sources."""
        micro_count = sum([self.oi, self.liquidations, self.funding, self.basis])
        return self.candles_15m and self.regime and micro_count >= 2

    @property
    def available_list(self) -> List[Feature]:
        out: list[Feature] = []
        if self.oi:
            out.append(Feature.OI)
        if self.liquidations:
            out.append(Feature.LIQUIDATIONS)
        if self.funding:
            out.append(Feature.FUNDING)
        if self.ls_ratio:
            out.append(Feature.LS_RATIO)
        if self.basis:
            out.append(Feature.BASIS)
        if self.candles_15m:
            out.append(Feature.CANDLES_15M)
        if self.candles_5m:
            out.append(Feature.CANDLES_5M)
        if self.candles_1h:
            out.append(Feature.CANDLES_1H)
        if self.regime:
            out.append(Feature.REGIME)
        return out

    @property
    def missing_list(self) -> List[Feature]:
        all_features = {Feature.OI, Feature.LIQUIDATIONS, Feature.FUNDING,
                        Feature.LS_RATIO, Feature.BASIS, Feature.CANDLES_15M,
                        Feature.CANDLES_5M, Feature.CANDLES_1H, Feature.REGIME}
        return sorted(all_features - set(self.available_list), key=lambda f: f.value)


# ---------------------------------------------------------------------------
# Value reference (shared between CFER and RAVR)
# ---------------------------------------------------------------------------

@dataclass
class ValueMetrics:
    """Output of value_reference module."""

    vwap: float = 0.0
    z_score: float = 0.0
    bb_mid: float = 0.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_width_pct: float = 0.0
    atr: float = 0.0
    atr_pct: float = 0.0


# ---------------------------------------------------------------------------
# Trade decision (output of the full pipeline)
# ---------------------------------------------------------------------------

@dataclass
class TradeDecision:
    """Complete record of a pipeline evaluation — trade or no-trade."""

    timestamp: str = ""
    cycle_id: str = ""
    symbol: str = ""
    strategy: Strategy = Strategy.CFER_BASELINE
    outcome: Outcome = Outcome.NO_COMPRESSION

    # Pipeline state
    compression: CompressionState = field(default_factory=CompressionState)
    breakout: BreakoutEvent = field(default_factory=BreakoutEvent)
    trap: TrapResult = field(default_factory=TrapResult)
    reclaim_detected: bool = False

    # Context
    regime: Regime = Regime.UNKNOWN
    session: Session = Session.DEAD
    features: FeatureAvailability = field(default_factory=FeatureAvailability)

    # Entry details (populated only when outcome == TRADE)
    direction: Direction = Direction.NEUTRAL
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0
    position_size_usd: float = 0.0
    leverage: int = 1

    # RAVR-specific
    z_score: float = 0.0
    vwap_distance_pct: float = 0.0

    # Risk state at decision time
    daily_loss_pct: float = 0.0
    weekly_loss_pct: float = 0.0
    consecutive_losses: int = 0
    open_positions: int = 0

    # Microstructure snapshot
    oi_change_1h_pct: float = 0.0
    funding_rate: float = 0.0
    basis_spread_pct: float = 0.0

    # Versioning
    config_version: str = ""
    param_version: str = ""
    git_sha: str = ""


# ---------------------------------------------------------------------------
# Closed trade record
# ---------------------------------------------------------------------------

@dataclass
class ClosedTrade:
    """Record of a completed trade with full audit trail."""

    timestamp_open: str = ""
    timestamp_close: str = ""
    symbol: str = ""
    strategy: Strategy = Strategy.CFER_BASELINE
    direction: Direction = Direction.NEUTRAL

    # Prices
    entry_price: float = 0.0
    exit_price: float = 0.0
    sl_price: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0

    # Position
    position_size_usd: float = 0.0
    leverage: int = 1

    # Result
    pnl_pct: float = 0.0
    pnl_usd: float = 0.0
    exit_reason: ExitReason = ExitReason.TIMEOUT
    duration_candles: int = 0
    capital_after: float = 0.0

    # Costs
    total_fees: float = 0.0
    total_slippage: float = 0.0

    # MAE / MFE (max adverse / favorable excursion during trade)
    mae_pct: float = 0.0
    mfe_pct: float = 0.0

    # Context at entry
    regime: Regime = Regime.UNKNOWN
    session: Session = Session.DEAD

    # CFER specifics
    compression_percentile: float = 0.0
    compression_candles: int = 0
    breakout_direction: Direction = Direction.NEUTRAL
    breakout_volume_ratio: float = 0.0
    trap_score: int = 0
    trap_evidence: List[TrapEvidence] = field(default_factory=list)

    # RAVR specifics
    z_score: float = 0.0
    vwap_distance_pct: float = 0.0

    # Microstructure snapshot at entry
    oi_change_1h_pct: float = 0.0
    funding_rate: float = 0.0
    basis_spread_pct: float = 0.0
    liquidation_vol_long: float = 0.0
    liquidation_vol_short: float = 0.0

    # Versioning
    config_version: str = ""
    param_version: str = ""
    git_sha: str = ""


# ---------------------------------------------------------------------------
# Backtest run metadata
# ---------------------------------------------------------------------------

@dataclass
class BacktestRunMeta:
    """Metadata saved with every backtest execution."""

    run_id: str = ""
    timestamp: str = ""
    strategy: Strategy = Strategy.CFER_BASELINE
    config_hash: str = ""
    param_version: str = ""
    git_sha: str = ""
    dataset_id: str = ""
    period_start: str = ""
    period_end: str = ""

    # Coverage report
    coverage_ohlcv_pct: float = 0.0
    coverage_oi_pct: float = 0.0
    coverage_liquidations_pct: float = 0.0
    coverage_funding_pct: float = 0.0
    coverage_basis_pct: float = 0.0
    candles_total: int = 0
    candles_eligible_enhanced: int = 0
    candles_eligible_enhanced_pct: float = 0.0
    gaps_detected: int = 0
    gap_details: str = ""  # JSON list of gap periods
