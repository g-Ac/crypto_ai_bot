# EXP result: breakout_compression regime-gated shadow

- criteria: `/home/pi/crypto_ai_bot/reports/exp_breakout_regime_gated_criteria_2026-06-12.md`
- pinned criteria hash: `e5d942591a7f86cdb3d58e66a0e669a87f66fafe8450a47576318b7a34edbcbc`
- csv: `/home/pi/crypto_ai_bot/reports/exp_breakout_regime_gated_shadow_2026-06-12.csv`
- run_end_utc: 2026-06-12T04:18:59.151132+00:00

## Signal counts

- discovery_blocked_by_regime: 373
- discovery_eligible_signal: 392
- discovery_raw_signal: 765
- oos_blocked_by_regime: 2
- oos_eligible_signal: 1
- oos_raw_signal: 3

## Results

### discovery

- verdict: DISCOVERY_ONLY
- reasons: discovery/in-sample não decide GO
- raw rows/signals recorded: 765
- filled trades: 20
- blocked_by_regime: 373
- rejected_by_risk: 372
- net: +1.6330% | avg: +0.0816% | median: -0.4631%
- WR: 45.0% | PF: 1.20
- false_breakout: 55.0% | TP1: 45.0% | TP2: 5.0% | timeout: 30.0%
- max_damage: -0.9507%
- max_positive_trade_share: 17.6%
- max_positive_day_share: 27.6%
- max_positive_symbol_direction_share: 51.2%

Por symbol:
- BTCUSDT: n=8 net=+1.8507% avg=+0.2313% PF=1.58
- ETHUSDT: n=12 net=-0.2177% avg=-0.0181% PF=0.96

Por regime:
- TRENDING: n=9 net=+0.6822% avg=+0.0758% PF=1.18
- WEAK_TREND: n=11 net=+0.9508% avg=+0.0864% PF=1.22

Por direction:
- LONG: n=7 net=-0.3914% avg=-0.0559% PF=0.88
- SHORT: n=13 net=+2.0244% avg=+0.1557% PF=1.40

Por exit_reason:
- sl_breakeven: n=3 net=+1.5705% avg=+0.5235% PF=inf
- sl_hit: n=10 net=-7.8653% avg=-0.7865% PF=0.00
- timeout: n=6 net=+6.7856% avg=+1.1309% PF=18.31
- tp2_hit: n=1 net=+1.1422% avg=+1.1422% PF=inf

Maiores ganhos:
- 2026-06-05 23:20:00 BTCUSDT SHORT WEAK_TREND timeout: +1.7402%
- 2026-06-02 22:50:00 BTCUSDT SHORT TRENDING timeout: +1.5000%
- 2026-06-04 07:20:00 ETHUSDT SHORT WEAK_TREND timeout: +1.4637%
- 2026-05-28 14:15:00 ETHUSDT LONG TRENDING timeout: +1.2470%
- 2026-06-02 05:50:00 BTCUSDT SHORT TRENDING timeout: +1.2267%
- 2026-05-14 14:20:00 ETHUSDT LONG WEAK_TREND tp2_hit: +1.1422%
- 2026-06-04 01:20:00 BTCUSDT SHORT TRENDING sl_breakeven: +0.5974%
- 2026-06-05 02:10:00 ETHUSDT SHORT WEAK_TREND sl_breakeven: +0.5923%
- 2026-06-08 10:35:00 ETHUSDT LONG WEAK_TREND sl_breakeven: +0.3808%
- 2026-05-19 01:25:00 ETHUSDT SHORT WEAK_TREND timeout: -0.3920%

Maiores danos:
- 2026-06-09 00:35:00 ETHUSDT SHORT TRENDING sl_hit: -0.9507%
- 2026-06-07 12:35:00 BTCUSDT SHORT TRENDING sl_hit: -0.9170%
- 2026-06-05 03:10:00 BTCUSDT SHORT WEAK_TREND sl_hit: -0.9000%
- 2026-06-10 13:35:00 ETHUSDT LONG WEAK_TREND sl_hit: -0.8801%
- 2026-06-05 12:35:00 ETHUSDT SHORT TRENDING sl_hit: -0.8665%
- 2026-06-03 05:55:00 BTCUSDT LONG WEAK_TREND sl_hit: -0.8625%
- 2026-06-02 02:30:00 ETHUSDT LONG WEAK_TREND sl_hit: -0.7982%
- 2026-06-01 12:30:00 ETHUSDT LONG TRENDING sl_hit: -0.6205%
- 2026-05-18 16:30:00 ETHUSDT SHORT WEAK_TREND sl_hit: -0.5356%
- 2026-05-28 13:35:00 BTCUSDT SHORT TRENDING sl_hit: -0.5342%

### oos

- verdict: DADO INSUFICIENTE
- reasons: menos de 30 trades shadow OOS preenchidos
- raw rows/signals recorded: 2
- filled trades: 0
- blocked_by_regime: 2
- rejected_by_risk: 0
- net: +0.0000% | avg: +0.0000% | median: +0.0000%
- WR: 0.0% | PF: 0.00
- false_breakout: 0.0% | TP1: 0.0% | TP2: 0.0% | timeout: 0.0%
- max_damage: +0.0000%

Maiores ganhos:

Maiores danos:

## Leitura fria

OOS ainda é pequeno demais. Pelo critério congelado, verdict obrigatório é DADO INSUFICIENTE.
Não alterar executor/bot com base neste resultado. Rodar novamente quando houver pelo menos 30 trades shadow OOS preenchidos.

