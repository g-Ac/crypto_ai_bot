"""K-axis ratio collector — top/retail divergence research (EXP-008-K).

Coleta hourly do Binance Futures (free tier, sem API key):
- topLongShortPositionRatio
- globalLongShortAccountRatio
- klines 1h (open/high/low/close/volume)
- fundingRate (8h)
- openInterestHist 1h

Para 14 simbolos do sub-regime EXP-008-K.

Schema: k_ratios, k_prices, k_collector_runs (prefixo k_).
Idempotente via INSERT OR IGNORE com PK composta.
Padrao consistente com shadow_simulator.py.

Spec completa: ~/obsidian-vault/context/decisoes/2026-04-29-spec-coletor-K-hermes.md

Uso:
    python k_collector.py             # run normal (overlap 12h)
    python k_collector.py --backfill  # forca limit=500 (primeira run / gap-fill)
    python k_collector.py --dry-run   # nao escreve no banco
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DB_PATH = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "HYPEUSDT", "LINKUSDT", "AVAXUSDT",
    "LTCUSDT", "TRXUSDT", "SUIUSDT", "1000PEPEUSDT",
]

BASE_URL = "https://fapi.binance.com"
USER_AGENT = "crypto_ai_bot/k_collector"
HTTP_TIMEOUT = 12.0
MAX_RETRIES = 4
BACKOFF_SECONDS = (5, 30, 120, 300)
OVERLAP_LIMIT = 12
BACKFILL_LIMIT = 500

# Retenção do endpoint da Binance (em horas) — LSR/OI: ~30d, funding: ~370d (até 1000).
# Usado pra (a) capar limit do backfill automático em valor útil, (b) classificar gaps
# como "recuperáveis" vs "perdidos" no relatório diário.
RETENTION_HOURS_LSR_OI = 30 * 24      # ~720h
RETENTION_HOURS_FUNDING = 365 * 24    # ~8760h (até 1000 entries no endpoint)

# Sanity de relógio: se Pi reboota sem RTC, relógio pode voltar errado.
# Aborta o run inteiro se ano detectado < MIN_YEAR — melhor não coletar do que
# envenenar o dado com timestamps absurdos.
MIN_YEAR_SANITY = 2025

ENDPOINT_TOP = "/futures/data/topLongShortPositionRatio"
ENDPOINT_GLOBAL = "/futures/data/globalLongShortAccountRatio"
ENDPOINT_KLINES = "/fapi/v1/klines"
ENDPOINT_FUNDING = "/fapi/v1/fundingRate"
ENDPOINT_OPEN_INTEREST = "/futures/data/openInterestHist"

SCHEMA = """
CREATE TABLE IF NOT EXISTS k_ratios (
    symbol           TEXT     NOT NULL,
    bucket_ts        INTEGER  NOT NULL,
    source           TEXT     NOT NULL,
    long_short_ratio REAL     NOT NULL,
    long_account     REAL,
    short_account    REAL,
    collected_at     INTEGER  NOT NULL,
    PRIMARY KEY (symbol, bucket_ts, source)
);
CREATE INDEX IF NOT EXISTS idx_k_ratios_bucket ON k_ratios(bucket_ts);
CREATE INDEX IF NOT EXISTS idx_k_ratios_symbol_ts ON k_ratios(symbol, bucket_ts);

CREATE TABLE IF NOT EXISTS k_prices (
    symbol         TEXT     NOT NULL,
    bucket_ts      INTEGER  NOT NULL,
    open_price     REAL     NOT NULL,
    close_price    REAL     NOT NULL,
    high_price     REAL     NOT NULL,
    low_price      REAL     NOT NULL,
    volume         REAL     NOT NULL,
    collected_at   INTEGER  NOT NULL,
    PRIMARY KEY (symbol, bucket_ts)
);
CREATE INDEX IF NOT EXISTS idx_k_prices_bucket ON k_prices(bucket_ts);

CREATE TABLE IF NOT EXISTS k_collector_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    INTEGER NOT NULL,
    finished_at   INTEGER,
    status        TEXT,
    symbols_ok    INTEGER DEFAULT 0,
    symbols_fail  INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS k_funding_rates (
    symbol        TEXT     NOT NULL,
    funding_time  INTEGER  NOT NULL,
    funding_rate  REAL     NOT NULL,
    mark_price    REAL,
    collected_at  INTEGER  NOT NULL,
    PRIMARY KEY (symbol, funding_time)
);
CREATE INDEX IF NOT EXISTS idx_k_funding_symbol_time
    ON k_funding_rates(symbol, funding_time);

