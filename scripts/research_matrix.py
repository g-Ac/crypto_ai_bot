"""Research Mode — First Matrix Run.

Replay script: fetches historical candles from Binance, simulates
the Research Mode scanner at each 15m step, generates DB + report.

Not a permanent module — research tooling only.

Usage:
    cd ~/crypto_ai_bot
    source .venv/bin/activate
    python scripts/research_matrix.py
"""

from __future__ import annotations

import sys
import time as time_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import ta

# --- Ensure project root is on sys.path ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from momentum.config import MomentumConfig
from momentum.research_db import ensure_tables
from momentum.research_report import format_report, generate_report
from momentum.research_runner import run_research_cycle


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
WARMUP_DAYS = 5  # extra 1h data for ADX(14) / BB(20) warmup
WINDOW = 100      # candles per evaluation (same as live)

DB_DIR = PROJECT_ROOT / "research"
BINANCE_URL = "https://api.binance.com/api/v3/klines"


def _parse_args() -> tuple[int, float, float, float]:
    """Parse --days=N, --breakeven=F, --pullback-min=N, --pullback-max=N from argv."""
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--breakeven", type=float, default=0.0)
    parser.add_argument("--pullback-min", type=float, default=30.0)
    parser.add_argument("--pullback-max", type=float, default=70.0)
    args, _ = parser.parse_known_args()
    return args.days, args.breakeven, args.pullback_min, args.pullback_max


def _paths(days: int, breakeven: float = 0.0,
           pullback_min: float = 30.0, pullback_max: float = 70.0):
    day_suffix = f"_{days}d" if days != 30 else ""
    be_suffix = ""
    if breakeven > 0:
        be_suffix = f"_be{int(round(breakeven * 100))}"
    pb_suffix = ""
    if pullback_min != 30.0 or pullback_max != 70.0:
        pb_suffix = f"_pb{int(round(pullback_min))}_{int(round(pullback_max))}"
    db = DB_DIR / f"matrix_v1{day_suffix}{be_suffix}{pb_suffix}.db"
    report = DB_DIR / f"matrix_v1{day_suffix}{be_suffix}{pb_suffix}_report.txt"
    return db, report


# ---------------------------------------------------------------------------
# Binance data fetching
# ---------------------------------------------------------------------------

