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
