"""Fase R do PREREG_maker_fill_v11.md — replay retroativo da politica maker.

Aplica a regra selada (§4) aos trades fechados de momentum_trades usando
klines 15m SPOT historicos (mesma fonte do paper executor / market.get_candles).

So pode MATAR, nunca aprovar: o fill por low/high de candle e otimista
(sem book/fila). Kill: PF liquido dos PnLs executados < 1.0.

Uso:
    cd ~/crypto_ai_bot && source .venv/bin/activate
    python scripts/replay_maker_shadow.py
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import BINANCE_SPOT_KLINES_URL  # noqa: E402
from momentum.maker_shadow import (  # noqa: E402
    MAKER_FEE_RATE,
    TAKER_FEE_RATE,
    locate_signal_candle,
    simulate_maker_trade,
    summarize_policy,
)

DB_PATH = os.path.join(ROOT, "runtime", "baseline", "bot.db")
OUT_PATH = os.path.join(ROOT, "research", "maker_shadow_phase_r.json")
M15_MS = 15 * 60 * 1000
TRADE_WINDOW = 17  # candles N..N+16 cobrem fill (N, N+1) + timeout (N+16)


def fetch_klines_15m(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    """Busca klines 15m spot paginados (limit 1000), dedup por open_time."""
    out: dict[int, dict] = {}
    cur = start_ms
    while cur < end_ms:
        url = (f"{BINANCE_SPOT_KLINES_URL}?symbol={symbol}&interval=15m"
               f"&startTime={cur}&endTime={end_ms}&limit=1000")
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        for k in data:
            out[k[0]] = {
                "open_time": k[0],
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
            }
        cur = data[-1][0] + M15_MS
        if len(data) < 1000:
            break
        time.sleep(0.25)
    return sorted(out.values(), key=lambda c: c["open_time"])


def load_trades() -> list[dict]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, timestamp, symbol, direction, entry_price, sl_price, "
        "tp1_price, tp2_price, duration_candles, exit_reason, "
        "pnl_pct AS gross_baseline, net_pnl_pct AS net_baseline, mfe_pct "
        "FROM momentum_trades ORDER BY id"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _ts_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def simulate_all(trades, klines_by_symbol, idx_by_symbol, fill_window=2):
    """Roda a sombra maker em todos os trades. Retorna (rows, anchor_failed)."""
    rows, anchor_failed = [], []
    for t in trades:
        ks = klines_by_symbol[t["symbol"]]
        idx = idx_by_symbol[t["symbol"]]
        ni, off = locate_signal_candle(
            ks, idx, _ts_ms(t["timestamp"]), t["duration_candles"],
            t["entry_price"],
        )
        if ni is None:
            anchor_failed.append(t["id"])
            continue
        sim = simulate_maker_trade(
            direction=t["direction"],
            entry_price=t["entry_price"],
            sl_price=t["sl_price"],
            tp1_price=t["tp1_price"],
            tp2_price=t["tp2_price"],
            candles=ks[ni: ni + TRADE_WINDOW],  # comeca no proprio N
            fill_window=fill_window,
        )
        rows.append({**sim, "trade_id": t["id"], "symbol": t["symbol"],
                     "anchor_offset": off,
                     "gross_baseline": t["gross_baseline"],
                     "net_baseline": t["net_baseline"],
                     "mfe_baseline": t["mfe_pct"]})
    return rows, anchor_failed


def aggregate(rows: list[dict]) -> dict:
    """Metricas da moldura sobre rows pareados (exclui incomplete do par)."""
    valid = [r for r in rows if r["exit_reason"] != "incomplete"]
    agg = {"policy": summarize_policy(rows)}

    agg["delta_net_pct_vs_taker"] = round(
        sum(r["net_pnl_pct"] for r in valid)
        - sum(r["net_baseline"] for r in valid), 4)
    agg["baseline_net_pct"] = round(sum(r["net_baseline"] for r in valid), 4)

    top10 = sorted(valid, key=lambda r: r["gross_baseline"], reverse=True)[:10]
    agg["top10_winners_filled"] = sum(1 for r in top10 if r["filled"])

    filled = [r for r in valid if r["filled"]]
    missed = [r for r in valid if not r["filled"]]
    agg["adverse_selection"] = {
        "avg_gross_baseline_filled": round(
            sum(r["gross_baseline"] for r in filled) / len(filled), 4)
        if filled else None,
        "avg_gross_baseline_missed": round(
            sum(r["gross_baseline"] for r in missed) / len(missed), 4)
        if missed else None,
        "avg_mfe_baseline_missed": round(
            sum(r["mfe_baseline"] for r in missed) / len(missed), 4)
        if missed else None,
    }

    reasons: dict[str, int] = {}
    for r in rows:
        reasons[r["exit_reason"]] = reasons.get(r["exit_reason"], 0) + 1
    agg["exit_reasons"] = reasons

    agg["by_symbol"] = {}
    for sym in sorted({r["symbol"] for r in rows}):
        sub = [r for r in rows if r["symbol"] == sym]
        sub_valid = [r for r in sub if r["exit_reason"] != "incomplete"]
        agg["by_symbol"][sym] = {
            **summarize_policy(sub),
            "delta_net_pct_vs_taker": round(
                sum(r["net_pnl_pct"] for r in sub_valid)
                - sum(r["net_baseline"] for r in sub_valid), 4),
        }
    return agg


def recompute_fee_sensitivity(rows: list[dict], maker_rate: float) -> dict:
    """Recalcula net com outra fee maker (caminho dos trades nao muda)."""
    adj = []
    for r in rows:
        if not r["filled"] or r["exit_reason"] == "incomplete":
            adj.append(dict(r))
            continue
        exit_fee = maker_rate if r["exit_reason"] in ("tp1_hit", "tp2_hit") \
            else TAKER_FEE_RATE
        adj.append({**r,
                    "net_pnl_pct": round(
                        r["gross_pnl_pct"] - (maker_rate + exit_fee), 4)})
    return summarize_policy(adj)


def main() -> None:
    trades = load_trades()
    print(f"Trades fechados no banco: {len(trades)}")

    start_ms = min(_ts_ms(t["timestamp"]) for t in trades) - 48 * 3600 * 1000
    end_ms = int(time.time() * 1000)

    klines_by_symbol, idx_by_symbol = {}, {}
    for sym in sorted({t["symbol"] for t in trades}):
        ks = fetch_klines_15m(sym, start_ms, end_ms)
        klines_by_symbol[sym] = ks
        idx_by_symbol[sym] = {k["open_time"]: i for i, k in enumerate(ks)}
        print(f"{sym}: {len(ks)} klines 15m spot")

    rows, anchor_failed = simulate_all(trades, klines_by_symbol, idx_by_symbol)
    print(f"Pareados: {len(rows)} | anchor_failed: {len(anchor_failed)}")

    offsets: dict[str, int] = {}
    for r in rows:
        key = str(r["anchor_offset"])
        offsets[key] = offsets.get(key, 0) + 1

    structural = [r for r in rows if r["anchor_offset"] in (0, -1)]

    report = {
        "prereg": "docs/pre_registros/PREREG_maker_fill_v11.md",
        "phase": "R (replay retroativo — so pode matar, nunca aprovar)",
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "fee_profile": {"maker": MAKER_FEE_RATE, "taker": TAKER_FEE_RATE},
        "n_trades_db": len(trades),
        "anchor_failed_ids": anchor_failed,
        "anchor_offsets": offsets,
        "main": aggregate(rows),
        "sensitivity": {
            "fill_window_1": aggregate(
                simulate_all(trades, klines_by_symbol, idx_by_symbol,
                             fill_window=1)[0]),
            "maker_001": recompute_fee_sensitivity(rows, 0.01),
            "maker_003": recompute_fee_sensitivity(rows, 0.03),
            "structural_anchors_only": aggregate(structural),
        },
    }

    pf = report["main"]["policy"]["pf_executados"]
    if pf is not None and pf < 1.0:
        report["verdict"] = (
            f"KILL — PF liquido dos executados {pf} < 1.0 mesmo com fill "
            "otimista; v1.1 inviavel tambem como maker.")
    elif pf is None:
        report["verdict"] = "INCONCLUSIVO — PF indefinido (nao aprova)."
    else:
        report["verdict"] = (
            f"SOBREVIVE A FASE R (PF executados {pf}) — nao aprova nada; "
            "Fase F (forward) julga.")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as fh:
        json.dump(report, fh, indent=2)

    print(json.dumps(report["main"], indent=2))
    print(f"\nVEREDICTO FASE R: {report['verdict']}")
    print(f"Relatorio completo: {OUT_PATH}")


if __name__ == "__main__":
    main()
