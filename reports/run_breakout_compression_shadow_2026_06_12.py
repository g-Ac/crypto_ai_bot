#!/usr/bin/env python3
"""Read-only shadow study: volatility contraction breakout with short continuation.

Does not touch bot runtime, state files, config, or execution code.
Outputs CSV + Markdown under reports/.
"""
from __future__ import annotations

import csv
import datetime as dt
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
OUT_CSV = ROOT / 'reports/breakout_compression_shadow_2026-06-12.csv'
OUT_MD = ROOT / 'reports/breakout_compression_shadow_2026-06-12.md'

SYMBOLS = ('BTCUSDT', 'ETHUSDT')
DAYS = 30
INTERVAL_MS = 5 * 60 * 1000
FEE_ROUNDTRIP_PCT = 0.10  # taker-like fee+slippage diagnostic, conservative
TIMEOUT_CANDLES = 60      # existing breakout executor timeout: 5h on 5m
FAST_INVALIDATION_CANDLES = 4
BINANCE_FAPI = 'https://fapi.binance.com/fapi/v1/klines'
UTC = dt.timezone.utc


def utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def ms(x: dt.datetime) -> int:
    return int(x.timestamp() * 1000)


def fmt_ts_ms(x: int) -> str:
    return dt.datetime.fromtimestamp(x / 1000, UTC).strftime('%Y-%m-%d %H:%M:%S')


