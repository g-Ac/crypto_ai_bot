import os
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import raiox_paper as rp


def _book():
    return rp.empty_book(10000.0)


def test_empty_book_defaults():
    b = _book()
    assert b["balance"] == 10000.0 and b["next_id"] == 1
    assert b["positions"] == [] and b["closed"] == []


def test_open_order_basic_and_ids():
    b = _book()
    p = rp.open_order(b, symbol="ETHUSDT", side="LONG", entry_price=1700,
                      margin_usd=500, leverage=10, now_s=1000)
    assert p["id"] == 1 and p["notional_usd"] == 5000.0
    assert p["qty"] == round(5000 / 1700, 8)
    assert b["next_id"] == 2 and len(b["positions"]) == 1
    assert rp.available_balance(b) == 9500.0


def test_open_order_rejects_bad_inputs():
    b = _book()
    with pytest.raises(ValueError, match="side_invalido"):
        rp.open_order(b, symbol="ETHUSDT", side="UP", entry_price=1700, margin_usd=10, leverage=5)
    with pytest.raises(ValueError, match="leverage_invalido"):
        rp.open_order(b, symbol="ETHUSDT", side="LONG", entry_price=1700, margin_usd=10, leverage=999)
    with pytest.raises(ValueError, match="saldo_insuficiente"):
        rp.open_order(b, symbol="ETHUSDT", side="LONG", entry_price=1700, margin_usd=99999, leverage=2)


def test_open_order_validates_sl_tp_sides():
    b = _book()
    with pytest.raises(ValueError, match="sl_invalido"):
        rp.open_order(b, symbol="ETHUSDT", side="LONG", entry_price=1700,
                      margin_usd=100, leverage=5, sl_price=1750)
    with pytest.raises(ValueError, match="tp_invalido"):
        rp.open_order(b, symbol="ETHUSDT", side="SHORT", entry_price=1700,
                      margin_usd=100, leverage=5, tp_price=1800)
    p = rp.open_order(b, symbol="ETHUSDT", side="LONG", entry_price=1700,
                      margin_usd=100, leverage=5, sl_price=1680, tp_price=1740)
    assert p["sl_price"] == 1680 and p["tp_price"] == 1740


def test_position_pnl_long_and_short():
    b = _book()
    pl = rp.open_order(b, symbol="ETHUSDT", side="LONG", entry_price=1000, margin_usd=100, leverage=10)
    m = rp.position_pnl(pl, 1010)  # +1% move, 10x -> +10% margem, notional 1000 -> +10 usd
    assert m["pnl_usd"] == 10.0 and m["pnl_pct"] == 10.0
    ps = rp.open_order(b, symbol="ETHUSDT", side="SHORT", entry_price=1000, margin_usd=100, leverage=10)
    m2 = rp.position_pnl(ps, 990)  # cai 1% -> short ganha
    assert m2["pnl_usd"] == 10.0 and m2["pnl_pct"] == 10.0


def test_close_position_updates_balance():
    b = _book()
    p = rp.open_order(b, symbol="ETHUSDT", side="LONG", entry_price=1000, margin_usd=100, leverage=10)
    closed = rp.close_position(b, p["id"], 1010, reason="manual", now_s=2000)
    assert closed["pnl_usd"] == 10.0 and closed["status"] == "closed"
    assert b["balance"] == 10010.0 and b["positions"] == []
    assert b["closed"][0]["id"] == p["id"]


def test_mark_and_autoclose_hits_sl_and_tp():
    b = _book()
    rp.open_order(b, symbol="ETHUSDT", side="LONG", entry_price=1000, margin_usd=100,
                  leverage=5, sl_price=980, tp_price=1040)
    rp.open_order(b, symbol="BTCUSDT", side="SHORT", entry_price=50000, margin_usd=100,
                  leverage=5, tp_price=49000)
    prices = {"ETHUSDT": 975, "BTCUSDT": 48000}
    auto = rp.mark_and_autoclose(b, lambda s: prices[s], now_s=3000)
    reasons = sorted(c["exit_reason"] for c in auto)
    assert reasons == ["sl_hit", "tp_hit"]
    assert b["positions"] == []


def test_view_summary_and_unrealized():
    b = _book()
    rp.open_order(b, symbol="ETHUSDT", side="LONG", entry_price=1000, margin_usd=100, leverage=10)
    v = rp.view(b, lambda s: 1010)
    assert v["available"] == 9900.0
    assert v["unrealized_usd"] == 10.0 and v["equity"] == 10010.0
    assert v["positions"][0]["mark"]["pnl_usd"] == 10.0


def test_save_load_roundtrip_and_reset():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        b = _book()
        rp.open_order(b, symbol="ETHUSDT", side="LONG", entry_price=1700, margin_usd=50, leverage=3)
        rp.save_book(path, b)
        b2 = rp.load_book(path)
        assert len(b2["positions"]) == 1 and b2["next_id"] == 2
        b3 = rp.reset_book(path)
        assert b3["positions"] == [] and rp.load_book(path)["balance"] == 10000.0
    finally:
        os.unlink(path)
