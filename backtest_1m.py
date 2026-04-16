"""Backtest engine for 1-minute trading system.

Candle-by-candle simulation with:
- Zero look-ahead (candle i only sees data up to i)
- Entry on open of candle i+1
- Mandatory fees on all P&L calculations
- Position tracking with SL/TP via high/low checks
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from config_1m import Config1m
from engines_1m.base import Engine1m
from indicators_1m import add_indicators_1m
from market_1m import fetch_1m_historical
from risk_calculator_1m import calculate_viability

logger = logging.getLogger(__name__)


@dataclass
class ClosedTrade1m:
    symbol: str
    direction: str
    engine: str
    entry_price: float
    exit_price: float
    sl_price: float
    tp_price: float
    entry_time: str
    exit_time: str
    exit_reason: str  # "SL", "TP", "TIMEOUT", "TRAILING"
    pnl_pct: float
    pnl_usd: float
    fee_usd: float
    notional_usd: float
    leverage: int
    duration_candles: int
    metadata: dict = field(default_factory=dict)


@dataclass
class _OpenPosition:
    symbol: str
    direction: str
    engine: str
    entry_price: float
    sl_price: float
    tp_price: float
    entry_time: str
    entry_candle_idx: int
    notional_usd: float
    leverage: int
    fee_roundtrip_pct: float
    metadata: dict = field(default_factory=dict)


@dataclass
class BacktestResult:
    trades: List[ClosedTrade1m]
    total_candles: int
    symbols: List[str]
    config: Config1m

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.pnl_usd > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.pnl_usd <= 0)

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def total_pnl_usd(self) -> float:
        return sum(t.pnl_usd for t in self.trades)

    @property
    def total_pnl_pct(self) -> float:
        return sum(t.pnl_pct for t in self.trades)

    @property
    def total_fee_usd(self) -> float:
        return sum(t.fee_usd for t in self.trades)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl_usd for t in self.trades if t.pnl_usd > 0)
        gross_loss = abs(sum(t.pnl_usd for t in self.trades if t.pnl_usd <= 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def avg_duration_candles(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.duration_candles for t in self.trades) / len(self.trades)

    @property
    def max_drawdown_pct(self) -> float:
        if not self.trades:
            return 0.0
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            cumulative += t.pnl_pct
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def summary(self) -> str:
        lines = [
            "=== Backtest 1m Result ===",
            f"Symbols: {', '.join(self.symbols)}",
            f"Candles: {self.total_candles}",
            f"Trades: {self.total_trades} (W:{self.wins} L:{self.losses})",
            f"Win rate: {self.win_rate:.1%}",
            f"P&L: ${self.total_pnl_usd:.2f} ({self.total_pnl_pct:.2f}%)",
            f"Fees paid: ${self.total_fee_usd:.2f}",
            f"Profit factor: {self.profit_factor:.2f}",
            f"Max drawdown: {self.max_drawdown_pct:.2f}%",
            f"Avg duration: {self.avg_duration_candles:.1f} candles",
        ]
        return "\n".join(lines)


# Min candles for indicators to be valid
_MIN_WARMUP = 25


class Backtest1m:
    """Candle-by-candle backtester for 1-min engines."""

    def __init__(self, engines: List[Engine1m], config: Config1m | None = None):
        self.engines = engines
        self.config = config or Config1m()

    def run_on_dataframe(self, symbol: str, df: pd.DataFrame) -> BacktestResult:
        """Run backtest on a pre-loaded DataFrame.

        Args:
            symbol: trading pair
            df: candle data with columns: timestamp/time, open, high, low, close, volume

        Returns:
            BacktestResult with all closed trades and metrics
        """
        # Normalize time column to "timestamp"
        if "time" in df.columns and "timestamp" not in df.columns:
            df = df.rename(columns={"time": "timestamp"})

        # Add indicators to full dataframe
        df_full = add_indicators_1m(df.copy())

        closed_trades: List[ClosedTrade1m] = []
        open_position: Optional[_OpenPosition] = None
        pending_signal = None  # Signal from candle i, to enter on candle i+1

        for i in range(_MIN_WARMUP, len(df_full)):
            candle = df_full.iloc[i]

            # 1. Check open position for SL/TP hit
            if open_position is not None:
                trade = self._check_exit(open_position, candle, i)
                if trade is not None:
                    closed_trades.append(trade)
                    open_position = None

            # 2. Execute pending entry on this candle's open
            if pending_signal is not None and open_position is None:
                signal_entry = pending_signal.entry_price
                open_position = self._try_open_position(
                    pending_signal, candle, i, symbol
                )
                pending_signal = None

                # B3: Check SL/TP on entry candle itself
                if open_position is not None:
                    trade = self._check_entry_exit(
                        open_position, candle, i, signal_entry
                    )
                    if trade is not None:
                        closed_trades.append(trade)
                        open_position = None

            # 3. Run engines on data up to candle i (no look-ahead)
            if open_position is None and pending_signal is None:
                visible = df_full.iloc[:i + 1]
                for engine in self.engines:
                    signal = engine.analyze(symbol, visible)
                    if signal is not None and signal.valid:
                        # Validate via risk calculator
                        viability = calculate_viability(
                            symbol=symbol,
                            entry_price=signal.entry_price,
                            sl_price=signal.sl_price,
                            tp_price=signal.tp1_price,
                            max_risk_per_trade_usd=self.config.max_risk_per_trade_usd,
                            min_rr_net=self.config.min_rr_net,
                            max_fee_impact_pct=self.config.max_fee_impact_pct,
                            min_sl_distance_pct=self.config.min_sl_distance_pct,
                            max_sl_distance_pct=self.config.max_sl_distance_pct,
                        )
                        if viability.viable:
                            signal.metadata["viability"] = {
                                "notional": viability.notional_usd,
                                "leverage": viability.leverage,
                                "fee_cost": viability.fee_cost_usd,
                                "rr_net": viability.risk_reward_net,
                            }
                            pending_signal = signal
                            break  # One signal per candle

        # Close any remaining open position at last candle close
        if open_position is not None:
            last = df_full.iloc[-1]
            trade = self._force_close(open_position, last, len(df_full) - 1)
            closed_trades.append(trade)

        return BacktestResult(
            trades=closed_trades,
            total_candles=len(df_full),
            symbols=[symbol],
            config=self.config,
        )

    def _try_open_position(
        self, signal, candle: pd.Series, idx: int, symbol: str,
    ) -> Optional[_OpenPosition]:
        """Try to open position at candle's open price.

        B1: Re-validates via Risk Calculator with actual entry price.
        Returns None if trade is no longer viable after gap.
        """
        entry_price = candle["open"]  # Enter on OPEN of next candle

        # B1: Recalculate viability with actual entry price
        viability = calculate_viability(
            symbol=symbol,
            entry_price=entry_price,
            sl_price=signal.sl_price,
            tp_price=signal.tp1_price,
            max_risk_per_trade_usd=self.config.max_risk_per_trade_usd,
            min_rr_net=self.config.min_rr_net,
            max_fee_impact_pct=self.config.max_fee_impact_pct,
            min_sl_distance_pct=self.config.min_sl_distance_pct,
            max_sl_distance_pct=self.config.max_sl_distance_pct,
        )
        if not viability.viable:
            return None

        # Update metadata with recalculated viability (actual entry price)
        signal.metadata["viability"] = {
            "notional": viability.notional_usd,
            "leverage": viability.leverage,
            "fee_cost": viability.fee_cost_usd,
            "rr_net": viability.risk_reward_net,
        }

        return _OpenPosition(
            symbol=symbol,
            direction=signal.direction.value,
            engine=signal.source,
            entry_price=entry_price,
            sl_price=signal.sl_price,
            tp_price=signal.tp1_price,
            entry_time=str(candle.get("timestamp", "")),
            entry_candle_idx=idx,
            notional_usd=viability.notional_usd,
            leverage=viability.leverage,
            fee_roundtrip_pct=self.config.fee_roundtrip_pct,
            metadata=signal.metadata,
        )

    def _check_entry_exit(
        self, pos: _OpenPosition, candle: pd.Series, idx: int,
        signal_entry_price: float,
    ) -> Optional[ClosedTrade1m]:
        """B3: Check if SL or TP hit on the entry candle itself.

        Uses gap direction to determine proximity when both are hit:
        - Gap toward TP side (LONG: entry > signal, SHORT: entry < signal) → TP first
        - Gap toward SL side → SL first
        """
        high = candle["high"]
        low = candle["low"]

        if pos.direction == "LONG":
            hit_sl = low <= pos.sl_price
            hit_tp = high >= pos.tp_price
        else:
            hit_sl = high >= pos.sl_price
            hit_tp = low <= pos.tp_price

        if not hit_sl and not hit_tp:
            return None

        if hit_sl and hit_tp:
            gap_toward_tp = (
                (pos.direction == "LONG" and pos.entry_price > signal_entry_price) or
                (pos.direction == "SHORT" and pos.entry_price < signal_entry_price)
            )
            if gap_toward_tp:
                exit_price = pos.tp_price
                exit_reason = "TP"
            else:
                exit_price = pos.sl_price
                exit_reason = "SL"
        elif hit_sl:
            exit_price = pos.sl_price
            exit_reason = "SL"
        else:
            exit_price = pos.tp_price
            exit_reason = "TP"

        return self._close_position(pos, exit_price, exit_reason, candle, idx)

    def _check_exit(
        self, pos: _OpenPosition, candle: pd.Series, idx: int,
    ) -> Optional[ClosedTrade1m]:
        """Check if SL or TP hit on this candle using high/low."""
        high = candle["high"]
        low = candle["low"]

        if pos.direction == "LONG":
            hit_sl = low <= pos.sl_price
            hit_tp = high >= pos.tp_price
        else:
            hit_sl = high >= pos.sl_price
            hit_tp = low <= pos.tp_price

        if not hit_sl and not hit_tp:
            return None

        if hit_sl and hit_tp:
            # B4: Use proximity to candle open to determine which hit first
            open_price = candle["open"]
            if abs(open_price - pos.tp_price) <= abs(open_price - pos.sl_price):
                exit_price = pos.tp_price
                exit_reason = "TP"
            else:
                exit_price = pos.sl_price
                exit_reason = "SL"
        elif hit_sl:
            exit_price = pos.sl_price
            exit_reason = "SL"
        else:
            exit_price = pos.tp_price
            exit_reason = "TP"

        return self._close_position(pos, exit_price, exit_reason, candle, idx)

    def _force_close(
        self, pos: _OpenPosition, candle: pd.Series, idx: int,
    ) -> ClosedTrade1m:
        """Force close at candle close (end of data)."""
        return self._close_position(
            pos, candle["close"], "END_OF_DATA", candle, idx
        )

    def _close_position(
        self,
        pos: _OpenPosition,
        exit_price: float,
        exit_reason: str,
        candle: pd.Series,
        idx: int,
    ) -> ClosedTrade1m:
        """Calculate P&L and create ClosedTrade1m."""
        if pos.direction == "LONG":
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
        else:
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100

        # P&L in USD (on notional)
        pnl_before_fees = pnl_pct / 100 * pos.notional_usd
        fee_usd = pos.notional_usd * pos.fee_roundtrip_pct / 100
        pnl_usd = pnl_before_fees - fee_usd
        pnl_pct_net = pnl_usd / pos.notional_usd * 100 if pos.notional_usd > 0 else 0

        duration = idx - pos.entry_candle_idx

        return ClosedTrade1m(
            symbol=pos.symbol,
            direction=pos.direction,
            engine=pos.engine,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            sl_price=pos.sl_price,
            tp_price=pos.tp_price,
            entry_time=pos.entry_time,
            exit_time=str(candle.get("timestamp", "")),
            exit_reason=exit_reason,
            pnl_pct=pnl_pct_net,
            pnl_usd=pnl_usd,
            fee_usd=fee_usd,
            notional_usd=pos.notional_usd,
            leverage=pos.leverage,
            duration_candles=duration,
            metadata=pos.metadata,
        )


def run_backtest_1m(
    symbols: List[str] | None = None,
    days: int = 30,
    config: Config1m | None = None,
    engines: List[Engine1m] | None = None,
) -> Dict[str, BacktestResult]:
    """Convenience function: fetch data and run backtest.

    Args:
        symbols: list of pairs (default from config)
        days: days of history
        config: Config1m instance
        engines: list of engines (default: MomentumBurst1m)

    Returns:
        Dict mapping symbol -> BacktestResult
    """
    from engines_1m.momentum_burst import MomentumBurst1m

    config = config or Config1m()
    symbols = symbols or config.symbols
    engines = engines or [MomentumBurst1m()]

    bt = Backtest1m(engines=engines, config=config)
    results = {}

    for symbol in symbols:
        logger.info("Fetching %d days of 1m data for %s...", days, symbol)
        df = fetch_1m_historical(symbol, days=days)

        if df.empty:
            logger.warning("No data for %s -- skipping", symbol)
            continue

        logger.info("Running backtest on %d candles for %s...", len(df), symbol)
        result = bt.run_on_dataframe(symbol, df)
        results[symbol] = result
        logger.info("\n%s", result.summary())

    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    results = run_backtest_1m(days=days)

    print("\n" + "=" * 50)
    for symbol, result in results.items():
        print(f"\n{symbol}:")
        print(result.summary())
