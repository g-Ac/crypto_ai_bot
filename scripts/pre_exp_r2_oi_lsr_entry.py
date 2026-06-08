#!/usr/bin/env python3
"""PRE-EXP R2: does OI/LSR add information at short entries?

Reads only the local baseline bot.db. It does not touch Momentum v1.1
runtime code, parameters, or live decisions.

Frozen high-level frame:
- Unit: each closed Momentum Pullback SHORT trade.
- Entry features: actual opening decision, outcome='trade' and blocked_by='none'.
- Outcome: net pnl_pct = DB gross pnl_pct - 0.08 round-trip fee.
- Anti-lookahead: hourly structural/price features use the last full hour
  before the 15m entry timestamp.
- Test: fixed 60/40 chronological split, baseline price/technical model
  versus baseline + OI/LSR model.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DB_PATH = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")
ROUND_TRIP_FEE_PCT = 0.08
HOLDOUT_FRAC = 0.60
RIDGE_ALPHA = 10.0
N_PERM = 2000
SEED = 20260608
MIN_TEST_N = 25


BASELINE_FEATURES = [
    "ret_1h",
    "ret_3h",
    "ret_6h",
    "ret_24h",
    "range_6h",
    "range_24h",
    "vol_6h",
    "vol_24h",
    "ema_gap_pct",
    "retracement_pct",
    "adx_slope_3",
    "di_spread",
    "is_btc",
    "regime_trending",
    "regime_weak_trend",
]

STRUCTURAL_FEATURES = [
    "log_oi",
    "oi_delta_1h",
    "oi_delta_3h",
    "oi_delta_6h",
    "oi_delta_24h",
    "lsr_global",
    "lsr_global_delta_6h",
    "lsr_global_delta_24h",
    "lsr_top",
    "lsr_top_delta_6h",
    "lsr_top_delta_24h",
]


@dataclass(frozen=True)
class ModelMetrics:
    r2: float
    spearman: float
    spread_bps: float
    n_top: int
    n_bottom: int


def _read_sql(con: sqlite3.Connection, query: str) -> pd.DataFrame:
    return pd.read_sql_query(query, con)


def _epoch_seconds(ts: pd.Timestamp) -> int:
    return int(ts.timestamp())


def _last_full_hour_before(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.floor("1h") - pd.Timedelta(hours=1)


def _rankdata(values: Iterable[float]) -> np.ndarray:
    a = np.asarray(list(values), dtype=float)
    order = np.argsort(a)
    ranks = np.empty(len(a), dtype=float)
    ranks[order] = np.arange(1, len(a) + 1, dtype=float)
    _, inv, counts = np.unique(a, return_inverse=True, return_counts=True)
    return (np.bincount(inv, weights=ranks) / counts)[inv]


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 5 or np.nanstd(x) == 0 or np.nanstd(y) == 0:
        return float("nan")
    rx = _rankdata(x)
    ry = _rankdata(y)
    rx -= rx.mean()
    ry -= ry.mean()
    den = math.sqrt(float((rx * rx).sum() * (ry * ry).sum()))
    return float((rx * ry).sum() / den) if den else float("nan")


def load_paired_shorts(con: sqlite3.Connection) -> pd.DataFrame:
    opens = _read_sql(
        con,
        """
        SELECT
            id AS decision_id,
            timestamp AS entry_ts,
            symbol,
            regime,
            ema_gap_pct,
            retracement_pct,
            adx_slope_3,
            di_spread
        FROM momentum_decisions
        WHERE outcome='trade'
          AND blocked_by='none'
          AND direction='SHORT'
        ORDER BY timestamp, id
        """,
    )
    trades = _read_sql(
        con,
        """
        SELECT
            id AS trade_id,
            timestamp AS close_ts,
            symbol,
            regime AS trade_regime,
            entry_price,
            exit_price,
            pnl_pct,
            pnl_usd,
            exit_reason,
            duration_candles
        FROM momentum_trades
        WHERE direction='SHORT'
        ORDER BY timestamp, id
        """,
    )
    if len(opens) != len(trades):
        raise RuntimeError(
            f"Cannot pair opens/trades: {len(opens)} short opens, {len(trades)} short closes"
        )

    paired = pd.concat(
        [
            opens.reset_index(drop=True).add_prefix("open_"),
            trades.reset_index(drop=True).add_prefix("trade_"),
        ],
        axis=1,
    )
    mismatched = paired[paired["open_symbol"] != paired["trade_symbol"]]
    if not mismatched.empty:
        ids = mismatched[["open_decision_id", "trade_trade_id", "open_symbol", "trade_symbol"]]
        raise RuntimeError(f"Open/trade symbol sequence mismatch: {ids.to_dict('records')}")

    paired["entry_ts"] = pd.to_datetime(paired["open_entry_ts"], utc=True)
    paired["close_ts"] = pd.to_datetime(paired["trade_close_ts"], utc=True)
    paired["pnl_pct_net"] = paired["trade_pnl_pct"].astype(float) - ROUND_TRIP_FEE_PCT
    paired["feature_hour"] = paired["entry_ts"].map(_last_full_hour_before)
    return paired


def load_hourly_panel(con: sqlite3.Connection, symbols: list[str]) -> dict[str, pd.DataFrame]:
    placeholders = ",".join("?" for _ in symbols)
    prices = pd.read_sql_query(
        f"""
        SELECT symbol, bucket_ts, open_price, high_price, low_price, close_price
        FROM k_prices
        WHERE symbol IN ({placeholders})
        ORDER BY symbol, bucket_ts
        """,
        con,
        params=symbols,
    )
    oi = pd.read_sql_query(
        f"""
        SELECT symbol, bucket_ts, sum_open_interest
        FROM k_open_interest
        WHERE symbol IN ({placeholders})
        ORDER BY symbol, bucket_ts
        """,
        con,
        params=symbols,
    )
    ratios = pd.read_sql_query(
        f"""
        SELECT symbol, bucket_ts, source, long_short_ratio
        FROM k_ratios
        WHERE symbol IN ({placeholders})
          AND source IN ('global_account', 'top_position')
        ORDER BY symbol, bucket_ts
        """,
        con,
        params=symbols,
    )

    prices["t"] = pd.to_datetime(prices["bucket_ts"], unit="s", utc=True)
    oi["t"] = pd.to_datetime(oi["bucket_ts"], unit="s", utc=True)
    ratios["t"] = pd.to_datetime(ratios["bucket_ts"], unit="s", utc=True)

    panels: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        p = prices[prices["symbol"] == symbol].set_index("t")
        o = oi[oi["symbol"] == symbol].set_index("t")[["sum_open_interest"]]
        r = ratios[ratios["symbol"] == symbol].pivot_table(
            index="t", columns="source", values="long_short_ratio", aggfunc="last"
        )
        idx = pd.date_range(p.index.min(), p.index.max(), freq="1h", tz="UTC")
        frame = (
            p[["open_price", "high_price", "low_price", "close_price"]]
            .reindex(idx)
            .ffill()
        )
        frame = frame.join(o.reindex(idx).ffill())
        frame = frame.join(r.reindex(idx).ffill())
        frame = add_hourly_features(frame)
        panels[symbol] = frame
    return panels


def add_hourly_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    close = out["close_price"].astype(float)
    high = out["high_price"].astype(float)
    low = out["low_price"].astype(float)
    ret = close.pct_change()

    for h in (1, 3, 6, 24):
        out[f"ret_{h}h"] = close.pct_change(h) * 100.0
    for h in (6, 24):
        out[f"range_{h}h"] = (
            (high.rolling(h).max() - low.rolling(h).min()) / close * 100.0
        )
        out[f"vol_{h}h"] = ret.rolling(h).std(ddof=0) * 100.0

    oi = out["sum_open_interest"].astype(float)
    out["log_oi"] = np.log(oi.replace(0, np.nan))
    for h in (1, 3, 6, 24):
        out[f"oi_delta_{h}h"] = np.log(oi / oi.shift(h)) * 100.0

    for source, name in (("global_account", "lsr_global"), ("top_position", "lsr_top")):
        series = out[source].astype(float)
        out[name] = np.log(series.replace(0, np.nan))
        for h in (6, 24):
            out[f"{name}_delta_{h}h"] = np.log(series / series.shift(h)) * 100.0
    return out


def build_dataset() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        paired = load_paired_shorts(con)
        symbols = sorted(paired["open_symbol"].unique().tolist())
        panels = load_hourly_panel(con, symbols)

    rows = []
    hourly_cols = [
        "ret_1h",
        "ret_3h",
        "ret_6h",
        "ret_24h",
        "range_6h",
        "range_24h",
        "vol_6h",
        "vol_24h",
        *STRUCTURAL_FEATURES,
    ]
    for _, row in paired.iterrows():
        panel = panels[row["open_symbol"]]
        feature_hour = row["feature_hour"]
        if feature_hour not in panel.index:
            continue
        values = panel.loc[feature_hour, hourly_cols]
        record = {
            "decision_id": int(row["open_decision_id"]),
            "trade_id": int(row["trade_trade_id"]),
            "symbol": row["open_symbol"],
            "entry_ts": row["entry_ts"].isoformat(),
            "feature_hour": feature_hour.isoformat(),
            "close_ts": row["close_ts"].isoformat(),
            "pnl_pct_gross": float(row["trade_pnl_pct"]),
            "pnl_pct_net": float(row["pnl_pct_net"]),
            "exit_reason": row["trade_exit_reason"],
            "ema_gap_pct": float(row["open_ema_gap_pct"]),
            "retracement_pct": float(row["open_retracement_pct"]),
            "adx_slope_3": float(row["open_adx_slope_3"]),
            "di_spread": float(row["open_di_spread"]),
            "is_btc": 1.0 if row["open_symbol"] == "BTCUSDT" else 0.0,
            "regime_trending": 1.0 if row["open_regime"] == "TRENDING" else 0.0,
            "regime_weak_trend": 1.0 if row["open_regime"] == "WEAK_TREND" else 0.0,
        }
        for col in hourly_cols:
            record[col] = float(values[col]) if pd.notna(values[col]) else np.nan
        rows.append(record)

    df = pd.DataFrame(rows).sort_values("entry_ts").reset_index(drop=True)
    needed = BASELINE_FEATURES + STRUCTURAL_FEATURES + ["pnl_pct_net"]
    return df.dropna(subset=needed).reset_index(drop=True)


def standardize(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    x_train = train[cols].to_numpy(dtype=float)
    x_test = test[cols].to_numpy(dtype=float)
    mu = x_train.mean(axis=0)
    sd = x_train.std(axis=0, ddof=0)
    sd[sd == 0] = 1.0
    return (x_train - mu) / sd, (x_test - mu) / sd


def ridge_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> np.ndarray:
    x_train, x_test = standardize(train, test, cols)
    y = train["pnl_pct_net"].to_numpy(dtype=float)

    # Intercept is not penalized.
    x_aug = np.column_stack([np.ones(len(x_train)), x_train])
    xtx = x_aug.T @ x_aug
    penalty = np.eye(xtx.shape[0]) * RIDGE_ALPHA
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(xtx + penalty, x_aug.T @ y)
    test_aug = np.column_stack([np.ones(len(x_test)), x_test])
    return test_aug @ beta


def top_bottom_spread(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, int, int]:
    n = len(y_true)
    k = max(1, int(round(n / 3)))
    order = np.argsort(y_pred)
    bottom = y_true[order[:k]]
    top = y_true[order[-k:]]
    return float((top.mean() - bottom.mean()) * 100.0), int(k), int(k)


def evaluate(y_true: np.ndarray, y_pred: np.ndarray, y_train_mean: float) -> ModelMetrics:
    denom = float(((y_true - y_train_mean) ** 2).sum())
    r2 = 1.0 - float(((y_true - y_pred) ** 2).sum()) / denom if denom > 0 else float("nan")
    sp = spearman(y_pred, y_true)
    spread, n_top, n_bottom = top_bottom_spread(y_true, y_pred)
    return ModelMetrics(r2=r2, spearman=sp, spread_bps=spread, n_top=n_top, n_bottom=n_bottom)


def model_comparison(df: pd.DataFrame) -> dict:
    cut = int(len(df) * HOLDOUT_FRAC)
    train = df.iloc[:cut].copy()
    test = df.iloc[cut:].copy()
    if len(test) < MIN_TEST_N:
        raise RuntimeError(f"Test set too small: n_test={len(test)}")

    y_test = test["pnl_pct_net"].to_numpy(dtype=float)
    y_train_mean = float(train["pnl_pct_net"].mean())

    base_pred = ridge_predict(train, test, BASELINE_FEATURES)
    full_cols = BASELINE_FEATURES + STRUCTURAL_FEATURES
    full_pred = ridge_predict(train, test, full_cols)

    base = evaluate(y_test, base_pred, y_train_mean)
    full = evaluate(y_test, full_pred, y_train_mean)
    observed_delta = full.spread_bps - base.spread_bps

    rng = np.random.default_rng(SEED)
    null_delta = np.empty(N_PERM)
    shuffled_cols = STRUCTURAL_FEATURES
    for i in range(N_PERM):
        train_p = train.copy()
        test_p = test.copy()
        order_train = rng.permutation(len(train_p))
        order_test = rng.permutation(len(test_p))
        train_p.loc[:, shuffled_cols] = train_p[shuffled_cols].to_numpy()[order_train]
        test_p.loc[:, shuffled_cols] = test_p[shuffled_cols].to_numpy()[order_test]
        pred_p = ridge_predict(train_p, test_p, full_cols)
        perm_metrics = evaluate(y_test, pred_p, y_train_mean)
        null_delta[i] = perm_metrics.spread_bps - base.spread_bps

    if observed_delta > 0:
        p_perm = float((null_delta >= observed_delta).mean())
    else:
        p_perm = float((null_delta <= observed_delta).mean())

    by_symbol = {}
    for symbol in sorted(test["symbol"].unique()):
        mask = test["symbol"].to_numpy() == symbol
        if mask.sum() < 6:
            continue
        base_spread, _, _ = top_bottom_spread(y_test[mask], base_pred[mask])
        full_spread, _, _ = top_bottom_spread(y_test[mask], full_pred[mask])
        by_symbol[symbol] = {
            "n": int(mask.sum()),
            "baseline_spread_bps": base_spread,
            "full_spread_bps": full_spread,
            "delta_spread_bps": full_spread - base_spread,
        }

    return {
        "n_total": int(len(df)),
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "train_start": str(train["entry_ts"].iloc[0]),
        "train_end": str(train["entry_ts"].iloc[-1]),
        "test_start": str(test["entry_ts"].iloc[0]),
        "test_end": str(test["entry_ts"].iloc[-1]),
        "baseline": base.__dict__,
        "full": full.__dict__,
        "delta": {
            "r2": full.r2 - base.r2,
            "spearman": full.spearman - base.spearman,
            "spread_bps": observed_delta,
            "perm_p_one_sided_for_delta_spread": p_perm,
        },
        "by_symbol_test": by_symbol,
    }


def label_result(metrics: dict) -> tuple[str, list[str]]:
    delta = metrics["delta"]
    by_symbol = metrics["by_symbol_test"]
    coherent_by_symbol = bool(by_symbol) and all(
        item["delta_spread_bps"] > 0 for item in by_symbol.values()
    )
    go = (
        metrics["n_test"] >= MIN_TEST_N
        and delta["r2"] > 0.05
        and delta["spearman"] > 0.10
        and delta["spread_bps"] > 25.0
        and delta["perm_p_one_sided_for_delta_spread"] <= 0.10
        and coherent_by_symbol
    )
    if go:
        return "vale abrir EXP formal", ["structural block improves all fixed OOS metrics"]

    negatives = sum(
        [
            delta["r2"] <= 0,
            delta["spearman"] <= 0,
            delta["spread_bps"] <= 0,
        ]
    )
    no_go = negatives >= 2 and delta["perm_p_one_sided_for_delta_spread"] >= 0.50
    if no_go:
        return "nao vale abrir EXP formal", [
            "structural block does not improve baseline on fixed OOS metrics"
        ]

    reasons = [
        "sample or OOS signal is not decisive under the frozen exploratory rubric",
        f"delta_r2={delta['r2']:.4f}",
        f"delta_spearman={delta['spearman']:.4f}",
        f"delta_spread_bps={delta['spread_bps']:.2f}",
        f"perm_p={delta['perm_p_one_sided_for_delta_spread']:.4f}",
    ]
    return "AMBIGUO / DADO INSUFICIENTE", reasons


def main() -> None:
    df = build_dataset()
    metrics = model_comparison(df)
    label, reasons = label_result(metrics)
    payload = {
        "frame": "PRE-EXP R2 OI/LSR at Momentum SHORT entries",
        "db_path": str(DB_PATH),
        "anti_lookahead": "last full hourly bucket before entry timestamp",
        "outcome": "pnl_pct_net = momentum_trades.pnl_pct - 0.08",
        "label": label,
        "reasons": reasons,
        "metrics": metrics,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
