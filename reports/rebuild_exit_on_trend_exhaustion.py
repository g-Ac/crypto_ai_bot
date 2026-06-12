#!/usr/bin/env python3
"""Rebuild exit-on-trend_exhaustion simulation from real DB + Binance 15m klines.

Descriptive research artifact only. Does not import or modify bot runtime code.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import sqlite3
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path('/home/pi/crypto_ai_bot')
DB = ROOT / 'runtime/baseline/bot.db'
OUT_CSV = ROOT / 'reports/exit_on_trend_exhaustion_sim_2026-06-11_rebuilt.csv'
OUT_MD = ROOT / 'reports/exit_on_trend_exhaustion_sim_2026-06-11_rebuilt.md'
START_ID = 1
END_ID = 156
INTERVAL_MS = 15 * 60 * 1000
BINANCE_URL = 'https://fapi.binance.com/fapi/v1/klines'

UTC = dt.timezone.utc


def parse_trade_ts(s: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(s)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_decision_ts(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)


def fmt_decision_ts(x: dt.datetime) -> str:
    return x.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S')


def ms(x: dt.datetime) -> int:
    return int(x.timestamp() * 1000)


def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    """Fetch paginated Binance futures klines with curl subprocess.

    Uses sequential curl rather than Python HTTP libraries because this Pi/Hermes
    setup has previously seen heap corruption in tool-side urllib loops.
    """
    out: list[dict[str, Any]] = []
    cur = start_ms - (2 * INTERVAL_MS)
    hard_end = end_ms + (2 * INTERVAL_MS)
    while cur <= hard_end:
        url = f'{BINANCE_URL}?symbol={symbol}&interval=15m&startTime={cur}&endTime={hard_end}&limit=1500'
        proc = subprocess.run(
            ['curl', '-sS', '--max-time', '20', url],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f'curl failed for {symbol}: rc={proc.returncode} stderr={proc.stderr[:300]}')
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f'JSON parse failed for {symbol}: {proc.stdout[:300]}') from exc
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
        last_open = int(data[-1][0])
        nxt = last_open + INTERVAL_MS
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.08)
    # de-dupe by open_ms
    by_open = {k['open_ms']: k for k in out}
    return [by_open[t] for t in sorted(by_open)]


def pct_for_exit(direction: str, entry: float, exit_price: float, cost_bps: float) -> float:
    if direction == 'LONG':
        gross = (exit_price / entry - 1.0) * 100.0
    else:
        gross = (1.0 - exit_price / entry) * 100.0
    return gross - (cost_bps / 100.0)


def nearest_entry_decision(conn: sqlite3.Connection, trade: sqlite3.Row, entry_est: dt.datetime) -> sqlite3.Row | None:
    start = fmt_decision_ts(entry_est - dt.timedelta(minutes=75))
    end = fmt_decision_ts(entry_est + dt.timedelta(minutes=75))
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
        (trade['symbol'], start, end, trade['direction'], int(entry_est.timestamp())),
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
        (symbol, fmt_decision_ts(entry_dec_ts), fmt_decision_ts(exit_ts)),
    ).fetchall()
    return rows[0] if rows else None


def kline_at_or_after(klines_by_symbol: dict[str, dict[int, dict[str, Any]]], symbol: str, ts: dt.datetime) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    # decision timestamps are aligned to 15m open in DB. Key exactly first; fallback to floor.
    open_ms = (ms(ts) // INTERVAL_MS) * INTERVAL_MS
    d = klines_by_symbol[symbol]
    cur = d.get(open_ms)
    nxt = d.get(open_ms + INTERVAL_MS)
    return cur, nxt


def summarize(rows: list[dict[str, Any]], price_col: str, sim_col: str) -> dict[str, Any]:
    actual = sum(r['actual_net_pct'] for r in rows)
    sim = sum(r[sim_col] for r in rows)
    changed = [r for r in rows if r['has_exhaustion'] and r[price_col] is not None]
    improved = [r for r in changed if r[sim_col] > r['actual_net_pct']]
    worsened = [r for r in changed if r[sim_col] < r['actual_net_pct']]
    return {
        'changed': len(changed),
        'improved': len(improved),
        'worsened': len(worsened),
        'actual': actual,
        'sim': sim,
        'delta': sim - actual,
    }


def group_summary(rows: list[dict[str, Any]], group_key: str, sim_col: str) -> list[tuple[str, int, int, float, float, float]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r[group_key])].append(r)
    out = []
    for key in sorted(groups):
        arr = groups[key]
        actual = sum(r['actual_net_pct'] for r in arr)
        sim = sum(r[sim_col] for r in arr)
        changed = sum(1 for r in arr if r['has_exhaustion'])
        out.append((key, len(arr), changed, actual, sim, sim - actual))
    return out


def apply_policy(rows: list[dict[str, Any]], name: str, predicate) -> dict[str, Any]:
    actual = sum(r['actual_net_pct'] for r in rows)
    sim = 0.0
    changed = improved = worsened = 0
    changed_rows = []
    for r in rows:
        use_exit = bool(r['has_exhaustion'] and r['next_open_price'] is not None and predicate(r))
        if use_exit:
            changed += 1
            new = r['sim_next_open_net_pct']
            changed_rows.append({**r, 'policy_delta': new - r['actual_net_pct']})
            if new > r['actual_net_pct']:
                improved += 1
            elif new < r['actual_net_pct']:
                worsened += 1
            sim += new
        else:
            sim += r['actual_net_pct']
    return {
        'name': name,
        'changed': changed,
        'improved': improved,
        'worsened': worsened,
        'actual': actual,
        'sim': sim,
        'delta': sim - actual,
        'rows': changed_rows,
    }


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    trades = conn.execute(
        'SELECT * FROM momentum_trades WHERE id BETWEEN ? AND ? ORDER BY id',
        (START_ID, END_ID),
    ).fetchall()
    if len(trades) != 156:
        raise RuntimeError(f'Expected 156 trades, got {len(trades)}')

    entry_exit: dict[int, tuple[dt.datetime, dt.datetime]] = {}
    min_ts = None
    max_ts = None
    symbols = sorted({t['symbol'] for t in trades})
    for t in trades:
        exit_ts = parse_trade_ts(t['timestamp'])
        entry_est = exit_ts - dt.timedelta(minutes=15 * int(t['duration_candles']))
        entry_exit[int(t['id'])] = (entry_est, exit_ts)
        min_ts = entry_est if min_ts is None else min(min_ts, entry_est)
        max_ts = exit_ts if max_ts is None else max(max_ts, exit_ts)

    assert min_ts is not None and max_ts is not None

    klines_by_symbol: dict[str, dict[int, dict[str, Any]]] = {}
    kline_counts: dict[str, int] = {}
    for symbol in symbols:
        klines = fetch_klines(symbol, ms(min_ts), ms(max_ts))
        kline_counts[symbol] = len(klines)
        klines_by_symbol[symbol] = {int(k['open_ms']): k for k in klines}

    rows: list[dict[str, Any]] = []
    missing_entry_dec = 0
    missing_price = 0
    for t in trades:
        tid = int(t['id'])
        entry_est, exit_ts = entry_exit[tid]
        entry_dec = nearest_entry_decision(conn, t, entry_est)
        if entry_dec is None:
            missing_entry_dec += 1
            entry_dec_ts = None
            exh = None
        else:
            entry_dec_ts = parse_decision_ts(entry_dec['timestamp'])
            exh = first_exhaustion(conn, t['symbol'], entry_dec_ts, exit_ts)

        has_exh = exh is not None
        exh_ts = parse_decision_ts(exh['timestamp']) if exh is not None else None
        cur = nxt = None
        if exh_ts is not None:
            cur, nxt = kline_at_or_after(klines_by_symbol, t['symbol'], exh_ts)
            if cur is None or nxt is None:
                missing_price += 1

        cost_bps = float(t['total_cost_bps'] if t['total_cost_bps'] is not None else 10.0)
        actual = float(t['net_pnl_pct'])
        current_close_price = float(cur['close']) if cur else None
        next_open_price = float(nxt['open']) if nxt else None
        next_close_price = float(nxt['close']) if nxt else None

        sim_current = pct_for_exit(t['direction'], float(t['entry_price']), current_close_price, cost_bps) if current_close_price is not None else actual
        sim_next_open = pct_for_exit(t['direction'], float(t['entry_price']), next_open_price, cost_bps) if next_open_price is not None else actual
        sim_next_close = pct_for_exit(t['direction'], float(t['entry_price']), next_close_price, cost_bps) if next_close_price is not None else actual

        age_candles = None
        if entry_dec_ts is not None and exh_ts is not None:
            age_candles = int(round((exh_ts - entry_dec_ts).total_seconds() / (15 * 60)))

        unrealized_gross_at_next_open = None
        unrealized_net_at_next_open = None
        if next_open_price is not None:
            if t['direction'] == 'LONG':
                unrealized_gross_at_next_open = (next_open_price / float(t['entry_price']) - 1.0) * 100.0
            else:
                unrealized_gross_at_next_open = (1.0 - next_open_price / float(t['entry_price'])) * 100.0
            unrealized_net_at_next_open = unrealized_gross_at_next_open - (cost_bps / 100.0)

        row = {
            'id': tid,
            'symbol': t['symbol'],
            'direction': t['direction'],
            'regime': t['regime'],
            'exit_reason': t['exit_reason'],
            'entry_price': float(t['entry_price']),
            'actual_exit_price': float(t['exit_price']),
            'actual_net_pct': actual,
            'duration_candles': int(t['duration_candles']),
            'mfe_pct': float(t['mfe_pct']),
            'mae_pct': float(t['mae_pct']),
            'total_cost_bps': cost_bps,
            'entry_est_ts': fmt_decision_ts(entry_est),
            'actual_exit_ts': fmt_decision_ts(exit_ts),
            'entry_decision_ts': fmt_decision_ts(entry_dec_ts) if entry_dec_ts else '',
            'has_exhaustion': has_exh,
            'exhaustion_ts': fmt_decision_ts(exh_ts) if exh_ts else '',
            'age_candles': age_candles if age_candles is not None else '',
            'current_close_price': current_close_price,
            'next_open_price': next_open_price,
            'next_close_price': next_close_price,
            'sim_current_close_net_pct': sim_current,
            'sim_next_open_net_pct': sim_next_open,
            'sim_next_close_net_pct': sim_next_close,
            'delta_current_close_pct': sim_current - actual,
            'delta_next_open_pct': sim_next_open - actual,
            'delta_next_close_pct': sim_next_close - actual,
            'unrealized_gross_at_next_open_pct': unrealized_gross_at_next_open,
            'unrealized_net_at_next_open_pct': unrealized_net_at_next_open,
            'entry_decision_regime': entry_dec['regime'] if entry_dec is not None else '',
            'entry_decision_adx_slope_3': entry_dec['adx_slope_3'] if entry_dec is not None else '',
            'entry_decision_di_spread': entry_dec['di_spread'] if entry_dec is not None else '',
            'entry_decision_ema_gap_pct': entry_dec['ema_gap_pct'] if entry_dec is not None else '',
            'entry_decision_retracement_pct': entry_dec['retracement_pct'] if entry_dec is not None else '',
        }
        rows.append(row)

    # CSV
    fieldnames = list(rows[0].keys())
    with OUT_CSV.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    s_current = summarize(rows, 'current_close_price', 'sim_current_close_net_pct')
    s_next_open = summarize(rows, 'next_open_price', 'sim_next_open_net_pct')
    s_next_close = summarize(rows, 'next_close_price', 'sim_next_close_net_pct')

    policies = [
        apply_policy(rows, 'all trend_exhaustion', lambda r: True),
        apply_policy(rows, 'only if unrealized gross <= 0 at next_open', lambda r: (r['unrealized_gross_at_next_open_pct'] is not None and r['unrealized_gross_at_next_open_pct'] <= 0)),
        apply_policy(rows, 'only if unrealized net <= 0 at next_open', lambda r: (r['unrealized_net_at_next_open_pct'] is not None and r['unrealized_net_at_next_open_pct'] <= 0)),
        apply_policy(rows, 'entry regime WEAK_TREND only', lambda r: r['regime'] == 'WEAK_TREND'),
        apply_policy(rows, 'WEAK_TREND and unrealized gross <= 0', lambda r: r['regime'] == 'WEAK_TREND' and r['unrealized_gross_at_next_open_pct'] is not None and r['unrealized_gross_at_next_open_pct'] <= 0),
        apply_policy(rows, 'WEAK_TREND and unrealized net <= 0', lambda r: r['regime'] == 'WEAK_TREND' and r['unrealized_net_at_next_open_pct'] is not None and r['unrealized_net_at_next_open_pct'] <= 0),
    ]
    for age in [1, 2, 3, 4, 6, 8]:
        policies.append(apply_policy(rows, f'age <= {age} candles', lambda r, age=age: r['age_candles'] != '' and int(r['age_candles']) <= age))

    discussed_ids = {146, 148, 154, 156}
    discussed = [r for r in rows if r['id'] in discussed_ids]
    improvements = sorted([r for r in rows if r['has_exhaustion']], key=lambda r: r['delta_next_open_pct'], reverse=True)[:25]
    worsens = sorted([r for r in rows if r['has_exhaustion']], key=lambda r: r['delta_next_open_pct'])[:25]

    def line_summary(summary: dict[str, Any], label: str) -> str:
        return f"- {label}: changed={summary['changed']}, improved={summary['improved']}, worsened={summary['worsened']}, sim_net={summary['sim']:+.4f}%, delta={summary['delta']:+.4f}%"

    md: list[str] = []
    md.append('# Simulação reconstruída: exit-on-trend_exhaustion pós-entrada')
    md.append('')
    md.append('Fonte: `runtime/baseline/bot.db` (`momentum_trades`, `momentum_decisions`) + Binance Futures API 15m klines (`fapi/v1/klines`, via `curl`).')
    md.append(f'Janela: `momentum_trades.id <= {END_ID}`, para bater com a autópsia visual original.')
    md.append('')
    md.append('## Premissas e limitações')
    md.append('')
    md.append('- Entrada por trade mapeada ao `momentum_decisions outcome=trade blocked_by=none` mais próximo da entrada estimada por `exit_time - duration_candles*15m`, dentro de ±75min.')
    md.append('- Evento de saída: primeiro `trend_exhaustion` após essa decisão de entrada e antes da saída real.')
    md.append('- Preços testados: `current_close` do candle 15m do evento, `next_open` e `next_close` do candle seguinte.')
    md.append('- Fees: usa `total_cost_bps` do trade, normalmente 10 bps.')
    md.append('- Isto ainda é simulação descritiva, não regra operacional. A semântica exata do timestamp do `momentum_decisions` precisa ser confirmada no código antes de implementação.')
    md.append('')
    md.append('## Cobertura')
    md.append('')
    md.append(f'- Trades: {len(rows)}')
    md.append(f'- Net real total: {sum(r["actual_net_pct"] for r in rows):+.4f}%')
    for symbol in symbols:
        md.append(f'- Klines {symbol}: {kline_counts[symbol]} candles 15m')
    md.append(f'- Trades sem decisão de entrada mapeada: {missing_entry_dec}')
    md.append(f'- Casos com trend_exhaustion pós-entrada e preço disponível: {sum(1 for r in rows if r["has_exhaustion"] and r["next_open_price"] is not None)}')
    md.append(f'- Casos com trend_exhaustion mas preço ausente: {missing_price}')
    md.append('')
    md.append('## Resultado agregado')
    md.append('')
    md.append(line_summary(s_current, 'current_close (close do candle do evento)'))
    md.append(line_summary(s_next_open, 'next_open (open do próximo candle)'))
    md.append(line_summary(s_next_close, 'next_close (close do próximo candle)'))
    md.append('')
    md.append('## Segmentos usando next_open')
    for key in ['exit_reason', 'symbol', 'direction', 'regime']:
        md.append('')
        md.append(f'### {key}')
        for val, n, changed, actual, sim, delta in group_summary(rows, key, 'sim_next_open_net_pct'):
            md.append(f'- {val}: n={n}, changed={changed}, actual={actual:+.3f}%, sim={sim:+.3f}%, delta={delta:+.3f}%')
    # symbol_direction segment
    md.append('')
    md.append('### symbol_direction')
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[f"{r['symbol']} {r['direction']}"].append(r)
    for val in sorted(groups):
        arr = groups[val]
        actual = sum(r['actual_net_pct'] for r in arr)
        sim = sum(r['sim_next_open_net_pct'] for r in arr)
        changed = sum(1 for r in arr if r['has_exhaustion'])
        md.append(f'- {val}: n={len(arr)}, changed={changed}, actual={actual:+.3f}%, sim={sim:+.3f}%, delta={sim-actual:+.3f}%')

    md.append('')
    md.append('## Maiores melhorias com next_open')
    for r in improvements:
        md.append(f"- #{r['id']} {r['symbol']} {r['direction']} {r['exit_reason']}: actual={r['actual_net_pct']:+.3f}% sim={r['sim_next_open_net_pct']:+.3f}% delta={r['delta_next_open_pct']:+.3f}% entry_dec={r['entry_decision_ts']} exhaustion={r['exhaustion_ts']} exit_price={r['next_open_price']}")
    md.append('')
    md.append('## Maiores pioras com next_open')
    for r in worsens:
        md.append(f"- #{r['id']} {r['symbol']} {r['direction']} {r['exit_reason']}: actual={r['actual_net_pct']:+.3f}% sim={r['sim_next_open_net_pct']:+.3f}% delta={r['delta_next_open_pct']:+.3f}% entry_dec={r['entry_decision_ts']} exhaustion={r['exhaustion_ts']} exit_price={r['next_open_price']}")

    md.append('')
    md.append('## Trades discutidos')
    for r in discussed:
        md.append(f"- #{r['id']} {r['symbol']} {r['direction']}: actual={r['actual_net_pct']:+.3f}%, entry_dec={r['entry_decision_ts']}, first_exh={r['exhaustion_ts'] or 'nenhum'}, current_close={r['sim_current_close_net_pct']:+.3f}% @ {r['current_close_price']}; next_open={r['sim_next_open_net_pct']:+.3f}% @ {r['next_open_price']}; next_close={r['sim_next_close_net_pct']:+.3f}% @ {r['next_close_price']}")

    md.append('')
    md.append('## Refinamentos observáveis testados')
    md.append('')
    md.append('Preço usado: `next_open` após o primeiro `trend_exhaustion`.')
    md.append('')
    for p in policies:
        md.append(f"- {p['name']}: changed={p['changed']}, improved={p['improved']}, worsened={p['worsened']}, sim={p['sim']:+.4f}%, delta={p['delta']:+.4f}%")
    best = max(policies, key=lambda p: p['delta'])
    md.append('')
    md.append(f"Melhor refinamento nesta amostra: `{best['name']}`, delta={best['delta']:+.4f}%.")
    md.append('')
    md.append('Mudanças principais nesse refinamento:')
    md.append('')
    md.append('Melhorias:')
    for r in sorted(best['rows'], key=lambda r: r['policy_delta'], reverse=True)[:8]:
        md.append(f"- #{r['id']} {r['symbol']} {r['direction']} {r['regime']} {r['exit_reason']}: actual={r['actual_net_pct']:+.3f}%, sim={r['sim_next_open_net_pct']:+.3f}%, delta={r['policy_delta']:+.3f}%")
    md.append('')
    md.append('Piores danos:')
    for r in sorted(best['rows'], key=lambda r: r['policy_delta'])[:8]:
        md.append(f"- #{r['id']} {r['symbol']} {r['direction']} {r['regime']} {r['exit_reason']}: actual={r['actual_net_pct']:+.3f}%, sim={r['sim_next_open_net_pct']:+.3f}%, delta={r['policy_delta']:+.3f}%")

    md.append('')
    md.append('## Leitura fria')
    md.append('')
    md.append(f"- A hipótese ampla `exit-on-trend_exhaustion` usando `next_open` deu delta={s_next_open['delta']:+.4f}%. Isso não é GO operacional.")
    md.append('- O sinal ajuda bastante em vários `sl_hit`, mas também corta winners e alguns timeouts bons.')
    md.append('- Segmentos/refinamentos positivos nesta mesma amostra devem ser tratados como hipótese, não como regra, porque foram encontrados depois de olhar os resultados.')
    md.append('- Próximo passo protocolar, se continuar: mini-EXP congelado com critérios antes de nova simulação/validação. Não alterar o executor direto.')
    md.append('')
    md.append('Verdict: DADO INSUFICIENTE para mudança operacional; hipótese útil para EXP, especialmente se pré-registrar `WEAK_TREND`/idade do exhaustion sem tunar após resultado.')

    OUT_MD.write_text('\n'.join(md) + '\n')
    print(f'Wrote {OUT_CSV}')
    print(f'Wrote {OUT_MD}')
    print(f"Summary next_open: changed={s_next_open['changed']} actual={s_next_open['actual']:+.4f} sim={s_next_open['sim']:+.4f} delta={s_next_open['delta']:+.4f}")


if __name__ == '__main__':
    main()
