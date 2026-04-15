"""Configuration for the defensive trading subsystem.

All parameters have sensible defaults from literature / first principles.
Do NOT optimize these before having baseline backtest results.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List


@dataclass
class DefensiveConfig:
    """Full configuration — frozen for a given param_version."""

    # --- Identity ---
    param_version: str = "v0.1"

    # --- Enabled strategies ---
    baseline_enabled: bool = True
    enhanced_enabled: bool = False   # Feature flag: off until baseline validated
    ravr_enabled: bool = False       # Benchmark: off until baseline validated

    # --- Capital and risk ---
    initial_capital: float = 1000.0
    max_risk_pct: float = 0.5        # 0.5% per trade (phase 1)
    max_positions: int = 1
    max_leverage: int = 3
    max_sl_pct: float = 2.5          # Reject trade if SL > 2.5%
    min_rr: float = 2.0              # Minimum reward:risk ratio

    # --- Compression detection (Layer 1) ---
    compression_lookback: int = 100
    compression_percentile: int = 20
    compression_min_decline: int = 6  # Consecutive candles of BB Width decline
    compression_atr_lookback: int = 4  # ATR must decline over this many candles
    compression_volume_mult: float = 1.2  # Volume must be <= SMA20 * this

    # --- Breakout detection (Layer 2) ---
    breakout_volume_mult: float = 1.5
    breakout_reclaim_window: int = 3  # Candles to reclaim range

    # --- v0.2: Compression as prior state ---
    compression_memory_window: int = 0   # v0.1=0 (require active), v0.2=12
    breakout_require_volume: bool = True  # v0.1=True, v0.2=False

    # --- Trap scoring (Layer 3 — Enhanced only) ---
    # HYPOTHESIS: weights are initial, validated by ablation
    trap_min_score: int = 30
    trap_min_score_no_primary: int = 40  # Higher bar without OI/liq
    trap_weight_oi: int = 35
    trap_weight_liq: int = 30
    trap_weight_crowding: int = 25
    trap_weight_basis: int = 15
    trap_oi_expand_threshold_pct: float = 0.3
    trap_liq_threshold_usd: float = 50_000.0
    trap_funding_threshold: float = 0.0001   # 0.01%
    trap_ls_ratio_long_threshold: float = 1.5
    trap_ls_ratio_short_threshold: float = 0.7

    # --- RAVR ---
    ravr_zscore_threshold: float = 2.0
    ravr_vwap_period: int = 96  # 96 * 15m = 24h

    # --- RAVR v2: exit structure ---
    # TP mode: "vwap" (fraction of VWAP distance) or "rr" (multiple of SL distance)
    ravr_tp1_mode: str = "vwap"
    ravr_tp1_vwap_frac: float = 1.0   # 1.0 = full VWAP (v1), 0.4 = 40% of distance
    ravr_tp1_rr_mult: float = 1.0     # TP1 = SL distance * this (only when mode="rr")
    ravr_tp2_vwap_frac: float = 1.5   # TP2 as fraction of VWAP distance (1.0=VWAP, 1.5=VWAP+50%)
    # Z-score decay exit: close when |z-score| drops below this (0=disabled)
    ravr_zscore_exit_threshold: float = 0.0
    # Smart timeout: if positive at this candle count, realize (0=disabled, uses normal timeout)
    ravr_smart_timeout_candles: int = 0
    ravr_smart_timeout_min_pnl_pct: float = 0.0  # Minimum PnL% to trigger smart timeout

    # --- Daily / weekly limits ---
    max_daily_loss_pct: float = 1.5
    max_weekly_loss_pct: float = 3.0
    max_daily_trades: int = 3
    cooldown_after_consecutive_losses: int = 2
    directional_cooldown_candles: int = 6  # No re-entry same side after SL

    # --- Session filtering ---
    elevated_sessions: List[str] = field(default_factory=lambda: ["asia", "dead"])
    elevated_trap_score: int = 45

    # --- Position management ---
    tp1_partial_pct: float = 50.0
    breakeven_buffer_pct: float = 0.05
    timeout_candles: int = 12  # 12 * 15m = 3h
    atr_sl_multiplier: float = 1.5
    atr_sl_floor_pct: float = 0.3

    # --- Timeframes ---
    signal_timeframe: str = "15m"
    execution_timeframe: str = "5m"
    regime_timeframe: str = "1h"

    # --- Costs (backtest) ---
    fee_per_side: float = 0.04
    slippage_normal: float = 0.02
    slippage_failed_breakout: float = 0.05
    slippage_regime_shift: float = 0.03

    # --- Symbols ---
    symbols: List[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])

    # --- Circuit breaker ---
    cb_max_drawdown_total_pct: float = 8.0
    cb_max_drawdown_30d_pct: float = 5.0
    cb_max_consecutive_losses: int = 5

    # --- Data quality thresholds ---
    data_stale_seconds: int = 300  # 5 minutes
    data_min_micro_sources: int = 2

    @property
    def config_hash(self) -> str:
        """Deterministic hash for versioning."""
        raw = json.dumps(asdict(self), sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()[:8]

    @classmethod
    def from_env(cls) -> "DefensiveConfig":
        """Override defaults with DEFENSIVE_* env vars where set."""
        c = cls()
        c.initial_capital = float(os.environ.get("DEFENSIVE_INITIAL_CAPITAL", c.initial_capital))
        symbols_env = os.environ.get("DEFENSIVE_SYMBOLS", "")
        if symbols_env.strip():
            c.symbols = [s.strip().upper() for s in symbols_env.split(",") if s.strip()]
        c.enhanced_enabled = os.environ.get("DEFENSIVE_ENHANCED", "false").lower() == "true"
        c.ravr_enabled = os.environ.get("DEFENSIVE_RAVR", "false").lower() == "true"
        return c
