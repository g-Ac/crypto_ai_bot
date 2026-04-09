# Backtest Parametrico - Resultados

- **Periodo**: 180 dias
- **Symbols**: BTCUSDT, ETHUSDT
- **Timeframe**: 5m (principal)
- **Exit**: Trailing stop (0.5x ATR activation, 0.8x ATR trail)
- **Fees**: 0.08% round-trip + 0.04% slippage
- **Capital**: $10,000 | Leverage: 3x | Risk: 2.0%/trade
- **Total combinacoes testadas**: 185

## Veredicto

**2 de 109 combinacoes com trades tem expectativa positiva.**
(1.8% das combinacoes com trades)

## Top 10 Combinacoes (por expectativa USD/trade)

| # | Motor | Symbol | Params | Trades | WR% | Exp$/trade | PnL$ | PF | Sharpe | MaxDD% |
|---|-------|--------|--------|--------|-----|------------|------|----|----|--------|
| 1 | rsi_bb_reversal | BTCUSDT | rsi=(25,75),bb=14/2.0 | 1 | 100.0 | +26.55 | +26.55 | 999.99 | 0.00 | 0.00 |
| 2 | rsi_bb_reversal | BTCUSDT | rsi=(28,72),bb=14/2.0 | 2 | 50.0 | +8.12 | +16.23 | 2.57 | 0.31 | 0.07 |

## Bottom 10 Combinacoes (piores)

| # | Motor | Symbol | Params | Trades | WR% | Exp$/trade | PnL$ |
|---|-------|--------|--------|--------|-----|------------|------|
| 1 | rsi_bb_reversal | BTCUSDT | rsi=(28,72),bb=30/2.5 | 9 | 33.3 | -48.04 | -432.40 |
| 2 | rsi_bb_reversal | BTCUSDT | rsi=(25,75),bb=20/2.5 | 6 | 33.3 | -50.48 | -302.90 |
| 3 | rsi_bb_reversal | BTCUSDT | rsi=(32,68),bb=20/2.0 | 3 | 33.3 | -52.09 | -156.27 |
| 4 | rsi_bb_reversal | BTCUSDT | rsi=(32,68),bb=30/2.0 | 4 | 0.0 | -60.84 | -243.36 |
| 5 | rsi_bb_reversal | BTCUSDT | rsi=(35,65),bb=20/2.0 | 6 | 0.0 | -68.09 | -408.54 |
| 6 | rsi_bb_reversal | BTCUSDT | rsi=(35,65),bb=30/2.0 | 3 | 0.0 | -68.44 | -205.31 |
| 7 | rsi_bb_reversal | BTCUSDT | rsi=(30,70),bb=14/2.0 | 3 | 0.0 | -76.47 | -229.40 |
| 8 | rsi_bb_reversal | BTCUSDT | rsi=(25,75),bb=30/2.0 | 1 | 0.0 | -91.66 | -91.66 |
| 9 | rsi_bb_reversal | BTCUSDT | rsi=(28,72),bb=30/2.0 | 1 | 0.0 | -91.66 | -91.66 |
| 10 | rsi_bb_reversal | BTCUSDT | rsi=(30,70),bb=30/2.0 | 1 | 0.0 | -91.66 | -91.66 |

## volume_breakout

Nenhuma combinacao gerou trades.

## rsi_bb_reversal

- **Combinacoes com trades**: 29
- **Expectativa media**: $-39.78/trade
- **Melhor expectativa**: $+26.55/trade
- **Pior expectativa**: $-91.66/trade
- **Win rate range**: 0.0% - 100.0%
- **Trades range**: 1 - 55
- **PF range**: 0.00 - 999.99
- **Com expectativa positiva**: 2 / 29

### Top 3 rsi_bb_reversal

