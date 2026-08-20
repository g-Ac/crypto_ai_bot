#!/usr/bin/env python3
"""Read-only autopsy for compression breakout shadow trades.

Tests whether regime-filtered breakout candidates show early follow-through or an
observable fast invalidation pattern. Does not modify bot runtime/config/state.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path('/home/pi/crypto_ai_bot')
sys.path.insert(0, str(ROOT))

from engines_5m.breakout import BreakoutEngine5m  # noqa: E402
from indicators_5m import add_indicators_5m  # noqa: E402

IN_CSV = ROOT / 'reports/breakout_compression_shadow_2026-06-12.csv'
OUT_CSV = ROOT / 'reports/breakout_regime_followthrough_autopsy_2026-06-12.csv'
OUT_MD = ROOT / 'reports/breakout_regime_followthrough_autopsy_2026-06-12.md'
BINANCE_FAPI = 'https://fapi.binance.com/fapi/v1/klines'
INTERVAL_MS = 5 * 60 * 1000
FEE_ROUNDTRIP_PCT = 0.10
HORIZONS = (1, 2, 3, 4, 8, 12)
GOOD_REGIMES = {'TRENDING', 'WEAK_TREND'}
UTC = dt.timezone.utc


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)


def fmt_ts_ms(x: int) -> str:
    return dt.datetime.fromtimestamp(x / 1000, UTC).strftime('%Y-%m-%d %H:%M:%S')


def ms(x: dt.datetime) -> int:
    return int(x.timestamp() * 1000)


def fetch_5m(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows: list[list[Any]] = []
    cur = start_ms
    while cur < end_ms:
        url = f'{BINANCE_FAPI}?symbol={symbol}&interval=5m&startTime={cur}&endTime={end_ms}&limit=1500'
        proc = None
        for attempt in range(1, 5):
            proc = subprocess.run(['curl', '--http1.1', '-sS', '--max-time', '20', url], capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                break
            time.sleep(0.5 * attempt)
        if proc is None or proc.returncode != 0:
            raise RuntimeError(f'curl failed for {symbol}: rc={proc.returncode if proc else None}')
        data = json.loads(proc.stdout)
        if not isinstance(data, list):
            raise RuntimeError(f'unexpected response for {symbol}: {data!r}')
        if not data:
            break
        rows.extend(data)
        nxt = int(data[-1][0]) + INTERVAL_MS
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.08)
    df = pd.DataFrame(rows, columns=['time','open','high','low','close','volume','close_time','qav','trades','taker_buy_base','taker_buy_quote','ignore'])
    if df.empty:
        return df
    df = df.drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    df['time'] = df['time'].astype(np.int64)
    df['timestamp'] = pd.to_datetime(df['time'], unit='ms', utc=True)
    return df


def pnl(direction: str, entry: float, exit_price: float) -> float:
    gross = (exit_price / entry - 1.0) * 100.0 if direction == 'LONG' else (1.0 - exit_price / entry) * 100.0
    return gross - FEE_ROUNDTRIP_PCT


def pf(xs: list[float]) -> float:
    g = sum(x for x in xs if x > 0)
    l = abs(sum(x for x in xs if x <= 0))
    return math.inf if l == 0 and g > 0 else (g / l if l else 0.0)


def boolish(x: str) -> bool:
    return str(x).lower() == 'true'


def get_signal_at(df_ind: pd.DataFrame, signal_ts: str) -> tuple[int, Any, dict[str, Any]]:
    t_ms = ms(parse_ts(signal_ts))
    matches = np.where(df_ind['time'].values == t_ms)[0]
    if len(matches) == 0:
        raise RuntimeError(f'signal timestamp not found: {signal_ts}')
    i = int(matches[0])
    engine = BreakoutEngine5m()
    visible = df_ind.iloc[max(0, i - 240): i + 1].copy()
    sig = engine.analyze(str(df_ind.attrs['symbol']), visible)
    if sig is None:
        raise RuntimeError(f'could not reconstruct signal at {signal_ts}')
    return i, sig, sig.metadata or {}


def enrich_trade(row: dict[str, str], df_ind: pd.DataFrame) -> dict[str, Any]:
    entry_ms = ms(parse_ts(row['entry_ts']))
    entry_idx = int(np.where(df_ind['time'].values == entry_ms)[0][0])
    signal_idx, sig, meta = get_signal_at(df_ind, row['signal_ts'])
    direction = row['direction']
    entry = float(row['entry_price'])
    actual_pnl = float(row['pnl_pct'])
    max_high = float(meta['max_high'])
    min_low = float(meta['min_low'])
    breakout_boundary = max_high if direction == 'LONG' else min_low
    tp1_dist_pct = abs(float(row['tp1_price']) - entry) / entry * 100.0
    sl_dist_pct = abs(entry - float(row['sl_price'])) / entry * 100.0

    out: dict[str, Any] = dict(row)
    out.update({
        'is_good_regime': row['regime'] in GOOD_REGIMES,
        'is_winner': actual_pnl > 0,
        'max_high': max_high,
        'min_low': min_low,
        'breakout_boundary': breakout_boundary,
        'tp1_dist_pct': tp1_dist_pct,
        'sl_dist_pct': sl_dist_pct,
    })

    first_back_inside = ''
    first_close_against = ''
    for h in HORIZONS:
        end_idx = min(len(df_ind) - 1, entry_idx + h - 1)
        window = df_ind.iloc[entry_idx:end_idx + 1]
        if direction == 'LONG':
            mfe = (window['high'].max() - entry) / entry * 100.0
            mae = (entry - window['low'].min()) / entry * 100.0
            close_h = float(df_ind.iloc[end_idx]['close'])
            back_inside = close_h <= max_high
            close_against = close_h < entry
        else:
            mfe = (entry - window['low'].min()) / entry * 100.0
            mae = (window['high'].max() - entry) / entry * 100.0
            close_h = float(df_ind.iloc[end_idx]['close'])
            back_inside = close_h >= min_low
            close_against = close_h > entry
        out[f'mfe_{h}'] = mfe
        out[f'mae_{h}'] = mae
        out[f'mfe_to_tp1_{h}'] = mfe / tp1_dist_pct if tp1_dist_pct else 0.0
        out[f'close_pnl_{h}'] = pnl(direction, entry, close_h)
        out[f'back_inside_{h}'] = back_inside
        out[f'close_against_{h}'] = close_against
        out[f'hyp_exit_back_inside_{h}_pnl'] = pnl(direction, entry, close_h) if back_inside else actual_pnl
        out[f'hyp_exit_close_against_{h}_pnl'] = pnl(direction, entry, close_h) if close_against else actual_pnl
        if back_inside and not first_back_inside:
            first_back_inside = h
        if close_against and not first_close_against:
            first_close_against = h
    out['first_back_inside_h'] = first_back_inside
    out['first_close_against_h'] = first_close_against
    return out


def summarize(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    xs = [float(r['pnl_pct']) for r in rows]
    return {
        'label': label,
        'n': len(rows),
        'net': sum(xs),
        'avg': float(np.mean(xs)) if xs else 0.0,
        'median': float(np.median(xs)) if xs else 0.0,
        'wr': sum(1 for x in xs if x > 0) / len(xs) * 100 if xs else 0.0,
        'pf': pf(xs),
        'false': sum(1 for r in rows if boolish(r['false_breakout'])) / len(rows) * 100 if rows else 0.0,
        'tp1': sum(1 for r in rows if boolish(r['tp1_hit'])) / len(rows) * 100 if rows else 0.0,
    }


def hyp_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    xs = [float(r[key]) for r in rows]
    base = [float(r['pnl_pct']) for r in rows]
    return {'net': sum(xs), 'delta': sum(xs) - sum(base), 'pf': pf(xs), 'wr': sum(1 for x in xs if x > 0) / len(xs) * 100 if xs else 0.0}


def main() -> None:
    with IN_CSV.open() as f:
        all_rows = list(csv.DictReader(f))
    filled = [r for r in all_rows if r['status'] == 'filled']
    if not filled:
        raise SystemExit('No filled rows in input CSV')

    by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in filled:
        by_symbol[r['symbol']].append(r)

    enriched: list[dict[str, Any]] = []
    for sym, rows in by_symbol.items():
        min_t = min(parse_ts(r['signal_ts']) for r in rows) - dt.timedelta(hours=4)
        max_t = max(parse_ts(r['exit_ts']) for r in rows) + dt.timedelta(hours=4)
        raw = fetch_5m(sym, ms(min_t), ms(max_t))
        raw.attrs['symbol'] = sym
        df_ind = add_indicators_5m(raw.copy())
        df_ind.attrs['symbol'] = sym
        for r in rows:
            enriched.append(enrich_trade(r, df_ind))

    fieldnames = sorted({k for r in enriched for k in r.keys()})
    with OUT_CSV.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(enriched)

    groups = [
        ('ALL', enriched),
        ('GOOD_REGIME TRENDING+WEAK_TREND', [r for r in enriched if r['is_good_regime']]),
        ('BAD_REGIME RANGING+VOLATILE', [r for r in enriched if not r['is_good_regime']]),
        ('WINNERS', [r for r in enriched if r['is_winner']]),
        ('LOSERS', [r for r in enriched if not r['is_winner']]),
    ]

    md: list[str] = []
    md.append('# Breakout regime/follow-through autopsy')
    md.append('')
    md.append('Status: DISCOVERY / READ-ONLY. Usa somente os 31 trades filled do shadow anterior; não altera bot.')
    md.append('')
    md.append(f'- input: `{IN_CSV}`')
    md.append(f'- output csv: `{OUT_CSV}`')
    md.append(f'- horizons: {", ".join(map(str, HORIZONS))} candles de 5m')
    md.append('- good_regime definido antes desta autópsia: TRENDING + WEAK_TREND')
    md.append('')
    md.append('## Base por grupo')
    md.append('')
    md.append('| grupo | n | net | avg | median | WR | PF | TP1% | false_breakout% |')
    md.append('|---|---:|---:|---:|---:|---:|---:|---:|---:|')
    for label, rows in groups:
        if not rows:
            continue
        s = summarize(rows, label)
        pfs = 'inf' if math.isinf(s['pf']) else f"{s['pf']:.2f}"
        md.append(f"| {label} | {s['n']} | {s['net']:+.4f}% | {s['avg']:+.4f}% | {s['median']:+.4f}% | {s['wr']:.1f}% | {pfs} | {s['tp1']:.1f}% | {s['false']:.1f}% |")
    md.append('')

    md.append('## Early MFE/MAE: winners vs losers')
    md.append('')
    md.append('| grupo | h | median MFE | median MAE | median MFE/TP1 | back_inside% | close_against% |')
    md.append('|---|---:|---:|---:|---:|---:|---:|')
    for label, rows in groups:
        if label not in {'GOOD_REGIME TRENDING+WEAK_TREND', 'BAD_REGIME RANGING+VOLATILE', 'WINNERS', 'LOSERS'} or not rows:
            continue
        for h in HORIZONS:
            md.append(
                f"| {label} | {h} | "
                f"{np.median([float(r[f'mfe_{h}']) for r in rows]):.4f}% | "
                f"{np.median([float(r[f'mae_{h}']) for r in rows]):.4f}% | "
                f"{np.median([float(r[f'mfe_to_tp1_{h}']) for r in rows]):.2f} | "
                f"{sum(1 for r in rows if r[f'back_inside_{h}'])/len(rows)*100:.1f}% | "
                f"{sum(1 for r in rows if r[f'close_against_{h}'])/len(rows)*100:.1f}% |"
            )
    md.append('')

    md.append('## Teste diagnóstico de invalidação rápida')
    md.append('')
    md.append('Hipóteses simuladas só como diagnóstico: se no candle H o close voltou para dentro da consolidação, sair no close_H; ou se fechou contra a entrada, sair no close_H. Se a condição não ocorre, mantém o resultado real shadow.')
    md.append('')
    md.append('| universo | regra | H | net | delta vs real | PF | WR |')
    md.append('|---|---|---:|---:|---:|---:|---:|')
    universes = [('ALL', enriched), ('GOOD_REGIME', [r for r in enriched if r['is_good_regime']]), ('BAD_REGIME', [r for r in enriched if not r['is_good_regime']])]
    for uname, rows in universes:
        if not rows:
            continue
        for h in (1, 2, 3, 4):
            for rule, key in [('back_inside', f'hyp_exit_back_inside_{h}_pnl'), ('close_against', f'hyp_exit_close_against_{h}_pnl')]:
                s = hyp_summary(rows, key)
                pfs = 'inf' if math.isinf(s['pf']) else f"{s['pf']:.2f}"
                md.append(f"| {uname} | {rule} | {h} | {s['net']:+.4f}% | {s['delta']:+.4f}% | {pfs} | {s['wr']:.1f}% |")
    md.append('')

    md.append('## Leitura fria')
    md.append('')
    good = [r for r in enriched if r['is_good_regime']]
    bad = [r for r in enriched if not r['is_good_regime']]
    sg = summarize(good, 'good')
    sb = summarize(bad, 'bad')
    sg_pf = 'inf' if math.isinf(sg['pf']) else f"{sg['pf']:.2f}"
    sb_pf = 'inf' if math.isinf(sb['pf']) else f"{sb['pf']:.2f}"
    md.append(f"- Regime direcional continua sendo a única pista: GOOD_REGIME n={sg['n']} net={sg['net']:+.4f}% PF={sg_pf}; BAD_REGIME n={sb['n']} net={sb['net']:+.4f}% PF={sb_pf}.")
    md.append('- Porém a amostra é pequena e ainda discovery. Isso não autoriza bot.')
    md.append('- Se uma regra de invalidação rápida melhora o universo GOOD_REGIME sem depender do BAD_REGIME, ela pode virar EXP congelado. Se só melhora removendo RANGING/VOLATILE, o EXP correto é regime-gate, não microgerenciamento.')
    md.append('- Não alterar executor/bot com base neste relatório.')
    md.append('')
    OUT_MD.write_text('\n'.join(md) + '\n')
    print(f'Wrote {OUT_CSV}')
    print(f'Wrote {OUT_MD}')
    print(f'filled={len(enriched)} good_regime={len(good)} bad_regime={len(bad)}')


if __name__ == '__main__':
    main()
