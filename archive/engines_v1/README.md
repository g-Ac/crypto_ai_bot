# Engines V1 (Archived)

These 3 scalping engines were replaced by microstructure-based motors on 2026-04-08.

## Why they were retired

The V1 engines used price-based technical indicators (EMA, RSI, Bollinger Bands, volume)
which are universally available and already priced in by the market. Confluence of 3
correlated indicators measuring the same thing (price history) provided no additional
information — like asking the same doctor 3 times.

## Replaced by

- `funding_engine.py` (M1) — Funding Rate + Long/Short Ratio (positioning)
- `liquidation_engine.py` (M2) — Liquidation Cascade + OI Divergence (forced flow)
- `basis_engine.py` (M3) — Basis Spread + Session Timing (market structure)

These new motors measure independent, non-price data: cost of positions, forced liquidations,
and futures/spot premium — providing genuine confluence.

## Files

- `volume_breakout.py` — Breakout de volume (3m candles)
- `rsi_bb_reversal.py` — RSI + Bollinger Band reversal (5m/15m candles)
- `ema_crossover.py` — EMA crossover + retest (3m/15m candles)

## Still referenced by

- `backtest_scalping.py` — Historical backtests still import these
- `diagnose_funnel.py` — Diagnostic tool
