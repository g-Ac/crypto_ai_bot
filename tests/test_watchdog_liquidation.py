"""Testes do watchdog do liquidation_collector.

Cobre a lógica pura de classificação (evaluate) e a integração real com o
liquidation_store (last_event_age_seconds -> evaluate).
"""
import os
import sqlite3
import sys

import liquidation_store as ls

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
import watchdog_liquidation as wl  # noqa: E402


# ─── Lógica pura: evaluate ──────────────────────────────────────────────────
def test_evaluate_never_when_age_none():
    assert wl.evaluate(None, 90) == ("never", None)


def test_evaluate_ok_well_below_threshold():
    status, gap = wl.evaluate(60, 90)  # 1 min
    assert status == "ok"
    assert gap == 1.0


def test_evaluate_ok_just_below_threshold():
    status, _ = wl.evaluate(89 * 60, 90)
    assert status == "ok"


def test_evaluate_boundary_exact_is_ok():
    # exatamente no threshold NÃO é stale (usa '>' estrito)
    status, gap = wl.evaluate(90 * 60, 90)
    assert status == "ok"
    assert gap == 90.0


def test_evaluate_stale_just_over_threshold():
    status, _ = wl.evaluate(90 * 60 + 1, 90)
    assert status == "stale"


def test_evaluate_stale_well_over():
    status, gap = wl.evaluate(120 * 60, 90)
    assert status == "stale"
    assert gap == 120.0


# ─── Integração com o store real ────────────────────────────────────────────
def _mem_conn():
    c = sqlite3.connect(":memory:")
    ls.ensure_schema(c)
    return c


def test_integration_fresh_event_is_ok():
    c = _mem_conn()
    now = 1_700_000_000
    ls.insert_liquidations(
        c, [("BTCUSDT", now * 1000, "SELL", 1.0, 60000.0, 60000.0, now)], source="bybit"
    )
    age = ls.last_event_age_seconds(c, now, source="bybit")
    assert wl.evaluate(age, 90)[0] == "ok"


def test_integration_old_event_is_stale():
    c = _mem_conn()
    now = 1_700_000_000
    old_event_s = now - 3 * 3600  # 3h atrás
    ls.insert_liquidations(
        c, [("BTCUSDT", old_event_s * 1000, "SELL", 1.0, 60000.0, 60000.0, old_event_s)],
        source="bybit",
    )
    age = ls.last_event_age_seconds(c, now, source="bybit")
    assert age >= 3 * 3600 - 1
    assert wl.evaluate(age, 90)[0] == "stale"


def test_integration_empty_table_is_never():
    c = _mem_conn()
    age = ls.last_event_age_seconds(c, 1_700_000_000, source="bybit")
    assert age is None
    assert wl.evaluate(age, 90)[0] == "never"


def test_integration_source_filter_isolates_bybit():
    # liquidação de outra venue não conta para o feed bybit
    c = _mem_conn()
    now = 1_700_000_000
    ls.insert_liquidations(
        c, [("BTCUSDT", now * 1000, "SELL", 1.0, 60000.0, 60000.0, now)], source="binance"
    )
    age = ls.last_event_age_seconds(c, now, source="bybit")
    assert age is None  # nada de bybit -> never
    assert wl.evaluate(age, 90)[0] == "never"
