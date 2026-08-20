from __future__ import annotations
import sqlite3, sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import options_collector as oc  # noqa: E402


def _conn():
    c = sqlite3.connect(":memory:")
    oc.init_db(c)
    return c


def test_upsert_features_idempotent():
    c = _conn()
    row = {"symbol": "BTC", "bucket_ts": 1_700_000_000, "spot": 65000.0,
           "gex": 1.2, "gex_abs": 3.4, "gamma_flip": 64000.0, "dvol": 37.0,
           "dvol_chg": -0.5, "skew_25d": 0.06, "iv_atm": 0.55, "rv_48h": 0.50,
           "vrp": 0.05, "term_slope": -0.02, "n_strikes": 900, "oi_total": 451333.0}
    assert oc.upsert_features(c, row, 1_700_000_100) == 1
    assert oc.upsert_features(c, row, 1_700_000_200) == 0   # mesmo PK -> ignora
    got = c.execute("SELECT gex, iv_atm FROM k_options_features").fetchone()
    assert got == (1.2, 0.55)


def test_upsert_agg_idempotent():
    c = _conn()
    rows = [{"symbol": "BTC", "bucket_ts": 1_700_000_000, "expiry_bucket": "7-30d",
             "strike_bucket": "atm", "oi": 1000.0, "iv_mean": 0.5, "n": 12}]
    assert oc.upsert_agg(c, rows, 1) == 1
    assert oc.upsert_agg(c, rows, 1) == 0


def test_clock_sanity_ok():
    ok, _ = oc.check_clock_sanity()
    assert ok is True


def test_parse_book_summary_filters_and_enriches():
    rows = [
        {"instrument_name": "BTC-26MAR27-105000-C", "mark_iv": 42.34,
         "open_interest": 135.6, "underlying_price": 67865.0},
        {"instrument_name": "BTC-PERPETUAL", "mark_iv": 0, "open_interest": 5},  # não-opção
        {"instrument_name": "BTC-26MAR27-90000-P", "mark_iv": 50.0,
         "open_interest": 10.0, "underlying_price": 67865.0},
    ]
    parsed = oc.parse_book_summary(rows, "BTC")
    assert len(parsed) == 2
    p = parsed[0]
    assert p["kind"] == "call" and p["strike"] == 105000.0
    assert p["iv"] == 0.4234       # % -> fração
    assert p["oi"] == 135.6


def test_parse_book_summary_skips_zero_iv():
    rows = [{"instrument_name": "BTC-26MAR27-105000-C", "mark_iv": 0.0,
             "open_interest": 1.0, "underlying_price": 1.0}]
    assert oc.parse_book_summary(rows, "BTC") == []


def test_aggregate_snapshot_buckets():
    now = 1_700_000_000
    chain = [
        {"kind": "call", "strike": 100.0, "iv": 0.5, "oi": 10.0, "expiry_ts": now + 10*86400},
        {"kind": "put",  "strike": 80.0,  "iv": 0.7, "oi": 5.0,  "expiry_ts": now + 10*86400},
    ]
    rows = oc.aggregate_snapshot(chain, 100.0, "BTC", now)
    assert all(r["symbol"] == "BTC" and r["bucket_ts"] == now for r in rows)
    atm = [r for r in rows if r["strike_bucket"] == "atm"][0]
    assert atm["oi"] == 10.0 and atm["n"] == 1


def test_build_feature_row_keys():
    now = 1_700_000_000
    chain = [
        {"kind": "call", "strike": 100.0, "iv": 0.5, "oi": 10.0, "expiry_ts": now + 30*86400},
        {"kind": "put",  "strike": 100.0, "iv": 0.5, "oi": 10.0, "expiry_ts": now + 30*86400},
    ]
    c = _conn()
    row = oc.build_feature_row(c, "BTC", chain, 100.0, (now, 37.0, -0.5), now)
    for k in ["symbol","bucket_ts","spot","gex","gex_abs","dvol","skew_25d","iv_atm","oi_total"]:
        assert k in row
    assert row["symbol"] == "BTC" and row["spot"] == 100.0 and row["dvol"] == 37.0
