"""S-B capital allocation: total pool fixed, divided by |universe|, max_positions = N.

Pure functions + minimal mutable state object for backtest accounting.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def compute_slot_size(capital_pool: float, n_universe: int) -> float:
    """Capital pool divided evenly across symbols."""
    if n_universe <= 0:
        raise ValueError(f"n_universe must be positive, got {n_universe}")
    return capital_pool / n_universe


def allocate_position_size(
    *,
    slot_size_usdt: float,
    entry: float,
    sl: float,
    risk_fraction: float,
) -> float:
    """Compute position size in USDT using risk-based sizing.

    risk_in_usdt = slot_size * risk_fraction
    risk_per_unit = abs(entry - sl)
    position_size_usdt = (risk_in_usdt / risk_per_unit) * entry
    """
    risk_per_unit = abs(entry - sl)
    if risk_per_unit == 0:
        raise ValueError("entry and sl must differ")
    risk_usdt = slot_size_usdt * risk_fraction
    return (risk_usdt / risk_per_unit) * entry


@dataclass
class PortfolioState:
    """Mutable portfolio accounting during a backtest run."""
    capital_pool: float
    slot_size: float
    open_symbols: set[str] = field(default_factory=set)
    allocated: float = 0.0
    peak_concurrent: int = 0

    def can_open(self) -> bool:
        return self.allocated + self.slot_size <= self.capital_pool + 1e-9


def open_slot(state: PortfolioState, symbol: str) -> None:
    if symbol in state.open_symbols:
        raise ValueError(f"{symbol} already open")
    if not state.can_open():
        raise ValueError(f"capital pool exhausted (allocated={state.allocated}, slot={state.slot_size}, pool={state.capital_pool})")
    state.open_symbols.add(symbol)
    state.allocated += state.slot_size
    if len(state.open_symbols) > state.peak_concurrent:
        state.peak_concurrent = len(state.open_symbols)


def close_slot(state: PortfolioState, symbol: str) -> None:
    if symbol not in state.open_symbols:
        raise ValueError(f"{symbol} not open")
    state.open_symbols.remove(symbol)
    state.allocated -= state.slot_size
    if state.allocated < 0:
        state.allocated = 0.0
