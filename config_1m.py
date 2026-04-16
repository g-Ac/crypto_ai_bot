"""Configuration for the 1-minute multi-engine trading system."""
from dataclasses import dataclass, field
from typing import List, Optional

BINANCE_MIN_NOTIONAL = {
    "BTCUSDT": 100,
    "ETHUSDT": 20,
    "SOLUSDT": 5,
    "BNBUSDT": 20,
    "XRPUSDT": 5,
    "DOGEUSDT": 5,
}
_DEFAULT_MIN_NOTIONAL = 5

BINANCE_MAX_LEVERAGE = {
    "BTCUSDT": 125,
    "ETHUSDT": 100,
    "SOLUSDT": 50,
    "BNBUSDT": 50,
    "XRPUSDT": 50,
    "DOGEUSDT": 50,
}
_DEFAULT_MAX_LEVERAGE = 50

def get_min_notional(symbol: str) -> float:
    return BINANCE_MIN_NOTIONAL.get(symbol, _DEFAULT_MIN_NOTIONAL)

def get_max_leverage(symbol: str) -> int:
    return BINANCE_MAX_LEVERAGE.get(symbol, _DEFAULT_MAX_LEVERAGE)

VALID_LEVERAGES = [1, 2, 3, 5, 10, 20, 25, 50, 75, 100, 125]

@dataclass
class Config1m:
    # Risk Calculator
    max_risk_per_trade_usd: float = 2.0
    min_rr_net: float = 1.5
    max_fee_impact_pct: float = 30.0
    min_sl_distance_pct: float = 0.05
    max_sl_distance_pct: float = 1.0
    preferred_leverage: Optional[int] = None
    use_maker_orders: bool = False
    maker_fee_pct: float = 0.02
    taker_fee_pct: float = 0.04
    fee_roundtrip_pct: float = 0.08

    def __post_init__(self):
        expected = (self.maker_fee_pct if self.use_maker_orders else self.taker_fee_pct) * 2
        if abs(self.fee_roundtrip_pct - expected) > 1e-9:
            self.fee_roundtrip_pct = expected

    # Position Management
    max_positions: int = 3
    cooldown_candles: int = 5
    daily_loss_limit_pct: float = 5.0

    # Capital
    capital_usd: float = 100.0

    # Symbols
    symbols: List[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

    # Engine flags
    engine_momentum_burst: bool = True
    engine_breakout: bool = False
    engine_sr_bounce: bool = False
    engine_mean_reversion: bool = False
    engine_liquidity_sweep: bool = False

    # Backtest
    backtest_days: int = 30