CREATE TABLE IF NOT EXISTS k_open_interest (
    symbol                   TEXT     NOT NULL,
    bucket_ts                INTEGER  NOT NULL,
    sum_open_interest        REAL     NOT NULL,
    sum_open_interest_value  REAL,
    collected_at             INTEGER  NOT NULL,
    PRIMARY KEY (symbol, bucket_ts)
);
CREATE INDEX IF NOT EXISTS idx_k_open_interest_symbol_ts
    ON k_open_interest(symbol, bucket_ts);
"""


class SymbolDelistedError(Exception):
    pass


class FetchError(Exception):
    pass


def now_ts() -> int:
    return int(time.time())


def http_get_json(path: str, params: dict) -> list:
    """GET com retry exponencial; raise SymbolDelistedError em HTTP 400."""
    url = f"{BASE_URL}{path}?{urlencode(params)}"
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
                raise FetchError(f"HTTP {resp.status}")
        except HTTPError as e:
            if e.code in (418, 429):
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BACKOFF_SECONDS[attempt])
                    continue
                raise FetchError(f"rate limit after {MAX_RETRIES} retries") from e
            if e.code == 400:
                raise SymbolDelistedError(
                    f"{params.get('symbol')}: HTTP 400"
                ) from e
            raise FetchError(f"HTTP {e.code}: {e.reason}") from e
        except URLError as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS[attempt])
                continue
            raise FetchError(f"URL error: {e}") from e
    raise FetchError(f"max retries exhausted: {last_err}")


def parse_ratio_response(rows: list, source: str) -> list[dict]:
    parsed: list[dict] = []
    for r in rows:
        try:
            ts_ms = int(r["timestamp"])
            ratio = float(r["longShortRatio"])
            parsed.append({
                "symbol": r["symbol"],
                "bucket_ts": ts_ms // 1000,
                "source": source,
                "long_short_ratio": ratio,
                "long_account": float(r["longAccount"]) if "longAccount" in r else None,
                "short_account": float(r["shortAccount"]) if "shortAccount" in r else None,
            })
        except (KeyError, ValueError, TypeError):
            continue
    return parsed


def parse_klines_response(rows: list, symbol: str) -> list[dict]:
    parsed: list[dict] = []
    for r in rows:
        try:
            parsed.append({
                "symbol": symbol,
                "bucket_ts": int(r[0]) // 1000,
                "open_price": float(r[1]),
                "high_price": float(r[2]),
                "low_price": float(r[3]),
                "close_price": float(r[4]),
                "volume": float(r[5]),
            })
        except (IndexError, ValueError, TypeError):
            continue
    return parsed


def parse_funding_response(rows: list, symbol: str) -> list[dict]:
    parsed: list[dict] = []
    for r in rows:
        try:
            item = {
                "symbol": r.get("symbol", symbol),
                "funding_time": int(r["fundingTime"]) // 1000,
                "funding_rate": float(r["fundingRate"]),
                "mark_price": None,
            }
            if r.get("markPrice") not in (None, ""):
                item["mark_price"] = float(r["markPrice"])
            parsed.append(item)
        except (KeyError, ValueError, TypeError):
            continue
    return parsed


def parse_open_interest_response(rows: list, symbol: str) -> list[dict]:
    parsed: list[dict] = []
    for r in rows:
        try:
            item = {
                "symbol": r.get("symbol", symbol),
                "bucket_ts": int(r["timestamp"]) // 1000,
                "sum_open_interest": float(r["sumOpenInterest"]),
                "sum_open_interest_value": None,
            }
            if r.get("sumOpenInterestValue") not in (None, ""):
                item["sum_open_interest_value"] = float(r["sumOpenInterestValue"])
            parsed.append(item)
        except (KeyError, ValueError, TypeError):
            continue
    return parsed


def validate_ratio(row: dict, now: int) -> bool:
    bts = row["bucket_ts"]
    if bts % 3600 != 0:
        return False
    if bts > now + 60:
        return False
    if now - bts > 35 * 86400:
        return False
    r = row["long_short_ratio"]
    if not (0.0 < r <= 100.0):
        return False
    la = row.get("long_account")
    sa = row.get("short_account")
    if la is not None and sa is not None:
        if not (0 <= la <= 1) or not (0 <= sa <= 1):
            return False
        if abs(la + sa - 1.0) > 0.01:
            return False
    return True


def validate_price(row: dict, now: int) -> bool:
    bts = row["bucket_ts"]
    if bts % 3600 != 0:
        return False
    if bts > now + 60:
        return False
    if now - bts > 35 * 86400:
        return False
    op, cp = row["open_price"], row["close_price"]
    hp, lp = row["high_price"], row["low_price"]
    if cp <= 0 or op <= 0:
        return False
    if hp < max(op, cp) - 1e-9:
        return False
    if lp > min(op, cp) + 1e-9:
        return False
    return True


def validate_funding(row: dict, now: int) -> bool:
    fts = row["funding_time"]
    if fts > now + 60:
        return False
    if now - fts > 370 * 86400:
        return False
    rate = row["funding_rate"]
    if not (-1.0 <= rate <= 1.0):
        return False
    mp = row.get("mark_price")
    if mp is not None and mp <= 0:
        return False
    return True


def validate_open_interest(row: dict, now: int) -> bool:
    bts = row["bucket_ts"]
    if bts % 3600 != 0:
        return False
    if bts > now + 60:
        return False
    if now - bts > 35 * 86400:
        return False
    oi = row["sum_open_interest"]
    if oi < 0:
        return False
    oi_value = row.get("sum_open_interest_value")
    if oi_value is not None and oi_value < 0:
        return False
    return True


def upsert_ratios(conn: sqlite3.Connection, rows: list[dict], collected_at: int) -> int:
    inserted = 0
    now = now_ts()
    for r in rows:
        if not validate_ratio(r, now):
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO k_ratios "
            "(symbol, bucket_ts, source, long_short_ratio, long_account, "
            " short_account, collected_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                r["symbol"], r["bucket_ts"], r["source"],
                r["long_short_ratio"], r.get("long_account"),
                r.get("short_account"), collected_at,
            ),
        )
        inserted += cur.rowcount
    return inserted


def upsert_prices(conn: sqlite3.Connection, rows: list[dict], collected_at: int) -> int:
    inserted = 0
    now = now_ts()
    for r in rows:
        if not validate_price(r, now):
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO k_prices "
            "(symbol, bucket_ts, open_price, close_price, high_price, "
            " low_price, volume, collected_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r["symbol"], r["bucket_ts"],
                r["open_price"], r["close_price"],
                r["high_price"], r["low_price"],
                r["volume"], collected_at,
            ),
        )
        inserted += cur.rowcount
    return inserted


def upsert_funding(conn: sqlite3.Connection, rows: list[dict], collected_at: int) -> int:
    inserted = 0
    now = now_ts()
    for r in rows:
        if not validate_funding(r, now):
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO k_funding_rates "
            "(symbol, funding_time, funding_rate, mark_price, collected_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                r["symbol"], r["funding_time"], r["funding_rate"],
                r.get("mark_price"), collected_at,
            ),
        )
        inserted += cur.rowcount
    return inserted


def upsert_open_interest(conn: sqlite3.Connection, rows: list[dict], collected_at: int) -> int:
    inserted = 0
    now = now_ts()
    for r in rows:
        if not validate_open_interest(r, now):
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO k_open_interest "
            "(symbol, bucket_ts, sum_open_interest, sum_open_interest_value, collected_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                r["symbol"], r["bucket_ts"], r["sum_open_interest"],
                r.get("sum_open_interest_value"), collected_at,
            ),
        )
        inserted += cur.rowcount
    return inserted


def fetch_for_symbol(symbol: str, limit: int) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    top_raw = http_get_json(ENDPOINT_TOP,
                            {"symbol": symbol, "period": "1h", "limit": limit})
    glob_raw = http_get_json(ENDPOINT_GLOBAL,
                             {"symbol": symbol, "period": "1h", "limit": limit})
    klines_raw = http_get_json(ENDPOINT_KLINES,
                               {"symbol": symbol, "interval": "1h", "limit": limit})
    funding_raw = http_get_json(ENDPOINT_FUNDING,
                                {"symbol": symbol, "limit": min(limit, 1000)})
    oi_raw = http_get_json(ENDPOINT_OPEN_INTEREST,
                           {"symbol": symbol, "period": "1h", "limit": limit})
    ratios = parse_ratio_response(top_raw, "top_position")
    ratios += parse_ratio_response(glob_raw, "global_account")
    prices = parse_klines_response(klines_raw, symbol)
    funding = parse_funding_response(funding_raw, symbol)
    open_interest = parse_open_interest_response(oi_raw, symbol)
    return ratios, prices, funding, open_interest


def run(conn: sqlite3.Connection, limit: int, dry_run: bool) -> tuple[str, int, int, int, list[str]]:
    started = now_ts()
    if not dry_run:
        cur = conn.execute(
            "INSERT INTO k_collector_runs (started_at, status) VALUES (?, 'running')",
            (started,),
        )
        run_id = cur.lastrowid
        conn.commit()
    else:
        run_id = -1

    rows_total = 0
    sym_ok = 0
    sym_fail = 0
    notes_parts: list[str] = []
    collected_at = now_ts()

    for sym in SYMBOLS:
        try:
            ratios, prices, funding, open_interest = fetch_for_symbol(sym, limit)
            if dry_run:
                rows_total += len(ratios) + len(prices) + len(funding) + len(open_interest)
                sym_ok += 1
                continue
            try:
                conn.execute("BEGIN")
                inserted_r = upsert_ratios(conn, ratios, collected_at)
                inserted_p = upsert_prices(conn, prices, collected_at)
                inserted_f = upsert_funding(conn, funding, collected_at)
                inserted_oi = upsert_open_interest(conn, open_interest, collected_at)
                conn.execute("COMMIT")
                rows_total += inserted_r + inserted_p + inserted_f + inserted_oi
                sym_ok += 1
            except sqlite3.Error as e:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                notes_parts.append(f"{sym}: db error {e}")
                sym_fail += 1
        except SymbolDelistedError as e:
            notes_parts.append(f"{sym}: delisted")
            sym_fail += 1
        except FetchError as e:
            notes_parts.append(f"{sym}: fetch {type(e).__name__}")
            sym_fail += 1
        except Exception as e:  # noqa: BLE001 - boundary catch
            notes_parts.append(f"{sym}: unexpected {type(e).__name__}")
            sym_fail += 1

    if sym_fail == 0:
        status = "ok"
    elif sym_ok > 0:
        status = "partial"
    else:
        status = "fail"

    if not dry_run:
        notes_str = "; ".join(notes_parts)[:500]
        conn.execute(
            "UPDATE k_collector_runs SET finished_at=?, status=?, "
            "symbols_ok=?, symbols_fail=?, rows_inserted=?, notes=? "
            "WHERE run_id=?",
            (now_ts(), status, sym_ok, sym_fail, rows_total, notes_str, run_id),
        )
        conn.commit()

    return status, sym_ok, sym_fail, rows_total, notes_parts


def check_clock_sanity() -> tuple[bool, str]:
    """Aborta se relógio do Pi voltou errado (pós-boot sem RTC e sem NTP ainda).

    Sem este check, validate_* rejeita silenciosamente dados bons (bts > now+60)
    ou aceita timestamps com 'collected_at' do passado distante.
    """
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    if now.year < MIN_YEAR_SANITY:
        return False, (f"relogio do Pi parece errado: ano={now.year} < "
                       f"{MIN_YEAR_SANITY}. Aguardando NTP. Aborta sem coletar.")
    return True, f"clock ok: {now.isoformat()}"


def last_bucket_ts(conn: sqlite3.Connection, table: str, symbol: str,
                   ts_col: str = "bucket_ts") -> int | None:
    """Retorna MAX(ts_col) por símbolo, ou None se nunca coletado.

    Usado pra detectar gap entre última coleta e agora — input pro backfill auto.
    """
    cur = conn.execute(
        f"SELECT MAX({ts_col}) FROM {table} WHERE symbol = ?", (symbol,)
    )
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def compute_dynamic_limit(conn: sqlite3.Connection, now: int) -> tuple[int, dict]:
    """Determina limit ótimo baseado no maior gap entre símbolos.

    Estratégia: pega o `bucket_ts` mais antigo entre os MAX por símbolo (i.e., o
    símbolo mais defasado dita o limit). Adiciona margem de segurança de 6h.
    Cap em BACKFILL_LIMIT (500) pra respeitar limite do endpoint LSR/OI.

    Retorna (limit, diagnostico) — diagnostico inclui staleness por tabela.
    """
    tables_specs = [
        ("k_ratios", "bucket_ts"),
        ("k_prices", "bucket_ts"),
        ("k_open_interest", "bucket_ts"),
        # k_funding_rates tem cadência 8h e retenção maior — não dita limit
        # mas reportamos staleness pra observabilidade
    ]
    max_gap_hours = 0
    staleness = {}
    for tbl, col in tables_specs:
        oldest_last_ts = None
        for sym in SYMBOLS:
            ts = last_bucket_ts(conn, tbl, sym, col)
            if ts is None:
                continue
            if oldest_last_ts is None or ts < oldest_last_ts:
                oldest_last_ts = ts
        if oldest_last_ts is None:
            staleness[tbl] = {"never_collected": True}
            continue
        gap_seconds = max(0, now - oldest_last_ts)
        gap_hours = gap_seconds // 3600
        staleness[tbl] = {
            "oldest_last_ts": int(oldest_last_ts),
            "gap_hours": int(gap_hours),
        }
        max_gap_hours = max(max_gap_hours, gap_hours)

    # Se algum bucket é "never_collected", força BACKFILL_LIMIT
    if any(v.get("never_collected") for v in staleness.values()):
        return BACKFILL_LIMIT, staleness

    # Margem de segurança: +6h pra cobrir overlap + possíveis publicações tardias.
    needed = int(max_gap_hours) + 6
    # Piso = OVERLAP_LIMIT (comportamento atual, sem regressão); teto = BACKFILL_LIMIT.
    limit = max(OVERLAP_LIMIT, min(BACKFILL_LIMIT, needed))
    return limit, staleness


def main() -> int:
    parser = argparse.ArgumentParser(description="K-axis ratio collector")
    parser.add_argument("--backfill", action="store_true",
                        help=f"forca limit={BACKFILL_LIMIT} (primeira run ou gap-fill)")
    parser.add_argument("--dry-run", action="store_true",
                        help="nao escreve no banco")
    args = parser.parse_args()

    # Sanity de relógio ANTES de qualquer coisa (poison-pill prevention)
    clock_ok, clock_msg = check_clock_sanity()
    if not clock_ok:
        print(f"ABORT: {clock_msg}", file=sys.stderr)
        return 2

    if not DB_PATH.parent.exists():
        print(f"ERRO: diretorio nao existe: {DB_PATH.parent}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH))
    try:
        # PRAGMAs crash-safety (synchronous=NORMAL é o sweet spot pra WAL: durabilidade
        # boa contra crash de processo + crash do OS sem perder commits, e mais rápido
        # que FULL. busy_timeout previne SQLITE_BUSY em concorrência com leitor).
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.executescript(SCHEMA)
        conn.commit()

        first_run = conn.execute("SELECT COUNT(*) FROM k_ratios").fetchone()[0] == 0

        # Determinação de limit:
        #   --backfill explícito → BACKFILL_LIMIT
        #   first_run            → BACKFILL_LIMIT
        #   senão                → compute_dynamic_limit (ajusta ao maior gap)
        if args.backfill or first_run:
            limit = BACKFILL_LIMIT
            staleness = {}
            limit_source = "manual_or_first_run"
        else:
            limit, staleness = compute_dynamic_limit(conn, now_ts())
            limit_source = "dynamic_from_gap"

        status, sym_ok, sym_fail, rows_total, notes = run(conn, limit, args.dry_run)

        prefix = "[dry-run] " if args.dry_run else ""
        msg = (f"{prefix}k_collector limit={limit} ({limit_source}) "
               f"status={status} ok={sym_ok} fail={sym_fail} "
               f"rows_inserted={rows_total}")
        if staleness:
            gap_summary = ", ".join(
                f"{t}={v.get('gap_hours', '?')}h"
                for t, v in staleness.items() if not v.get("never_collected")
            )
            if gap_summary:
                msg += f" staleness=[{gap_summary}]"
        if notes:
            msg += f" notes={'; '.join(notes[:5])}"
        print(msg)

        return 0 if status != "fail" else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
