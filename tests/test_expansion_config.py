"""Tests for ExpansionConfig."""
from dataclasses import FrozenInstanceError

import pytest

from momentum.expansion.config import (
    BUCKET_ASSIGNMENT,
    ExpansionConfig,
    SLIPPAGE_BY_BUCKET,
)


def test_config_defaults():
    cfg = ExpansionConfig(universe=["BTCUSDT", "ETHUSDT"])
    assert cfg.period_main_days == 365
    assert cfg.period_holdout_days == 90
    assert cfg.n_folds == 12
    assert cfg.required_history_days == 455
    assert cfg.gap_threshold_pct == 0.5
    assert cfg.slippage_universal_sensitivity == 0.10
    assert cfg.pf_threshold_main == 1.25
    assert cfg.pf_ratio_vs_baseline == 1.10
    assert cfg.dd_ratio_vs_baseline == 1.30
    assert cfg.min_folds_positive == 9
    assert cfg.holdout_pf_min == 1.0
    assert cfg.holdout_ratio_vs_main == 0.9
    assert cfg.symbol_destructive_min_n == 60
    assert cfg.symbol_destructive_max_pf == 0.5


def test_config_frozen():
    cfg = ExpansionConfig(universe=["BTCUSDT"])
    with pytest.raises(FrozenInstanceError):
        cfg.period_main_days = 180


def test_bucket_assignment_covers_all_candidates():
    expected = {
        "BTCUSDT", "ETHUSDT", "SOLUSDT",
        "XRPUSDT", "DOGEUSDT", "BNBUSDT", "ADAUSDT",
        "LINKUSDT", "AVAXUSDT", "SUIUSDT", "AAVEUSDT", "LTCUSDT", "NEARUSDT",
    }
    assert set(BUCKET_ASSIGNMENT.keys()) == expected
    valid_buckets = {"core", "high_beta", "infra"}
    for sym, bucket in BUCKET_ASSIGNMENT.items():
        assert bucket in valid_buckets, f"{sym} has invalid bucket {bucket}"


def test_slippage_by_bucket():
    assert SLIPPAGE_BY_BUCKET == {"core": 0.03, "high_beta": 0.07, "infra": 0.05}


def test_slippage_for_symbol():
    cfg = ExpansionConfig(universe=["BTCUSDT", "DOGEUSDT", "LINKUSDT"])
    assert cfg.slippage_for("BTCUSDT") == 0.03
    assert cfg.slippage_for("DOGEUSDT") == 0.07
    assert cfg.slippage_for("LINKUSDT") == 0.05


def test_unknown_symbol_raises():
    cfg = ExpansionConfig(universe=["UNKNOWNUSDT"])
    with pytest.raises(KeyError):
        cfg.slippage_for("UNKNOWNUSDT")
