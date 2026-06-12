#!/usr/bin/env python3
"""Frozen EXP runner: regime-gated compression breakout shadow.

Research-only. Does not modify trading runtime, state files, config, or bot code.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path('/home/pi/crypto_ai_bot')
sys.path.insert(0, str(ROOT))

from engines_5m.breakout import BreakoutEngine5m  # noqa: E402
from indicators_5m import add_indicators_5m  # noqa: E402
from risk_calculator_1m import calculate_viability  # noqa: E402

DB = ROOT / 'runtime/baseline/bot.db'
CRITERIA = ROOT / 'reports/exp_breakout_regime_gated_criteria_2026-06-12.md'
PINNED_CRITERIA_HASH = 'e5d942591a7f86cdb3d58e66a0e669a87f66fafe8450a47576318b7a34edbcbc'
OUT_CSV = ROOT / 'reports/exp_breakout_regime_gated_shadow_2026-06-12.csv'
OUT_MD = ROOT / 'reports/exp_breakout_regime_gated_shadow_2026-06-12.md'

SYMBOLS = ('BTCUSDT', 'ETHUSDT')
DISCOVERY_START = dt.datetime(2026, 5, 13, tzinfo=dt.timezone.utc)
OOS_START = dt.datetime(2026, 6, 12, tzinfo=dt.timezone.utc)
INTERVAL_MS = 5 * 60 * 1000
FEE_ROUNDTRIP_PCT = 0.10
TIMEOUT_CANDLES = 60
GOOD_REGIMES = {'TRENDING', 'WEAK_TREND'}
BINANCE_FAPI = 'https://fapi.binance.com/fapi/v1/klines'
UTC = dt.timezone.utc


def assert_criteria_hash() -> None:
    actual = hashlib.sha256(CRITERIA.read_bytes()).hexdigest()
    if actual != PINNED_CRITERIA_HASH:
        raise SystemExit(
            f'CRITERIA HASH MISMATCH\nexpected={PINNED_CRITERIA_HASH}\nactual={actual}\n'
            'Criteria file changed. Open a new EXP or update hash intentionally.'
        )


def utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def ms(x: dt.datetime) -> int:
    return int(x.timestamp() * 1000)


def fmt_ts_ms(x: int) -> str:
    return dt.datetime.fromtimestamp(x / 1000, UTC).strftime('%Y-%m-%d %H:%M:%S')


def parse_decision_ts(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)


def fetch_5m_futures(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
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
            rc = proc.returncode if proc else 'none'
            stderr = proc.stderr[:300] if proc else 'no process'
            raise RuntimeError(f'curl failed for {symbol}: rc={rc} stderr={stderr}')
        data = json.loads(proc.stdout)
        if not isinstance(data, list):
            raise RuntimeError(f'Unexpected Binance response for {symbol}: {data!r}')
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
    for col in ['open','high','low','close','volume']:
        df[col] = df[col].astype(float)
    df['time'] = df['time'].astype(np.int64)
    df['timestamp'] = pd.to_datetime(df['time'], unit='ms', utc=True)
    return df


def get_regime_lookup(conn: sqlite3.Connection, symbol: str, start: dt.datetime, end: dt.datetime) -> list[tuple[int, str]]:
    rows = conn.execute(
        """
        SELECT timestamp, regime
        FROM momentum_decisions
        WHERE symbol=? AND timestamp BETWEEN ? AND ? AND regime IS NOT NULL AND regime != ''
        ORDER BY timestamp
        """,
        (symbol, start.strftime('%Y-%m-%d %H:%M:%S'), end.strftime('%Y-%m-%d %H:%M:%S')),
    ).fetchall()
    out = []
    for ts, reg in rows:
        try:
            out.append((int(parse_decision_ts(ts).timestamp()), reg))
        except Exception:
            pass
    return out


def nearest_regime(lookup: list[tuple[int, str]], signal_ms: int) -> tuple[str, bool]:
    if not lookup:
        return 'UNKNOWN', False
    s = signal_ms // 1000
    best = min(lookup, key=lambda x: abs(x[0] - s))
    ok = abs(best[0] - s) <= 45 * 60
    return (best[1] if ok else 'UNKNOWN'), ok


def calc_pnl(direction: str, entry: float, exit_price: float) -> float:
    gross = (exit_price / entry - 1.0) * 100.0 if direction == 'LONG' else (1.0 - exit_price / entry) * 100.0
    return gross - FEE_ROUNDTRIP_PCT


def profit_factor(pnls: list[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p <= 0))
    if losses == 0:
        return math.inf if gains > 0 else 0.0
    return gains / losses


def simulate_exit(df: pd.DataFrame, entry_i: int, sig: Any) -> dict[str, Any] | None:
    if entry_i >= len(df):
        return None
    entry = float(df.iloc[entry_i]['open'])
    sl = float(sig.sl_price)
    tp1 = float(sig.tp1_price)
    tp2 = float(sig.tp2_price)
    direction = sig.direction.value
    viability = calculate_viability(sig.symbol, entry, sl, tp1, 20.0, 1)
    if not viability.viable:
        return {'status': 'rejected', 'reject_reason': viability.reason, 'entry_price': entry, 'sl_price': sl, 'tp1_price': tp1, 'tp2_price': tp2}

    tp1_hit = False
    tp1_exit_price = None
    stop = sl
    mfe = 0.0
    mae = 0.0
    exit_reason = None
    exit_price = None
    duration = 0
    for j in range(entry_i, min(len(df), entry_i + TIMEOUT_CANDLES)):
        duration += 1
        c = df.iloc[j]
        high = float(c['high']); low = float(c['low']); close = float(c['close'])
        if direction == 'LONG':
            mfe = max(mfe, (high - entry) / entry * 100.0)
            mae = max(mae, (entry - low) / entry * 100.0)
            if low <= stop:
                exit_reason = 'sl_hit' if not tp1_hit else 'sl_breakeven'
                exit_price = stop if not tp1_hit else 0.5 * tp1_exit_price + 0.5 * entry
                break
            if not tp1_hit and high >= tp1:
                tp1_hit = True; tp1_exit_price = tp1; stop = entry
                if high >= tp2:
                    exit_reason = 'tp2_hit'; exit_price = 0.5 * tp1 + 0.5 * tp2; break
            elif tp1_hit and high >= tp2:
                exit_reason = 'tp2_hit'; exit_price = 0.5 * tp1_exit_price + 0.5 * tp2; break
        else:
            mfe = max(mfe, (entry - low) / entry * 100.0)
            mae = max(mae, (high - entry) / entry * 100.0)
            if high >= stop:
                exit_reason = 'sl_hit' if not tp1_hit else 'sl_breakeven'
                exit_price = stop if not tp1_hit else 0.5 * tp1_exit_price + 0.5 * entry
                break
            if not tp1_hit and low <= tp1:
                tp1_hit = True; tp1_exit_price = tp1; stop = entry
                if low <= tp2:
                    exit_reason = 'tp2_hit'; exit_price = 0.5 * tp1 + 0.5 * tp2; break
            elif tp1_hit and low <= tp2:
                exit_reason = 'tp2_hit'; exit_price = 0.5 * tp1_exit_price + 0.5 * tp2; break
        if duration >= TIMEOUT_CANDLES:
            exit_reason = 'timeout'; exit_price = close; break
    if exit_reason is None:
        exit_reason = 'data_end'; exit_price = float(df.iloc[min(len(df)-1, entry_i+TIMEOUT_CANDLES-1)]['close'])
    pnl = calc_pnl(direction, entry, float(exit_price))
    return {
        'status': 'filled', 'reject_reason': '', 'entry_price': entry, 'sl_price': sl, 'tp1_price': tp1, 'tp2_price': tp2,
        'exit_price': float(exit_price), 'exit_reason': exit_reason, 'pnl_pct': pnl, 'duration_candles': duration,
        'mfe_pct': mfe, 'mae_pct': mae, 'tp1_hit': tp1_hit, 'tp2_hit': exit_reason == 'tp2_hit',
        'false_breakout': (not tp1_hit) and exit_reason in {'sl_hit','timeout','data_end'},
    }


def sample_for_ts(signal_ms: int) -> str:
    return 'discovery' if dt.datetime.fromtimestamp(signal_ms/1000, UTC) < OOS_START else 'oos'


def run_symbol(conn: sqlite3.Connection, symbol: str, start: dt.datetime, end: dt.datetime) -> tuple[list[dict[str, Any]], Counter]:
    raw = fetch_5m_futures(symbol, ms(start), ms(end))
    if raw.empty:
        return [], Counter()
    df = add_indicators_5m(raw.copy())
    engine = BreakoutEngine5m()
    regimes = get_regime_lookup(conn, symbol, start - dt.timedelta(hours=2), end + dt.timedelta(hours=2))
    rows: list[dict[str, Any]] = []
    counts = Counter()
    open_until = -1
    pending: tuple[int, Any, str, bool] | None = None

    for i in range(engine._MIN_CANDLES, len(df)):
        if pending is not None and i > open_until:
            sig_i, sig, regime, regime_present = pending
            sim = simulate_exit(df, i, sig)
            if sim is not None:
                meta = sig.metadata or {}
                rec = {
                    'sample': sample_for_ts(int(df.iloc[sig_i]['time'])),
                    'symbol': symbol,
                    'signal_ts': fmt_ts_ms(int(df.iloc[sig_i]['time'])),
                    'entry_ts': fmt_ts_ms(int(df.iloc[i]['time'])),
                    'direction': sig.direction.value,
                    'symbol_direction': f'{symbol} {sig.direction.value}',
                    'regime': regime,
                    'regime_present': regime_present,
                    'eligible_regime': regime in GOOD_REGIMES,
                    'lookback': meta.get('lookback'),
                    'range_pct': meta.get('range_pct'),
                    'bb_bandwidth': meta.get('bb_bandwidth'),
                    'vol_ratio': meta.get('vol_ratio'),
                    'body_ratio': meta.get('body_ratio'),
                    **sim,
                }
                if sim['status'] == 'filled':
                    exit_i = min(len(df)-1, i + int(sim['duration_candles']) - 1)
                    rec['exit_ts'] = fmt_ts_ms(int(df.iloc[exit_i]['time']))
                    open_until = exit_i
                rows.append(rec)
            pending = None

        if i <= open_until or pending is not None:
            continue
        visible = df.iloc[max(0, i-240):i+1].copy()
        sig = engine.analyze(symbol, visible)
        if sig is None or not sig.valid:
            continue
        counts[f'{sample_for_ts(int(df.iloc[i]["time"]))}_raw_signal'] += 1
        regime, present = nearest_regime(regimes, int(df.iloc[i]['time']))
        if regime not in GOOD_REGIMES:
            rows.append({
                'sample': sample_for_ts(int(df.iloc[i]['time'])), 'symbol': symbol, 'signal_ts': fmt_ts_ms(int(df.iloc[i]['time'])),
                'entry_ts': '', 'exit_ts': '', 'direction': sig.direction.value, 'symbol_direction': f'{symbol} {sig.direction.value}',
                'regime': regime, 'regime_present': present, 'eligible_regime': False, 'status': 'blocked_by_regime',
                'reject_reason': 'regime_not_directional', 'pnl_pct': '', 'exit_reason': '',
            })
            counts[f'{sample_for_ts(int(df.iloc[i]["time"]))}_blocked_by_regime'] += 1
            continue
        counts[f'{sample_for_ts(int(df.iloc[i]["time"]))}_eligible_signal'] += 1
        pending = (i, sig, regime, present)
    return rows, counts


def eval_sample(rows: list[dict[str, Any]], sample: str) -> dict[str, Any]:
    sample_rows = [r for r in rows if r.get('sample') == sample]
    filled = [r for r in sample_rows if r.get('status') == 'filled']
    pnls = [float(r['pnl_pct']) for r in filled]
    wins = [p for p in pnls if p > 0]
    positive = sum(wins)
    max_trade_share = max(wins) / positive if wins and positive > 0 else None
    day_pos: dict[str, float] = defaultdict(float)
    group_pos: dict[str, float] = defaultdict(float)
    for r in filled:
        p = float(r['pnl_pct'])
        if p > 0:
            day_pos[str(r['entry_ts'])[:10]] += p
            group_pos[str(r['symbol_direction'])] += p
    max_day_share = max(day_pos.values()) / positive if len(day_pos) >= 1 and positive > 0 else None
    max_group_share = max(group_pos.values()) / positive if len(group_pos) >= 2 and positive > 0 else None
    max_damage = min(pnls, default=0.0)
    false_rate = sum(1 for r in filled if r.get('false_breakout')) / len(filled) * 100 if filled else 0.0
    tp1_rate = sum(1 for r in filled if r.get('tp1_hit')) / len(filled) * 100 if filled else 0.0
    tp2_rate = sum(1 for r in filled if r.get('tp2_hit')) / len(filled) * 100 if filled else 0.0
    timeout_rate = sum(1 for r in filled if r.get('exit_reason') == 'timeout') / len(filled) * 100 if filled else 0.0
    verdict = 'GO'
    reasons: list[str] = []
    if sample == 'oos':
        if len(filled) < 30:
            verdict = 'DADO INSUFICIENTE'; reasons.append('menos de 30 trades shadow OOS preenchidos')
        if len({str(r['entry_ts'])[:10] for r in filled}) <= 1 and filled:
            verdict = 'DADO INSUFICIENTE'; reasons.append('trades OOS concentrados em apenas 1 dia')
        if any(r.get('regime') == 'UNKNOWN' or not r.get('regime_present') for r in filled):
            verdict = 'DADO INSUFICIENTE'; reasons.append('regime ausente em trade elegível')
        if verdict != 'DADO INSUFICIENTE':
            if sum(pnls) <= 0:
                verdict = 'NO-GO'; reasons.append('PnL net total OOS <= 0')
            if profit_factor(pnls) < 1.20:
                verdict = 'NO-GO'; reasons.append('PF net OOS < 1.20')
            if (len(wins) / len(filled) * 100 if filled else 0.0) < 40:
                verdict = 'NO-GO'; reasons.append('winrate OOS < 40%')
            if false_rate > 60:
                verdict = 'NO-GO'; reasons.append('false breakout rate OOS > 60%')
            if max_damage <= -1.25:
                verdict = 'NO-GO'; reasons.append('dano individual <= -1.25%')
            if max_trade_share is not None and max_trade_share > 0.50:
                verdict = 'NO-GO'; reasons.append('maior trade positivo > 50% do lucro positivo')
            if max_day_share is not None and max_day_share > 0.60:
                verdict = 'NO-GO'; reasons.append('maior dia > 60% do lucro positivo')
            if max_group_share is not None and max_group_share > 0.80:
                verdict = 'NO-GO'; reasons.append('maior symbol_direction > 80% do lucro positivo')
    else:
        verdict = 'DISCOVERY_ONLY'
        reasons.append('discovery/in-sample não decide GO')
    return {
        'sample': sample, 'rows': sample_rows, 'filled': filled, 'blocked': [r for r in sample_rows if r.get('status') == 'blocked_by_regime'],
        'rejected': [r for r in sample_rows if r.get('status') == 'rejected'], 'net': sum(pnls),
        'avg': float(np.mean(pnls)) if pnls else 0.0, 'median': float(np.median(pnls)) if pnls else 0.0,
        'wr': len(wins) / len(filled) * 100 if filled else 0.0, 'pf': profit_factor(pnls),
        'false_rate': false_rate, 'tp1_rate': tp1_rate, 'tp2_rate': tp2_rate, 'timeout_rate': timeout_rate,
        'max_damage': max_damage, 'max_trade_share': max_trade_share, 'max_day_share': max_day_share, 'max_group_share': max_group_share,
        'verdict': verdict, 'reasons': reasons,
    }


def append_eval(md: list[str], ev: dict[str, Any]) -> None:
    md.append(f"### {ev['sample']}")
    md.append('')
    pf_s = 'inf' if math.isinf(ev['pf']) else f"{ev['pf']:.2f}"
    md.extend([
        f"- verdict: {ev['verdict']}",
        f"- reasons: {', '.join(ev['reasons']) if ev['reasons'] else 'passou todos os critérios'}",
        f"- raw rows/signals recorded: {len(ev['rows'])}",
        f"- filled trades: {len(ev['filled'])}",
        f"- blocked_by_regime: {len(ev['blocked'])}",
        f"- rejected_by_risk: {len(ev['rejected'])}",
        f"- net: {ev['net']:+.4f}% | avg: {ev['avg']:+.4f}% | median: {ev['median']:+.4f}%",
        f"- WR: {ev['wr']:.1f}% | PF: {pf_s}",
        f"- false_breakout: {ev['false_rate']:.1f}% | TP1: {ev['tp1_rate']:.1f}% | TP2: {ev['tp2_rate']:.1f}% | timeout: {ev['timeout_rate']:.1f}%",
        f"- max_damage: {ev['max_damage']:+.4f}%",
    ])
    if ev['max_trade_share'] is not None:
        md.append(f"- max_positive_trade_share: {ev['max_trade_share']*100:.1f}%")
    if ev['max_day_share'] is not None:
        md.append(f"- max_positive_day_share: {ev['max_day_share']*100:.1f}%")
    if ev['max_group_share'] is not None:
        md.append(f"- max_positive_symbol_direction_share: {ev['max_group_share']*100:.1f}%")
    md.append('')
    for key in ('symbol','regime','direction','exit_reason'):
        groups: dict[str, list[float]] = defaultdict(list)
        for r in ev['filled']:
            groups[str(r.get(key,''))].append(float(r['pnl_pct']))
        if groups:
            md.append(f'Por {key}:')
            for g, xs in sorted(groups.items()):
                pfv = profit_factor(xs)
                pfs = 'inf' if math.isinf(pfv) else f'{pfv:.2f}'
                md.append(f"- {g}: n={len(xs)} net={sum(xs):+.4f}% avg={np.mean(xs):+.4f}% PF={pfs}")
            md.append('')
    md.append('Maiores ganhos:')
    for r in sorted(ev['filled'], key=lambda x: float(x['pnl_pct']), reverse=True)[:10]:
        md.append(f"- {r['entry_ts']} {r['symbol']} {r['direction']} {r['regime']} {r['exit_reason']}: {float(r['pnl_pct']):+.4f}%")
    md.append('')
    md.append('Maiores danos:')
    for r in sorted(ev['filled'], key=lambda x: float(x['pnl_pct']))[:10]:
        md.append(f"- {r['entry_ts']} {r['symbol']} {r['direction']} {r['regime']} {r['exit_reason']}: {float(r['pnl_pct']):+.4f}%")
    md.append('')


def main() -> None:
    assert_criteria_hash()
    end = utc_now()
    start = DISCOVERY_START
    conn = sqlite3.connect(DB)
    all_rows: list[dict[str, Any]] = []
    counts = Counter()
    for sym in SYMBOLS:
        rows, c = run_symbol(conn, sym, start, end)
        all_rows.extend(rows)
        counts.update(c)

    fieldnames = sorted({k for r in all_rows for k in r.keys()})
    with OUT_CSV.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(all_rows)

    disc = eval_sample(all_rows, 'discovery')
    oos = eval_sample(all_rows, 'oos')
    md: list[str] = []
    md.append('# EXP result: breakout_compression regime-gated shadow')
    md.append('')
    md.append(f'- criteria: `{CRITERIA}`')
    md.append(f'- pinned criteria hash: `{PINNED_CRITERIA_HASH}`')
    md.append(f'- csv: `{OUT_CSV}`')
    md.append(f'- run_end_utc: {end.isoformat()}')
    md.append('')
    md.append('## Signal counts')
    md.append('')
    for k in sorted(counts):
        md.append(f'- {k}: {counts[k]}')
    md.append('')
    md.append('## Results')
    md.append('')
    append_eval(md, disc)
    append_eval(md, oos)
    md.append('## Leitura fria')
    md.append('')
    if oos['verdict'] == 'DADO INSUFICIENTE':
        md.append('OOS ainda é pequeno demais. Pelo critério congelado, verdict obrigatório é DADO INSUFICIENTE.')
    md.append('Não alterar executor/bot com base neste resultado. Rodar novamente quando houver pelo menos 30 trades shadow OOS preenchidos.')
    md.append('')
    OUT_MD.write_text('\n'.join(md) + '\n')
    print(f'Wrote {OUT_CSV}')
    print(f'Wrote {OUT_MD}')
    print(f"discovery_filled={len(disc['filled'])} oos_filled={len(oos['filled'])} oos_verdict={oos['verdict']}")


if __name__ == '__main__':
    main()