1. **rsi=(25,75),bb=14/2.0** (BTCUSDT) - Trades: 1, WR: 100.0%, Exp: $+26.55/trade, PnL: $+26.55, PF: 999.99, Sharpe: 0.00
2. **rsi=(28,72),bb=14/2.0** (BTCUSDT) - Trades: 2, WR: 50.0%, Exp: $+8.12/trade, PnL: $+16.23, PF: 2.57, Sharpe: 0.31
3. **rsi=(25,75),bb=14/2.5** (BTCUSDT) - Trades: 13, WR: 38.5%, Exp: $-14.30/trade, PnL: $-185.85, PF: 0.72, Sharpe: -0.13

## ema_crossover

- **Combinacoes com trades**: 80
- **Expectativa media**: $-12.78/trade
- **Melhor expectativa**: $-0.83/trade
- **Pior expectativa**: $-17.55/trade
- **Win rate range**: 28.5% - 44.6%
- **Trades range**: 74 - 340
- **PF range**: 0.66 - 0.98
- **Com expectativa positiva**: 0 / 80

### Top 3 ema_crossover

1. **ema=(12,26),zone=0.1,maxc=5** (BTCUSDT) - Trades: 74, WR: 44.6%, Exp: $-0.83/trade, PnL: $-61.61, PF: 0.98, Sharpe: -0.01
2. **ema=(12,26),zone=0.2,maxc=5** (BTCUSDT) - Trades: 74, WR: 44.6%, Exp: $-0.83/trade, PnL: $-61.61, PF: 0.98, Sharpe: -0.01
3. **ema=(12,26),zone=0.3,maxc=5** (BTCUSDT) - Trades: 74, WR: 44.6%, Exp: $-0.83/trade, PnL: $-61.61, PF: 0.98, Sharpe: -0.01

## Analise de Sensibilidade

Parametros que mais afetam a expectativa (range de expectativa por valor):

### RSI/BB Reversal

**rsi_oversold**:
  - 25: avg $-32.22, range [-91.66, +26.55] (n=5)
  - 28: avg $-35.81, range [-91.66, +8.12] (n=6)
  - 30: avg $-50.96, range [-91.66, -27.91] (n=6)
  - 32: avg $-40.98, range [-60.84, -26.00] (n=6)
  - 35: avg $-37.65, range [-68.44, -16.99] (n=6)

**bb_period**:
  - 14: avg $-22.36, range [-76.47, +26.55] (n=10)
  - 20: avg $-39.52, range [-68.09, -20.50] (n=9)
  - 30: avg $-57.42, range [-91.66, -18.52] (n=10)

**bb_std**:
  - 2.0: avg $-50.72, range [-91.66, +26.55] (n=14)
  - 2.5: avg $-29.56, range [-50.48, -14.30] (n=15)

### EMA Crossover

**ema_fast**:
  - 5: avg $-11.95, range [-16.30, -4.64] (n=32)
  - 8: avg $-14.69, range [-15.12, -14.12] (n=16)
  - 9: avg $-16.51, range [-17.55, -14.05] (n=16)
  - 12: avg $-8.82, range [-13.22, -0.83] (n=16)

**retest_zone_pct**:
  - 0.1: avg $-12.48, range [-16.59, -0.83] (n=20)
  - 0.2: avg $-12.89, range [-17.55, -0.83] (n=20)
  - 0.3: avg $-12.89, range [-17.55, -0.83] (n=20)
  - 0.5: avg $-12.89, range [-17.55, -0.83] (n=20)

**max_candles_since_cross**:
  - 5: avg $-9.63, range [-15.39, -0.83] (n=20)
  - 10: avg $-12.64, range [-16.63, -8.15] (n=20)
  - 15: avg $-14.44, range [-17.55, -11.04] (n=20)
  - 20: avg $-14.44, range [-17.55, -11.04] (n=20)

## Combinacoes sem sinais

76 combinacoes nao geraram nenhum sinal.
Isso indica filtros muito restritivos para esses parametros.
