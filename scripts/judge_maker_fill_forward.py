#!/usr/bin/env python3
"""Julgamento read-only da Fase F maker-fill, com corte original de 31/07.

Aplica os cinco critérios selados em docs/pre_registros/PREREG_maker_fill_v11.md.
Remove somente a fixture sintética conhecida que testes antigos gravaram no bot.db;
a identidade vem do próprio tests/test_momentum_paper_executor.py, não de PnL.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_DEFAULT = ROOT / "runtime/baseline/bot.db"
OUT_DEFAULT = ROOT / "docs/relatorios/2026-08-03-maker-fill-fase-f.json"
CUTOFF = "2026-08-01"
MIN_SAMPLE = 50


def _is_known_test_fixture(r: dict) -> bool:
    if r["candle_open_ts"] != 1776254400 or r["symbol"] != "BTCUSDT" \
            or r["limit_price"] != 85000.0:
        return False
    levels = (r["direction"], r["sl_price"], r["tp1_price"], r["tp2_price"])
    return levels in {
        ("LONG", 84500.0, 85800.0, 86500.0),
        ("SHORT", 85500.0, 84200.0, 83500.0),
    }


def clean_rows(rows: list[dict]) -> tuple[list[dict], int]:
    clean = [r for r in rows if not _is_known_test_fixture(r)]
    return clean, len(rows) - len(clean)


def _pf(values: list[float]) -> float | None:
    wins = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    return wins / losses if wins > 0 and losses > 0 else None


def _symbol_metrics(rows: list[dict], symbol: str) -> dict:
    sub = [r for r in rows if r["symbol"] == symbol]
    executed = [float(r["net_pnl_pct"]) for r in sub if r["status"] == "closed"]
    pf = _pf(executed)
    return {
        "n": len(sub),
        "fills": len(executed),
        "maker_net_pct": round(sum(executed), 6),
        "pf_executados": round(pf, 6) if pf is not None else None,
    }


def evaluate(rows: list[dict]) -> dict:
    unresolved = [r for r in rows if r["status"] not in {"closed", "no_fill"}]
    if unresolved:
        raise ValueError(f"há {len(unresolved)} sombras não resolvidas")
    missing_pair = [r for r in rows if r.get("taker_net_pnl_pct") is None]
    if missing_pair:
        raise ValueError(f"há {len(missing_pair)} sombras sem pareamento taker")

    n = len(rows)
    filled = [r for r in rows if r["status"] == "closed"]
    maker_values = [float(r["net_pnl_pct"]) for r in filled]
    fill_rate = len(filled) / n if n else None
    pf = _pf(maker_values)
    maker_total = sum(maker_values)
    taker_total = sum(float(r["taker_net_pnl_pct"]) for r in rows)
    delta = maker_total - taker_total

    top10 = sorted(rows, key=lambda r: float(r["taker_net_pnl_pct"]), reverse=True)[:10]
    top10_captured = sum(r["status"] == "closed" for r in top10)

    by_symbol = {s: _symbol_metrics(rows, s) for s in ("BTCUSDT", "ETHUSDT")}
    symbols_pass = all(
        m["n"] > 0 and m["maker_net_pct"] >= 0
        and m["pf_executados"] is not None and m["pf_executados"] >= 1.0
        for m in by_symbol.values()
    )

    criteria = {
        "c1_fill_rate": {
            "value": round(fill_rate, 6) if fill_rate is not None else None,
            "threshold": ">= 0.50", "pass": fill_rate is not None and fill_rate >= 0.50,
        },
        "c2_pf_agregado": {
            "value": round(pf, 6) if pf is not None else None,
            "threshold": ">= 1.15", "pass": pf is not None and pf >= 1.15,
        },
        "c3_delta_maker_taker_pct": {
            "value": round(delta, 6), "threshold": "> 0", "pass": delta > 0,
        },
        "c4_top10_winners_capturados": {
            "value": top10_captured, "threshold": ">= 5", "pass": top10_captured >= 5,
        },
        "c5_convergencia_btc_eth": {
            "value": by_symbol,
            "threshold": "cada símbolo: maker_net >= 0 e PF >= 1.00",
            "pass": symbols_pass,
        },
    }

    if n < MIN_SAMPLE:
        verdict = "INCONCLUSIVO"
    else:
        verdict = "GO" if all(c["pass"] for c in criteria.values()) else "NO-GO"

    avg_filled = sum(float(r["taker_net_pnl_pct"]) for r in filled) / len(filled) if filled else None
    missed = [r for r in rows if r["status"] == "no_fill"]
    avg_missed = sum(float(r["taker_net_pnl_pct"]) for r in missed) / len(missed) if missed else None

    return {
        "veredito": verdict,
        "n": n,
        "fills": len(filled),
        "no_fill": len(missed),
        "maker_net_total_pct": round(maker_total, 6),
        "taker_net_total_pct": round(taker_total, 6),
        "criterios": criteria,
        "selecao_adversa": {
            "taker_net_medio_quando_maker_preenche": round(avg_filled, 6) if avg_filled is not None else None,
            "taker_net_medio_quando_maker_nao_preenche": round(avg_missed, 6) if avg_missed is not None else None,
        },
    }


def load_and_validate(db_path=DB_DEFAULT) -> tuple[list[dict], dict]:
    uri = f"file:{Path(db_path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    raw = [dict(r) for r in conn.execute(
        "SELECT * FROM momentum_maker_shadow WHERE created_at < ? ORDER BY id", (CUTOFF,)
    )]
    clean, removed = clean_rows(raw)

    shapes = {
        (r["symbol"], r["direction"], r["candle_open_ts"], r["limit_price"],
         r["sl_price"], r["tp1_price"], r["tp2_price"])
        for r in clean
    }
    if len(shapes) != len(clean):
        raise ValueError("duplicatas permaneceram após remover a fixture conhecida")

    start_day = min(r["signal_ts"][:10] for r in clean)
    trades = conn.execute(
        "SELECT net_pnl_pct, gross_pnl_pct, total_cost_bps FROM momentum_trades "
        "WHERE timestamp >= ? AND timestamp < ? ORDER BY net_pnl_pct",
        (start_day, CUTOFF),
    ).fetchall()
    conn.close()

    if len(trades) != len(clean):
        raise ValueError(f"população não casa: {len(clean)} sombras vs {len(trades)} trades")
    costs = sorted({float(r["total_cost_bps"]) for r in trades})
    if costs != [10.0]:
        raise ValueError(f"custos baseline não são constantes em 10 bps: {costs}")
    shadow_net = sorted(round(float(r["taker_net_pnl_pct"]), 8) for r in clean)
    trade_net = sorted(round(float(r["net_pnl_pct"]), 8) for r in trades)
    if shadow_net != trade_net:
        raise ValueError("multiset de PnL taker das sombras não casa com momentum_trades")

    audit = {
        "raw_rows": len(raw), "synthetic_fixture_rows_removed": removed,
        "clean_unique_rows": len(clean), "baseline_trades": len(trades),
        "baseline_cost_bps_values": costs,
        "top10_ranking_note": "gross = net + 10 bps constante; ranking por taker_net é idêntico",
    }
    return clean, audit


def main(db_path=DB_DEFAULT, out_path=OUT_DEFAULT) -> dict:
    rows, audit = load_and_validate(db_path)
    payload = evaluate(rows)
    payload.update({
        "fase": "F", "estudo": "maker-fill-v1.1",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "cutoff_exclusive": CUTOFF,
        "data_quality": audit,
        "criterios_source": "docs/pre_registros/PREREG_maker_fill_v11.md §5-§6",
    })
    if out_path is not None:
        Path(out_path).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


if __name__ == "__main__":
    p = main()
    print(f"MAKER-FILL FASE F: {p['veredito']} | n={p['n']} | fills={p['fills']}")
    for name, c in p["criterios"].items():
        print(f"  {name}: {'PASS' if c['pass'] else 'FAIL'} | {c['value']}")
    print(f"relatório: {OUT_DEFAULT}")
