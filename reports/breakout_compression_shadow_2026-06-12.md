# Shadow read-only: compression breakout → short continuation

Status: DISCOVERY / READ-ONLY. Não é EXP congelado e não autoriza alteração operacional.

- window: 2026-05-13T04:01:28.719005+00:00 até 2026-06-12T04:01:28.719005+00:00
- symbols: BTCUSDT, ETHUSDT
- data: Binance Futures 5m klines via curl
- signal engine: existing `BreakoutEngine5m` parameters
- cost model: 0.10% round-trip diagnostic
- timeout: 60 candles de 5m
- fast-followthrough diagnostic: TP1 até 4 candles
- csv: `/home/pi/crypto_ai_bot/reports/breakout_compression_shadow_2026-06-12.csv`

## Funnel de oportunidades

| symbol | compression | price_break | price+body | strict candidate | filled | rejected |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 8275 | 1016 | 756 | 393 | 12 | 389 |
| ETHUSDT | 7838 | 859 | 647 | 334 | 19 | 338 |

## Resultado shadow preenchido

### Total

| grupo | n | net_sum | avg | median | WR | PF | TP1% | TP1<=4% | false_breakout% | avg_dur |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ALL | 31 | -3.1279% | -0.1009% | -0.5729% | 32.3% | 0.79 | 32.3% | 0.0% | 67.7% | 30.2 |

### Por símbolo

| grupo | n | net_sum | avg | median | WR | PF | TP1% | TP1<=4% | false_breakout% | avg_dur |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 12 | -0.3298% | -0.0275% | -0.5380% | 33.3% | 0.94 | 33.3% | 0.0% | 66.7% | 35.2 |
| ETHUSDT | 19 | -2.7981% | -0.1473% | -0.5804% | 31.6% | 0.70 | 31.6% | 0.0% | 68.4% | 27.0 |

### Por regime aproximado

| grupo | n | net_sum | avg | median | WR | PF | TP1% | TP1<=4% | false_breakout% | avg_dur |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RANGING | 6 | -3.8715% | -0.6453% | -0.7303% | 0.0% | 0.00 | 0.0% | 0.0% | 100.0% | 18.3 |
| TRENDING | 9 | +0.6822% | +0.0758% | -0.5342% | 44.4% | 1.18 | 44.4% | 0.0% | 55.6% | 32.1 |
| VOLATILE | 5 | -0.8894% | -0.1779% | -0.5729% | 20.0% | 0.66 | 20.0% | 0.0% | 80.0% | 24.8 |
| WEAK_TREND | 11 | +0.9508% | +0.0864% | -0.3920% | 45.5% | 1.22 | 45.5% | 0.0% | 54.5% | 37.5 |

### Por direção

| grupo | n | net_sum | avg | median | WR | PF | TP1% | TP1<=4% | false_breakout% | avg_dur |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LONG | 11 | -3.2348% | -0.2941% | -0.6993% | 27.3% | 0.46 | 27.3% | 0.0% | 72.7% | 26.5 |
| SHORT | 20 | +0.1070% | +0.0053% | -0.5349% | 35.0% | 1.01 | 35.0% | 0.0% | 65.0% | 32.2 |

### Por exit_reason

| grupo | n | net_sum | avg | median | WR | PF | TP1% | TP1<=4% | false_breakout% | avg_dur |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sl_breakeven | 3 | +1.5705% | +0.5235% | +0.5923% | 100.0% | inf | 100.0% | 0.0% | 0.0% | 21.7 |
| sl_hit | 18 | -13.7805% | -0.7656% | -0.8110% | 0.0% | 0.00 | 0.0% | 0.0% | 100.0% | 18.6 |
| timeout | 8 | +6.1764% | +0.7720% | +1.2369% | 62.5% | 7.17 | 62.5% | 0.0% | 37.5% | 60.0 |
| tp2_hit | 2 | +2.9057% | +1.4529% | +1.4529% | 100.0% | inf | 100.0% | 0.0% | 0.0% | 28.0 |

