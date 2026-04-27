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