def fetch_5m_futures(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows: list[list[Any]] = []
    cur = start_ms
    while cur < end_ms:
        url = f'{BINANCE_FAPI}?symbol={symbol}&interval=5m&startTime={cur}&endTime={end_ms}&limit=1500'
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

    df = pd.DataFrame(rows, columns=[
        'time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
        'qav', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore',
    ])
    if df.empty:
        return df
    df = df.drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
    for col in ['open', 'high', 'low', 'close', 'volume', 'qav', 'taker_buy_base', 'taker_buy_quote']:
        df[col] = df[col].astype(float)
    df['time'] = df['time'].astype(np.int64)
    df['timestamp'] = pd.to_datetime(df['time'], unit='ms', utc=True)
    return df


def profit_factor(pnls: list[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p <= 0))
    if losses == 0:
        return math.inf if gains > 0 else 0.0
    return gains / losses


def calc_pnl(direction: str, entry: float, exit_price: float) -> float:
    gross = (exit_price / entry - 1.0) * 100.0 if direction == 'LONG' else (1.0 - exit_price / entry) * 100.0
    return gross - FEE_ROUNDTRIP_PCT


def simulate_exit(df: pd.DataFrame, entry_i: int, sig: Any) -> dict[str, Any] | None:
    # Signal is generated on candle i-1; enter at candle entry_i open.
    if entry_i >= len(df):
        return None
    entry = float(df.iloc[entry_i]['open'])
    sl = float(sig.sl_price)
    tp1 = float(sig.tp1_price)
    tp2 = float(sig.tp2_price)
    direction = sig.direction.value

    viability = calculate_viability(
        symbol=sig.symbol,
        entry_price=entry,
        sl_price=sl,
        tp_price=tp1,
        max_risk_per_trade_usd=20.0,
        preferred_leverage=1,
    )
    if not viability.viable:
        return {
            'rejected': True,
            'reject_reason': viability.reason,
            'entry_price': entry,
            'sl_price': sl,
            'tp1_price': tp1,
            'tp2_price': tp2,
        }

    tp1_hit = False
    tp1_exit_price = None
    stop = sl
    mfe = 0.0
    mae = 0.0
    mfe_4 = 0.0
    mae_4 = 0.0
    reached_tp1_by_4 = False
    exit_reason = None
    exit_price = None
    duration = 0

    for j in range(entry_i, min(len(df), entry_i + TIMEOUT_CANDLES)):
        duration += 1
        c = df.iloc[j]
        high = float(c['high'])
        low = float(c['low'])
        close = float(c['close'])
        if direction == 'LONG':
            cur_mfe = (high - entry) / entry * 100.0
            cur_mae = (entry - low) / entry * 100.0
        else:
            cur_mfe = (entry - low) / entry * 100.0
            cur_mae = (high - entry) / entry * 100.0
        mfe = max(mfe, cur_mfe)
        mae = max(mae, cur_mae)
        if duration <= FAST_INVALIDATION_CANDLES:
            mfe_4 = max(mfe_4, cur_mfe)
            mae_4 = max(mae_4, cur_mae)

        if direction == 'LONG':
            if low <= stop:
                exit_reason = 'sl_hit' if not tp1_hit else 'sl_breakeven'
                exit_price = stop if not tp1_hit else 0.5 * tp1_exit_price + 0.5 * entry
                break
            if not tp1_hit and high >= tp1:
                tp1_hit = True
                tp1_exit_price = tp1
                stop = entry
                if duration <= FAST_INVALIDATION_CANDLES:
                    reached_tp1_by_4 = True
                if high >= tp2:
                    exit_reason = 'tp2_hit'
                    exit_price = 0.5 * tp1 + 0.5 * tp2
                    break
            elif tp1_hit and high >= tp2:
                exit_reason = 'tp2_hit'
                exit_price = 0.5 * tp1_exit_price + 0.5 * tp2
                break
        else:
            if high >= stop:
                exit_reason = 'sl_hit' if not tp1_hit else 'sl_breakeven'
                exit_price = stop if not tp1_hit else 0.5 * tp1_exit_price + 0.5 * entry
                break
            if not tp1_hit and low <= tp1:
                tp1_hit = True
                tp1_exit_price = tp1
                stop = entry
                if duration <= FAST_INVALIDATION_CANDLES:
                    reached_tp1_by_4 = True
                if low <= tp2:
                    exit_reason = 'tp2_hit'
                    exit_price = 0.5 * tp1 + 0.5 * tp2
                    break
            elif tp1_hit and low <= tp2:
                exit_reason = 'tp2_hit'
                exit_price = 0.5 * tp1_exit_price + 0.5 * tp2
                break

        if duration >= TIMEOUT_CANDLES:
            exit_reason = 'timeout'
            exit_price = close
            break

    if exit_reason is None:
        c = df.iloc[min(len(df) - 1, entry_i + TIMEOUT_CANDLES - 1)]
        exit_reason = 'data_end'
        exit_price = float(c['close'])

    pnl = calc_pnl(direction, entry, float(exit_price))
    false_breakout = (not tp1_hit) and exit_reason in {'sl_hit', 'timeout', 'data_end'}
    no_fast_followthrough = not reached_tp1_by_4
    return {
        'rejected': False,
        'reject_reason': '',
        'entry_price': entry,
        'sl_price': sl,
        'tp1_price': tp1,
        'tp2_price': tp2,
        'exit_price': float(exit_price),
        'exit_reason': exit_reason,
        'pnl_pct': pnl,
        'duration_candles': duration,
        'mfe_pct': mfe,
        'mae_pct': mae,
        'mfe_4_pct': mfe_4,
        'mae_4_pct': mae_4,
        'tp1_hit': tp1_hit,
        'reached_tp1_by_4': reached_tp1_by_4,
        'false_breakout': false_breakout,
        'no_fast_followthrough': no_fast_followthrough,
    }


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
            t = int(dt.datetime.strptime(ts, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC).timestamp())
            out.append((t, reg))
        except Exception:
            pass
    return out


def nearest_regime(lookup: list[tuple[int, str]], signal_ms: int) -> str:
    if not lookup:
        return 'UNKNOWN'
    s = signal_ms // 1000
    best = min(lookup, key=lambda x: abs(x[0] - s))
    if abs(best[0] - s) <= 45 * 60:
        return best[1]
    return 'UNKNOWN'


def stage_counts(df_ind: pd.DataFrame) -> Counter:
    engine = BreakoutEngine5m()
    counts = Counter()
    highs = df_ind['high'].values
    lows = df_ind['low'].values
    closes = df_ind['close'].values
    opens = df_ind['open'].values
    for idx in range(engine._MIN_CANDLES, len(df_ind)):
        vol_ratio = df_ind['vol_ratio'].values[idx]
        body_ratio = df_ind['body_ratio'].values[idx]
        if np.isnan(vol_ratio) or np.isnan(body_ratio):
            continue
        found_compression = False
        found_break_price = False
        found_body = False
        found_volume = False
        for lookback in range(engine.LOOKBACK_MAX, engine.LOOKBACK_MIN - 1, -1):
            cons_start = idx - lookback
            cons_end = idx
            if cons_start < 0:
                continue
            max_high = float(np.max(highs[cons_start:cons_end]))
            min_low = float(np.min(lows[cons_start:cons_end]))
            if min_low <= 0:
                continue
            range_pct = (max_high - min_low) / min_low * 100.0
            bb_bw_pre = df_ind['bb_bandwidth'].values[idx - 1]
            if np.isnan(bb_bw_pre):
                continue
            if range_pct < engine.RANGE_THRESHOLD_PCT and bb_bw_pre < engine.BB_BANDWIDTH_MAX:
                found_compression = True
                close_now = float(closes[idx])
                is_green = closes[idx] > opens[idx]
                breaks = (close_now > max_high and is_green) or (close_now < min_low and not is_green)
                if breaks:
                    found_break_price = True
                    if body_ratio >= engine.BODY_RATIO_MIN:
                        found_body = True
                    if vol_ratio >= engine.VOLUME_MULTIPLE_MIN:
                        found_volume = True
                break
        if found_compression:
            counts['compression'] += 1
        if found_break_price:
            counts['price_break'] += 1
        if found_break_price and found_body:
            counts['price_body_break'] += 1
        if found_break_price and found_body and found_volume:
            counts['strict_breakout_candidate'] += 1
    return counts


def run_symbol(conn: sqlite3.Connection, symbol: str, start: dt.datetime, end: dt.datetime) -> tuple[list[dict[str, Any]], Counter]:
    raw = fetch_5m_futures(symbol, ms(start), ms(end))
    if raw.empty:
        return [], Counter()
    df_ind = add_indicators_5m(raw.copy())
    engine = BreakoutEngine5m()
    regimes = get_regime_lookup(conn, symbol, start - dt.timedelta(hours=2), end + dt.timedelta(hours=2))
    counts = stage_counts(df_ind)

    trades: list[dict[str, Any]] = []
    position_open_until = -1
    pending_sig = None
    pending_i = None
    for i in range(engine._MIN_CANDLES, len(raw)):
        if pending_sig is not None and i > position_open_until:
            sim = simulate_exit(df_ind, i, pending_sig)
            if sim is not None:
                if sim.get('rejected'):
                    # Keep rejected candidates in row-level CSV for visibility, but not as trades.
                    trades.append({
                        'symbol': symbol,
                        'signal_ts': fmt_ts_ms(int(df_ind.iloc[pending_i]['time'])),
                        'entry_ts': fmt_ts_ms(int(df_ind.iloc[i]['time'])),
                        'direction': pending_sig.direction.value,
                        'regime': nearest_regime(regimes, int(df_ind.iloc[pending_i]['time'])),
                        'status': 'rejected',
                        **sim,
                    })
                else:
                    exit_i = min(len(df_ind) - 1, i + int(sim['duration_candles']) - 1)
                    position_open_until = exit_i
                    meta = pending_sig.metadata or {}
                    trades.append({
                        'symbol': symbol,
                        'signal_ts': fmt_ts_ms(int(df_ind.iloc[pending_i]['time'])),
                        'entry_ts': fmt_ts_ms(int(df_ind.iloc[i]['time'])),
                        'exit_ts': fmt_ts_ms(int(df_ind.iloc[exit_i]['time'])),
                        'direction': pending_sig.direction.value,
                        'regime': nearest_regime(regimes, int(df_ind.iloc[pending_i]['time'])),
                        'status': 'filled',
                        'lookback': meta.get('lookback'),
                        'range_pct': meta.get('range_pct'),
                        'bb_bandwidth': meta.get('bb_bandwidth'),
                        'vol_ratio': meta.get('vol_ratio'),
                        'body_ratio': meta.get('body_ratio'),
                        **sim,
                    })
            pending_sig = None
            pending_i = None

        if i <= position_open_until or pending_sig is not None:
            continue
        visible = df_ind.iloc[max(0, i - 240): i + 1].copy()
        sig = engine.analyze(symbol, visible)
        if sig is not None and sig.valid:
            pending_sig = sig
            pending_i = i
    return trades, counts


def summarize(rows: list[dict[str, Any]], key: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get('status') != 'filled':
            continue
        groups[r[key] if key else 'ALL'].append(r)
    out = []
    for name, g in sorted(groups.items()):
        pnls = [float(r['pnl_pct']) for r in g]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        out.append((str(name), {
            'n': len(g),
            'net_sum': sum(pnls),
            'avg': float(np.mean(pnls)) if pnls else 0.0,
            'median': float(np.median(pnls)) if pnls else 0.0,
            'winrate': len(wins) / len(g) * 100 if g else 0.0,
            'pf': profit_factor(pnls),
            'tp1_rate': sum(1 for r in g if r.get('tp1_hit')) / len(g) * 100 if g else 0.0,
            'tp1_by_4_rate': sum(1 for r in g if r.get('reached_tp1_by_4')) / len(g) * 100 if g else 0.0,
            'false_breakout_rate': sum(1 for r in g if r.get('false_breakout')) / len(g) * 100 if g else 0.0,
            'avg_duration': float(np.mean([float(r['duration_candles']) for r in g])) if g else 0.0,
        }))
    return out


def momentum_same_period(conn: sqlite3.Connection, start: dt.datetime, end: dt.datetime) -> list[tuple[str, int, float, float]]:
    return conn.execute(
        """
        SELECT COALESCE(regime,'') AS regime, COUNT(*) AS n,
               ROUND(SUM(net_pnl_pct),4) AS net_sum,
               ROUND(AVG(net_pnl_pct),4) AS net_avg
        FROM momentum_trades
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY COALESCE(regime,'')
        ORDER BY n DESC
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()


def write_outputs(rows: list[dict[str, Any]], counts_by_symbol: dict[str, Counter], start: dt.datetime, end: dt.datetime, conn: sqlite3.Connection) -> None:
    fieldnames = sorted({k for r in rows for k in r.keys()})
    with OUT_CSV.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    filled = [r for r in rows if r.get('status') == 'filled']
    rejected = [r for r in rows if r.get('status') == 'rejected']
    md: list[str] = []
    md.append('# Shadow read-only: compression breakout → short continuation')
    md.append('')
    md.append('Status: DISCOVERY / READ-ONLY. Não é EXP congelado e não autoriza alteração operacional.')
    md.append('')
    md.append(f'- window: {start.isoformat()} até {end.isoformat()}')
    md.append(f'- symbols: {", ".join(SYMBOLS)}')
    md.append('- data: Binance Futures 5m klines via curl')
    md.append('- signal engine: existing `BreakoutEngine5m` parameters')
    md.append(f'- cost model: {FEE_ROUNDTRIP_PCT:.2f}% round-trip diagnostic')
    md.append(f'- timeout: {TIMEOUT_CANDLES} candles de 5m')
    md.append(f'- fast-followthrough diagnostic: TP1 até {FAST_INVALIDATION_CANDLES} candles')
    md.append(f'- csv: `{OUT_CSV}`')
    md.append('')
    md.append('## Funnel de oportunidades')
    md.append('')
    md.append('| symbol | compression | price_break | price+body | strict candidate | filled | rejected |')
    md.append('|---|---:|---:|---:|---:|---:|---:|')
    for sym in SYMBOLS:
        c = counts_by_symbol.get(sym, Counter())
        md.append(f"| {sym} | {c['compression']} | {c['price_break']} | {c['price_body_break']} | {c['strict_breakout_candidate']} | {sum(1 for r in filled if r['symbol']==sym)} | {sum(1 for r in rejected if r['symbol']==sym)} |")
    md.append('')
    md.append('## Resultado shadow preenchido')
    md.append('')
    if not filled:
        md.append('Nenhum trade shadow preenchido pelos critérios atuais. Isso sugere que o motor pode estar rígido/dormindo ou que não houve compressão+rompimento suficiente na janela.')
    else:
        for title, key in [('Total', None), ('Por símbolo', 'symbol'), ('Por regime aproximado', 'regime'), ('Por direção', 'direction'), ('Por exit_reason', 'exit_reason')]:
            md.append(f'### {title}')
            md.append('')
            md.append('| grupo | n | net_sum | avg | median | WR | PF | TP1% | TP1<=4% | false_breakout% | avg_dur |')
            md.append('|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
            for name, s in summarize(filled, key):
                pf = 'inf' if math.isinf(s['pf']) else f"{s['pf']:.2f}"
                md.append(f"| {name} | {s['n']} | {s['net_sum']:+.4f}% | {s['avg']:+.4f}% | {s['median']:+.4f}% | {s['winrate']:.1f}% | {pf} | {s['tp1_rate']:.1f}% | {s['tp1_by_4_rate']:.1f}% | {s['false_breakout_rate']:.1f}% | {s['avg_duration']:.1f} |")
            md.append('')
        md.append('### Top danos')
        md.append('')
        for r in sorted(filled, key=lambda x: float(x['pnl_pct']))[:10]:
            md.append(f"- {r['entry_ts']} {r['symbol']} {r['direction']} {r['regime']} {r['exit_reason']}: pnl={float(r['pnl_pct']):+.4f}% mfe4={float(r['mfe_4_pct']):.4f}% mae4={float(r['mae_4_pct']):.4f}%")
        md.append('')
        md.append('### Top ganhos')
        md.append('')
        for r in sorted(filled, key=lambda x: float(x['pnl_pct']), reverse=True)[:10]:
            md.append(f"- {r['entry_ts']} {r['symbol']} {r['direction']} {r['regime']} {r['exit_reason']}: pnl={float(r['pnl_pct']):+.4f}% mfe4={float(r['mfe_4_pct']):.4f}% mae4={float(r['mae_4_pct']):.4f}%")
        md.append('')
    md.append('## Momentum Pullback no mesmo período')
    md.append('')
    mt = momentum_same_period(conn, start, end)
    if not mt:
        md.append('Nenhum momentum_trade fechado no mesmo período da janela.')
    else:
        md.append('| regime | n | net_sum | net_avg |')
        md.append('|---|---:|---:|---:|')
        for reg, n, net_sum, net_avg in mt:
            md.append(f'| {reg or "(blank)"} | {n} | {float(net_sum):+.4f}% | {float(net_avg):+.4f}% |')
    md.append('')
    md.append('## Leitura fria')
    md.append('')
    if len(filled) < 10:
        md.append('- Amostra shadow pequena demais para conclusão. Resultado serve para calibrar se o motor está observando oportunidades, não para GO/NO-GO.')
    else:
        total = summarize(filled, None)[0][1]
        pf_s = 'inf' if math.isinf(total['pf']) else f"{total['pf']:.2f}"
        md.append(f"- PF shadow total: {pf_s}; net_sum={total['net_sum']:+.4f}%; false_breakout={total['false_breakout_rate']:.1f}%.")
        if total['pf'] < 1.0 or total['net_sum'] <= 0:
            md.append('- Como descoberta inicial, não há sinal de edge líquido. Se continuar, precisa ser por hipótese estrutural nova, não ajuste fino.')
        else:
            md.append('- Como descoberta inicial, há algo para investigar; próximo passo seria congelar um EXP separado antes de qualquer mudança no bot.')
    md.append('- Não alterar executor/bot com base neste relatório.')
    md.append('')
    OUT_MD.write_text('\n'.join(md) + '\n')


def main() -> None:
    end = utc_now()
    start = end - dt.timedelta(days=DAYS)
    conn = sqlite3.connect(DB)
    all_rows: list[dict[str, Any]] = []
    counts: dict[str, Counter] = {}
    for sym in SYMBOLS:
        rows, c = run_symbol(conn, sym, start, end)
        all_rows.extend(rows)
        counts[sym] = c
    write_outputs(all_rows, counts, start, end, conn)
    filled = [r for r in all_rows if r.get('status') == 'filled']
    rejected = [r for r in all_rows if r.get('status') == 'rejected']
    print(f'Wrote {OUT_CSV}')
    print(f'Wrote {OUT_MD}')
    print(f'filled={len(filled)} rejected={len(rejected)}')
    if filled:
        pnls = [float(r['pnl_pct']) for r in filled]
        print(f'net_sum={sum(pnls):+.4f}% pf={profit_factor(pnls):.2f}')


if __name__ == '__main__':
    main()
