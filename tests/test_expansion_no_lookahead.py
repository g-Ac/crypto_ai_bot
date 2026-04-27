"""No-lookahead invariant: signal_fn never sees candles >= execution_shift index."""
import numpy as np
import pandas as pd

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.research_runner import run_portfolio_backtest


def test_signal_fn_only_sees_history_up_to_decision_candle():
    cfg = ExpansionConfig(universe=("BTCUSDT",))
    n = 50
    candles = {"BTCUSDT": pd.DataFrame({
        "close_time_ms": np.arange(n, dtype=np.int64) * 900_000,
        "open": np.arange(n, dtype=float),
        "high": np.arange(n, dtype=float) + 1,
        "low": np.arange(n, dtype=float) - 1,
        "close": np.arange(n, dtype=float),
        "volume": np.full(n, 1000.0),
    })}

    seen_lengths: list[int] = []

    def recording_signal_fn(*, candles, symbol, regime_label, timestamp, config=None):
        seen_lengths.append(len(candles))
        return None

    run_portfolio_backtest(
        config=cfg, candles_by_symbol=candles,
        signal_fn=recording_signal_fn,
        capital_pool_usdt=1000.0, risk_fraction=0.01,
        execution_shift=1,
    )
    # signal_fn must never see all 50 candles (would mean future leak)
    assert all(L < n for L in seen_lengths), \
        f"signal_fn saw a dataset of full length n={n} which means look-ahead"
    # And it must see strictly increasing history lengths starting from 1
    assert seen_lengths[0] == 1
    assert seen_lengths == sorted(seen_lengths)
