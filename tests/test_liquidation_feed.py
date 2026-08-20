"""Testes do gancho de persistencia (event_sink) do liquidation_feed."""
import json

import liquidation_feed as lf


def _msg(symbol="BTCUSDT", side="SELL", qty="1.0", price="60000.0", T=1700000000000):
    return json.dumps(
        {"e": "forceOrder", "E": T,
         "o": {"s": symbol, "S": side, "q": qty, "p": price, "ap": price, "T": T}}
    ).encode()


def test_sink_receives_event():
    lf._symbols = {"BTCUSDT"}
    captured = []
    lf.set_event_sink(lambda *a: captured.append(a))
    try:
        lf._process_message(_msg())
    finally:
        lf.set_event_sink(None)
    assert len(captured) == 1
    event_ms, symbol, side, qty, price, notional = captured[0]
    assert symbol == "BTCUSDT"
    assert side == "SELL"
    assert qty == 1.0
    assert price == 60000.0
    assert notional == 60000.0
    assert event_ms == 1700000000000


def test_sink_exception_does_not_propagate():
    lf._symbols = {"BTCUSDT"}
    lf.set_event_sink(lambda *a: (_ for _ in ()).throw(ValueError("boom")))
    try:
        lf._process_message(_msg())  # nao deve levantar
    finally:
        lf.set_event_sink(None)


def test_sink_not_called_for_other_symbol():
    lf._symbols = {"BTCUSDT"}
    captured = []
    lf.set_event_sink(lambda *a: captured.append(a))
    try:
        lf._process_message(_msg(symbol="DOGEUSDT"))
    finally:
        lf.set_event_sink(None)
    assert captured == []


def test_no_sink_is_safe():
    lf._symbols = {"BTCUSDT"}
    lf.set_event_sink(None)
    lf._process_message(_msg())  # sem sink, nao deve levantar


def test_in_memory_window_still_works_with_sink():
    """O gancho nao pode quebrar o comportamento original (janela em memoria)."""
    lf._symbols = {"BTCUSDT"}
    with lf._lock:
        lf._liquidations.clear()
    lf.set_event_sink(lambda *a: None)
    try:
        lf._process_message(_msg(side="SELL", qty="2.0", price="50000.0"))
    finally:
        lf.set_event_sink(None)
    agg = lf.get_symbol_liquidations("BTCUSDT")
    assert agg["count"] == 1
    assert agg["liquidation_vol_long"] == 100000.0  # SELL = long liquidada
