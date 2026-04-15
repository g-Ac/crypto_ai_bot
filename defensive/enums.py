"""Frozen enums and codes for the defensive trading subsystem.

These are contracts. Do NOT rename or remove values after paper trading starts.
Adding new values is allowed. Renaming breaks audit log comparisons.
"""

from enum import Enum


# --- Signal / Trade direction ---

class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


# --- Strategy identifier ---

class Strategy(str, Enum):
    CFER_BASELINE = "cfer_baseline"
    CFER_ENHANCED = "cfer_enhanced"
    RAVR = "ravr"


# --- Decision outcome (why a cycle resulted in trade or no-trade) ---

class Outcome(str, Enum):
    # Trade opened
    TRADE = "trade"

    # No-trade: pipeline stages
    NO_COMPRESSION = "no_compression"
    NO_BREAKOUT = "no_breakout"
    NO_TRAP = "no_trap"              # Enhanced only
    NO_RECLAIM = "no_reclaim"
    ZSCORE_INSUFFICIENT = "zscore_insufficient"  # RAVR only

    # No-trade: context filters
    REGIME_BLOCKED = "regime_blocked"
    SESSION_BLOCKED = "session_blocked"

    # No-trade: risk gates
    RISK_BLOCKED = "risk_blocked"
    COOLDOWN = "cooldown"
    DAILY_LIMIT = "daily_limit"
    WEEKLY_LIMIT = "weekly_limit"
    IN_POSITION = "in_position"
    MAX_POSITIONS = "max_positions"

    # No-trade: kill switches
    DATA_QUALITY_KILL = "data_quality_kill"
    LATENCY_KILL = "latency_kill"
    CIRCUIT_BREAKER = "circuit_breaker"

    # Error
    ERROR = "error"


# --- Exit reason (why a position was closed) ---

class ExitReason(str, Enum):
    TP1 = "tp1"
    TP2 = "tp2"
    STOP_LOSS = "sl"
    TIMEOUT = "timeout"
    REGIME_SHIFT = "regime_shift"
    CIRCUIT_BREAKER = "circuit_breaker"
    MANUAL = "manual"
    ZSCORE_DECAY = "zscore_decay"       # RAVR v2: z-score reverted below exit threshold
    SMART_TIMEOUT = "smart_timeout"     # RAVR v2: timeout with positive PnL capture


# --- Trap evidence labels ---

class TrapEvidence(str, Enum):
    OI_TRAP = "oi_trap"
    LIQUIDATION_TRAP = "liq_trap"
    CROWDING_TRAP = "crowding_trap"
    BASIS_TRAP = "basis_trap"


# --- Feature availability flags ---

class Feature(str, Enum):
    OI = "oi"
    LIQUIDATIONS = "liquidations"
    FUNDING = "funding"
    LS_RATIO = "ls_ratio"
    BASIS = "basis"
    CANDLES_15M = "candles_15m"
    CANDLES_5M = "candles_5m"
    CANDLES_1H = "candles_1h"
    REGIME = "regime"


# --- Market regime (mirrors htf.py but frozen here as contract) ---

class Regime(str, Enum):
    TRENDING = "TRENDING"
    WEAK_TREND = "WEAK_TREND"
    VOLATILE = "VOLATILE"
    RANGING = "RANGING"
    CHOPPY = "CHOPPY"
    UNKNOWN = "UNKNOWN"


# --- Session ---

class Session(str, Enum):
    ASIA = "asia"
    EUROPE = "europe"
    US = "us"
    DEAD = "dead"


# --- Permissive regimes for defensive trading ---

PERMISSIVE_REGIMES = frozenset({Regime.RANGING, Regime.WEAK_TREND})
BLOCKED_REGIMES = frozenset({Regime.TRENDING, Regime.VOLATILE, Regime.CHOPPY})
