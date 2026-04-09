#!/usr/bin/env python3
"""
diagnose_funnel.py - Diagnose why scalping signals are being blocked.

Runs the 3 engines on current data for all symbols and reports
what each engine sees and why signals are blocked.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from config import SYMBOLS
from signal_types import Direction, ScalpingConfig
from scalping_data import add_scalping_indicators
from market import get_candles

import volume_breakout
import rsi_bb_reversal
import ema_crossover

ENGINE_NAMES = {
    "volume_breakout": "Volume Breakout",
    "rsi_bb_reversal": "RSI/BB Reversal",
    "ema_crossover": "EMA Crossover",
}


def fetch_data(symbol):
    """Fetch 3m, 5m, 15m data for a symbol."""
    try:
        df_3m = get_candles(symbol, "3m", 100)
        df_5m = get_candles(symbol, "5m", 100)
        df_15m = get_candles(symbol, "15m", 100)
        return df_3m, df_5m, df_15m
    except Exception as e:
        print(f"  ERRO ao buscar dados: {e}")
        return None, None, None


def diagnose_symbol(symbol, config):
    """Run all 3 engines and report results."""
    df_3m, df_5m, df_15m = fetch_data(symbol)
    if df_3m is None or df_5m is None:
        return {"error": "dados insuficientes"}

    # Add indicators
    df_3m_ind = add_scalping_indicators(df_3m.copy())
    df_5m_ind = add_scalping_indicators(df_5m.copy())
    df_15m_ind = None
    if df_15m is not None and len(df_15m) >= 50:
        df_15m_ind = add_scalping_indicators(df_15m.copy())

    results = {}

    # Volume Breakout
    sig_vb = volume_breakout.analyze(symbol, config, df_3m=df_3m_ind, df_5m=df_5m_ind)
    results["volume_breakout"] = {
        "valid": sig_vb.valid,
        "direction": sig_vb.direction.value if sig_vb.valid else "NEUTRAL",
        "reason": sig_vb.reason if hasattr(sig_vb, 'reason') and sig_vb.reason else ("SINAL" if sig_vb.valid else "bloqueado"),
        "strength": sig_vb.strength if sig_vb.valid else 0,
    }

    # RSI/BB Reversal
    sig_rsi = rsi_bb_reversal.analyze(symbol, config, df_5m=df_5m_ind, df_15m=df_15m_ind)
    results["rsi_bb_reversal"] = {
        "valid": sig_rsi.valid,
        "direction": sig_rsi.direction.value if sig_rsi.valid else "NEUTRAL",
        "reason": sig_rsi.reason if hasattr(sig_rsi, 'reason') and sig_rsi.reason else ("SINAL" if sig_rsi.valid else "bloqueado"),
        "strength": sig_rsi.strength if sig_rsi.valid else 0,
    }

    # EMA Crossover
    sig_ema = ema_crossover.analyze(symbol, config, df_3m=df_3m_ind, df_15m=df_15m_ind)
    results["ema_crossover"] = {
        "valid": sig_ema.valid,
        "direction": sig_ema.direction.value if sig_ema.valid else "NEUTRAL",
        "reason": sig_ema.reason if hasattr(sig_ema, 'reason') and sig_ema.reason else ("SINAL" if sig_ema.valid else "bloqueado"),
        "strength": sig_ema.strength if sig_ema.valid else 0,
    }

    # Confluence
    all_signals = [sig_vb, sig_rsi, sig_ema]
    valid_signals = [s for s in all_signals if s.valid]
    long_count = sum(1 for s in valid_signals if s.direction == Direction.LONG)
    short_count = sum(1 for s in valid_signals if s.direction == Direction.SHORT)

    if long_count > 0 and short_count > 0:
        confluence = "CONFLITO (sinais opostos)"
        score = 0
    elif long_count >= 2:
        confluence = f"{long_count}/3 LONG"
        score = long_count
    elif short_count >= 2:
        confluence = f"{short_count}/3 SHORT"
        score = short_count
    elif long_count == 1 or short_count == 1:
        d = "LONG" if long_count else "SHORT"
        confluence = f"1/3 {d} (insuficiente)"
        score = 1
    else:
        confluence = "0/3 (nenhum sinal)"
        score = 0

    results["confluence"] = confluence
    results["score"] = score

    # Extra context: current price, RSI, ATR
    last_5m = df_5m_ind.iloc[-1]
    results["context"] = {
        "price": round(float(last_5m["close"]), 4),
        "rsi": round(float(last_5m.get("rsi", 0)), 1) if "rsi" in last_5m else "N/A",
    }

    return results


def main():
    config = ScalpingConfig()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"DIAGNOSTICO DO FUNIL — {now}")
    print("=" * 60)

    engine_blocks = {"volume_breakout": 0, "rsi_bb_reversal": 0, "ema_crossover": 0}
    engine_signals = {"volume_breakout": 0, "rsi_bb_reversal": 0, "ema_crossover": 0}
    block_reasons = {}

    for symbol in SYMBOLS:
        print(f"\n{symbol}:")
        result = diagnose_symbol(symbol, config)

        if "error" in result:
            print(f"  ERRO: {result['error']}")
            continue

        ctx = result.get("context", {})
        print(f"  Preco: ${ctx.get('price', '?')} | RSI: {ctx.get('rsi', '?')}")

        for eng_key in ["volume_breakout", "rsi_bb_reversal", "ema_crossover"]:
            eng = result[eng_key]
            label = ENGINE_NAMES[eng_key]
            if eng["valid"]:
                print(f"  {label:20s}: SINAL {eng['direction']} (forca={eng['strength']})")
                engine_signals[eng_key] += 1
            else:
                reason = eng.get("reason", "desconhecido")
                print(f"  {label:20s}: BLOQUEADO — {reason}")
                engine_blocks[eng_key] += 1
                block_reasons.setdefault(eng_key, {})
                block_reasons[eng_key][reason] = block_reasons[eng_key].get(reason, 0) + 1

        print(f"  Confluencia: {result['confluence']}")

    # Summary
    total = len(SYMBOLS)
    print(f"\n{'=' * 60}")
    print(f"RESUMO:")
    print(f"{'=' * 60}")
    print(f"  Simbolos analisados: {total}")

    print(f"\n  Motor                   Sinais  Bloqueados  Taxa Bloq")
    print(f"  {'-'*55}")
    most_blocked = None
    most_blocked_pct = 0
    for eng_key in ["volume_breakout", "rsi_bb_reversal", "ema_crossover"]:
        s = engine_signals[eng_key]
        b = engine_blocks[eng_key]
        pct = (b / total * 100) if total > 0 else 0
        print(f"  {ENGINE_NAMES[eng_key]:22s}  {s:>5}   {b:>9}   {pct:>5.0f}%")
        if pct > most_blocked_pct:
            most_blocked_pct = pct
            most_blocked = eng_key

    if most_blocked:
        print(f"\n  Principal gargalo: {ENGINE_NAMES[most_blocked]} ({most_blocked_pct:.0f}% bloqueado)")
        reasons = block_reasons.get(most_blocked, {})
        if reasons:
            print(f"  Motivos mais frequentes:")
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1])[:3]:
                print(f"    - {reason} ({count}x)")

    print(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
