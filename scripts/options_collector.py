"""Coletor de opções Deribit (EXP-019 Fase 0). Hourly, idempotente, ts da Deribit.

Padrão consolidado de scripts/k_collector.py. Só coleta — nenhuma análise.
Spec: research/exp019_options_structure/PREREGISTRO.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import options_features as of  # noqa: E402

DB_PATH = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")
SYMBOLS = ["BTC", "ETH"]
INDEX_NAME = {"BTC": "btc_usd", "ETH": "eth_usd"}
BASE_URL = "https://www.deribit.com/api/v2"
USER_AGENT = "crypto_ai_bot/options_collector"
HTTP_TIMEOUT = 15.0
MAX_RETRIES = 4
BACKOFF_SECONDS = (5, 30, 120, 300)
MIN_YEAR_SANITY = 2025

SCHEMA = """
CREATE TABLE IF NOT EXISTS k_options_features (
    symbol      TEXT    NOT NULL,
    bucket_ts   INTEGER NOT NULL,
    spot        REAL,
    gex         REAL, gex_abs REAL, gamma_flip REAL,
    dvol        REAL, dvol_chg REAL,
    skew_25d    REAL, iv_atm REAL, rv_48h REAL, vrp REAL, term_slope REAL,
    n_strikes   INTEGER, oi_total REAL,
    collected_at INTEGER NOT NULL,
    PRIMARY KEY (symbol, bucket_ts)
);
CREATE INDEX IF NOT EXISTS idx_k_options_features_bucket ON k_options_features(bucket_ts);

CREATE TABLE IF NOT EXISTS k_options_snapshot_agg (
    symbol        TEXT    NOT NULL,
    bucket_ts     INTEGER NOT NULL,
    expiry_bucket TEXT    NOT NULL,
    strike_bucket TEXT    NOT NULL,
    oi            REAL, iv_mean REAL, n INTEGER,
    collected_at  INTEGER NOT NULL,
    PRIMARY KEY (symbol, bucket_ts, expiry_bucket, strike_bucket)
);

