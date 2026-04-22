"""Configuration for Pair Trading — EXP-004.

v1.0 parameters. Frozen after first backtest PASS per registry rules.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Tuple


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw == "":
        return default
    return raw in ("1", "true", "yes", "y", "t")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return default
    return float(raw)


@dataclass
class PairConfig:
    """Frozen v1.0 parameters for Pair Trading BTC/ETH."""

    # Symbols & timeframe
    symbols: Tuple[str, str] = ("BTCUSDT", "ETHUSDT")
    timeframe: str = "15m"

    # Spread / z-score windows (15m candles)
    window_candles: int = 96          # 24h
    zscore_window_candles: int = 96   # 24h

    # Entry / exit thresholds on |z|
    entry_z: float = 2.0
    entry_max_z: float = 2.9          # skip if already past SL zone
    exit_tp_z: float = 0.5
    exit_sl_z: float = 3.0

    # Time-based exit
    time_stop_candles: int = 96       # 24h

    # Capital (USD)
    capital_per_leg_usd: float = 500.0
    total_capital_usd: float = 1000.0
    max_concurrent_positions: int = 1

    # Safety
    circuit_breaker_dd_pct: float = 5.0

    # Costs
    fees_taker_pct: float = 0.04      # per leg, per side (entry+exit both legs = 0.16% RT)
    slippage_pct: float = 0.0         # paper assumption; sensitivity analysis in backtest

    # Versioning / activation
    param_version: str = "pair-trading-v1.0"
    enabled: bool = False             # default off; activated via env or explicit CLI

    def __post_init__(self) -> None:
        if self.entry_z <= 0:
            raise ValueError(f"entry_z must be > 0, got {self.entry_z}")
        if not (self.exit_tp_z < self.entry_z):
            raise ValueError(
                f"exit_tp_z < entry_z required, got {self.exit_tp_z} vs {self.entry_z}"
            )
        if not (self.entry_z < self.exit_sl_z):
            raise ValueError(
                f"entry_z < exit_sl_z required, got {self.entry_z} vs {self.exit_sl_z}"
            )
        if self.entry_max_z < self.entry_z:
            raise ValueError(
                f"entry_max_z >= entry_z required, got {self.entry_max_z} vs {self.entry_z}"
            )
        if abs(self.capital_per_leg_usd * 2 - self.total_capital_usd) > 1e-6:
            raise ValueError(
                f"capital: per_leg*2 must equal total, "
                f"got {self.capital_per_leg_usd}*2 != {self.total_capital_usd}"
            )

    @classmethod
    def from_env(cls) -> "PairConfig":
        """Construct from env vars, recomputing invariants.

        Supported overrides:
          PAIR_TRADER_ENABLED (bool)
          PAIR_CAPITAL_USD    (float) — total pool; per_leg auto-recomputed
        """
        enabled = _env_bool("PAIR_TRADER_ENABLED", default=False)
        total = _env_float("PAIR_CAPITAL_USD", default=1000.0)
        per_leg = total / 2.0
        return cls(
            enabled=enabled,
            total_capital_usd=total,
            capital_per_leg_usd=per_leg,
        )
