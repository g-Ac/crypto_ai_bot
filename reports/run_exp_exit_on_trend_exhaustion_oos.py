#!/usr/bin/env python3
"""EXP runner: exit-on-trend_exhaustion OOS validation.

Research-only script. Does not modify trading runtime.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import sqlite3
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path('/home/pi/crypto_ai_bot')
DB = ROOT / 'runtime/baseline/bot.db'
CRITERIA = ROOT / 'reports/exp_exit_on_trend_exhaustion_criteria_2026-06-11.md'
PINNED_CRITERIA_HASH = 'b686760bab2c350012c59593d5fd7774a662cbce54014312b8b155b276a50eae'
OUT_CSV = ROOT / 'reports/exp_exit_on_trend_exhaustion_oos_2026-06-11.csv'
OUT_MD = ROOT / 'reports/exp_exit_on_trend_exhaustion_oos_2026-06-11.md'

DISCOVERY_MAX_ID = 156
INTERVAL_MS = 15 * 60 * 1000
BINANCE_URL = 'https://fapi.binance.com/fapi/v1/klines'
UTC = dt.timezone.utc


def assert_criteria_hash() -> None:
    actual = hashlib.sha256(CRITERIA.read_bytes()).hexdigest()
    if actual != PINNED_CRITERIA_HASH:
        raise SystemExit(
            f'CRITERIA HASH MISMATCH\nexpected={PINNED_CRITERIA_HASH}\nactual={actual}\n'
            'Criteria file changed. Open a new EXP or update hash intentionally.'
        )


def parse_trade_ts(s: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(s)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_decision_ts(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)


def fmt_ts(x: dt.datetime) -> str:
    return x.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S')


def ms(x: dt.datetime) -> int:
    return int(x.timestamp() * 1000)


def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cur = start_ms - 2 * INTERVAL_MS
    hard_end = end_ms + 2 * INTERVAL_MS
    while cur <= hard_end:
        url = f'{BINANCE_URL}?symbol={symbol}&interval=15m&startTime={cur}&endTime={hard_end}&limit=1500'
        proc = None
        for attempt in range(1, 5):
            proc = subprocess.run(
                ['curl', '--http1.1', '-sS', '--max-time', '20', url],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                break
            time.sleep(0.5 * attempt)
        if proc is None or proc.returncode != 0:
            stderr = proc.stderr[:300] if proc is not None else 'no process'
            rc = proc.returncode if proc is not None else 'none'
            raise RuntimeError(f'curl failed for {symbol}: rc={rc} stderr={stderr}')
        data = json.loads(proc.stdout)
        if not isinstance(data, list):
            raise RuntimeError(f'Unexpected Binance response for {symbol}: {data!r}')
        if not data:
            break
        for k in data:
            out.append({
                'open_ms': int(k[0]),
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
            })
        nxt = int(data[-1][0]) + INTERVAL_MS
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.08)
    by_open = {k['open_ms']: k for k in out}
    return [by_open[t] for t in sorted(by_open)]


def pct_for_exit(direction: str, entry: float, exit_price: float, cost_bps: float) -> float:
    gross = (exit_price / entry - 1.0) * 100.0 if direction == 'LONG' else (1.0 - exit_price / entry) * 100.0
    return gross - cost_bps / 100.0


def nearest_entry_decision(conn: sqlite3.Connection, trade: sqlite3.Row, entry_est: dt.datetime) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT * FROM momentum_decisions
        WHERE symbol=?
          AND timestamp BETWEEN ? AND ?
          AND outcome='trade'
          AND blocked_by='none'
          AND direction=?
        ORDER BY ABS(strftime('%s', timestamp) - ?)
        LIMIT 1
        """,
        (
            trade['symbol'],
            fmt_ts(entry_est - dt.timedelta(minutes=75)),
            fmt_ts(entry_est + dt.timedelta(minutes=75)),
            trade['direction'],
            int(entry_est.timestamp()),
        ),
    ).fetchall()
    return rows[0] if rows else None


