"""Baseline strategies for comparison with pair trading edge."""
from __future__ import annotations

import numpy as np


def buy_and_hold_pf(prices: np.ndarray) -> float:
    """Profit factor of a buy-and-hold position over the full price series.

    Interpreted as one single trade: entry at prices[0], exit at prices[-1].
    PF = gross_win / gross_loss (pair of infinite or zero edge cases).
    """
    prices = np.asarray(prices, dtype=np.float64)
    if len(prices) < 2:
        return 0.0
    total_return = (prices[-1] - prices[0]) / prices[0]
    if total_return > 0:
        return float("inf")
    return 0.0


def random_trader_pf_distribution(*args, **kwargs):
    """Stub — implemented in Task 12."""
    raise NotImplementedError("Task 12 implements this function")
