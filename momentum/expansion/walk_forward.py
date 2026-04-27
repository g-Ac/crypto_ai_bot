"""Walk-forward partitioning into N monthly folds (no overlap)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd


@dataclass(frozen=True)
class FoldData:
    fold_idx: int
    candles_by_symbol: Mapping[str, pd.DataFrame]


def partition_into_folds(
    candles_by_symbol: Mapping[str, pd.DataFrame],
    n_folds: int,
) -> list[FoldData]:
    """Split candles into N sequential, non-overlapping folds.

    All symbols must have the same number of candles (caller's responsibility
    via align_candles_by_timestamp). Remainder candles are added to the last fold.
    """
    if n_folds <= 0:
        raise ValueError(f"n_folds must be positive, got {n_folds}")
    n_candles = min(len(df) for df in candles_by_symbol.values())
    if n_candles < n_folds * 2:
        raise ValueError(f"Not enough candles ({n_candles}) for {n_folds} folds")

    fold_size = n_candles // n_folds
    folds: list[FoldData] = []
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_folds - 1 else n_candles
        fold_candles = {
            sym: df.iloc[start:end].reset_index(drop=True)
            for sym, df in candles_by_symbol.items()
        }
        folds.append(FoldData(fold_idx=i, candles_by_symbol=fold_candles))
    return folds


from typing import Callable, Optional

from momentum.expansion.config import ExpansionConfig
from momentum.expansion.research_runner import (
    ExpansionResult,
    run_portfolio_backtest,
)


@dataclass(frozen=True)
class FoldResult:
    fold_idx: int
    metrics: dict
    n_trades: int
    expansion_result: ExpansionResult


def run_walk_forward(
    *,
    config: ExpansionConfig,
    folds: list[FoldData],
    signal_fn: Callable,
    capital_pool_usdt: float,
    risk_fraction: float,
    regime_fn: Optional[Callable[[str], str]] = None,
) -> list[FoldResult]:
    """Run run_portfolio_backtest on each fold; return per-fold metrics."""
    results: list[FoldResult] = []
    for fold in folds:
        # Each fold gets a fresh PortfolioState (no carryover across folds)
        result = run_portfolio_backtest(
            config=config,
            candles_by_symbol=fold.candles_by_symbol,
            signal_fn=signal_fn,
            capital_pool_usdt=capital_pool_usdt,
            risk_fraction=risk_fraction,
            regime_fn=regime_fn,
        )
        results.append(FoldResult(
            fold_idx=fold.fold_idx,
            metrics=result.metrics,
            n_trades=result.metrics["n_trades"],
            expansion_result=result,
        ))
    return results
