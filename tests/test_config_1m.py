"""Tests for 1-minute system configuration."""
import pytest

def test_config_defaults():
    from config_1m import Config1m
    c = Config1m()
    assert c.max_risk_per_trade_usd == 2.0
    assert c.min_rr_net == 1.5
    assert c.max_fee_impact_pct == 30.0
    assert c.min_sl_distance_pct == 0.05
    assert c.max_sl_distance_pct == 1.0
    assert c.preferred_leverage is None
    assert c.use_maker_orders is False
    assert c.max_positions == 3
    assert c.cooldown_candles == 5
    assert c.daily_loss_limit_pct == 5.0
    assert c.capital_usd == 100.0
    assert c.symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert c.backtest_days == 30
    assert c.fee_roundtrip_pct == 0.08

def test_config_custom_values():
    from config_1m import Config1m
    c = Config1m(max_risk_per_trade_usd=5.0, capital_usd=500.0, symbols=["BTCUSDT"])
    assert c.max_risk_per_trade_usd == 5.0
    assert c.capital_usd == 500.0
    assert c.symbols == ["BTCUSDT"]

def test_binance_min_notional():
    from config_1m import get_min_notional
    assert get_min_notional("BTCUSDT") == 100
    assert get_min_notional("ETHUSDT") == 20
    assert get_min_notional("UNKNOWNUSDT") == 5

def test_valid_leverages():
    from config_1m import VALID_LEVERAGES
    assert VALID_LEVERAGES == [1, 2, 3, 5, 10, 20, 25, 50, 75, 100, 125]
    assert VALID_LEVERAGES == sorted(VALID_LEVERAGES)

def test_engine_flags_default():
    from config_1m import Config1m
    c = Config1m()
    assert c.engine_momentum_burst is True
    assert c.engine_breakout is False
    assert c.engine_sr_bounce is False
    assert c.engine_mean_reversion is False
    assert c.engine_liquidity_sweep is False


def test_max_leverage_per_symbol():
    from config_1m import get_max_leverage
    assert get_max_leverage("BTCUSDT") == 125
    assert get_max_leverage("ETHUSDT") == 100
    assert get_max_leverage("SOLUSDT") == 50
    assert get_max_leverage("UNKNOWNUSDT") == 50  # default


def test_fee_roundtrip_auto_sync():
    """fee_roundtrip_pct is auto-corrected if inconsistent with per-side fees."""
    from config_1m import Config1m
    # Taker default: 0.04 * 2 = 0.08
    c = Config1m()
    assert c.fee_roundtrip_pct == 0.08
    # Mismatch: roundtrip says 0.10 but taker is 0.04 -> corrected to 0.08
    c2 = Config1m(fee_roundtrip_pct=0.10)
    assert c2.fee_roundtrip_pct == pytest.approx(0.08)
    # Maker mode: 0.02 * 2 = 0.04
    c3 = Config1m(use_maker_orders=True)
    assert c3.fee_roundtrip_pct == pytest.approx(0.04)
