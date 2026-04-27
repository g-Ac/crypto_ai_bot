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
