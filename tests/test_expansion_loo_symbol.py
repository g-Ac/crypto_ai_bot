"""Tests for leave-one-out by symbol."""
from momentum.expansion.leave_one_out import loo_by_symbol


def _trade(sym, pnl):
    return {"symbol": sym, "pnl_pct": pnl}


def test_loo_removes_one_symbol_at_a_time():
    trades = [
        _trade("BTCUSDT", 1.0), _trade("BTCUSDT", -0.5),
        _trade("ETHUSDT", 2.0),
        _trade("DOGEUSDT", 0.3),
    ]
    universe = ("BTCUSDT", "ETHUSDT", "DOGEUSDT")
    loo = loo_by_symbol(trades, universe)
    assert set(loo.keys()) == set(universe)
    # When BTCUSDT is removed, only ETH(+2.0) and DOGE(+0.3) remain
    assert loo["BTCUSDT"]["n_trades"] == 2


def test_loo_preserves_others():
    trades = [_trade("BTCUSDT", 1.0), _trade("ETHUSDT", -1.0)]
    loo = loo_by_symbol(trades, ("BTCUSDT", "ETHUSDT"))
    assert loo["BTCUSDT"]["n_trades"] == 1  # only ETH left
    assert loo["ETHUSDT"]["n_trades"] == 1  # only BTC left


def test_loo_empty_trades():
    loo = loo_by_symbol([], ("BTCUSDT", "ETHUSDT"))
    for sym in ("BTCUSDT", "ETHUSDT"):
        assert loo[sym]["n_trades"] == 0
