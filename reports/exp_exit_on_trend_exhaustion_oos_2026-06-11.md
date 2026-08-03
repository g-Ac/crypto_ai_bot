# EXP result: exit-on-trend_exhaustion OOS validation

- criteria: `/home/pi/crypto_ai_bot/reports/exp_exit_on_trend_exhaustion_criteria_2026-06-11.md`
- pinned criteria hash: `b686760bab2c350012c59593d5fd7774a662cbce54014312b8b155b276a50eae`
- csv: `/home/pi/crypto_ai_bot/reports/exp_exit_on_trend_exhaustion_oos_2026-06-11.csv`

## Amostra

- total trades: 283
- discovery trades (`id <= 156`): 156
- OOS trades (`id > 156`): 127
- OOS with any exhaustion price: 42

Discovery é contexto apenas; verdict vem de OOS.

## Discovery / in-sample context

### H1 discovery — WEAK_TREND only

- verdict: NO-GO
- reasons: dano individual excede -1.25%
- OOS trades: 156
- changed: 31
- improved: 17
- worsened: 14
- actual_net: -3.2303%
- sim_net: -1.4844%
- delta: +1.7459%
- max_damage: -1.6186%
- max_positive_trade_share: 13.6%
- max_positive_symbol_direction_share: 49.0%

Maiores melhorias:
- #156 BTCUSDT LONG timeout: actual=-1.606% sim=-0.440% delta=+1.165%
- #68 BTCUSDT LONG timeout: actual=-1.482% sim=-0.510% delta=+0.972%
- #53 ETHUSDT SHORT sl_hit: actual=-1.172% sim=-0.214% delta=+0.957%
- #10 BTCUSDT LONG sl_hit: actual=-1.286% sim=-0.494% delta=+0.792%
- #33 ETHUSDT SHORT sl_hit: actual=-0.921% sim=-0.243% delta=+0.678%
- #52 BTCUSDT SHORT sl_hit: actual=-1.618% sim=-1.052% delta=+0.566%
- #20 ETHUSDT LONG sl_hit: actual=-0.600% sim=-0.098% delta=+0.502%
- #92 BTCUSDT SHORT timeout: actual=-0.435% sim=+0.011% delta=+0.446%
- #111 BTCUSDT LONG sl_hit: actual=-0.600% sim=-0.159% delta=+0.441%
- #136 ETHUSDT SHORT sl_hit: actual=-0.790% sim=-0.414% delta=+0.376%

Maiores danos:
- #129 BTCUSDT SHORT tp1_hit: actual=+0.749% sim=-0.870% delta=-1.619%
- #14 ETHUSDT LONG tp2_hit: actual=+0.650% sim=-0.259% delta=-0.909%
- #130 BTCUSDT SHORT timeout: actual=-0.257% sim=-1.160% delta=-0.903%
- #44 BTCUSDT LONG tp2_hit: actual=+0.650% sim=-0.168% delta=-0.818%
- #135 ETHUSDT SHORT timeout: actual=+0.107% sim=-0.481% delta=-0.588%
- #22 BTCUSDT SHORT timeout: actual=-0.061% sim=-0.573% delta=-0.512%
- #90 ETHUSDT LONG tp1_hit: actual=+0.376% sim=-0.127% delta=-0.502%
- #128 ETHUSDT SHORT tp1_hit: actual=+0.777% sim=+0.435% delta=-0.343%
- #113 BTCUSDT LONG timeout: actual=-0.519% sim=-0.764% delta=-0.245%
- #35 ETHUSDT LONG timeout: actual=-0.221% sim=-0.354% delta=-0.133%

### H2 discovery — age <= 2 candles

- verdict: GO
- reasons: passou todos os critérios
- OOS trades: 156
- changed: 18
- improved: 11
- worsened: 7
- actual_net: -3.2303%
- sim_net: -0.8871%
- delta: +2.3432%
- max_damage: -0.9033%
- max_positive_trade_share: 20.6%
- max_positive_symbol_direction_share: 44.5%

