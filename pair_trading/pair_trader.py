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
    raise NotImplementedError("Implemented in Task 5 and Task 6")
