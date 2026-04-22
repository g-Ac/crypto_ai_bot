"""Pair trader — decision logic. Pure function over SpreadSnapshot.

decide() is called every cycle; returns PairDecision that the executor
translates into actions on state.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pair_trading.config import PairConfig
from pair_trading.spread_calculator import SpreadSnapshot


class PairAction(str, Enum):
    NO_ACTION = "no_action"
    OPEN_LONG_BTC_SHORT_ETH = "open_long_btc_short_eth"
    OPEN_SHORT_BTC_LONG_ETH = "open_short_btc_long_eth"
    CLOSE_TP = "close_tp"
    CLOSE_SL = "close_sl"
    CLOSE_TIMEOUT = "close_timeout"
    HOLD = "hold"


@dataclass(frozen=True)
class PairPosition:
    """Represents an open pair position (minimal for decision logic)."""
    direction: PairAction  # one of OPEN_LONG_BTC_SHORT_ETH or OPEN_SHORT_BTC_LONG_ETH
    entry_z: float
    candles_held: int  # count of candles since entry (incremented by executor each cycle)


@dataclass(frozen=True)
class PairDecision:
    action: PairAction
    blocked_by: Optional[str] = None
    trigger_reason: Optional[str] = None


def decide(
    snapshot: SpreadSnapshot,
    position: Optional[PairPosition],
    config: PairConfig,
    circuit_breaker_active: bool = False,
) -> PairDecision:
    # Invalid snapshot → no action regardless of state
    if not snapshot.is_valid:
        return PairDecision(PairAction.NO_ACTION, blocked_by="invalid_zscore")

    # Position management (exit logic) — implemented in Task 6
    if position is not None:
        return _decide_exit(snapshot, position, config)

    # Entry logic
    if circuit_breaker_active:
        return PairDecision(PairAction.NO_ACTION, blocked_by="circuit_breaker")

    z = snapshot.z_score
    abs_z = abs(z)

    if abs_z < config.entry_z:
        return PairDecision(PairAction.NO_ACTION, blocked_by="z_below_threshold")

    if abs_z > config.entry_max_z:
        return PairDecision(PairAction.NO_ACTION, blocked_by="z_above_entry_guard")

    # Valid entry zone: config.entry_z <= |z| <= config.entry_max_z
    if z > 0:
        return PairDecision(
            PairAction.OPEN_SHORT_BTC_LONG_ETH,
            trigger_reason=f"z={z:.2f}>=+{config.entry_z}",
        )
    else:
        return PairDecision(
            PairAction.OPEN_LONG_BTC_SHORT_ETH,
            trigger_reason=f"z={z:.2f}<=-{config.entry_z}",
        )


def _decide_exit(
    snapshot: SpreadSnapshot,
    position: PairPosition,
    config: PairConfig,
) -> PairDecision:
    """Exit priority: SL > TIMEOUT > TP."""
    abs_z = abs(snapshot.z_score)

    # 1. SL
    if abs_z >= config.exit_sl_z:
        return PairDecision(
            PairAction.CLOSE_SL,
            trigger_reason=f"|z|={abs_z:.2f}>={config.exit_sl_z}",
        )

    # 2. TIMEOUT
    if position.candles_held >= config.time_stop_candles:
        return PairDecision(
            PairAction.CLOSE_TIMEOUT,
            trigger_reason=f"candles_held={position.candles_held}>={config.time_stop_candles}",
        )

    # 3. TP
    if abs_z <= config.exit_tp_z:
        return PairDecision(
            PairAction.CLOSE_TP,
            trigger_reason=f"tp: |z|={abs_z:.2f}<={config.exit_tp_z}",
        )

    return PairDecision(PairAction.HOLD)
