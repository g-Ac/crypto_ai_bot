"""Tests for run_portfolio_backtest pure function."""
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.research_runner import (
    ExpansionResult,
    run_portfolio_backtest,
)


def _candles(n: int, base: float, drift: float = 0.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base * np.exp(np.cumsum(rng.normal(drift, 0.005, n)))
    highs = closes * (1.0 + np.abs(rng.normal(0, 0.002, n)))
    lows = closes * (1.0 - np.abs(rng.normal(0, 0.002, n)))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volumes = rng.uniform(100, 1000, n)
    return pd.DataFrame({
        "close_time_ms": np.arange(n, dtype=np.int64) * 900_000,
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": volumes,
    })


def _no_signal_fn(*, candles, symbol, regime_label, timestamp, config=None):
    return None


def _force_long_signal_fn(*, candles, symbol, regime_label, timestamp, config=None):
    """Always emits a TRADE long signal at the most recent candle."""
    from momentum.config import MomentumDirection, MomentumOutcome
    from momentum.momentum_trader import MomentumSignal
    last = candles.iloc[-1]
    entry = float(last["close"])
    return MomentumSignal(
        outcome=MomentumOutcome.TRADE,
        direction=MomentumDirection.LONG,
        entry_price=entry,
        sl_price=entry * 0.98,
        tp1_price=entry * 1.02,
        tp2_price=entry * 1.05,
        symbol=symbol, regime=regime_label, timestamp=timestamp,
    )


def _basic_config(universe: tuple[str, ...]) -> ExpansionConfig:
    return ExpansionConfig(universe=universe)


def test_no_signals_produces_zero_trades():
    cfg = _basic_config(("BTCUSDT", "ETHUSDT"))
    candles = {"BTCUSDT": _candles(100, 50000.0, seed=1),
               "ETHUSDT": _candles(100, 3000.0, seed=2)}
    result = run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles,
        signal_fn=_no_signal_fn,
        capital_pool_usdt=10000.0,
        risk_fraction=0.01,
    )
    assert isinstance(result, ExpansionResult)
    assert len(result.trades) == 0
    assert result.peak_concurrent_positions == 0


def test_input_validation_empty_candles():
    cfg = _basic_config(("BTCUSDT",))
    with pytest.raises(ValueError):
        run_portfolio_backtest(
            config=cfg, candles_by_symbol={},
            signal_fn=_no_signal_fn,
            capital_pool_usdt=10000.0,
            risk_fraction=0.01,
        )


def test_input_validation_universe_mismatch():
    cfg = _basic_config(("BTCUSDT", "ETHUSDT"))
    with pytest.raises(ValueError):
        run_portfolio_backtest(
            config=cfg, candles_by_symbol={"BTCUSDT": _candles(100, 50000.0)},
            signal_fn=_no_signal_fn,
            capital_pool_usdt=10000.0,
            risk_fraction=0.01,
        )


def test_force_close_at_end_of_series():
    cfg = _basic_config(("BTCUSDT",))
    candles = {"BTCUSDT": _candles(150, 50000.0, drift=0.001, seed=3)}
    result = run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles,
        signal_fn=_force_long_signal_fn,
        capital_pool_usdt=10000.0,
        risk_fraction=0.01,
    )
    # All trades must have an exit_ts (force-close at end)
    for t in result.trades:
        assert t["exit_ts"] is not None
        assert t["exit_reason"] in {"SL", "TP1", "TP2", "TIMEOUT", "TRAIL", "FORCE_CLOSE"}


def test_capital_pool_caps_concurrency():
    cfg = _basic_config(("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    candles = {
        "BTCUSDT": _candles(150, 50000.0, drift=0.001, seed=4),
        "ETHUSDT": _candles(150, 3000.0, drift=0.001, seed=5),
        "SOLUSDT": _candles(150, 100.0, drift=0.001, seed=6),
    }
    # Pool 300 with slot 100; max 3 concurrent — fine
    result = run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles,
        signal_fn=_force_long_signal_fn,
        capital_pool_usdt=300.0,
        risk_fraction=0.01,
    )
    assert result.peak_concurrent_positions <= 3


def test_pure_function_no_side_effects_on_candles():
    cfg = _basic_config(("BTCUSDT",))
    candles_orig = _candles(100, 50000.0, seed=7)
    candles = {"BTCUSDT": candles_orig.copy()}
    run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles,
        signal_fn=_force_long_signal_fn,
        capital_pool_usdt=10000.0,
        risk_fraction=0.01,
    )
    pd.testing.assert_frame_equal(candles["BTCUSDT"], candles_orig)
