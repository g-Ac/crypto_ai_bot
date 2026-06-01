"""Tests for trailing stop logic in check_exit()."""

import pytest
from momentum.research_runner import check_exit

# trailing-stop v1.3 foi especificado (docs/superpowers) e teve testes escritos (TDD),
# mas a implementacao nunca foi feita — a v1.1 foi congelada como baseline (otimo local,
# decisao de parar de tunar). Testes preservados como skip ate (e se) o trailing voltar.
pytestmark = pytest.mark.skip(reason="trailing-stop v1.3 nao implementado; v1.1 congelada")

LONG_BASE = dict(
    direction="LONG", entry_price=100.0,
    sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
    duration_candles=5, timeout_candles=16,
)

SHORT_BASE = dict(
    direction="SHORT", entry_price=100.0,
    sl_price=105.0, tp1_price=90.0, tp2_price=85.0,
    duration_candles=5, timeout_candles=16,
)


class TestTrailingNotActivated:
    def test_trailing_disabled_when_pct_zero(self):
        r = check_exit(**LONG_BASE, candle_high=108.0, candle_low=99.0, candle_close=107.0,
            current_mfe=7.0, current_mae=-1.0, trailing_pct=0.0, trailing_trigger_pct=0.5, current_trailing_sl=0.0)
        assert r["closed"] is False
        assert r["new_trailing_sl"] == 0.0

    def test_trailing_not_active_before_threshold(self):
        r = check_exit(**LONG_BASE, candle_high=103.0, candle_low=99.0, candle_close=102.0,
            current_mfe=2.0, current_mae=-1.0, trailing_pct=1.0, trailing_trigger_pct=0.5, current_trailing_sl=0.0)
        assert r["closed"] is False
        assert r["new_trailing_sl"] == 0.0


class TestTrailingActivation:
    def test_trailing_activates_long(self):
        # TP1 dist=10, trigger=50%=5 in price. high=106 -> MFE=6% -> 6.0>=5.0
        # trailing_sl = 106 * (1 - 1.0/100) = 104.94
        r = check_exit(**LONG_BASE, candle_high=106.0, candle_low=101.0, candle_close=105.0,
            current_mfe=4.0, current_mae=-1.0, trailing_pct=1.0, trailing_trigger_pct=0.5, current_trailing_sl=0.0)
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(104.94)

    def test_trailing_activates_short(self):
        # TP1 dist=10, trigger=50%=5 in price. low=94 -> MFE=6% -> 6.0>=5.0
        # trailing_sl = 94 * (1 + 1.0/100) = 94.94
        r = check_exit(**SHORT_BASE, candle_high=99.0, candle_low=94.0, candle_close=95.0,
            current_mfe=4.0, current_mae=-0.5, trailing_pct=1.0, trailing_trigger_pct=0.5, current_trailing_sl=0.0)
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(94.94)


class TestTrailingAdvances:
    def test_trailing_advances_on_new_high(self):
        # Previous trailing=104.94. New high=108 -> candidate=108*0.99=106.92 > 104.94
        r = check_exit(**LONG_BASE, candle_high=108.0, candle_low=105.0, candle_close=107.0,
            current_mfe=6.0, current_mae=-1.0, trailing_pct=1.0, trailing_trigger_pct=0.5, current_trailing_sl=104.94)
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(106.92)

    def test_trailing_does_not_recede(self):
        # Previous trailing=106.92. New high=105 -> candidate=103.95 < 106.92 -> stays
        r = check_exit(**LONG_BASE, candle_high=105.0, candle_low=103.0, candle_close=104.0,
            current_mfe=8.0, current_mae=-1.0, trailing_pct=1.0, trailing_trigger_pct=0.5, current_trailing_sl=106.92)
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(106.92)

    def test_short_trailing_advances_on_new_low(self):
        # Previous trailing=94.94. New low=92 -> candidate=92*1.01=92.92 < 94.94
        r = check_exit(**SHORT_BASE, candle_high=95.0, candle_low=92.0, candle_close=93.0,
            current_mfe=6.0, current_mae=-0.5, trailing_pct=1.0, trailing_trigger_pct=0.5, current_trailing_sl=94.94)
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(92.92)


class TestTrailingStopHit:
    def test_trailing_stop_hit_long(self):
        # trailing_sl=106.92, candle_low=106.0 <= 106.92 -> hit
        r = check_exit(**LONG_BASE, candle_high=107.5, candle_low=106.0, candle_close=106.5,
            current_mfe=8.0, current_mae=-1.0, trailing_pct=1.0, trailing_trigger_pct=0.5, current_trailing_sl=106.92)
        assert r["closed"] is True
        assert r["exit_reason"] == "trailing_stop"
        assert r["exit_price"] == pytest.approx(106.92)
        assert r["pnl_pct"] == pytest.approx(6.92)

    def test_trailing_stop_hit_short(self):
        # trailing_sl=92.92, candle_high=93.5 >= 92.92 -> hit
        r = check_exit(**SHORT_BASE, candle_high=93.5, candle_low=91.0, candle_close=93.0,
            current_mfe=8.0, current_mae=-0.5, trailing_pct=1.0, trailing_trigger_pct=0.5, current_trailing_sl=92.92)
        assert r["closed"] is True
        assert r["exit_reason"] == "trailing_stop"
        assert r["exit_price"] == pytest.approx(92.92)
        assert r["pnl_pct"] == pytest.approx(7.08)


class TestTrailingBreakevenInteraction:
    def test_trailing_respects_breakeven_floor(self):
        # candle_high=101, trailing_pct=2.0 -> candidate=101*0.98=98.98
        # breakeven=entry=100. max(98.98,100)=100
        r = check_exit(**LONG_BASE, candle_high=101.0, candle_low=99.5, candle_close=100.5,
            current_mfe=5.5, current_mae=-0.5, breakeven_trigger_pct=0.5,
            trailing_pct=2.0, trailing_trigger_pct=0.5, current_trailing_sl=0.0)
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(100.0)

    def test_trailing_above_breakeven_takes_precedence(self):
        # candle_high=108, trailing_pct=2.0 -> candidate=108*0.98=105.84
        # breakeven=entry=100. max(105.84,100)=105.84
        r = check_exit(**LONG_BASE, candle_high=108.0, candle_low=105.0, candle_close=107.0,
            current_mfe=6.0, current_mae=-0.5, breakeven_trigger_pct=0.5,
            trailing_pct=2.0, trailing_trigger_pct=0.5, current_trailing_sl=0.0)
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(105.84)


class TestTrailingBackwardCompat:
    def test_no_trailing_params_same_as_v12(self):
        r = check_exit(**LONG_BASE, candle_high=103.0, candle_low=99.0, candle_close=102.0,
            current_mfe=2.0, current_mae=-1.0)
        assert r["closed"] is False
        assert r["new_trailing_sl"] == 0.0