CREATE TABLE IF NOT EXISTS k_options_collector_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL, finished_at INTEGER, status TEXT,
    symbols_ok INTEGER DEFAULT 0, symbols_fail INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0, notes TEXT
);
"""

_FEATURE_COLS = ["symbol","bucket_ts","spot","gex","gex_abs","gamma_flip","dvol",
                 "dvol_chg","skew_25d","iv_atm","rv_48h","vrp","term_slope",
                 "n_strikes","oi_total"]


def now_ts() -> int:
    return int(time.time())


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_features(conn, row: dict, collected_at: int) -> int:
    vals = [row.get(c) for c in _FEATURE_COLS] + [collected_at]
    placeholders = ", ".join(["?"] * len(vals))
    cur = conn.execute(
        f"INSERT OR IGNORE INTO k_options_features "
        f"({', '.join(_FEATURE_COLS)}, collected_at) VALUES ({placeholders})",
        vals,
    )
    return cur.rowcount


def upsert_agg(conn, rows: list[dict], collected_at: int) -> int:
    inserted = 0
    for r in rows:
        cur = conn.execute(
            "INSERT OR IGNORE INTO k_options_snapshot_agg "
            "(symbol, bucket_ts, expiry_bucket, strike_bucket, oi, iv_mean, n, collected_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (r["symbol"], r["bucket_ts"], r["expiry_bucket"], r["strike_bucket"],
             r.get("oi"), r.get("iv_mean"), r.get("n"), collected_at),
        )
        inserted += cur.rowcount
    return inserted


def check_clock_sanity() -> tuple[bool, str]:
    now = dt.datetime.now(dt.timezone.utc)
    if now.year < MIN_YEAR_SANITY:
        return False, f"relogio do Pi parece errado: ano={now.year} < {MIN_YEAR_SANITY}. Aborta."
    return True, f"clock ok: {now.isoformat()}"


class FetchError(Exception):
    pass


def http_get_json(path: str, params: dict):
    url = f"{BASE_URL}{path}?{urlencode(params)}"
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8"))
                    return payload.get("result", payload)
                raise FetchError(f"HTTP {resp.status}")
        except HTTPError as e:
            if e.code in (429, 503):
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BACKOFF_SECONDS[attempt]); continue
                raise FetchError(f"rate limit after {MAX_RETRIES}") from e
            raise FetchError(f"HTTP {e.code}: {e.reason}") from e
        except URLError as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS[attempt]); continue
            raise FetchError(f"URL error: {e}") from e
    raise FetchError(f"max retries exhausted: {last_err}")


def parse_book_summary(rows: list, currency: str) -> list[dict]:
    out = []
    for r in rows:
        meta = of.parse_instrument_name(r.get("instrument_name", ""))
        if meta is None:
            continue
        try:
            iv = round(float(r.get("mark_iv") or 0.0) / 100.0, 6)
            oi = float(r.get("open_interest") or 0.0)
            under = float(r.get("underlying_price") or 0.0)
        except (ValueError, TypeError):
            continue
        if iv <= 0:
            continue
        out.append({"kind": meta["kind"], "strike": meta["strike"],
                    "expiry_ts": meta["expiry_ts"], "iv": iv, "oi": oi,
                    "underlying": under})
    return out


def fetch_index(currency: str) -> float:
    res = http_get_json("/public/get_index_price", {"index_name": INDEX_NAME[currency]})
    return float(res["index_price"])


def fetch_dvol(currency: str):
    end = now_ts() * 1000
    start = end - 6 * 3600 * 1000
    res = http_get_json("/public/get_volatility_index_data",
                        {"currency": currency, "start_timestamp": start,
                         "end_timestamp": end, "resolution": "3600"})
    data = res.get("data", []) if isinstance(res, dict) else []
    if not data:
        return None, None, None
    last = data[-1]; ts = int(last[0]) // 1000; close = float(last[4])
    prev = float(data[-2][4]) if len(data) > 1 else None
    chg = (close - prev) if prev is not None else None
    return ts, close, chg


def _expiry_bucket(expiry_ts, now_ts_val):
    d = (expiry_ts - now_ts_val) / 86400.0
    if d < 7: return "0-7d"
    if d < 30: return "7-30d"
    if d < 90: return "30-90d"
    return "90d+"


def _strike_bucket(strike, spot):
    m = strike / spot if spot else 1.0
    if m < 0.85: return "deep_put"
    if m < 0.97: return "otm_put"
    if m <= 1.03: return "atm"
    if m <= 1.15: return "otm_call"
    return "deep_call"


def aggregate_snapshot(chain, spot, symbol, bucket_ts):
    agg: dict = {}
    for c in chain:
        key = (_expiry_bucket(c["expiry_ts"], bucket_ts), _strike_bucket(c["strike"], spot))
        a = agg.setdefault(key, {"oi": 0.0, "iv_sum": 0.0, "n": 0})
        a["oi"] += c["oi"] or 0.0
        a["iv_sum"] += c["iv"]; a["n"] += 1
    return [{"symbol": symbol, "bucket_ts": bucket_ts, "expiry_bucket": eb,
             "strike_bucket": sb, "oi": v["oi"],
             "iv_mean": v["iv_sum"] / v["n"] if v["n"] else None, "n": v["n"]}
            for (eb, sb), v in agg.items()]


def read_recent_closes(conn, symbol, hours=48):
    cutoff = now_ts() - hours * 3600
    try:
        rows = conn.execute(
            "SELECT close_price FROM k_prices WHERE symbol=? AND bucket_ts>=? ORDER BY bucket_ts",
            (f"{symbol}USDT", cutoff),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]


def build_feature_row(conn, currency, chain, spot, dvol_tuple, bucket_ts):
    gex, gex_abs = of.compute_gex(chain, spot, bucket_ts)
    iv_atm = of.compute_iv_atm(chain, spot, bucket_ts)
    rv = of.realized_vol(read_recent_closes(conn, currency, 48))
    _, dvol, dvol_chg = dvol_tuple
    return {
        "symbol": currency, "bucket_ts": bucket_ts, "spot": spot,
        "gex": gex, "gex_abs": gex_abs,
        "gamma_flip": of.compute_gamma_flip(chain, spot, bucket_ts),
        "dvol": dvol, "dvol_chg": dvol_chg,
        "skew_25d": of.compute_skew_25d(chain, spot, bucket_ts),
        "iv_atm": iv_atm, "rv_48h": rv, "vrp": of.compute_vrp(iv_atm, rv),
        "term_slope": of.compute_term_slope(chain, spot, bucket_ts),
        "n_strikes": len(chain), "oi_total": sum((c["oi"] or 0.0) for c in chain),
    }


def fetch_for_symbol(currency):
    raw = http_get_json("/public/get_book_summary_by_currency",
                        {"currency": currency, "kind": "option"})
    chain = parse_book_summary(raw, currency)
    spot = fetch_index(currency)
    dvol_tuple = fetch_dvol(currency)
    # ts da Deribit (DVOL) truncado pra hora; fallback p/ now truncado
    src_ts = dvol_tuple[0] or now_ts()
    bucket_ts = src_ts - src_ts % 3600
    return chain, spot, dvol_tuple, bucket_ts


def run(conn, dry_run):
    started = now_ts()
    run_id = -1
    if not dry_run:
        run_id = conn.execute(
            "INSERT INTO k_options_collector_runs (started_at, status) VALUES (?, 'running')",
            (started,)).lastrowid
        conn.commit()
    rows_total = sym_ok = sym_fail = 0
    notes = []
    collected_at = now_ts()
    for cur_sym in SYMBOLS:
        try:
            chain, spot, dvol_tuple, bucket_ts = fetch_for_symbol(cur_sym)
            if not chain:
                notes.append(f"{cur_sym}: cadeia vazia"); sym_fail += 1; continue
            frow = build_feature_row(conn, cur_sym, chain, spot, dvol_tuple, bucket_ts)
            agg = aggregate_snapshot(chain, spot, cur_sym, bucket_ts)
            if dry_run:
                print(f"[dry-run] {cur_sym} bucket={bucket_ts} gex={frow['gex']:.4g} "
                      f"skew={frow['skew_25d']} iv_atm={frow['iv_atm']} dvol={frow['dvol']} "
                      f"strikes={frow['n_strikes']} agg_rows={len(agg)}")
                sym_ok += 1; continue
            conn.execute("BEGIN")
            rows_total += upsert_features(conn, frow, collected_at)
            rows_total += upsert_agg(conn, agg, collected_at)
            conn.execute("COMMIT")
            sym_ok += 1
        except Exception as e:  # noqa: BLE001 - boundary
            try: conn.execute("ROLLBACK")
            except sqlite3.Error: pass
            notes.append(f"{cur_sym}: {type(e).__name__}: {e}"); sym_fail += 1
    status = "ok" if sym_fail == 0 else ("partial" if sym_ok else "fail")
    if not dry_run:
        conn.execute("UPDATE k_options_collector_runs SET finished_at=?, status=?, "
                     "symbols_ok=?, symbols_fail=?, rows_inserted=?, notes=? WHERE run_id=?",
                     (now_ts(), status, sym_ok, sym_fail, rows_total,
                      "; ".join(notes)[:500], run_id))
        conn.commit()
    return status, sym_ok, sym_fail, rows_total, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Deribit options collector (EXP-019)")
    parser.add_argument("--dry-run", action="store_true", help="não escreve no banco")
    args = parser.parse_args()
    ok, msg = check_clock_sanity()
    if not ok:
        print(f"ABORT: {msg}", file=sys.stderr); return 2
    if not DB_PATH.parent.exists():
        print(f"ERRO: diretorio nao existe: {DB_PATH.parent}", file=sys.stderr); return 1
    conn = sqlite3.connect(str(DB_PATH))
    try:
        init_db(conn)
        status, sym_ok, sym_fail, rows_total, notes = run(conn, args.dry_run)
        prefix = "[dry-run] " if args.dry_run else ""
        msg = f"{prefix}options_collector status={status} ok={sym_ok} fail={sym_fail} rows={rows_total}"
        if notes: msg += f" notes={'; '.join(notes[:5])}"
        print(msg)
        return 0 if status != "fail" else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
