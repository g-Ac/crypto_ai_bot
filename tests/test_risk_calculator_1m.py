"""Tests for 1-minute Risk Calculator (Motor 0)."""
import pytest
from risk_calculator_1m import calculate_viability, TradeViability


class TestBasicViability:
    def test_viable_long_trade(self):
        v = calculate_viability(
            symbol="BTCUSDT", entry_price=60000.0,
            sl_price=59850.0, tp_price=60450.0,  # 0.25% SL, 0.75% TP
            max_risk_per_trade_usd=2.0,
        )
        assert v.viable is True
        assert v.notional_usd == pytest.approx(2.0 / 0.0025, rel=0.01)
        assert v.leverage > 0
        assert v.risk_reward_net >= 1.5
        assert v.fee_cost_usd > 0
        assert v.expected_profit_usd > 0
        assert v.expected_loss_usd > 0

    def test_viable_short_trade(self):
        v = calculate_viability(
            symbol="ETHUSDT", entry_price=3000.0,
            sl_price=3015.0, tp_price=2955.0,  # 0.5% SL, 1.5% TP
            max_risk_per_trade_usd=2.0,
        )
        assert v.viable is True
        assert v.risk_reward_net >= 1.5

    def test_notional_below_minimum_is_not_viable(self):
        v = calculate_viability(
            symbol="BTCUSDT", entry_price=60000.0,
            sl_price=59400.0, tp_price=61800.0,
            max_risk_per_trade_usd=0.10,
        )
        assert v.viable is False
        assert "minimo" in v.reason.lower() or "notional" in v.reason.lower()

    def test_poor_rr_is_not_viable(self):
        v = calculate_viability(
            symbol="ETHUSDT", entry_price=3000.0,
            sl_price=2985.0, tp_price=3010.0,  # 0.5% SL, 0.33% TP
            max_risk_per_trade_usd=2.0,
        )
        assert v.viable is False
        assert "r:r" in v.reason.lower() or "rr" in v.reason.lower()

    def test_stop_too_tight_is_not_viable(self):
        v = calculate_viability(
            symbol="BTCUSDT", entry_price=60000.0,
            sl_price=59990.0, tp_price=60100.0,  # ~0.017% SL
            max_risk_per_trade_usd=2.0,
        )
        assert v.viable is False
        assert "stop" in v.reason.lower() or "sl" in v.reason.lower()

    def test_stop_too_wide_is_not_viable(self):
        v = calculate_viability(
            symbol="BTCUSDT", entry_price=60000.0,
            sl_price=59200.0, tp_price=62400.0,  # ~1.33% SL
            max_risk_per_trade_usd=2.0,
        )
        assert v.viable is False


class TestFeeCalculations:
    def test_fee_cost_is_positive(self):
        v = calculate_viability(
            symbol="ETHUSDT", entry_price=3000.0,
            sl_price=2985.0, tp_price=3045.0,
            max_risk_per_trade_usd=2.0,
        )
        assert v.fee_cost_usd > 0
        assert v.min_profit_to_breakeven > 0

    def test_maker_fees_are_lower(self):
        v_taker = calculate_viability(
            symbol="ETHUSDT", entry_price=3000.0,
            sl_price=2985.0, tp_price=3045.0,
            max_risk_per_trade_usd=2.0, use_maker=False,
        )
        v_maker = calculate_viability(
            symbol="ETHUSDT", entry_price=3000.0,
            sl_price=2985.0, tp_price=3045.0,
            max_risk_per_trade_usd=2.0, use_maker=True,
        )
        assert v_maker.fee_cost_usd < v_taker.fee_cost_usd

    def test_high_fee_impact_is_not_viable(self):
        v = calculate_viability(
            symbol="SOLUSDT", entry_price=150.0,
            sl_price=149.85, tp_price=150.18,  # 0.1% SL, 0.12% TP
            max_risk_per_trade_usd=2.0,
        )
        assert v.viable is False


class TestLeverageCalculation:
    def test_auto_leverage_picks_valid_value(self):
        from config_1m import VALID_LEVERAGES
        v = calculate_viability(
            symbol="BTCUSDT", entry_price=60000.0,
            sl_price=59850.0, tp_price=60450.0,
            max_risk_per_trade_usd=2.0,
        )
        assert v.leverage in VALID_LEVERAGES

    def test_preferred_leverage_is_used(self):
        v = calculate_viability(
            symbol="BTCUSDT", entry_price=60000.0,
            sl_price=59850.0, tp_price=60450.0,
            max_risk_per_trade_usd=2.0, preferred_leverage=50,
        )
        assert v.leverage == 50

    def test_position_size_equals_notional_over_leverage(self):
        v = calculate_viability(
            symbol="ETHUSDT", entry_price=3000.0,
            sl_price=2985.0, tp_price=3045.0,
            max_risk_per_trade_usd=2.0,
        )
        assert v.position_size_usd == pytest.approx(v.notional_usd / v.leverage, rel=0.01)


class TestEdgeCases:
    def test_sl_equals_entry_returns_not_viable(self):
        v = calculate_viability(
            symbol="BTCUSDT", entry_price=60000.0,
            sl_price=60000.0, tp_price=60300.0,
            max_risk_per_trade_usd=2.0,
        )
        assert v.viable is False

    def test_tp_equals_entry_returns_not_viable(self):
        v = calculate_viability(
            symbol="BTCUSDT", entry_price=60000.0,
            sl_price=59850.0, tp_price=60000.0,
            max_risk_per_trade_usd=2.0,
        )
        assert v.viable is False

    def test_unknown_symbol_uses_default_min_notional(self):
        v = calculate_viability(
            symbol="NEWCOINUSDT", entry_price=1.0,
            sl_price=0.997, tp_price=1.009,
            max_risk_per_trade_usd=2.0,
        )
        assert isinstance(v, TradeViability)
