"""Robustness validation: v1.0 vs v1.1 (B1).

Three analyses:
1. Monthly consistency — PF/WR/PnL per month, v1.0 vs v1.1
2. Holdout out-of-sample — 30 days before the 90-day window
3. Regime breakdown — v1.0 vs v1.1 by TRENDING vs WEAK_TREND

Usage:
    cd ~/crypto_ai_bot
    source .venv/bin/activate
    python -m momentum.robustness_check
"""

from __future__ import annotations

import sqlite3
import sys
import time as time_mod
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from momentum.config import MomentumConfig
from momentum.research_db import ensure_tables
from momentum.research_runner import run_research_cycle


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
WARMUP_DAYS = 5
WINDOW = 100
BINANCE_URL = "https://api.binance.com/api/v3/klines"

V10_DB = PROJECT_ROOT / "research" / "tuning_v1_1" / "v1_baseline.db"
V11_DB = PROJECT_ROOT / "research" / "tuning_v1_1" / "B1_floor05.db"
HOLDOUT_DIR = PROJECT_ROOT / "research" / "robustness"

V10_CONFIG = MomentumConfig(
    sl_floor_pct=0.3,
    param_version="momentum-pullback-v1",
)
V11_CONFIG = MomentumConfig(
    sl_floor_pct=0.5,
    param_version="momentum-pullback-v1.1",
)


# ---------------------------------------------------------------------------
# Trade stats helper
# ---------------------------------------------------------------------------

def compute_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute PF, WR, avg/total PnL from a list of closed trades."""
    if not trades:
        return {
            "count": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "avg_pnl": 0.0, "total_pnl": 0.0, "profit_factor": 0.0,
        }

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0

    return {
        "count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_pnl": round(sum(pnls) / len(pnls), 4),
        "total_pnl": round(sum(pnls), 4),
        "profit_factor": (
            round(gross_profit / gross_loss, 2)
            if gross_loss > 0
            else float("inf")
        ),
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def query_closed_trades(db_path: Path) -> List[Dict[str, Any]]:
    """Read all closed trades from a research DB."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM momentum_trades "
        "WHERE exit_price IS NOT NULL ORDER BY timestamp"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Analysis 1: Monthly consistency
# ---------------------------------------------------------------------------

def analyze_monthly(
    v10_trades: List[Dict], v11_trades: List[Dict],
) -> Dict[str, Any]:
    """Break trades into calendar months, compare v1.0 vs v1.1."""

    def _group_by_month(trades: List[Dict]) -> Dict[str, List[Dict]]:
        months: Dict[str, List[Dict]] = {}
        for t in trades:
            key = t["timestamp"][:7]  # "2026-01"
            months.setdefault(key, []).append(t)
        return months

    v10_months = _group_by_month(v10_trades)
    v11_months = _group_by_month(v11_trades)
    all_months = sorted(set(list(v10_months) + list(v11_months)))

    results: Dict[str, Any] = {}
    v11_wins = 0

    for month in all_months:
        v10_stats = compute_stats(v10_months.get(month, []))
        v11_stats = compute_stats(v11_months.get(month, []))
        winner = "v1.1" if v11_stats["total_pnl"] >= v10_stats["total_pnl"] else "v1.0"
        if winner == "v1.1":
            v11_wins += 1
        results[month] = {"v1.0": v10_stats, "v1.1": v11_stats, "winner": winner}

    n = len(all_months)
    if n == 0:
        conclusion = "sem dados"
    elif v11_wins >= (n + 1) // 2 + 1:  # strict majority
        conclusion = "consistente"
    elif v11_wins >= (n + 1) // 2:
        conclusion = "parcial"
    else:
        conclusion = "fragil"

    return {
        "months": results,
        "v11_wins": v11_wins,
        "total_months": n,
        "conclusion": conclusion,
    }


# ---------------------------------------------------------------------------
# Analysis 3: Regime breakdown
# ---------------------------------------------------------------------------

