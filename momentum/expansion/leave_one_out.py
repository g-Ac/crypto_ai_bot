"""Leave-one-out: by symbol and by fold."""
from __future__ import annotations

from typing import Iterable, Mapping

from momentum.expansion.metrics import compute_portfolio_metrics


def loo_by_symbol(
    trades: Iterable[Mapping], universe: Iterable[str],
) -> dict[str, dict]:
    """For each symbol, compute aggregate metrics WITHOUT that symbol's trades."""
    trades_list = list(trades)
    out: dict[str, dict] = {}
    for sym in universe:
        remaining = [t for t in trades_list if t.get("symbol") != sym]
        out[sym] = compute_portfolio_metrics(remaining)
    return out


def loo_by_fold(fold_results: Iterable[Mapping]) -> dict[int, dict]:
    """For each fold, compute aggregate metrics WITHOUT that fold's trades.

    fold_results: iterable of dicts with keys 'fold_idx' and 'trades'.
    """
    folds = list(fold_results)
    out: dict[int, dict] = {}
    for skip in folds:
        skip_idx = skip["fold_idx"]
        remaining_trades: list = []
        for f in folds:
            if f["fold_idx"] == skip_idx:
                continue
            remaining_trades.extend(f["trades"])
        out[skip_idx] = compute_portfolio_metrics(remaining_trades)
    return out
