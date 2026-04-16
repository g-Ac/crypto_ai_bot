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