### Top danos

- 2026-06-09 00:35:00 ETHUSDT SHORT TRENDING sl_hit: pnl=-0.9507% mfe4=0.6674% mae4=0.1588%
- 2026-06-07 12:35:00 BTCUSDT SHORT TRENDING sl_hit: pnl=-0.9170% mfe4=0.4154% mae4=0.2165%
- 2026-05-27 13:45:00 ETHUSDT SHORT RANGING sl_hit: pnl=-0.9062% mfe4=0.0200% mae4=0.9003%
- 2026-06-05 03:10:00 BTCUSDT SHORT WEAK_TREND sl_hit: pnl=-0.9000% mfe4=0.1159% mae4=0.6700%
- 2026-06-10 13:35:00 ETHUSDT LONG WEAK_TREND sl_hit: pnl=-0.8801% mfe4=1.3008% mae4=0.0547%
- 2026-06-05 12:35:00 ETHUSDT SHORT TRENDING sl_hit: pnl=-0.8665% mfe4=0.3224% mae4=0.5550%
- 2026-06-03 05:55:00 BTCUSDT LONG WEAK_TREND sl_hit: pnl=-0.8625% mfe4=0.1465% mae4=0.2993%
- 2026-05-26 14:25:00 BTCUSDT LONG RANGING sl_hit: pnl=-0.8568% mfe4=0.4110% mae4=1.1479%
- 2026-05-15 02:35:00 ETHUSDT SHORT VOLATILE sl_hit: pnl=-0.8238% mfe4=0.0221% mae4=0.7535%
- 2026-06-02 02:30:00 ETHUSDT LONG WEAK_TREND sl_hit: pnl=-0.7982% mfe4=0.3089% mae4=0.1861%

### Top ganhos

- 2026-05-26 14:40:00 ETHUSDT SHORT VOLATILE tp2_hit: pnl=+1.7636% mfe4=0.4085% mae4=0.2367%
- 2026-06-05 23:20:00 BTCUSDT SHORT WEAK_TREND timeout: pnl=+1.7402% mfe4=1.0909% mae4=0.0627%
- 2026-06-02 22:50:00 BTCUSDT SHORT TRENDING timeout: pnl=+1.5000% mfe4=0.8539% mae4=0.1172%
- 2026-06-04 07:20:00 ETHUSDT SHORT WEAK_TREND timeout: pnl=+1.4637% mfe4=0.1712% mae4=0.4686%
- 2026-05-28 14:15:00 ETHUSDT LONG TRENDING timeout: pnl=+1.2470% mfe4=0.4863% mae4=0.3528%
- 2026-06-02 05:50:00 BTCUSDT SHORT TRENDING timeout: pnl=+1.2267% mfe4=0.2435% mae4=0.0551%
- 2026-05-14 14:20:00 ETHUSDT LONG WEAK_TREND tp2_hit: pnl=+1.1422% mfe4=0.2726% mae4=0.1043%
- 2026-06-04 01:20:00 BTCUSDT SHORT TRENDING sl_breakeven: pnl=+0.5974% mfe4=0.5010% mae4=0.4596%
- 2026-06-05 02:10:00 ETHUSDT SHORT WEAK_TREND sl_breakeven: pnl=+0.5923% mfe4=0.5439% mae4=0.2975%
- 2026-06-08 10:35:00 ETHUSDT LONG WEAK_TREND sl_breakeven: pnl=+0.3808% mfe4=0.0580% mae4=0.2476%

## Momentum Pullback no mesmo período

| regime | n | net_sum | net_avg |
|---|---:|---:|---:|
| WEAK_TREND | 43 | +1.8282% | +0.0425% |
| TRENDING | 43 | +8.5648% | +0.1992% |

## Leitura fria

- PF shadow total: 0.79; net_sum=-3.1279%; false_breakout=67.7%.
- Como descoberta inicial, não há sinal de edge líquido. Se continuar, precisa ser por hipótese estrutural nova, não ajuste fino.
- Não alterar executor/bot com base neste relatório.

