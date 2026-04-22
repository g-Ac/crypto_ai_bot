"""Tests for spread_calculator."""
import numpy as np
import pytest
from pair_trading.spread_calculator import compute_snapshot, SpreadSnapshot


def _synthetic_prices(n, start=100.0, noise=0.0, seed=0, drift=0.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, noise, n)
    return start * np.exp(np.cumsum(rets))


def test_flat_prices_return_zero_zscore():
    btc = np.full(200, 50000.0)
    eth = np.full(200, 3000.0)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    # flat prices → cum_spread is 0, std is 0 → z is None (invalid)
    assert snap.is_valid is False


def test_divergent_prices_give_high_zscore():
    # BTC and ETH both have baseline noise; BTC gets extra drift in the last
    # 30 candles. This makes the MOST RECENT cum_spread diverge strongly
    # from its rolling-window history, producing high |z-score|.
    # Seed fixed for reproducibility.
    rng = np.random.default_rng(42)
    n = 300
    btc_ret = rng.normal(0, 0.01, n)
    eth_ret = rng.normal(0, 0.01, n)
    btc_ret[-30:] += 0.02  # late BTC outperformance
    btc = 50000.0 * np.exp(np.cumsum(btc_ret))
    eth = 3000.0 * np.exp(np.cumsum(eth_ret))
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert snap.is_valid
    assert snap.z_score > 2.0  # late divergence → elevated recent spread vs history


def test_short_history_returns_invalid():
    btc = np.full(50, 50000.0)
    eth = np.full(50, 3000.0)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert snap.is_valid is False


def test_nan_in_prices_is_invalid():
    btc = np.full(200, 50000.0)
    btc[50] = np.nan
    eth = np.full(200, 3000.0)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert snap.is_valid is False


def test_zero_in_prices_is_invalid():
    btc = np.full(200, 50000.0)
    btc[50] = 0.0
    eth = np.full(200, 3000.0)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert snap.is_valid is False


def test_cum_spread_matches_log_ratio_diff():
    # cum_spread(t) == log(BTC(t)/BTC(t-W)) - log(ETH(t)/ETH(t-W))
    btc = _synthetic_prices(200, noise=0.01, seed=1)
    eth = _synthetic_prices(200, noise=0.01, seed=2)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    expected = (np.log(btc[-1]/btc[-97]) - np.log(eth[-1]/eth[-97]))
    assert abs(snap.cum_spread - expected) < 1e-9


def test_correlation_strong_and_weak():
    # Identical series → correlation ≈ 1
    same = _synthetic_prices(200, noise=0.02, seed=3)
    snap_same = compute_snapshot(same, same, window=96, zscore_window=96)
    # cum_spread identical paths is zero → z invalid, but correlation still computed
    assert snap_same.correlation > 0.99

    # Anti-correlated series → correlation negative
    a = _synthetic_prices(200, noise=0.02, seed=4)
    b = 1.0 / a
    snap_anti = compute_snapshot(a, b, window=96, zscore_window=96)
    assert snap_anti.correlation < -0.8


def test_is_valid_true_normal_case():
    btc = _synthetic_prices(200, noise=0.01, seed=10)
    eth = _synthetic_prices(200, noise=0.01, seed=11)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert snap.is_valid
    assert not np.isnan(snap.z_score)


def test_snapshot_dataclass_immutable_fields():
    btc = _synthetic_prices(200, noise=0.01, seed=20)
    eth = _synthetic_prices(200, noise=0.01, seed=21)
    snap = compute_snapshot(btc, eth, window=96, zscore_window=96)
    assert isinstance(snap, SpreadSnapshot)
    # Required fields present
    for f in ("cum_spread", "rolling_mean", "rolling_std", "z_score",
              "correlation", "is_valid"):
        assert hasattr(snap, f)
