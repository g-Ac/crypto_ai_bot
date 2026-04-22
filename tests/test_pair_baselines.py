"""Tests for baselines (buy-and-hold, random trader)."""
import numpy as np
import pytest

from pair_trading.baselines import buy_and_hold_pf, random_trader_pf_distribution


def test_buy_and_hold_up_market():
    # Price doubles — buy-and-hold is very positive, PF is infinite (no losing trade)
    prices = np.array([100.0, 110.0, 120.0, 150.0, 200.0])
    pf = buy_and_hold_pf(prices)
    assert pf == float("inf")


def test_buy_and_hold_down_market():
    prices = np.array([100.0, 90.0, 80.0])
    pf = buy_and_hold_pf(prices)
    assert pf == 0.0


def test_buy_and_hold_flat_market():
    prices = np.array([100.0, 100.0, 100.0])
    pf = buy_and_hold_pf(prices)
    assert pf == 0.0


def test_random_trader_reproducible():
    prices = np.array([100.0 + i * 0.1 for i in range(300)])
    dist_a = random_trader_pf_distribution(
        prices, n_trades=10, avg_hold=5, n_runs=20, seed=42,
    )
    dist_b = random_trader_pf_distribution(
        prices, n_trades=10, avg_hold=5, n_runs=20, seed=42,
    )
    assert dist_a == dist_b


def test_random_trader_different_seed_differs():
    prices = np.array([100.0 + i * 0.1 for i in range(300)])
    dist_a = random_trader_pf_distribution(
        prices, n_trades=10, avg_hold=5, n_runs=20, seed=1,
    )
    dist_b = random_trader_pf_distribution(
        prices, n_trades=10, avg_hold=5, n_runs=20, seed=2,
    )
    assert dist_a != dist_b


def test_random_trader_percentiles_available():
    prices = np.array([100.0 + i * 0.1 for i in range(300)])
    dist = random_trader_pf_distribution(
        prices, n_trades=10, avg_hold=5, n_runs=100, seed=42,
    )
    p95 = np.percentile(dist, 95)
    p50 = np.percentile(dist, 50)
    assert p95 >= p50
