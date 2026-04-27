"""Tests for walk-forward fold partitioning."""
import numpy as np
import pandas as pd
import pytest

from momentum.expansion.walk_forward import FoldData, partition_into_folds


def _df(n_candles: int, start_ms: int = 0, step_ms: int = 900_000) -> pd.DataFrame:
    return pd.DataFrame({
        "close_time_ms": np.arange(start_ms, start_ms + n_candles * step_ms, step_ms, dtype=np.int64),
        "open": np.full(n_candles, 100.0),
        "high": np.full(n_candles, 101.0),
        "low": np.full(n_candles, 99.0),
        "close": np.full(n_candles, 100.5),
        "volume": np.full(n_candles, 1000.0),
    })


def test_partition_evenly_into_n_folds():
    n_candles = 1200  # 12 folds × 100 candles each
    candles = {"BTCUSDT": _df(n_candles), "ETHUSDT": _df(n_candles)}
    folds = partition_into_folds(candles, n_folds=12)
    assert len(folds) == 12
    for fold in folds:
        assert isinstance(fold, FoldData)
        for sym in candles:
            assert len(fold.candles_by_symbol[sym]) == 100


def test_partition_handles_remainder():
    n_candles = 1205  # 12 × 100 + 5 remainder
    candles = {"BTCUSDT": _df(n_candles)}
    folds = partition_into_folds(candles, n_folds=12)
    total_candles = sum(len(f.candles_by_symbol["BTCUSDT"]) for f in folds)
    assert total_candles == 1205  # nothing dropped


def test_partition_fold_indices_sequential():
    candles = {"BTCUSDT": _df(120)}
    folds = partition_into_folds(candles, n_folds=12)
    for i, fold in enumerate(folds):
        assert fold.fold_idx == i


def test_partition_fold_boundaries_no_overlap():
    candles = {"BTCUSDT": _df(120)}
    folds = partition_into_folds(candles, n_folds=12)
    seen = set()
    for fold in folds:
        for ts in fold.candles_by_symbol["BTCUSDT"]["close_time_ms"]:
            assert ts not in seen, f"timestamp {ts} appears in multiple folds"
            seen.add(int(ts))
    assert len(seen) == 120


def test_partition_n_folds_must_be_positive():
    candles = {"BTCUSDT": _df(100)}
    with pytest.raises(ValueError):
        partition_into_folds(candles, n_folds=0)


def test_partition_too_few_candles_raises():
    candles = {"BTCUSDT": _df(5)}
    with pytest.raises(ValueError):
        partition_into_folds(candles, n_folds=12)