def first_exhaustion(conn: sqlite3.Connection, symbol: str, entry_dec_ts: dt.datetime, exit_ts: dt.datetime) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT * FROM momentum_decisions
        WHERE symbol=?
          AND timestamp > ?
          AND timestamp <= ?
          AND (outcome='trend_exhaustion' OR blocked_by='trend_exhaustion')
        ORDER BY timestamp
        LIMIT 1
        """,
        (symbol, fmt_ts(entry_dec_ts), fmt_ts(exit_ts)),
    ).fetchall()
    return rows[0] if rows else None


def kline_current_next(klines_by_symbol: dict[str, dict[int, dict[str, Any]]], symbol: str, ts: dt.datetime) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    open_ms = (ms(ts) // INTERVAL_MS) * INTERVAL_MS
    d = klines_by_symbol[symbol]
    return d.get(open_ms), d.get(open_ms + INTERVAL_MS)


def build_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    trades = conn.execute('SELECT * FROM momentum_trades ORDER BY id').fetchall()
    if not trades:
        return []
    min_ts = None
    max_ts = None
    for t in trades:
        exit_ts = parse_trade_ts(t['timestamp'])
        entry_est = exit_ts - dt.timedelta(minutes=15 * int(t['duration_candles']))
        min_ts = entry_est if min_ts is None else min(min_ts, entry_est)
        max_ts = exit_ts if max_ts is None else max(max_ts, exit_ts)
    assert min_ts is not None and max_ts is not None

    symbols = sorted({t['symbol'] for t in trades})
    klines_by_symbol = {s: {k['open_ms']: k for k in fetch_klines(s, ms(min_ts), ms(max_ts))} for s in symbols}

    rows: list[dict[str, Any]] = []
    for t in trades:
        exit_ts = parse_trade_ts(t['timestamp'])
        entry_est = exit_ts - dt.timedelta(minutes=15 * int(t['duration_candles']))
        entry_dec = nearest_entry_decision(conn, t, entry_est)
        entry_dec_ts = parse_decision_ts(entry_dec['timestamp']) if entry_dec is not None else None
        exh = first_exhaustion(conn, t['symbol'], entry_dec_ts, exit_ts) if entry_dec_ts else None
        exh_ts = parse_decision_ts(exh['timestamp']) if exh is not None else None
        cur = nxt = None
        if exh_ts is not None:
            cur, nxt = kline_current_next(klines_by_symbol, t['symbol'], exh_ts)
        cost_bps = float(t['total_cost_bps'] if t['total_cost_bps'] is not None else 10.0)
        next_open = float(nxt['open']) if nxt else None
        actual = float(t['net_pnl_pct'])
        sim_exit_net = pct_for_exit(t['direction'], float(t['entry_price']), next_open, cost_bps) if next_open is not None else actual
        age = ''
        if entry_dec_ts and exh_ts:
            age = int(round((exh_ts - entry_dec_ts).total_seconds() / (15 * 60)))
        rows.append({
            'id': int(t['id']),
            'sample': 'discovery' if int(t['id']) <= DISCOVERY_MAX_ID else 'oos',
            'symbol': t['symbol'],
            'direction': t['direction'],
            'symbol_direction': f"{t['symbol']} {t['direction']}",
            'regime': t['regime'],
            'exit_reason': t['exit_reason'],
            'entry_price': float(t['entry_price']),
            'actual_exit_price': float(t['exit_price']),
            'actual_net_pct': actual,
            'entry_est_ts': fmt_ts(entry_est),
            'actual_exit_ts': fmt_ts(exit_ts),
            'entry_decision_ts': fmt_ts(entry_dec_ts) if entry_dec_ts else '',
            'has_exhaustion': bool(exh_ts and next_open is not None),
            'exhaustion_ts': fmt_ts(exh_ts) if exh_ts else '',
            'age_candles': age,
            'next_open_price': next_open,
            'sim_exit_net_pct': sim_exit_net,
            'delta_exit_pct': sim_exit_net - actual,
            'h1_applies': bool(exh_ts and next_open is not None and t['regime'] == 'WEAK_TREND'),
            'h2_applies': bool(exh_ts and next_open is not None and age != '' and int(age) <= 2),
        })
    return rows


def eval_policy(rows: list[dict[str, Any]], name: str, predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    actual = sum(r['actual_net_pct'] for r in rows)
    sim = 0.0
    changed_rows = []
    for r in rows:
        if predicate(r):
            changed_rows.append(r)
            sim += r['sim_exit_net_pct']
        else:
            sim += r['actual_net_pct']
    improved = [r for r in changed_rows if r['delta_exit_pct'] > 0]
    worsened = [r for r in changed_rows if r['delta_exit_pct'] < 0]
    positive_delta = sum(r['delta_exit_pct'] for r in improved)
    max_pos_share = None
    if positive_delta > 0 and improved:
        max_pos_share = max(r['delta_exit_pct'] for r in improved) / positive_delta
    group_pos: dict[str, float] = defaultdict(float)
    for r in improved:
        group_pos[r['symbol_direction']] += r['delta_exit_pct']
    max_group_share = None
    if positive_delta > 0 and len(group_pos) >= 2:
        max_group_share = max(group_pos.values()) / positive_delta
    max_damage = min((r['delta_exit_pct'] for r in changed_rows), default=0.0)
    verdict_reasons = []
    verdict = 'GO'
    if len(rows) < 30:
        verdict = 'DADO INSUFICIENTE'; verdict_reasons.append('menos de 30 trades OOS')
    if len(changed_rows) < 10:
        verdict = 'DADO INSUFICIENTE'; verdict_reasons.append('menos de 10 trades OOS alterados')
    if any(r['has_exhaustion'] and r['next_open_price'] is None for r in changed_rows):
        verdict = 'DADO INSUFICIENTE'; verdict_reasons.append('preço ausente em trade alterado')
    if verdict != 'DADO INSUFICIENTE':
        if sim - actual <= 0:
            verdict = 'NO-GO'; verdict_reasons.append('delta total OOS <= 0')
        if len(worsened) > len(improved):
            verdict = 'NO-GO'; verdict_reasons.append('piora mais trades do que melhora')
        if max_damage <= -1.25:
            verdict = 'NO-GO'; verdict_reasons.append('dano individual excede -1.25%')
        if max_pos_share is not None and max_pos_share > 0.50:
            verdict = 'NO-GO'; verdict_reasons.append('1 trade responde por mais de 50% do delta positivo')
        if max_group_share is not None and max_group_share > 0.80:
            verdict = 'NO-GO'; verdict_reasons.append('1 grupo symbol_direction responde por mais de 80% do delta positivo')
        if verdict == 'GO':
            if sim - actual < 2.0:
                verdict = 'NO-GO'; verdict_reasons.append('delta total OOS < +2.0pp')
            if len(improved) < len(worsened):
                verdict = 'NO-GO'; verdict_reasons.append('improved < worsened')
    return {
        'name': name,
        'rows': rows,
        'changed_rows': changed_rows,
        'actual': actual,
        'sim': sim,
        'delta': sim - actual,
        'changed': len(changed_rows),
        'improved': len(improved),
        'worsened': len(worsened),
        'max_damage': max_damage,
        'max_pos_share': max_pos_share,
        'max_group_share': max_group_share,
        'verdict': verdict,
        'reasons': verdict_reasons,
    }


def append_policy_md(md: list[str], result: dict[str, Any]) -> None:
    md.append(f"### {result['name']}")
    md.append('')
    md.append(f"- verdict: {result['verdict']}")
    md.append(f"- reasons: {', '.join(result['reasons']) if result['reasons'] else 'passou todos os critérios'}")
    md.append(f"- OOS trades: {len(result['rows'])}")
    md.append(f"- changed: {result['changed']}")
    md.append(f"- improved: {result['improved']}")
    md.append(f"- worsened: {result['worsened']}")
    md.append(f"- actual_net: {result['actual']:+.4f}%")
    md.append(f"- sim_net: {result['sim']:+.4f}%")
    md.append(f"- delta: {result['delta']:+.4f}%")
    md.append(f"- max_damage: {result['max_damage']:+.4f}%")
    if result['max_pos_share'] is not None:
        md.append(f"- max_positive_trade_share: {result['max_pos_share']*100:.1f}%")
    if result['max_group_share'] is not None:
        md.append(f"- max_positive_symbol_direction_share: {result['max_group_share']*100:.1f}%")
    md.append('')
    md.append('Maiores melhorias:')
    for r in sorted(result['changed_rows'], key=lambda x: x['delta_exit_pct'], reverse=True)[:10]:
        md.append(f"- #{r['id']} {r['symbol']} {r['direction']} {r['exit_reason']}: actual={r['actual_net_pct']:+.3f}% sim={r['sim_exit_net_pct']:+.3f}% delta={r['delta_exit_pct']:+.3f}%")
    md.append('')
    md.append('Maiores danos:')
    for r in sorted(result['changed_rows'], key=lambda x: x['delta_exit_pct'])[:10]:
        md.append(f"- #{r['id']} {r['symbol']} {r['direction']} {r['exit_reason']}: actual={r['actual_net_pct']:+.3f}% sim={r['sim_exit_net_pct']:+.3f}% delta={r['delta_exit_pct']:+.3f}%")
    md.append('')


def main() -> None:
    assert_criteria_hash()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = build_rows(conn)
    with OUT_CSV.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    discovery = [r for r in rows if r['sample'] == 'discovery']
    oos = [r for r in rows if r['sample'] == 'oos']

    h1_discovery = eval_policy(discovery, 'H1 discovery — WEAK_TREND only', lambda r: r['h1_applies'])
    h2_discovery = eval_policy(discovery, 'H2 discovery — age <= 2 candles', lambda r: r['h2_applies'])
    h1_oos = eval_policy(oos, 'H1 OOS — WEAK_TREND only', lambda r: r['h1_applies'])
    h2_oos = eval_policy(oos, 'H2 OOS — age <= 2 candles', lambda r: r['h2_applies'])

    md: list[str] = []
    md.append('# EXP result: exit-on-trend_exhaustion OOS validation')
    md.append('')
    md.append(f'- criteria: `{CRITERIA}`')
    md.append(f'- pinned criteria hash: `{PINNED_CRITERIA_HASH}`')
    md.append(f'- csv: `{OUT_CSV}`')
    md.append('')
    md.append('## Amostra')
    md.append('')
    md.append(f'- total trades: {len(rows)}')
    md.append(f'- discovery trades (`id <= {DISCOVERY_MAX_ID}`): {len(discovery)}')
    md.append(f'- OOS trades (`id > {DISCOVERY_MAX_ID}`): {len(oos)}')
    md.append(f'- OOS with any exhaustion price: {sum(1 for r in oos if r["has_exhaustion"])}')
    md.append('')
    md.append('Discovery é contexto apenas; verdict vem de OOS.')
    md.append('')
    md.append('## Discovery / in-sample context')
    md.append('')
    append_policy_md(md, h1_discovery)
    append_policy_md(md, h2_discovery)
    md.append('## OOS verdict')
    md.append('')
    append_policy_md(md, h1_oos)
    append_policy_md(md, h2_oos)
    md.append('## Leitura fria')
    md.append('')
    if len(oos) < 30:
        md.append('OOS ainda é pequeno demais. Pelo critério congelado, verdict obrigatório é DADO INSUFICIENTE.')
    md.append('Não alterar executor/bot com base neste resultado. Rodar novamente quando houver pelo menos 30 trades OOS e 10 trades alterados por hipótese.')
    OUT_MD.write_text('\n'.join(md) + '\n')
    print(f'Wrote {OUT_CSV}')
    print(f'Wrote {OUT_MD}')
    print(f'OOS trades={len(oos)} H1={h1_oos["verdict"]} H2={h2_oos["verdict"]}')


if __name__ == '__main__':
    main()
