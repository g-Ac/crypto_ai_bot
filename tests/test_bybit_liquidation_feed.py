"""Testes do bybit_liquidation_feed (parsing allLiquidation + sink)."""
import json

import bybit_liquidation_feed as bf


def _liq_msg(items):
    return json.dumps({"topic": "allLiquidation.BTCUSDT", "type": "snapshot",
                       "ts": 1700000000000, "data": items}).encode()


def test_parses_single_liquidation():
    captured = []
    bf.set_event_sink(lambda *a: captured.append(a))
    try:
        bf._process_message(_liq_msg([
            {"T": 1700000000111, "s": "BTCUSDT", "S": "Sell", "v": "0.5", "p": "60000"}
        ]))
    finally:
        bf.set_event_sink(None)
    assert len(captured) == 1
    event_ms, symbol, side, qty, price, notional = captured[0]
    assert event_ms == 1700000000111
    assert symbol == "BTCUSDT"
    assert side == "SELL"        # normalizado pra maiusculo
    assert qty == 0.5
    assert price == 60000.0
    assert notional == 30000.0


def test_parses_multiple_items():
    captured = []
    bf.set_event_sink(lambda *a: captured.append(a))
    try:
        bf._process_message(_liq_msg([
            {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "1", "p": "100"},
            {"T": 2, "s": "BTCUSDT", "S": "Sell", "v": "2", "p": "200"},
        ]))
    finally:
        bf.set_event_sink(None)
    assert len(captured) == 2
    assert captured[0][2] == "BUY"
    assert captured[1][5] == 400.0  # 2 * 200


def test_ignores_subscribe_ack():
    captured = []
    bf.set_event_sink(lambda *a: captured.append(a))
    try:
        bf._process_message(json.dumps({"success": True, "op": "subscribe"}).encode())
        bf._process_message(json.dumps({"op": "pong"}).encode())
    finally:
        bf.set_event_sink(None)
    assert captured == []


def test_skips_malformed_item_without_crashing():
    captured = []
    bf.set_event_sink(lambda *a: captured.append(a))
    try:
        bf._process_message(_liq_msg([
            {"s": "BTCUSDT", "S": "Buy"},                       # falta v/p -> pulado
            {"T": 9, "s": "ETHUSDT", "S": "Buy", "v": "1", "p": "3000"},  # ok
        ]))
    finally:
        bf.set_event_sink(None)
    assert len(captured) == 1
    assert captured[0][1] == "ETHUSDT"


def test_zero_qty_is_skipped():
    captured = []
    bf.set_event_sink(lambda *a: captured.append(a))
    try:
        bf._process_message(_liq_msg([
            {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "0", "p": "100"}
        ]))
    finally:
        bf.set_event_sink(None)
    assert captured == []


def test_sink_exception_does_not_propagate():
    bf.set_event_sink(lambda *a: (_ for _ in ()).throw(ValueError("boom")))
    try:
        bf._process_message(_liq_msg([
            {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "1", "p": "100"}
        ]))  # nao deve levantar
    finally:
        bf.set_event_sink(None)


def test_garbage_payload_is_safe():
    bf.set_event_sink(lambda *a: None)
    try:
        bf._process_message(b"\x00\x01 not json")  # nao deve levantar
    finally:
        bf.set_event_sink(None)
