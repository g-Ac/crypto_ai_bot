"""Preflight: per-symbol eligibility check against Binance fapi history."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping

import requests


_FAPI_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"


def _fetch_first_kline_time(symbol: str) -> int:
    """Return close_time_ms of first available 15m kline for symbol."""
    resp = requests.get(_FAPI_KLINES_URL, params={
        "symbol": symbol, "interval": "15m", "startTime": 0, "limit": 1,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise RuntimeError(f"No klines returned for {symbol}")
    # Index 0 is open_time_ms; use it as the "first available" marker
    return int(data[0][0])


@dataclass(frozen=True)
class PreflightResult:
    frozen_at: str
    required_days: int
    universe: list[str]
    ineligible: Mapping[str, Mapping]
    candidates_checked: int
    per_symbol_stats: Mapping[str, Mapping] = field(default_factory=dict)

    @property
    def universe_size(self) -> int:
        return len(self.universe)

    def to_dict(self) -> dict:
        return {
            "frozen_at": self.frozen_at,
            "required_days": self.required_days,
            "universe": list(self.universe),
            "ineligible": dict(self.ineligible),
            "candidates_checked": self.candidates_checked,
            "universe_size": self.universe_size,
            "per_symbol_stats": dict(self.per_symbol_stats),
        }


def run_preflight(
    *,
    symbols: list[str],
    required_days: int,
    today: datetime | None = None,
) -> PreflightResult:
    today = today or datetime.now(tz=timezone.utc)
    universe: list[str] = []
    ineligible: dict[str, dict] = {}
    per_symbol_stats: dict[str, dict] = {}

    for sym in symbols:
        first_kline_ms = _fetch_first_kline_time(sym)
        first_kline_dt = datetime.fromtimestamp(first_kline_ms / 1000.0, tz=timezone.utc)
        days_available = (today - first_kline_dt).days
        per_symbol_stats[sym] = {
            "first_kline": first_kline_dt.isoformat(),
            "days_available": days_available,
        }
        if days_available >= required_days:
            universe.append(sym)
        else:
            ineligible[sym] = {
                "first_kline": first_kline_dt.isoformat(),
                "days_available": days_available,
                "reason": "below_required_days",
            }

    return PreflightResult(
        frozen_at=today.isoformat(),
        required_days=required_days,
        universe=universe,
        ineligible=ineligible,
        candidates_checked=len(symbols),
        per_symbol_stats=per_symbol_stats,
    )