def analyze_regime(
    v10_trades: List[Dict], v11_trades: List[Dict],
) -> Dict[str, Any]:
    """Compare v1.0 vs v1.1 by regime."""

    def _group_by_regime(trades: List[Dict]) -> Dict[str, List[Dict]]:
        regimes: Dict[str, List[Dict]] = {}
        for t in trades:
            r = t.get("regime", "UNKNOWN") or "UNKNOWN"
            regimes.setdefault(r, []).append(t)
        return regimes

    v10_regimes = _group_by_regime(v10_trades)
    v11_regimes = _group_by_regime(v11_trades)
    all_regimes = sorted(set(list(v10_regimes) + list(v11_regimes)))

    results: Dict[str, Any] = {}
    for regime in all_regimes:
        v10_stats = compute_stats(v10_regimes.get(regime, []))
        v11_stats = compute_stats(v11_regimes.get(regime, []))
        results[regime] = {
            "v1.0": v10_stats,
            "v1.1": v11_stats,
            "pnl_delta": round(v11_stats["total_pnl"] - v10_stats["total_pnl"], 4),
            "wr_delta": round(v11_stats["win_rate"] - v10_stats["win_rate"], 1),
        }

    improved = sum(1 for r in results.values() if r["pnl_delta"] > 0)
    total = len(results)

    if total == 0:
        conclusion = "sem dados"
    elif improved == total:
        conclusion = "generalizada"
    elif improved * 2 >= total:  # at least half
        conclusion = "parcial"
    else:
        conclusion = "regime-especifica"

    return {
        "regimes": results,
        "regimes_improved": improved,
        "total_regimes": total,
        "conclusion": conclusion,
    }


# ---------------------------------------------------------------------------
# Data fetching (for holdout)
# ---------------------------------------------------------------------------

def fetch_candles(
    symbol: str, interval: str, start_ms: int, end_ms: int,
) -> pd.DataFrame:
    """Fetch historical candles from Binance with pagination."""
    import requests

    all_rows: list = []
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol": symbol, "interval": interval,
            "startTime": cursor, "endTime": end_ms, "limit": 1000,
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
        time_mod.sleep(0.25)

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


