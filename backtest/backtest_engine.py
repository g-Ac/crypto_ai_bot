"""Backtest engine — candle-by-candle simulation for CFER and RAVR.

Uses the SAME signal modules as live (compression, breakout, reclaim, trap).
Only the data feed and fill simulation differ from live operation.

Invariants:
  - Zero lookahead: at candle[t], only candles[0..t] are visible.
  - Slippage always adverse.
  - Same signal engine as live — no duplicated logic.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import asdict, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from defensive.breakout_detector import detect_breakout, detect_reclaim
from defensive.compression_detector import detect_compression
from defensive.config import DefensiveConfig
from defensive.enums import (
    BLOCKED_REGIMES,
    PERMISSIVE_REGIMES,
    Direction,
    ExitReason,
    Outcome,
    Regime,
    Session,
    Strategy,
)
from defensive.models import (
    BacktestRunMeta,
    BreakoutEvent,
    ClosedTrade,
    CompressionState,
    FeatureAvailability,
    TradeDecision,
    TrapResult,
)
from defensive.ravr_trader import evaluate_ravr
from defensive.trap_detector import detect_trap
from defensive.value_reference import compute_value_metrics

logger = logging.getLogger(__name__)

# Minimum candles needed for signal computation
MIN_CANDLES_15M = 130  # 100 for BB/VWAP + 30 buffer


# ---------------------------------------------------------------------------
# Session detection
# ---------------------------------------------------------------------------

def _classify_session(ts: pd.Timestamp) -> Session:
    """Classify UTC hour into trading session."""
    hour = ts.hour
    if 0 <= hour < 8:
        return Session.ASIA
    elif 8 <= hour < 14:
        return Session.EUROPE
    elif 14 <= hour < 21:
        return Session.US
    else:
        return Session.DEAD


# ---------------------------------------------------------------------------
# Regime from 1h candles (simplified for backtest)
# ---------------------------------------------------------------------------

def _classify_regime(candles_1h: pd.DataFrame) -> Regime:
    """Simplified regime classification from 1h candles.

    Uses BB Width percentile and ATR trend as proxy.
    In production, htf.py does this — here we replicate the logic
    to maintain signal parity without importing htf.py (which has
    dependencies on the live bot infrastructure).
    """
    if len(candles_1h) < 30:
        return Regime.UNKNOWN

    close = candles_1h["close"].values
    high = candles_1h["high"].values
    low = candles_1h["low"].values

    # BB Width percentile
    sma20 = pd.Series(close).rolling(20).mean().values
    std20 = pd.Series(close).rolling(20).std(ddof=0).values
    bb_w = np.where(sma20 > 0, (4 * std20) / sma20 * 100, 0.0)

    current_bw = float(bb_w[-1]) if not np.isnan(bb_w[-1]) else 0.0
    lookback = bb_w[-30:]
    valid = lookback[~np.isnan(lookback)]
    bw_pct = float(np.sum(valid < current_bw) / len(valid) * 100) if len(valid) > 0 else 50.0

    # ADX proxy: directional movement
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    tr = np.concatenate([[high[0] - low[0]], tr])
    atr14 = pd.Series(tr).rolling(14).mean().values
    current_atr = float(atr14[-1]) if not np.isnan(atr14[-1]) else 0.0
    atr_pct = (current_atr / close[-1] * 100) if close[-1] > 0 else 0.0

    # Simple regime classification
    if bw_pct > 80 and atr_pct > 1.5:
        return Regime.VOLATILE
    elif bw_pct > 60:
        return Regime.TRENDING
    elif bw_pct < 25:
        return Regime.RANGING
    elif bw_pct < 45:
        return Regime.WEAK_TREND
    else:
        return Regime.CHOPPY


# ---------------------------------------------------------------------------
# Slippage / cost model
# ---------------------------------------------------------------------------

def _apply_slippage(
    price: float, direction: Direction, is_entry: bool, config: DefensiveConfig,
    context: str = "normal",
) -> float:
    """Apply adverse slippage to a price.

    Args:
        price: Raw price.
        direction: LONG or SHORT.
        is_entry: True for entries, False for exits.
        config: DefensiveConfig.
        context: "normal", "failed_breakout", "regime_shift".
    """
    slip_map = {
        "normal": config.slippage_normal,
        "failed_breakout": config.slippage_failed_breakout,
        "regime_shift": config.slippage_regime_shift,
    }
    slip_pct = slip_map.get(context, config.slippage_normal) / 100

    if direction == Direction.LONG:
        if is_entry:
            return price * (1 + slip_pct)  # Worse entry (higher)
        else:
            return price * (1 - slip_pct)  # Worse exit (lower)
    else:
        if is_entry:
            return price * (1 - slip_pct)  # Worse entry (lower)
        else:
            return price * (1 + slip_pct)  # Worse exit (higher)


def _compute_fees(position_size_usd: float, config: DefensiveConfig) -> float:
    """Compute round-trip fee."""
    return position_size_usd * config.fee_per_side / 100 * 2


# ---------------------------------------------------------------------------
# Position tracking
# ---------------------------------------------------------------------------

class _OpenPosition:
    """Tracks an open position during backtest."""

    __slots__ = (
        "direction", "entry_price", "sl_price", "tp1_price", "tp2_price",
        "position_size_usd", "entry_timestamp", "entry_candle_idx",
        "strategy", "symbol", "regime", "session", "breakout",
        "compression_percentile", "compression_candles",
        "trap_score", "trap_evidence", "z_score", "vwap_distance_pct",
        "micro_snapshot", "config_version", "param_version", "git_sha",
        "mae_pct", "mfe_pct", "tp1_hit", "remaining_pct",
        "vwap_period",
    )

    def __init__(self, decision: TradeDecision, config: DefensiveConfig):
        self.direction = decision.direction
        self.entry_price = decision.entry_price
        self.sl_price = decision.sl_price
        self.tp1_price = decision.tp1_price
        self.tp2_price = decision.tp2_price
        self.position_size_usd = decision.position_size_usd
        self.entry_timestamp = decision.timestamp
        self.entry_candle_idx = 0
        self.strategy = decision.strategy
        self.symbol = decision.symbol
        self.regime = decision.regime
        self.session = decision.session

        # CFER context
        self.breakout = decision.breakout
        self.compression_percentile = decision.compression.bb_width_percentile
        self.compression_candles = decision.compression.consecutive_decline
        self.trap_score = decision.trap.score
        self.trap_evidence = list(decision.trap.evidence)

        # RAVR context
        self.z_score = decision.z_score
        self.vwap_distance_pct = decision.vwap_distance_pct

        # Micro snapshot
        self.micro_snapshot = {
            "oi_change_1h_pct": decision.oi_change_1h_pct,
            "funding_rate": decision.funding_rate,
            "basis_spread_pct": decision.basis_spread_pct,
        }

        # Versioning
        self.config_version = decision.config_version
        self.param_version = decision.param_version
        self.git_sha = decision.git_sha

        # Tracking
        self.mae_pct = 0.0
        self.mfe_pct = 0.0
        self.tp1_hit = False
        self.remaining_pct = 100.0
        self.vwap_period = config.ravr_vwap_period

    def update_mae_mfe(self, current_price: float) -> None:
        """Update MAE/MFE based on current price."""
        if self.direction == Direction.LONG:
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
        else:
            pnl_pct = (self.entry_price - current_price) / self.entry_price * 100

        if pnl_pct < self.mae_pct:
            self.mae_pct = pnl_pct
        if pnl_pct > self.mfe_pct:
            self.mfe_pct = pnl_pct

    def check_exit(
        self, candle: pd.Series, candles_since_entry: int, current_regime: Regime,
        config: DefensiveConfig,
        current_zscore: float = 0.0,
    ) -> Optional[Tuple[ExitReason, float]]:
        """Check if position should be exited.

        Returns (exit_reason, raw_exit_price) or None.
        Uses candle high/low for SL/TP checks (intra-candle simulation).

        Args:
            current_zscore: Live z-score for RAVR v2 z-score decay exit.
        """
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        # --- SL check (uses high/low, not close) ---
        if self.direction == Direction.LONG and low <= self.sl_price:
            return (ExitReason.STOP_LOSS, self.sl_price)
        if self.direction == Direction.SHORT and high >= self.sl_price:
            return (ExitReason.STOP_LOSS, self.sl_price)

        # --- TP1 partial check ---
        if not self.tp1_hit:
            if self.direction == Direction.LONG and high >= self.tp1_price:
                self.tp1_hit = True
                self.remaining_pct = config.tp1_partial_pct
                # Move SL to breakeven + buffer
                self.sl_price = self.entry_price * (1 + config.breakeven_buffer_pct / 100)
            elif self.direction == Direction.SHORT and low <= self.tp1_price:
                self.tp1_hit = True
                self.remaining_pct = config.tp1_partial_pct
                self.sl_price = self.entry_price * (1 - config.breakeven_buffer_pct / 100)

        # --- TP2 check (full exit) ---
        if self.tp1_hit:
            if self.direction == Direction.LONG and high >= self.tp2_price:
                return (ExitReason.TP2, self.tp2_price)
            if self.direction == Direction.SHORT and low <= self.tp2_price:
                return (ExitReason.TP2, self.tp2_price)

        # --- Z-score decay exit (RAVR v2 Variant D) ---
        if config.ravr_zscore_exit_threshold > 0 and current_zscore != 0.0:
            if abs(current_zscore) <= config.ravr_zscore_exit_threshold:
                return (ExitReason.ZSCORE_DECAY, close)

        # --- Regime shift exit ---
        if current_regime in BLOCKED_REGIMES and current_regime != self.regime:
            return (ExitReason.REGIME_SHIFT, close)

        # --- Smart timeout (RAVR v2 Variant E) ---
        if (config.ravr_smart_timeout_candles > 0
                and candles_since_entry >= config.ravr_smart_timeout_candles):
            if self.direction == Direction.LONG:
                pnl_pct = (close - self.entry_price) / self.entry_price * 100
            else:
                pnl_pct = (self.entry_price - close) / self.entry_price * 100
            if pnl_pct >= config.ravr_smart_timeout_min_pnl_pct:
                return (ExitReason.SMART_TIMEOUT, close)

        # --- Timeout ---
        if candles_since_entry >= config.timeout_candles:
            return (ExitReason.TIMEOUT, close)

        return None


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """Candle-by-candle backtester for CFER Baseline/Enhanced and RAVR."""

    def __init__(self, config: DefensiveConfig):
        self.config = config
        self.trades: List[ClosedTrade] = []
        self.decisions: List[TradeDecision] = []
        self.position: Optional[_OpenPosition] = None
        self.capital = config.initial_capital

        # Risk tracking
        self._daily_loss: float = 0.0
        self._daily_trades: int = 0
        self._consecutive_losses: int = 0
        self._cooldown_start_idx: int = -999  # Candle index when cooldown began
        self._last_sl_direction: Optional[Direction] = None
        self._candles_since_last_sl: int = 999
        self._current_day: str = ""

    def run(
        self,
        candles_15m: pd.DataFrame,
        candles_1h: pd.DataFrame,
        symbol: str = "BTCUSDT",
        micro_data: Optional[pd.DataFrame] = None,
    ) -> BacktestRunMeta:
        """Run backtest on provided data.

        Args:
            candles_15m: Full 15m OHLCV with timestamp column.
            candles_1h: Full 1h OHLCV for regime detection.
            symbol: Trading symbol.
            micro_data: Optional microstructure data for Enhanced mode.

        Returns:
            BacktestRunMeta with run metadata.
        """
        run_id = str(uuid.uuid4())[:8]
        # Determine active strategy
        if self.config.ravr_enabled and not self.config.baseline_enabled:
            active_strategy = Strategy.RAVR
        elif self.config.enhanced_enabled:
            active_strategy = Strategy.CFER_ENHANCED
        else:
            active_strategy = Strategy.CFER_BASELINE

        meta = BacktestRunMeta(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            strategy=active_strategy,
            config_hash=self.config.config_hash,
            param_version=self.config.param_version,
            period_start=str(candles_15m["timestamp"].iloc[0]) if len(candles_15m) > 0 else "",
            period_end=str(candles_15m["timestamp"].iloc[-1]) if len(candles_15m) > 0 else "",
            candles_total=len(candles_15m),
        )

        if len(candles_15m) < MIN_CANDLES_15M:
            logger.warning("Insufficient 15m candles: %d < %d", len(candles_15m), MIN_CANDLES_15M)
            return meta

        # Pre-compute 1h regime at each 15m timestamp
        regime_cache = self._build_regime_cache(candles_15m, candles_1h)

        # Micro data index for Enhanced mode
        micro_index = self._build_micro_index(micro_data) if micro_data is not None else {}

        # Track pending breakout for reclaim detection
        pending_breakout: Optional[BreakoutEvent] = None
        breakout_candle_idx = 0

        # v0.2: Track recent compression state
        last_compression_idx = -999
        last_compression = CompressionState()

        # Main loop: iterate 15m candles
        for i in range(MIN_CANDLES_15M, len(candles_15m)):
            window = candles_15m.iloc[:i + 1]
            current_ts = candles_15m["timestamp"].iloc[i]
            session = _classify_session(current_ts)
            regime = regime_cache.get(i, Regime.UNKNOWN)

            # Daily reset
            day_key = str(current_ts.date()) if hasattr(current_ts, "date") else str(current_ts)[:10]
            if day_key != self._current_day:
                self._current_day = day_key
                self._daily_loss = 0.0
                self._daily_trades = 0

            self._candles_since_last_sl += 1

            # --- Manage open position ---
            if self.position is not None:
                last_candle = candles_15m.iloc[i]
                self.position.update_mae_mfe(float(last_candle["close"]))
                candles_since = i - self.position.entry_candle_idx

                # Compute live z-score for RAVR z-score decay exit
                current_zscore = 0.0
                if (self.config.ravr_zscore_exit_threshold > 0
                        and self.position.strategy == Strategy.RAVR):
                    vm_live = compute_value_metrics(
                        window, vwap_period=self.position.vwap_period,
                    )
                    current_zscore = vm_live.z_score

                exit_result = self.position.check_exit(
                    last_candle, candles_since, regime, self.config,
                    current_zscore=current_zscore,
                )
                if exit_result is not None:
                    exit_reason, raw_exit_price = exit_result
                    self._close_position(exit_reason, raw_exit_price, str(current_ts), i)
                continue  # Don't open new positions while managing one

            # --- Strategy path: RAVR or CFER ---
            if active_strategy == Strategy.RAVR:
                self._run_ravr_candle(
                    window, regime, session, symbol, run_id, i, current_ts,
                )
                continue

            # --- CFER pipeline ---
            decision = TradeDecision(
                timestamp=str(current_ts),
                cycle_id=f"cfer_{run_id}_{i}",
                symbol=symbol,
                strategy=(Strategy.CFER_ENHANCED if self.config.enhanced_enabled
                          else Strategy.CFER_BASELINE),
                regime=regime,
                session=session,
            )

            # Gate: risk checks
            risk_outcome = self._check_risk(decision.direction, candle_idx=i)
            if risk_outcome is not None:
                decision.outcome = risk_outcome
                self.decisions.append(decision)
                continue

            # Gate: regime
            if regime not in PERMISSIVE_REGIMES:
                decision.outcome = Outcome.REGIME_BLOCKED
                self.decisions.append(decision)
                pending_breakout = None
                continue

            # Layer 1: Compression (detect and remember)
            compression = detect_compression(window, self.config)
            decision.compression = compression

            if compression.active:
                last_compression_idx = i
                last_compression = compression

            # v0.2: Check for recent compression (within memory window)
            # v0.1: Require compression active NOW
            compression_memory = self.config.compression_memory_window
            has_compression = compression.active  # v0.1 default
            if compression_memory > 0:
                # v0.2: compression happened recently
                has_compression = (i - last_compression_idx) <= compression_memory

            if not has_compression:
                decision.outcome = Outcome.NO_COMPRESSION
                self.decisions.append(decision)
                pending_breakout = None
                continue

            # Layer 2: Breakout detection
            # v0.2: use last_compression for BB reference even if not active now
            effective_compression = compression if compression.active else last_compression

            if pending_breakout is None:
                breakout = detect_breakout(window, effective_compression, self.config)
                decision.breakout = breakout

                if not breakout.detected:
                    decision.outcome = Outcome.NO_BREAKOUT
                    self.decisions.append(decision)
                    continue

                # Breakout detected — wait for reclaim
                pending_breakout = breakout
                breakout_candle_idx = i
                decision.outcome = Outcome.NO_RECLAIM  # Will check next candles
                self.decisions.append(decision)
                continue

            # Layer 4: Reclaim check (after breakout)
            decision.breakout = pending_breakout
            candles_since_breakout = i - breakout_candle_idx

            if candles_since_breakout > self.config.breakout_reclaim_window:
                # Window expired
                decision.outcome = Outcome.NO_RECLAIM
                self.decisions.append(decision)
                pending_breakout = None
                continue

            reclaimed = detect_reclaim(window, pending_breakout, self.config)
            decision.reclaim_detected = reclaimed

            if not reclaimed:
                decision.outcome = Outcome.NO_RECLAIM
                self.decisions.append(decision)
                continue

            # Layer 3: Trap confirmation (Enhanced only)
            if self.config.enhanced_enabled:
                features = self._get_features(current_ts, micro_index)
                decision.features = features

                micro_at = micro_index.get(breakout_candle_idx)
                micro_after = micro_index.get(i)

                trap = detect_trap(
                    pending_breakout, micro_at, micro_after, features, self.config,
                )
                decision.trap = trap

                if not trap.confirmed:
                    decision.outcome = Outcome.NO_TRAP
                    self.decisions.append(decision)
                    pending_breakout = None
                    continue

            # Directional cooldown check
            entry_direction = (Direction.SHORT if pending_breakout.direction == Direction.LONG
                               else Direction.LONG)

            if (self._last_sl_direction == entry_direction
                    and self._candles_since_last_sl < self.config.directional_cooldown_candles):
                decision.outcome = Outcome.COOLDOWN
                self.decisions.append(decision)
                pending_breakout = None
                continue

            # --- ENTRY ---
            decision.direction = entry_direction
            last_close = float(candles_15m["close"].iloc[i])
            vm = compute_value_metrics(window)

            # SL/TP calculation
            atr = vm.atr if vm.atr > 0 else last_close * 0.005
            sl_distance = max(
                atr * self.config.atr_sl_multiplier,
                last_close * self.config.atr_sl_floor_pct / 100,
            )

            # Check SL % limit
            sl_pct = sl_distance / last_close * 100 if last_close > 0 else 999.0
            if sl_pct > self.config.max_sl_pct:
                decision.outcome = Outcome.RISK_BLOCKED
                self.decisions.append(decision)
                pending_breakout = None
                continue

            # Entry with slippage (failed breakout context)
            entry_price = _apply_slippage(
                last_close, entry_direction, is_entry=True, config=self.config,
                context="failed_breakout",
            )

            if entry_direction == Direction.LONG:
                decision.sl_price = entry_price - sl_distance
                tp1_distance = sl_distance * self.config.min_rr
                decision.tp1_price = entry_price + tp1_distance
                decision.tp2_price = entry_price + tp1_distance * 1.5
            else:
                decision.sl_price = entry_price + sl_distance
                tp1_distance = sl_distance * self.config.min_rr
                decision.tp1_price = entry_price - tp1_distance
                decision.tp2_price = entry_price - tp1_distance * 1.5

            # Position sizing
            risk_usd = self.capital * self.config.max_risk_pct / 100
            position_size = risk_usd / (sl_pct / 100) if sl_pct > 0 else 0
            position_size = min(position_size, self.capital * self.config.max_leverage)

            decision.entry_price = entry_price
            decision.position_size_usd = position_size
            decision.outcome = Outcome.TRADE

            # Versioning
            decision.config_version = self.config.config_hash
            decision.param_version = self.config.param_version

            self.decisions.append(decision)

            # Open position
            self.position = _OpenPosition(decision, self.config)
            self.position.entry_candle_idx = i
            self._daily_trades += 1

            pending_breakout = None

        return meta

    def _close_position(
        self, exit_reason: ExitReason, raw_exit_price: float,
        timestamp: str, candle_idx: int,
    ) -> None:
        """Close the current position and record the trade."""
        pos = self.position
        if pos is None:
            return

        # Apply slippage to exit
        context = "normal"
        if exit_reason == ExitReason.STOP_LOSS:
            context = "failed_breakout"
        elif exit_reason == ExitReason.REGIME_SHIFT:
            context = "regime_shift"

        exit_price = _apply_slippage(
            raw_exit_price, pos.direction, is_entry=False,
            config=self.config, context=context,
        )

        # PnL calculation
        if pos.direction == Direction.LONG:
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
        else:
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100

        # Account for partial TP1
        if pos.tp1_hit and exit_reason != ExitReason.STOP_LOSS:
            # TP1 was hit: partial closed at TP1, remaining at final exit
            tp1_pnl = (pos.tp1_price - pos.entry_price) / pos.entry_price * 100
            if pos.direction == Direction.SHORT:
                tp1_pnl = (pos.entry_price - pos.tp1_price) / pos.entry_price * 100
            tp1_weight = (100 - pos.remaining_pct) / 100  # fraction closed at TP1
            tp2_weight = pos.remaining_pct / 100           # fraction at final exit
            pnl_pct = tp1_pnl * tp1_weight + pnl_pct * tp2_weight

        # Fees
        fees = _compute_fees(pos.position_size_usd, self.config)
        fees_pct = fees / pos.position_size_usd * 100 if pos.position_size_usd > 0 else 0

        net_pnl_pct = pnl_pct - fees_pct
        pnl_usd = pos.position_size_usd * net_pnl_pct / 100

        # Update capital
        self.capital += pnl_usd

        # Risk tracking
        if net_pnl_pct < 0:
            self._daily_loss += abs(net_pnl_pct)
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.config.cooldown_after_consecutive_losses:
                self._cooldown_start_idx = candle_idx
        else:
            self._consecutive_losses = 0

        if exit_reason == ExitReason.STOP_LOSS:
            self._last_sl_direction = pos.direction
            self._candles_since_last_sl = 0

        duration = candle_idx - pos.entry_candle_idx

        trade = ClosedTrade(
            timestamp_open=pos.entry_timestamp,
            timestamp_close=timestamp,
            symbol=pos.symbol,
            strategy=pos.strategy,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            sl_price=pos.sl_price,
            tp1_price=pos.tp1_price,
            tp2_price=pos.tp2_price,
            position_size_usd=pos.position_size_usd,
            pnl_pct=net_pnl_pct,
            pnl_usd=pnl_usd,
            exit_reason=exit_reason,
            duration_candles=duration,
            capital_after=self.capital,
            total_fees=fees,
            total_slippage=abs(pos.entry_price - float(pos.entry_price)),  # Simplified
            mae_pct=pos.mae_pct,
            mfe_pct=pos.mfe_pct,
            regime=pos.regime,
            session=pos.session,
            compression_percentile=pos.compression_percentile,
            compression_candles=pos.compression_candles,
            breakout_direction=pos.breakout.direction if pos.breakout else Direction.NEUTRAL,
            breakout_volume_ratio=pos.breakout.volume_ratio if pos.breakout else 0.0,
            trap_score=pos.trap_score,
            trap_evidence=pos.trap_evidence,
            z_score=pos.z_score,
            vwap_distance_pct=pos.vwap_distance_pct,
            oi_change_1h_pct=pos.micro_snapshot.get("oi_change_1h_pct", 0.0),
            funding_rate=pos.micro_snapshot.get("funding_rate", 0.0),
            basis_spread_pct=pos.micro_snapshot.get("basis_spread_pct", 0.0),
            config_version=pos.config_version,
            param_version=pos.param_version,
            git_sha=pos.git_sha,
        )

        self.trades.append(trade)
        self.position = None

    def _check_risk(self, direction: Direction, candle_idx: int = 0) -> Optional[Outcome]:
        """Pre-trade risk checks. Returns rejection Outcome or None."""
        if self.position is not None:
            return Outcome.IN_POSITION

        if self._daily_trades >= self.config.max_daily_trades:
            return Outcome.DAILY_LIMIT

        if self._daily_loss >= self.config.max_daily_loss_pct:
            return Outcome.DAILY_LIMIT

        if self._consecutive_losses >= self.config.cooldown_after_consecutive_losses:
            # Cooldown expires after directional_cooldown_candles * 2
            cooldown_duration = self.config.directional_cooldown_candles * 2
            if (candle_idx - self._cooldown_start_idx) < cooldown_duration:
                return Outcome.COOLDOWN
            # Expired — reset counter and allow trading
            self._consecutive_losses = 0

        return None

    def _run_ravr_candle(
        self,
        window: pd.DataFrame,
        regime: Regime,
        session: Session,
        symbol: str,
        run_id: str,
        i: int,
        current_ts,
    ) -> None:
        """Execute RAVR strategy for one candle. Opens trades when signal fires."""
        decision = evaluate_ravr(
            window, regime, session, self.config,
            symbol=symbol, cycle_id=f"ravr_{run_id}_{i}",
            timestamp=str(current_ts),
        )

        # Apply risk gates before execution
        if decision.outcome == Outcome.TRADE:
            risk_outcome = self._check_risk(decision.direction, candle_idx=i)
            if risk_outcome is not None:
                decision.outcome = risk_outcome
                self.decisions.append(decision)
                return

            # SL % check
            last_close = float(window["close"].iloc[-1])
            if last_close > 0:
                sl_distance = abs(decision.entry_price - decision.sl_price)
                sl_pct = sl_distance / last_close * 100
                if sl_pct > self.config.max_sl_pct:
                    decision.outcome = Outcome.RISK_BLOCKED
                    self.decisions.append(decision)
                    return

            # --- OPEN POSITION ---
            entry_price = _apply_slippage(
                decision.entry_price, decision.direction, is_entry=True,
                config=self.config, context="normal",
            )

            # Recalculate TP/SL from slipped entry, preserving VWAP-based distances
            tp1_distance = abs(decision.tp1_price - decision.entry_price)
            tp2_distance = abs(decision.tp2_price - decision.entry_price)
            sl_distance_raw = abs(decision.sl_price - decision.entry_price)

            if decision.direction == Direction.LONG:
                decision.sl_price = entry_price - sl_distance_raw
                decision.tp1_price = entry_price + tp1_distance
                decision.tp2_price = entry_price + tp2_distance
            else:
                decision.sl_price = entry_price + sl_distance_raw
                decision.tp1_price = entry_price - tp1_distance
                decision.tp2_price = entry_price - tp2_distance

            # Position sizing
            risk_usd = self.capital * self.config.max_risk_pct / 100
            sl_pct_actual = sl_distance_raw / entry_price * 100 if entry_price > 0 else 1.0
            pos_size = risk_usd / (sl_pct_actual / 100) if sl_pct_actual > 0 else 0
            pos_size = min(pos_size, self.capital * self.config.max_leverage)

            decision.entry_price = entry_price
            decision.position_size_usd = pos_size
            decision.config_version = self.config.config_hash
            decision.param_version = self.config.param_version

            self.position = _OpenPosition(decision, self.config)
            self.position.entry_candle_idx = i
            self._daily_trades += 1

        self.decisions.append(decision)

    def _build_regime_cache(
        self, candles_15m: pd.DataFrame, candles_1h: pd.DataFrame,
    ) -> Dict[int, Regime]:
        """Pre-compute regime for each 15m candle using only past 1h data.

        For each 15m candle timestamp, find 1h candles that have already closed
        (strict lookahead prevention).
        """
        cache: Dict[int, Regime] = {}

        if len(candles_1h) == 0:
            return cache

        for i in range(len(candles_15m)):
            ts = candles_15m["timestamp"].iloc[i]
            # Only use 1h candles that have closed before this 15m candle
            mask = candles_1h["timestamp"] <= ts
            past_1h = candles_1h[mask]
            cache[i] = _classify_regime(past_1h)

        return cache

    def _build_micro_index(
        self, micro_data: pd.DataFrame,
    ) -> Dict[int, Dict]:
        """Index microstructure data for quick lookup.

        For now returns empty — Enhanced mode will populate this.
        """
        # TODO: Index micro data by 15m candle alignment
        return {}

    def _get_features(
        self, timestamp: pd.Timestamp, micro_index: Dict,
    ) -> FeatureAvailability:
        """Determine which features are available at this timestamp."""
        # Baseline: candles + regime only
        features = FeatureAvailability(candles_15m=True, regime=True)

        if micro_index:
            # Enhanced mode would check freshness of each micro source
            features.oi = True
            features.liquidations = True
            features.funding = True
            features.basis = True

        return features
