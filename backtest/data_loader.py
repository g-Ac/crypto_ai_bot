"""Data loading and validation for backtesting.

Loads OHLCV from CSV, validates quality, and produces a coverage report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class DataQualityReport:
    """Quality report produced before every backtest run."""

    symbol: str = ""
    timeframe: str = ""
    period_start: str = ""
    period_end: str = ""
    candles_total: int = 0
    candles_expected: int = 0
    candles_missing: int = 0
    coverage_pct: float = 0.0
    gaps: List[str] = field(default_factory=list)  # List of gap descriptions
    zeros_found: int = 0
    outliers_found: int = 0
    valid: bool = False

    def summary(self) -> str:
        status = "PASS" if self.valid else "FAIL"
        return (
            f"[{status}] {self.symbol} {self.timeframe}: "
            f"{self.candles_total}/{self.candles_expected} candles "
            f"({self.coverage_pct:.1f}%), {len(self.gaps)} gaps, "
            f"{self.zeros_found} zeros, {self.outliers_found} outliers"
        )


def load_candles(
    path: str | Path,
    symbol: str = "",
    timeframe: str = "15m",
) -> pd.DataFrame:
    """Load candle data from CSV file.

    Expected columns: timestamp, open, high, low, close, volume
    Timestamp can be ISO string or unix millis.

    Returns:
        DataFrame sorted by timestamp ascending with standard columns.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    df = pd.read_csv(path)

    # Normalize column names to lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    # Handle timestamp
    if "timestamp" in df.columns:
        if df["timestamp"].dtype in ("int64", "float64"):
            # Unix millis
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    elif "date" in df.columns:
        df["timestamp"] = pd.to_datetime(df["date"], utc=True)
    else:
        raise ValueError("No timestamp or date column found")

    df = df.sort_values("timestamp").reset_index(drop=True)

    # Cast numeric columns
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def validate_data(df: pd.DataFrame, timeframe: str = "15m") -> DataQualityReport:
    """Validate data quality and produce a report.

    Checks: gaps, zeros, outliers, coverage.
    """
    report = DataQualityReport(timeframe=timeframe)

    if len(df) == 0:
        return report

    if "timestamp" not in df.columns:
        report.valid = False
        return report

    report.period_start = str(df["timestamp"].iloc[0])
    report.period_end = str(df["timestamp"].iloc[-1])
    report.candles_total = len(df)

    # Expected candles based on timeframe
    tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    minutes = tf_minutes.get(timeframe, 15)
    time_span = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).total_seconds() / 60
    report.candles_expected = max(1, int(time_span / minutes) + 1)
    report.candles_missing = max(0, report.candles_expected - report.candles_total)
    report.coverage_pct = report.candles_total / max(1, report.candles_expected) * 100

    # Detect gaps (> 2 consecutive missing candles)
    if len(df) > 1:
        diffs = df["timestamp"].diff().dt.total_seconds() / 60
        gap_threshold = minutes * 3  # > 2 missing candles
        gap_mask = diffs > gap_threshold
        for idx in df.index[gap_mask]:
            prev_ts = df["timestamp"].iloc[max(0, idx - 1)]
            curr_ts = df["timestamp"].iloc[idx]
            gap_candles = int(diffs.iloc[idx] / minutes) - 1
            report.gaps.append(f"{prev_ts} → {curr_ts} ({gap_candles} missing)")

    # Zeros
    zeros = (df["close"] == 0) | (df["volume"] == 0) | df["close"].isna()
    report.zeros_found = int(zeros.sum())

    # Outliers (> 20% single candle move)
    if len(df) > 1:
        pct_change = df["close"].pct_change().abs()
        report.outliers_found = int((pct_change > 0.20).sum())

    # Valid: coverage >= 95%, no critical issues
    report.valid = report.coverage_pct >= 95 and report.zeros_found == 0

    return report