def compute_regimes(candles_1h: pd.DataFrame) -> pd.DataFrame:
    """Compute regime label for each 1h candle (mirrors htf.py)."""
    import ta as ta_lib

    if len(candles_1h) < 30:
        return pd.DataFrame(columns=["time", "close_time", "regime_label"])

    high = candles_1h["high"]
    low = candles_1h["low"]
    close = candles_1h["close"]

    adx = ta_lib.trend.ADXIndicator(high, low, close, window=14).adx()
    bb = ta_lib.volatility.BollingerBands(close, window=20, window_dev=2)
    bb_width = (bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg() * 100

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
    """Find regime for a 15m timestamp."""
    mask = regimes_df["close_time"] <= ts_15m
    if not mask.any():
        return "UNKNOWN"
    return regimes_df.loc[mask].iloc[-1]["regime_label"]


# ---------------------------------------------------------------------------
# Replay engine (for holdout)
# ---------------------------------------------------------------------------

def replay_variant(
    config: MomentumConfig,
    db_path: Path,
    all_data: Dict[str, Any],
    n_steps: int,
    *,
    progress_every: int = 500,
) -> Dict[str, int]:
    """Replay one config variant over pre-fetched candle data."""
    if db_path.exists():
        db_path.unlink()
    ensure_tables(db_path)

    total_dec = 0
    total_opened = 0
    total_closed = 0
    t_start = time_mod.time()

    for step in range(n_steps):
        idx = WINDOW + step

        def _make_candle_fn(end_idx: int) -> Callable:
            def candle_fn(symbol: str, interval: str, limit: int):
                c15 = all_data[symbol]["candles_15m"]
                start = max(0, end_idx - WINDOW)
                return c15.iloc[start:end_idx].reset_index(drop=True)
            return candle_fn

        def _make_regime_fn(end_idx: int) -> Callable:
            def regime_fn(symbol: str):
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

        if progress_every and ((step + 1) % progress_every == 0 or step == n_steps - 1):
            elapsed = time_mod.time() - t_start
            print(
                f"    Step {step + 1:>5d}/{n_steps}  "
                f"dec={total_dec}  opened={total_opened}  "
                f"closed={total_closed}  [{elapsed:.0f}s]"
            )

    return {"decisions": total_dec, "opened": total_opened, "closed": total_closed}


# ---------------------------------------------------------------------------
# Analysis 2: Holdout out-of-sample
# ---------------------------------------------------------------------------

def run_holdout(
    holdout_days: int = 30,
    *,
    fetch_fn: Optional[Callable] = None,
    regime_compute_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Fetch candles before the 90-day window, replay both v1.0 and v1.1.

    Args:
        holdout_days: Number of days for the holdout period.
        fetch_fn: Override candle fetcher (for testing).
        regime_compute_fn: Override regime computation (for testing).
    """
    if fetch_fn is None:
        fetch_fn = fetch_candles
    if regime_compute_fn is None:
        regime_compute_fn = compute_regimes

    # Determine holdout period from the earliest trade in the 90-day data
    if not V10_DB.exists():
        return {"error": f"DB not found: {V10_DB}"}

    conn = sqlite3.connect(str(V10_DB))
    row = conn.execute("SELECT MIN(timestamp) FROM momentum_trades").fetchone()
    conn.close()

    if not row or not row[0]:
        return {"error": "No trades in v1.0 DB"}

    earliest_trade = pd.Timestamp(row[0])
    holdout_end = earliest_trade
    holdout_start = holdout_end - pd.Timedelta(days=holdout_days)

    holdout_end_ms = int(holdout_end.timestamp() * 1000)
    holdout_start_15m_ms = int(holdout_start.timestamp() * 1000)
    warmup_start = holdout_start - pd.Timedelta(days=WARMUP_DAYS)
    holdout_start_1h_ms = int(warmup_start.timestamp() * 1000)

    print(f"  Holdout: {holdout_start:%Y-%m-%d %H:%M} → {holdout_end:%Y-%m-%d %H:%M} UTC")
    print()

    # Fetch data
    all_data: Dict[str, Any] = {}
    for symbol in SYMBOLS:
        print(f"  [{symbol}] Fetching 15m...", end="", flush=True)
        c15 = fetch_fn(symbol, "15m", holdout_start_15m_ms, holdout_end_ms)
        print(f" {len(c15)}", end="  ", flush=True)

        print("1h...", end="", flush=True)
        c1h = fetch_fn(symbol, "1h", holdout_start_1h_ms, holdout_end_ms)
        print(f" {len(c1h)}", end="  ", flush=True)

        regimes = regime_compute_fn(c1h)
        valid = (regimes["regime_label"] != "UNKNOWN").sum() if len(regimes) > 0 else 0
        print(f"regimes: {valid}")

        all_data[symbol] = {"candles_15m": c15, "regimes": regimes}

    min_len = min(len(all_data[s]["candles_15m"]) for s in SYMBOLS)
    n_steps = min_len - WINDOW

    if n_steps <= 0:
        return {"error": "Not enough candles for holdout replay"}

    HOLDOUT_DIR.mkdir(parents=True, exist_ok=True)

    # Replay v1.0
    print(f"\n  Replaying v1.0 ({n_steps} steps)...")
    v10_path = HOLDOUT_DIR / "holdout_v10.db"
    t0 = time_mod.time()
    replay_variant(V10_CONFIG, v10_path, all_data, n_steps)
    print(f"  v1.0 done in {time_mod.time() - t0:.1f}s\n")

    # Replay v1.1
    print(f"  Replaying v1.1 ({n_steps} steps)...")
    v11_path = HOLDOUT_DIR / "holdout_v11.db"
    t0 = time_mod.time()
    replay_variant(V11_CONFIG, v11_path, all_data, n_steps)
    print(f"  v1.1 done in {time_mod.time() - t0:.1f}s\n")

    v10_trades = query_closed_trades(v10_path)
    v11_trades = query_closed_trades(v11_path)
    v10_stats = compute_stats(v10_trades)
    v11_stats = compute_stats(v11_trades)

    # Verdict
    if v10_stats["count"] == 0 and v11_stats["count"] == 0:
        conclusion = "sem dados"
    elif v11_stats["total_pnl"] >= v10_stats["total_pnl"]:
        conclusion = "reforça"
    elif v11_stats["total_pnl"] >= v10_stats["total_pnl"] * 0.9:
        conclusion = "neutra"
    else:
        conclusion = "alerta"

    return {
        "period": f"{holdout_start:%Y-%m-%d} → {holdout_end:%Y-%m-%d}",
        "steps": n_steps,
        "v1.0": v10_stats,
        "v1.1": v11_stats,
        "conclusion": conclusion,
    }


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def format_robustness_report(
    monthly: Dict, holdout: Dict, regime: Dict,
) -> str:
    """Render the three analyses as human-readable text."""
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("  ROBUSTNESS CHECK — v1.0 vs v1.1 (B1)")
    lines.append("=" * 60)
    lines.append("")

    # --- Monthly ---
    lines.append("─" * 60)
    lines.append("  1. CONSISTENCIA MENSAL")
    lines.append("─" * 60)
    lines.append("")
    lines.append(
        f"  {'Mes':<10s} │ {'v1.0 PnL':>10s} {'WR':>6s} {'PF':>6s}"
        f" │ {'v1.1 PnL':>10s} {'WR':>6s} {'PF':>6s}"
        f" │ {'Vence':>5s}"
    )
    lines.append("  " + "─" * 74)

    for month, data in monthly["months"].items():
        v10 = data["v1.0"]
        v11 = data["v1.1"]
        v10_pf = _fmt_pf(v10["profit_factor"])
        v11_pf = _fmt_pf(v11["profit_factor"])
        lines.append(
            f"  {month:<10s} │ {v10['total_pnl']:>+9.4f}% {v10['win_rate']:>5.1f}% {v10_pf:>6s}"
            f" │ {v11['total_pnl']:>+9.4f}% {v11['win_rate']:>5.1f}% {v11_pf:>6s}"
            f" │ {data['winner']:>5s}"
        )

    lines.append("")
    lines.append(
        f"  v1.1 vence {monthly['v11_wins']} de {monthly['total_months']} meses"
        f" → {monthly['conclusion'].upper()}"
    )
    lines.append("")

    # --- Holdout ---
    lines.append("─" * 60)
    lines.append("  2. HOLDOUT OUT-OF-SAMPLE")
    lines.append("─" * 60)
    lines.append("")

    if "error" in holdout:
        lines.append(f"  ERRO: {holdout['error']}")
    else:
        lines.append(f"  Periodo: {holdout['period']}")
        lines.append(f"  Steps:   {holdout['steps']}")
        lines.append("")

        for label in ("v1.0", "v1.1"):
            s = holdout[label]
            pf = _fmt_pf(s["profit_factor"])
            lines.append(
                f"  {label}:  {s['count']:>3d} trades  "
                f"WR={s['win_rate']:>5.1f}%  PF={pf:>6s}  "
                f"PnL={s['total_pnl']:>+9.4f}%"
            )

        lines.append("")
        lines.append(f"  Conclusao holdout: {holdout['conclusion'].upper()}")

    lines.append("")

    # --- Regime ---
    lines.append("─" * 60)
    lines.append("  3. BREAKDOWN POR REGIME")
    lines.append("─" * 60)
    lines.append("")

    for regime_name, data in regime["regimes"].items():
        v10 = data["v1.0"]
        v11 = data["v1.1"]
        lines.append(f"  {regime_name}:")
        lines.append(
            f"    v1.0: n={v10['count']:>3d}  "
            f"WR={v10['win_rate']:>5.1f}%  "
            f"PnL={v10['total_pnl']:>+9.4f}%"
        )
        lines.append(
            f"    v1.1: n={v11['count']:>3d}  "
            f"WR={v11['win_rate']:>5.1f}%  "
            f"PnL={v11['total_pnl']:>+9.4f}%"
        )
        lines.append(
            f"    Delta: PnL={data['pnl_delta']:>+.4f}%  "
            f"WR={data['wr_delta']:>+.1f}pp"
        )
        lines.append("")

    lines.append(
        f"  Melhora {regime['conclusion'].upper()} "
        f"({regime['regimes_improved']}/{regime['total_regimes']} regimes)"
    )
    lines.append("")

    # --- Final verdict ---
    lines.append("=" * 60)
    lines.append("  VEREDICTO FINAL")
    lines.append("=" * 60)
    lines.append("")

    verdicts = [monthly["conclusion"], regime["conclusion"]]
    if "conclusion" in holdout:
        verdicts.append(holdout["conclusion"])

    positive = {"consistente", "generalizada", "reforça"}
    negative = {"fragil", "regime-especifica", "alerta"}

    pos_count = sum(1 for v in verdicts if v in positive)
    neg_count = sum(1 for v in verdicts if v in negative)

    if neg_count == 0 and pos_count >= 2:
        final = "ROBUSTA — v1.1 confirmada como baseline segura"
    elif neg_count >= 2:
        final = "FRAGIL — v1.1 pode ser overfit, considerar manter v1.0"
    else:
        final = "INCONCLUSIVA — v1.1 parcialmente validada, monitorar"

    lines.append(f"  Mensal:   {monthly['conclusion']}")
    if "conclusion" in holdout:
        lines.append(f"  Holdout:  {holdout['conclusion']}")
    lines.append(f"  Regimes:  {regime['conclusion']}")
    lines.append("")
    lines.append(f"  >>> {final}")
    lines.append("")

    return "\n".join(lines)


def _fmt_pf(pf: float) -> str:
    return f"{pf:.2f}" if pf != float("inf") else "inf"


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_robustness_check() -> str:
    """Run all 3 analyses and return formatted report."""
    print("=" * 55)
    print("  ROBUSTNESS CHECK — v1.0 vs v1.1 (B1)")
    print("=" * 55)
    print()

    # Load trades once for analyses 1 and 3
    print("  Loading trades from existing DBs...")
    v10_trades = query_closed_trades(V10_DB)
    v11_trades = query_closed_trades(V11_DB)
    print(f"  v1.0: {len(v10_trades)} closed trades")
    print(f"  v1.1: {len(v11_trades)} closed trades")
    print()

    # Analysis 1: Monthly (offline, fast)
    print("  [1/3] Consistencia mensal...")
    monthly = analyze_monthly(v10_trades, v11_trades)
    print(f"    v1.1 vence {monthly['v11_wins']}/{monthly['total_months']} meses")
    print()

    # Analysis 2: Holdout (online, slow — fetches Binance data)
    print("  [2/3] Holdout out-of-sample...")
    holdout = run_holdout(holdout_days=30)
    print()

    # Analysis 3: Regime breakdown (offline, fast)
    print("  [3/3] Breakdown por regime...")
    regime = analyze_regime(v10_trades, v11_trades)
    print(
        f"    Melhora: {regime['conclusion']} "
        f"({regime['regimes_improved']}/{regime['total_regimes']})"
    )
    print()

    # Format and save
    report_text = format_robustness_report(monthly, holdout, regime)

    HOLDOUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = HOLDOUT_DIR / "robustness_report.txt"
    report_path.write_text(report_text, encoding="utf-8")

    print(report_text)
    print(f"  Report saved: {report_path}")

    return report_text


if __name__ == "__main__":
    run_robustness_check()
