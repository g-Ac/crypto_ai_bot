"""Cumulative return spread + z-score + correlation.

Pure functions. No I/O, no state. Input: two aligned price arrays.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class SpreadSnapshot:
    cum_spread: float
    rolling_mean: float
    rolling_std: float
    z_score: float
    correlation: float
    is_valid: bool


def _is_clean(arr: np.ndarray) -> bool:
    return (
        np.isfinite(arr).all()
        and (arr > 0).all()
    )


def _cum_spread_series(btc: np.ndarray, eth: np.ndarray, window: int) -> np.ndarray:
    """Return array of cum_spread values for each t where it's defined.

    cum_spread(t) = log(btc[t]/btc[t-window]) - log(eth[t]/eth[t-window])
    Result length = len(btc) - window.
    """
    log_btc = np.log(btc)
    log_eth = np.log(eth)
    # For each t in [window, len-1], compute log(btc[t]/btc[t-window]) - same for eth
    return (log_btc[window:] - log_btc[:-window]) - (log_eth[window:] - log_eth[:-window])


def compute_snapshot(
    btc: np.ndarray,
    eth: np.ndarray,
    window: int,
    zscore_window: int,
) -> SpreadSnapshot:
    """Compute current SpreadSnapshot from aligned price arrays.

    Returns SpreadSnapshot with is_valid=False if math is undefined.
    Never raises — caller uses is_valid to decide.
    """
    btc = np.asarray(btc, dtype=np.float64)
    eth = np.asarray(eth, dtype=np.float64)

    required = window + zscore_window
    if len(btc) < required or len(eth) < required:
        return SpreadSnapshot(0.0, 0.0, 0.0, float("nan"), 0.0, False)

    if not (_is_clean(btc) and _is_clean(eth)):
        return SpreadSnapshot(0.0, 0.0, 0.0, float("nan"), 0.0, False)

    spread_series = _cum_spread_series(btc, eth, window)
    if len(spread_series) < zscore_window:
        return SpreadSnapshot(0.0, 0.0, 0.0, float("nan"), 0.0, False)

    recent = spread_series[-zscore_window:]
    mean = float(np.mean(recent))
    std = float(np.std(recent, ddof=0))
    cum_spread = float(spread_series[-1])

    # Correlation of 15m log-returns over the same window
    btc_ret = np.diff(np.log(btc[-(zscore_window + 1):]))
    eth_ret = np.diff(np.log(eth[-(zscore_window + 1):]))
    if np.std(btc_ret) == 0 or np.std(eth_ret) == 0:
        corr = 0.0
    else:
        corr = float(np.corrcoef(btc_ret, eth_ret)[0, 1])

    if std == 0.0 or not np.isfinite(std):
        return SpreadSnapshot(cum_spread, mean, std, float("nan"), corr, False)

    z = (cum_spread - mean) / std
    if not np.isfinite(z):
        return SpreadSnapshot(cum_spread, mean, std, float("nan"), corr, False)

    return SpreadSnapshot(cum_spread, mean, std, z, corr, True)