def fetch_candles(
    symbol: str, interval: str, start_ms: int, end_ms: int,
) -> pd.DataFrame:
    """Fetch historical candles from Binance with pagination."""
    all_rows: list = []
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        }

        for attempt in range(3):
            try:
                resp = requests.get(BINANCE_URL, params=params, timeout=15)
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt == 2:
                    raise RuntimeError(
                        f"Binance API failed after 3 attempts: {exc}"
                    ) from exc
                time_mod.sleep(2 ** attempt)

        data = resp.json()
        if not data:
            break

        all_rows.extend(data)
        cursor = data[-1][6] + 1  # close_time + 1ms

        if len(data) < 1000:
            break

        time_mod.sleep(0.25)  # rate limit courtesy

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbbav", "tbqav", "ignore",
    ])

    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)

    df["time"] = pd.to_datetime(df["time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    df["timestamp"] = df["time"].astype(str)

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Regime computation (mirrors htf.py logic)
# ---------------------------------------------------------------------------

def compute_regimes(candles_1h: pd.DataFrame) -> pd.DataFrame:
    """Compute regime label for each 1h candle.

    Uses the same ADX/BB classification as htf.get_htf_regime.
    """
    if len(candles_1h) < 30:
        return pd.DataFrame(columns=["time", "close_time", "regime_label"])

    high = candles_1h["high"]
    low = candles_1h["low"]
    close = candles_1h["close"]

    adx = ta.trend.ADXIndicator(high, low, close, window=14).adx()
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    bb_upper = bb.bollinger_hband()
    bb_lower = bb.bollinger_lband()
    bb_mid = bb.bollinger_mavg()
    bb_width = (bb_upper - bb_lower) / bb_mid * 100

    labels = []
    for i in range(len(candles_1h)):
        a = adx.iloc[i]
        bw = bb_width.iloc[i]

        if pd.isna(a) or pd.isna(bw):
            labels.append("UNKNOWN")
        elif a >= 25:
            labels.append("TRENDING" if bw > 1.5 else "WEAK_TREND")
        elif bw > 2.0:
            labels.append("VOLATILE")
        elif bw >= 0.8:
            labels.append("RANGING")
        else:
            labels.append("CHOPPY")

    return pd.DataFrame({
        "time": candles_1h["time"].values,
        "close_time": candles_1h["close_time"].values,
        "regime_label": labels,
    })


def lookup_regime(regimes_df: pd.DataFrame, ts_15m) -> str:
    """Find regime for a 15m timestamp.

    Uses the most recent 1h candle whose close_time <= ts_15m.
    This matches htf.py's .iloc[-2] behavior (penultimate candle).
    """
    mask = regimes_df["close_time"] <= ts_15m
    if not mask.any():
        return "UNKNOWN"
    return regimes_df.loc[mask].iloc[-1]["regime_label"]


# ---------------------------------------------------------------------------
# Main replay
# ---------------------------------------------------------------------------

def run_matrix(
    days: int | None = None,
    breakeven: float | None = None,
    pullback_min: float | None = None,
    pullback_max: float | None = None,
) -> dict:
    if days is None or breakeven is None or pullback_min is None or pullback_max is None:
        d, be, pb_min, pb_max = _parse_args()
        if days is None:
            days = d
        if breakeven is None:
            breakeven = be
        if pullback_min is None:
            pullback_min = pb_min
        if pullback_max is None:
            pullback_max = pb_max

    db_path, report_path = _paths(days, breakeven, pullback_min, pullback_max)

    variant_bits = []
    if breakeven > 0:
        variant_bits.append(f"BE={breakeven}")
    if pullback_min != 30.0 or pullback_max != 70.0:
        variant_bits.append(f"PB={pullback_min}-{pullback_max}")
    variant = (" + " + " + ".join(variant_bits)) if variant_bits else ""
    print("=" * 55)
    print(f"  MOMENTUM PULLBACK — RESEARCH MATRIX v1{variant} ({days} days)")
    print("=" * 55)
    print(f"  Symbols: {', '.join(SYMBOLS)}")
    print(f"  Period:  {days} days + {WARMUP_DAYS} days warmup (1h)")
    print(f"  Window:  {WINDOW} candles per evaluation")
    if breakeven > 0:
        print(f"  Variant: breakeven_trigger_pct={breakeven}")
    if pullback_min != 30.0 or pullback_max != 70.0:
        print(f"  Variant: pullback_min_pct={pullback_min}, pullback_max_pct={pullback_max}")
    print()

    # --- Time range ---
    end_dt = datetime.now(timezone.utc)
    start_15m = end_dt - timedelta(days=days)
    start_1h = end_dt - timedelta(days=days + WARMUP_DAYS)

    start_15m_ms = int(start_15m.timestamp() * 1000)
    start_1h_ms = int(start_1h.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    print(f"  15m range: {start_15m:%Y-%m-%d %H:%M} → {end_dt:%Y-%m-%d %H:%M} UTC")
    print(f"  1h range:  {start_1h:%Y-%m-%d %H:%M} → {end_dt:%Y-%m-%d %H:%M} UTC")
    print()

    # --- Fetch data ---
    all_data: dict = {}
    for symbol in SYMBOLS:
        print(f"  [{symbol}] Fetching 15m candles...", end="", flush=True)
        c15 = fetch_candles(symbol, "15m", start_15m_ms, end_ms)
        print(f" {len(c15)} candles")

        print(f"  [{symbol}] Fetching 1h candles...", end="", flush=True)
        c1h = fetch_candles(symbol, "1h", start_1h_ms, end_ms)
        print(f" {len(c1h)} candles")

        print(f"  [{symbol}] Computing regimes...", end="", flush=True)
        regimes = compute_regimes(c1h)
        valid = regimes[regimes["regime_label"] != "UNKNOWN"]
        print(f" {len(valid)} valid labels")

        # Regime distribution for sanity
        dist = regimes["regime_label"].value_counts().to_dict()
        print(f"  [{symbol}] Regime dist: {dist}")

        all_data[symbol] = {"candles_15m": c15, "regimes": regimes}
        print()

    # --- Setup DB ---
    DB_DIR.mkdir(exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    ensure_tables(db_path)

    config = MomentumConfig(
        breakeven_trigger_pct=breakeven,
        pullback_min_pct=pullback_min,
        pullback_max_pct=pullback_max,
    )

    # --- Replay loop ---
    min_len = min(len(all_data[s]["candles_15m"]) for s in SYMBOLS)
    n_steps = min_len - WINDOW

    if n_steps <= 0:
        print("ERROR: Not enough candles for replay.")
        sys.exit(1)

    print(f"  Replaying {n_steps} steps x {len(SYMBOLS)} symbols...")
    print()

    t_start = time_mod.time()
    total_dec = 0
    total_opened = 0
    total_closed = 0

    for step in range(n_steps):
        idx = WINDOW + step  # end index (exclusive → iloc[:idx])

        def _make_candle_fn(end_idx: int):
            def candle_fn(symbol, interval, limit):
                c15 = all_data[symbol]["candles_15m"]
                start = max(0, end_idx - WINDOW)
                return c15.iloc[start:end_idx].reset_index(drop=True)
            return candle_fn

        def _make_regime_fn(end_idx: int):
            def regime_fn(symbol):
                c15 = all_data[symbol]["candles_15m"]
                ts = c15.iloc[end_idx - 1]["time"]
                label = lookup_regime(all_data[symbol]["regimes"], ts)
                return {"regime_label": label}
            return regime_fn

        result = run_research_cycle(
            SYMBOLS, db_path, config,
            candle_fn=_make_candle_fn(idx),
            regime_fn=_make_regime_fn(idx),
        )

        total_dec += result["decisions_recorded"]
        total_opened += result["trades_opened"]
        total_closed += result["trades_closed"]

        if (step + 1) % 500 == 0 or step == n_steps - 1:
            elapsed = time_mod.time() - t_start
            print(
                f"  Step {step + 1:>5d}/{n_steps}  "
                f"dec={total_dec}  opened={total_opened}  "
                f"closed={total_closed}  [{elapsed:.0f}s]"
            )

    elapsed = time_mod.time() - t_start
    print()
    print(f"  Replay complete in {elapsed:.1f}s")
    print()

    # --- Generate report ---
    report = generate_report(db_path)
    text = format_report(report)

    report_path.write_text(text, encoding="utf-8")

    print(f"  DB saved:     {db_path}")
    print(f"  Report saved: {report_path}")
    print()
    print(text)

    return report


if __name__ == "__main__":
    run_matrix()