Maiores melhorias:
- #156 BTCUSDT LONG timeout: actual=-1.606% sim=-0.440% delta=+1.165%
- #68 BTCUSDT LONG timeout: actual=-1.482% sim=-0.510% delta=+0.972%
- #53 ETHUSDT SHORT sl_hit: actual=-1.172% sim=-0.214% delta=+0.957%
- #92 BTCUSDT SHORT timeout: actual=-0.435% sim=+0.011% delta=+0.446%
- #55 ETHUSDT LONG sl_hit: actual=-0.807% sim=-0.366% delta=+0.441%
- #57 BTCUSDT LONG sl_hit: actual=-1.126% sim=-0.745% delta=+0.382%
- #136 ETHUSDT SHORT sl_hit: actual=-0.790% sim=-0.414% delta=+0.376%
- #25 ETHUSDT SHORT sl_hit: actual=-0.680% sim=-0.314% delta=+0.366%
- #34 BTCUSDT SHORT sl_hit: actual=-0.600% sim=-0.354% delta=+0.246%
- #134 BTCUSDT SHORT timeout: actual=-0.120% sim=+0.120% delta=+0.239%

Maiores danos:
- #130 BTCUSDT SHORT timeout: actual=-0.257% sim=-1.160% delta=-0.903%
- #44 BTCUSDT LONG tp2_hit: actual=+0.650% sim=-0.168% delta=-0.818%
- #135 ETHUSDT SHORT timeout: actual=+0.107% sim=-0.481% delta=-0.588%
- #90 ETHUSDT LONG tp1_hit: actual=+0.376% sim=-0.127% delta=-0.502%
- #113 BTCUSDT LONG timeout: actual=-0.519% sim=-0.764% delta=-0.245%
- #35 ETHUSDT LONG timeout: actual=-0.221% sim=-0.354% delta=-0.133%
- #61 BTCUSDT LONG sl_hit: actual=-0.600% sim=-0.729% delta=-0.129%
- #146 ETHUSDT LONG sl_hit: actual=-0.982% sim=-0.912% delta=+0.070%
- #134 BTCUSDT SHORT timeout: actual=-0.120% sim=+0.120% delta=+0.239%
- #34 BTCUSDT SHORT sl_hit: actual=-0.600% sim=-0.354% delta=+0.246%

## OOS verdict

### H1 OOS — WEAK_TREND only

- verdict: GO
- reasons: passou todos os critérios
- OOS trades: 127
- changed: 26
- improved: 16
- worsened: 10
- actual_net: -19.0795%
- sim_net: -15.3648%
- delta: +3.7147%
- max_damage: -0.4407%
- max_positive_trade_share: 17.5%
- max_positive_symbol_direction_share: 41.8%

Maiores melhorias:
- #240 ETHUSDT SHORT sl_hit: actual=-1.256% sim=-0.209% delta=+1.047%
- #239 ETHUSDT LONG sl_hit: actual=-1.220% sim=-0.262% delta=+0.958%
- #181 BTCUSDT SHORT timeout: actual=-1.437% sim=-0.498% delta=+0.939%
- #171 BTCUSDT SHORT sl_hit: actual=-0.723% sim=-0.215% delta=+0.507%
- #262 ETHUSDT SHORT sl_hit: actual=-0.600% sim=-0.137% delta=+0.463%
- #237 ETHUSDT SHORT sl_hit: actual=-0.815% sim=-0.392% delta=+0.423%
- #248 ETHUSDT LONG timeout: actual=-0.504% sim=-0.194% delta=+0.310%
- #280 ETHUSDT SHORT timeout: actual=-0.515% sim=-0.229% delta=+0.286%
- #165 ETHUSDT LONG timeout: actual=-0.209% sim=+0.049% delta=+0.257%
- #176 ETHUSDT SHORT sl_hit: actual=-0.713% sim=-0.495% delta=+0.218%

