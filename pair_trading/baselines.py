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


def random_trader_pf_distribution(
    prices: np.ndarray,
    n_trades: int,
    avg_hold: int,
    n_runs: int = 100,
    seed: int = 42,
) -> list:
    """Simulate a random trader N runs and return list of PFs.

    Each run executes n_trades with random entry timestamps, random direction
    (long/short), and fixed holding period of avg_hold candles. Fees not applied
    (gross baseline).
    """
    prices = np.asarray(prices, dtype=np.float64)
    n = len(prices)
    if n < avg_hold + 1 or n_trades <= 0:
        return [0.0] * n_runs

    rng = np.random.default_rng(seed)
    pfs = []
    for _ in range(n_runs):
        pnls = []
        for _ in range(n_trades):
            # Random entry index in [0, n - avg_hold - 1]
            entry_idx = int(rng.integers(0, n - avg_hold))
            exit_idx = entry_idx + avg_hold
            direction = 1 if rng.random() < 0.5 else -1
            ret = (prices[exit_idx] - prices[entry_idx]) / prices[entry_idx] * direction * 100.0
            pnls.append(ret)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gw = sum(wins)
        gl = abs(sum(losses))
        if gl == 0:
            pf = float("inf") if gw > 0 else 0.0
        else:
            pf = gw / gl
        pfs.append(pf)
    return pfs
