"""Testes do k_collector — parsing e validacao.

Cobre:
- parse_ratio_response: dict bem-formado vs malformado
- parse_klines_response: idem para klines
- validate_ratio: ranges, alinhamento, timestamps
- validate_price: OHLC consistency
- upsert: idempotencia (INSERT OR IGNORE)

Nao testa HTTP ao vivo (mock seria overhead pra valor pequeno; backfill manual e
runs reais cobrem caminho integrado).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import k_collector as kc  # noqa: E402


# ─── parse_ratio_response ───────────────────────────────────────────────


def test_parse_ratio_well_formed():
    raw = [
        {
            "symbol": "BTCUSDT",
            "longAccount": "0.4553",
            "longShortRatio": "0.8358",
            "shortAccount": "0.5447",
            "timestamp": 1777521600000,
        },
        {
            "symbol": "BTCUSDT",
            "longAccount": "0.4577",
            "longShortRatio": "0.8441",
            "shortAccount": "0.5423",
            "timestamp": 1777528800000,
        },
    ]
    parsed = kc.parse_ratio_response(raw, "top_position")
    assert len(parsed) == 2
    p = parsed[0]
    assert p["symbol"] == "BTCUSDT"
    assert p["bucket_ts"] == 1777521600
    assert p["source"] == "top_position"
    assert p["long_short_ratio"] == pytest.approx(0.8358)
    assert p["long_account"] == pytest.approx(0.4553)
    assert p["short_account"] == pytest.approx(0.5447)


def test_parse_ratio_skips_malformed():
    raw = [
        {"symbol": "BTC", "timestamp": 1777521600000},  # sem ratio
        {"longShortRatio": "0.8", "timestamp": "bad"},  # ts invalido
        {
            "symbol": "BTCUSDT",
            "longShortRatio": "0.84",
            "longAccount": "0.45",
            "shortAccount": "0.55",
            "timestamp": 1777521600000,
        },
    ]
    parsed = kc.parse_ratio_response(raw, "global_account")
    assert len(parsed) == 1
    assert parsed[0]["bucket_ts"] == 1777521600


def test_parse_ratio_handles_missing_accounts():
    raw = [
        {
            "symbol": "BTCUSDT",
            "longShortRatio": "0.84",
            "timestamp": 1777521600000,
        },
    ]
    parsed = kc.parse_ratio_response(raw, "top_position")
    assert len(parsed) == 1
    assert parsed[0]["long_account"] is None
    assert parsed[0]["short_account"] is None


# ─── parse_klines_response ─────────────────────────────────────────────


def test_parse_klines_well_formed():
    raw = [
        [1777521600000, "75881.60", "75931.70", "75363.20", "75458.30",
         "4706.240", 1777525199999, "355674488.31770", 116871, "2185.122",
         "165158588.63390", "0"]
    ]
    parsed = kc.parse_klines_response(raw, "BTCUSDT")
    assert len(parsed) == 1
    p = parsed[0]
    assert p["symbol"] == "BTCUSDT"
    assert p["bucket_ts"] == 1777521600
    assert p["open_price"] == pytest.approx(75881.60)
    assert p["high_price"] == pytest.approx(75931.70)
    assert p["low_price"] == pytest.approx(75363.20)
    assert p["close_price"] == pytest.approx(75458.30)
    assert p["volume"] == pytest.approx(4706.240)


def test_parse_klines_skips_malformed():
    raw = [
        [1777521600000],  # campos insuficientes
        ["bad-ts", "1", "2", "0.5", "1.5", "10"],  # ts nao-numerico
        [1777521600000, "75000", "75100", "74900", "75050", "1000"],  # ok
    ]
    parsed = kc.parse_klines_response(raw, "BTCUSDT")
    assert len(parsed) == 1


# ─── validate_ratio ─────────────────────────────────────────────────────


@pytest.fixture
def now():
    return 1780000000  # epoch fixo para testes determinísticos


def make_ratio(now: int, **overrides) -> dict:
    base = {
        "symbol": "BTCUSDT",
        "bucket_ts": (now // 3600) * 3600 - 3600,  # hora cheia, passado próximo
        "source": "top_position",
        "long_short_ratio": 0.85,
        "long_account": 0.46,
        "short_account": 0.54,
    }
    base.update(overrides)
    return base


def test_validate_ratio_ok(now):
    assert kc.validate_ratio(make_ratio(now), now)


def test_validate_ratio_misaligned_bucket(now):
    r = make_ratio(now, bucket_ts=now - 1800)  # nao alinhado a hora
    assert not kc.validate_ratio(r, now)


def test_validate_ratio_future_bucket(now):
    r = make_ratio(now, bucket_ts=now + 7200)
    assert not kc.validate_ratio(r, now)


def test_validate_ratio_too_old(now):
    r = make_ratio(now, bucket_ts=now - 40 * 86400)
    assert not kc.validate_ratio(r, now)


def test_validate_ratio_negative_or_zero(now):
    r = make_ratio(now, long_short_ratio=0.0)
    assert not kc.validate_ratio(r, now)
    r = make_ratio(now, long_short_ratio=-1.0)
    assert not kc.validate_ratio(r, now)


def test_validate_ratio_extreme_high_rejected(now):
    r = make_ratio(now, long_short_ratio=150.0)
    assert not kc.validate_ratio(r, now)


def test_validate_ratio_account_fractions_must_sum_to_one(now):
    r = make_ratio(now, long_account=0.5, short_account=0.4)
    assert not kc.validate_ratio(r, now)


def test_validate_ratio_account_fractions_out_of_range(now):
    r = make_ratio(now, long_account=1.5, short_account=-0.5)
    assert not kc.validate_ratio(r, now)


def test_validate_ratio_missing_accounts_ok(now):
    r = make_ratio(now, long_account=None, short_account=None)
    assert kc.validate_ratio(r, now)


# ─── validate_price ─────────────────────────────────────────────────────


def make_price(now: int, **overrides) -> dict:
    base = {
        "symbol": "BTCUSDT",
        "bucket_ts": (now // 3600) * 3600 - 3600,
        "open_price": 75000.0,
        "high_price": 75100.0,
        "low_price": 74900.0,
        "close_price": 75050.0,
        "volume": 1000.0,
    }
    base.update(overrides)
    return base


def test_validate_price_ok(now):
    assert kc.validate_price(make_price(now), now)


def test_validate_price_negative_close(now):
    p = make_price(now, close_price=-1.0)
    assert not kc.validate_price(p, now)


def test_validate_price_high_below_open_close(now):
    p = make_price(now, high_price=74000.0)  # menor que open=75000
    assert not kc.validate_price(p, now)


def test_validate_price_low_above_open_close(now):
    p = make_price(now, low_price=76000.0)  # maior que open=75000
    assert not kc.validate_price(p, now)


def test_validate_price_misaligned_ts(now):
    p = make_price(now, bucket_ts=now - 100)
    assert not kc.validate_price(p, now)


# ─── upsert idempotencia ───────────────────────────────────────────────


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(kc.SCHEMA)
    return c


def test_upsert_ratios_idempotent(conn, now, monkeypatch):
    monkeypatch.setattr(kc, "now_ts", lambda: now)
    rows = [make_ratio(now)]
    n1 = kc.upsert_ratios(conn, rows, collected_at=now)
    n2 = kc.upsert_ratios(conn, rows, collected_at=now)
    assert n1 == 1
    assert n2 == 0  # PK colide, INSERT OR IGNORE
    cnt = conn.execute("SELECT COUNT(*) FROM k_ratios").fetchone()[0]
    assert cnt == 1


def test_upsert_prices_idempotent(conn, now, monkeypatch):
    monkeypatch.setattr(kc, "now_ts", lambda: now)
    rows = [make_price(now)]
    n1 = kc.upsert_prices(conn, rows, collected_at=now)
    n2 = kc.upsert_prices(conn, rows, collected_at=now)
    assert n1 == 1
    assert n2 == 0
    cnt = conn.execute("SELECT COUNT(*) FROM k_prices").fetchone()[0]
    assert cnt == 1


def test_upsert_ratios_drops_invalid(conn, now, monkeypatch):
    monkeypatch.setattr(kc, "now_ts", lambda: now)
    rows = [
        make_ratio(now, long_short_ratio=200.0),  # invalido (>100)
        make_ratio(now, bucket_ts=(now // 3600) * 3600 - 7200),  # ok, hora diferente
    ]
    n = kc.upsert_ratios(conn, rows, collected_at=now)
    assert n == 1
    cnt = conn.execute("SELECT COUNT(*) FROM k_ratios").fetchone()[0]
    assert cnt == 1


def test_upsert_ratios_distinct_sources_coexist(conn, now, monkeypatch):
    monkeypatch.setattr(kc, "now_ts", lambda: now)
    bts = (now // 3600) * 3600 - 3600
    rows = [
        make_ratio(now, bucket_ts=bts, source="top_position"),
        make_ratio(now, bucket_ts=bts, source="global_account"),
    ]
    n = kc.upsert_ratios(conn, rows, collected_at=now)
    assert n == 2
    cnt = conn.execute("SELECT COUNT(*) FROM k_ratios").fetchone()[0]
    assert cnt == 2


# ─── funding / open interest extension ─────────────────────────────────


def make_funding(now: int, **overrides) -> dict:
    base = {
        "symbol": "BTCUSDT",
        "funding_time": (now // 3600) * 3600 - 8 * 3600,
        "funding_rate": 0.0001,
        "mark_price": 75000.0,
    }
    base.update(overrides)
    return base


def make_open_interest(now: int, **overrides) -> dict:
    base = {
        "symbol": "BTCUSDT",
        "bucket_ts": (now // 3600) * 3600 - 3600,
        "sum_open_interest": 1000.0,
        "sum_open_interest_value": 75000000.0,
    }
    base.update(overrides)
    return base


def test_parse_funding_response_well_formed():
    raw = [{
        "symbol": "BTCUSDT",
        "fundingTime": 1777996800000,
        "fundingRate": "-0.00008240",
        "markPrice": "81488.70000000",
    }]
    parsed = kc.parse_funding_response(raw, "BTCUSDT")
    assert len(parsed) == 1
    assert parsed[0]["symbol"] == "BTCUSDT"
    assert parsed[0]["funding_time"] == 1777996800
    assert parsed[0]["funding_rate"] == pytest.approx(-0.00008240)
    assert parsed[0]["mark_price"] == pytest.approx(81488.7)


def test_parse_funding_response_skips_malformed():
    raw = [
        {"symbol": "BTCUSDT", "fundingRate": "0.0001"},
        {"symbol": "BTCUSDT", "fundingTime": 1777996800000, "fundingRate": "bad"},
        {"symbol": "BTCUSDT", "fundingTime": 1777996800000, "fundingRate": "0.0001"},
    ]
    parsed = kc.parse_funding_response(raw, "BTCUSDT")
    assert len(parsed) == 1
    assert parsed[0]["mark_price"] is None


def test_parse_open_interest_response_well_formed():
    raw = [{
        "symbol": "BTCUSDT",
        "sumOpenInterest": "114322.01300000",
        "sumOpenInterestValue": "9288743581.65910000",
        "timestamp": 1778000400000,
    }]
    parsed = kc.parse_open_interest_response(raw, "BTCUSDT")
    assert len(parsed) == 1
    assert parsed[0]["symbol"] == "BTCUSDT"
    assert parsed[0]["bucket_ts"] == 1778000400
    assert parsed[0]["sum_open_interest"] == pytest.approx(114322.013)
    assert parsed[0]["sum_open_interest_value"] == pytest.approx(9288743581.6591)


def test_parse_open_interest_response_skips_malformed():
    raw = [
        {"symbol": "BTCUSDT", "timestamp": 1778000400000},
        {"symbol": "BTCUSDT", "sumOpenInterest": "bad", "timestamp": 1778000400000},
        {"symbol": "BTCUSDT", "sumOpenInterest": "1", "timestamp": 1778000400000},
    ]
    parsed = kc.parse_open_interest_response(raw, "BTCUSDT")
    assert len(parsed) == 1
    assert parsed[0]["sum_open_interest_value"] is None


def test_validate_funding_ok(now):
    assert kc.validate_funding(make_funding(now), now)


def test_validate_funding_rejects_future(now):
    assert not kc.validate_funding(make_funding(now, funding_time=now + 7200), now)


def test_validate_funding_rejects_absurd_rate(now):
    assert not kc.validate_funding(make_funding(now, funding_rate=1.5), now)


def test_validate_open_interest_ok(now):
    assert kc.validate_open_interest(make_open_interest(now), now)


def test_validate_open_interest_rejects_misaligned_bucket(now):
    assert not kc.validate_open_interest(make_open_interest(now, bucket_ts=now - 100), now)


def test_validate_open_interest_rejects_negative_oi(now):
    assert not kc.validate_open_interest(make_open_interest(now, sum_open_interest=-1), now)


def test_upsert_funding_idempotent(conn, now, monkeypatch):
    monkeypatch.setattr(kc, "now_ts", lambda: now)
    rows = [make_funding(now)]
    n1 = kc.upsert_funding(conn, rows, collected_at=now)
    n2 = kc.upsert_funding(conn, rows, collected_at=now)
    assert n1 == 1
    assert n2 == 0
    cnt = conn.execute("SELECT COUNT(*) FROM k_funding_rates").fetchone()[0]
    assert cnt == 1


def test_upsert_open_interest_idempotent(conn, now, monkeypatch):
    monkeypatch.setattr(kc, "now_ts", lambda: now)
    rows = [make_open_interest(now)]
    n1 = kc.upsert_open_interest(conn, rows, collected_at=now)
    n2 = kc.upsert_open_interest(conn, rows, collected_at=now)
    assert n1 == 1
    assert n2 == 0
    cnt = conn.execute("SELECT COUNT(*) FROM k_open_interest").fetchone()[0]
    assert cnt == 1