Maiores danos:
- #202 ETHUSDT SHORT tp1_hit: actual=+0.163% sim=-0.277% delta=-0.441%
- #249 ETHUSDT SHORT timeout: actual=-0.001% sim=-0.387% delta=-0.386%
- #222 ETHUSDT LONG timeout: actual=-0.058% sim=-0.352% delta=-0.293%
- #270 ETHUSDT SHORT timeout: actual=-0.402% sim=-0.654% delta=-0.253%
- #230 ETHUSDT LONG timeout: actual=+0.037% sim=-0.186% delta=-0.223%
- #168 ETHUSDT SHORT tp1_hit: actual=+0.291% sim=+0.098% delta=-0.193%
- #261 ETHUSDT SHORT tp1_hit: actual=+0.052% sim=-0.104% delta=-0.155%
- #274 BTCUSDT LONG timeout: actual=-0.131% sim=-0.265% delta=-0.134%
- #259 ETHUSDT SHORT tp1_hit: actual=+0.064% sim=-0.067% delta=-0.131%
- #256 ETHUSDT LONG timeout: actual=-0.710% sim=-0.766% delta=-0.056%

### H2 OOS — age <= 2 candles

- verdict: NO-GO
- reasons: delta total OOS < +2.0pp
- OOS trades: 127
- changed: 10
- improved: 5
- worsened: 5
- actual_net: -19.0795%
- sim_net: -17.4494%
- delta: +1.6301%
- max_damage: -0.7405%
- max_positive_trade_share: 36.2%
- max_positive_symbol_direction_share: 52.2%

Maiores melhorias:
- #240 ETHUSDT SHORT sl_hit: actual=-1.256% sim=-0.209% delta=+1.047%
- #181 BTCUSDT SHORT timeout: actual=-1.437% sim=-0.498% delta=+0.939%
- #262 ETHUSDT SHORT sl_hit: actual=-0.600% sim=-0.137% delta=+0.463%
- #165 ETHUSDT LONG timeout: actual=-0.209% sim=+0.049% delta=+0.257%
- #220 BTCUSDT LONG timeout: actual=-0.429% sim=-0.242% delta=+0.187%
- #197 BTCUSDT LONG timeout: actual=-0.100% sim=-0.222% delta=-0.122%
- #172 ETHUSDT SHORT sl_hit: actual=-0.600% sim=-0.733% delta=-0.133%
- #274 BTCUSDT LONG timeout: actual=-0.131% sim=-0.265% delta=-0.134%
- #272 BTCUSDT SHORT sl_hit: actual=-0.600% sim=-0.735% delta=-0.135%
- #164 ETHUSDT LONG timeout: actual=-1.112% sim=-1.853% delta=-0.740%

Maiores danos:
- #164 ETHUSDT LONG timeout: actual=-1.112% sim=-1.853% delta=-0.740%
- #272 BTCUSDT SHORT sl_hit: actual=-0.600% sim=-0.735% delta=-0.135%
- #274 BTCUSDT LONG timeout: actual=-0.131% sim=-0.265% delta=-0.134%
- #172 ETHUSDT SHORT sl_hit: actual=-0.600% sim=-0.733% delta=-0.133%
- #197 BTCUSDT LONG timeout: actual=-0.100% sim=-0.222% delta=-0.122%
- #220 BTCUSDT LONG timeout: actual=-0.429% sim=-0.242% delta=+0.187%
- #165 ETHUSDT LONG timeout: actual=-0.209% sim=+0.049% delta=+0.257%
- #262 ETHUSDT SHORT sl_hit: actual=-0.600% sim=-0.137% delta=+0.463%
- #181 BTCUSDT SHORT timeout: actual=-1.437% sim=-0.498% delta=+0.939%
- #240 ETHUSDT SHORT sl_hit: actual=-1.256% sim=-0.209% delta=+1.047%

## Leitura fria

Não alterar executor/bot com base neste resultado. Rodar novamente quando houver pelo menos 30 trades OOS e 10 trades alterados por hipótese.
