"""Base class for 1-minute trading engines.

All engines MUST inherit from Engine1m and implement analyze().
"""
from typing import List, Optional

import pandas as pd

from signal_types import Signal


class Engine1m:
    """Interface for pluggable 1-minute engines."""

    name: str = "base"
    version: str = "0.0.0"

    def analyze(
        self,
        symbol: str,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame | None = None,
        market_data: dict | None = None,
    ) -> Optional[Signal]:
        """Analyze candle data and return Signal if setup is valid.

        The Signal MUST have:
          - direction: Direction.LONG or Direction.SHORT
          - entry_price, sl_price, tp1_price set
          - sl_distance_pct calculated
          - strength: 0.0-1.0
          - source: self.name
          - valid: True
          - metadata: dict with engine-specific details

        Args:
            symbol: trading pair (e.g. "BTCUSDT")
            df_1m: 1-min candles with indicators from indicators_1m
            df_5m: optional 5-min candles for HTF context
            market_data: optional dict with funding, OI, etc

        Returns:
            Signal if valid setup found, None otherwise
        """
        raise NotImplementedError

    def required_indicators(self) -> List[str]:
        """List of indicator columns this engine needs in df_1m."""
        raise NotImplementedError
