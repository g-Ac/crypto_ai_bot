"""ExpansionConfig — frozen parameters for EXP-005.

All thresholds and bucket mappings are a-priori, congealed before backtest.
See spec section 6 for criteria definitions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


BUCKET_ASSIGNMENT: Mapping[str, str] = {
    "BTCUSDT": "core", "ETHUSDT": "core", "SOLUSDT": "core",
    "XRPUSDT": "high_beta", "DOGEUSDT": "high_beta",
    "BNBUSDT": "high_beta", "ADAUSDT": "high_beta",
    "LINKUSDT": "infra", "AVAXUSDT": "infra", "SUIUSDT": "infra",
    "AAVEUSDT": "infra", "LTCUSDT": "infra", "NEARUSDT": "infra",
}

SLIPPAGE_BY_BUCKET: Mapping[str, float] = {
    "core": 0.03,       # majors (pct per leg)
    "high_beta": 0.07,  # high-beta liquidos
    "infra": 0.05,      # infra/DeFi
}


@dataclass(frozen=True)
class ExpansionConfig:
    """Frozen config for EXP-005. Universe must be passed in (from preflight)."""

    universe: tuple[str, ...]

    # Window
    period_main_days: int = 365
    period_holdout_days: int = 90
    n_folds: int = 12
    required_history_days: int = 455

    # Data validation
    gap_threshold_pct: float = 0.5  # max acceptable gap as pct of expected candles

    # Slippage (universal sensitivity sweep)
    slippage_universal_sensitivity: float = 0.10  # pct per leg

    # GO/NO-GO criteria thresholds (a priori — see spec section 6)
    pf_threshold_main: float = 1.25                  # criterion #1
    pf_ratio_vs_baseline: float = 1.10               # criterion #2
    dd_ratio_vs_baseline: float = 1.30               # criterion #4
    min_folds_positive: int = 9                      # criterion #5 (out of 12)
    holdout_pf_min: float = 1.0                      # criterion #8 part 1
    holdout_ratio_vs_main: float = 0.9               # criterion #8 part 2
    symbol_destructive_min_n: int = 60               # criterion #9 trigger
    symbol_destructive_max_pf: float = 0.5           # criterion #9 threshold
    slippage_collapse_min_pf: float = 1.0            # criterion #10

    # LOO tolerance
    loo_fold_outliers_tolerated: int = 1             # criterion #7 — 1 fold can fail

    def __post_init__(self):
        if not self.universe:
            raise ValueError("universe must not be empty")

    def slippage_for(self, symbol: str) -> float:
        """Return slippage pct per leg for the given symbol's bucket."""
        bucket = BUCKET_ASSIGNMENT[symbol]
        return SLIPPAGE_BY_BUCKET[bucket]

    def bucket_for(self, symbol: str) -> str:
        return BUCKET_ASSIGNMENT[symbol]
