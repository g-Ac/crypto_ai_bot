"""Base class for 5-minute trading engines.

All engines MUST inherit from Engine5m and implement analyze().
"""
from abc import ABC, abstractmethod
from typing import List, Optional

import pandas as pd

from signal_types import Signal


class Engine5m(ABC):
    """Interface for pluggable 5-minute engines.

    Subclasses MUST:
      - Set `name` to a unique string (not "base")
      - Set `version` to a semver string
      - Implement `analyze()` and `required_indicators()`
    """

    name: str = "base"
    version: str = "0.0.0"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name == "base":
            raise TypeError(
                f"{cls.__name__} must define a 'name' class attribute "
                f"different from 'base'"
            )

    @abstractmethod
    def analyze(
        self,
        symbol: str,
        df_5m: pd.DataFrame,
        market_data: dict | None = None,
    ) -> Optional[Signal]:
        """Analyze 5-min candle data and return Signal if setup is valid.

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
            df_5m: 5-min candles with indicators from indicators_5m
            market_data: optional dict with funding, OI, etc

        Returns:
            Signal if valid setup found, None otherwise
        """
        ...

    @abstractmethod
    def required_indicators(self) -> List[str]:
        """List of indicator columns this engine needs in df_5m."""
        ...
