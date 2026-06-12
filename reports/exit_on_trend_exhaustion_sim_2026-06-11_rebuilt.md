# Simulação reconstruída: exit-on-trend_exhaustion pós-entrada

Fonte: `runtime/baseline/bot.db` (`momentum_trades`, `momentum_decisions`) + Binance Futures API 15m klines (`fapi/v1/klines`, via `curl`).
Janela: `momentum_trades.id <= 156`, para bater com a autópsia visual original.

## Premissas e limitações

- Entrada por trade mapeada ao `momentum_decisions outcome=trade blocked_by=none` mais próximo da entrada estimada por `exit_time - duration_candles*15m`, dentro de ±75min.
- Evento de saída: primeiro `trend_exhaustion` após essa decisão de entrada e antes da saída real.
- Preços testados: `current_close` do candle 15m do evento, `next_open` e `next_close` do candle seguinte.
- Fees: usa `total_cost_bps` do trade, normalmente 10 bps.
- Isto ainda é simulação descritiva, não regra operacional. A semântica exata do timestamp do `momentum_decisions` precisa ser confirmada no código antes de implementação.

## Cobertura

- Trades: 156
- Net real total: -3.2303%
- Klines BTCUSDT: 5356 candles 15m
- Klines ETHUSDT: 5356 candles 15m
- Trades sem decisão de entrada mapeada: 0
- Casos com trend_exhaustion pós-entrada e preço disponível: 55
- Casos com trend_exhaustion mas preço ausente: 0

## Resultado agregado

- current_close (close do candle do evento): changed=55, improved=32, worsened=23, sim_net=-5.0242%, delta=-1.7939%
- next_open (open do próximo candle): changed=55, improved=32, worsened=23, sim_net=-5.0244%, delta=-1.7941%
- next_close (close do próximo candle): changed=55, improved=28, worsened=27, sim_net=-5.9155%, delta=-2.6852%

## Segmentos usando next_open

### exit_reason
- sl_hit: n=34, changed=24, actual=-26.923%, sim=-19.454%, delta=+7.469%
- timeout: n=48, changed=23, actual=-11.184%, sim=-13.092%, delta=-1.908%
- tp1_hit: n=66, changed=5, actual=+28.111%, sim=+24.137%, delta=-3.974%
- tp2_hit: n=8, changed=3, actual=+6.766%, sim=+3.385%, delta=-3.381%

### symbol
- BTCUSDT: n=87, changed=32, actual=-6.423%, sim=-6.020%, delta=+0.403%
- ETHUSDT: n=69, changed=23, actual=+3.193%, sim=+0.996%, delta=-2.197%

### direction
- LONG: n=75, changed=27, actual=-10.612%, sim=-10.267%, delta=+0.346%
- SHORT: n=81, changed=28, actual=+7.382%, sim=+5.242%, delta=-2.140%

### regime
- TRENDING: n=78, changed=24, actual=+0.616%, sim=-2.924%, delta=-3.540%
- WEAK_TREND: n=78, changed=31, actual=-3.847%, sim=-2.101%, delta=+1.746%

### symbol_direction
- BTCUSDT LONG: n=45, changed=18, actual=-11.074%, sim=-8.487%, delta=+2.588%
- BTCUSDT SHORT: n=42, changed=14, actual=+4.651%, sim=+2.466%, delta=-2.185%
- ETHUSDT LONG: n=30, changed=9, actual=+0.462%, sim=-1.780%, delta=-2.242%
- ETHUSDT SHORT: n=39, changed=14, actual=+2.731%, sim=+2.776%, delta=+0.045%

## Maiores melhorias com next_open
- #156 BTCUSDT LONG timeout: actual=-1.606% sim=-0.440% delta=+1.165% entry_dec=2026-06-10 17:15:00 exhaustion=2026-06-10 17:45:00 exit_price=61944.4
- #68 BTCUSDT LONG timeout: actual=-1.482% sim=-0.510% delta=+0.972% entry_dec=2026-05-11 00:30:00 exhaustion=2026-05-11 01:00:00 exit_price=81466.1
- #53 ETHUSDT SHORT sl_hit: actual=-1.172% sim=-0.214% delta=+0.957% entry_dec=2026-05-04 15:30:00 exhaustion=2026-05-04 15:45:00 exit_price=2348.63
- #10 BTCUSDT LONG sl_hit: actual=-1.286% sim=-0.494% delta=+0.792% entry_dec=2026-04-19 14:30:00 exhaustion=2026-04-19 16:30:00 exit_price=75522.1
- #33 ETHUSDT SHORT sl_hit: actual=-0.921% sim=-0.243% delta=+0.678% entry_dec=2026-04-28 14:15:00 exhaustion=2026-04-28 16:15:00 exit_price=2276.23
- #52 BTCUSDT SHORT sl_hit: actual=-1.618% sim=-1.052% delta=+0.566% entry_dec=2026-05-04 11:45:00 exhaustion=2026-05-04 14:30:00 exit_price=79484.5
- #20 ETHUSDT LONG sl_hit: actual=-0.600% sim=-0.098% delta=+0.502% entry_dec=2026-04-22 21:30:00 exhaustion=2026-04-22 22:45:00 exit_price=2398.96
- #92 BTCUSDT SHORT timeout: actual=-0.435% sim=+0.011% delta=+0.446% entry_dec=2026-05-17 16:15:00 exhaustion=2026-05-17 16:45:00 exit_price=77995.1
- #55 ETHUSDT LONG sl_hit: actual=-0.807% sim=-0.366% delta=+0.441% entry_dec=2026-05-05 14:30:00 exhaustion=2026-05-05 14:45:00 exit_price=2377.28
- #111 BTCUSDT LONG sl_hit: actual=-0.600% sim=-0.159% delta=+0.441% entry_dec=2026-05-28 23:15:00 exhaustion=2026-05-29 01:45:00 exit_price=73558.5
- #57 BTCUSDT LONG sl_hit: actual=-1.126% sim=-0.745% delta=+0.382% entry_dec=2026-05-06 13:15:00 exhaustion=2026-05-06 13:45:00 exit_price=81621.4
- #136 ETHUSDT SHORT sl_hit: actual=-0.790% sim=-0.414% delta=+0.376% entry_dec=2026-06-06 20:45:00 exhaustion=2026-06-06 21:15:00 exit_price=1560.66
- #25 ETHUSDT SHORT sl_hit: actual=-0.680% sim=-0.314% delta=+0.366% entry_dec=2026-04-24 10:15:00 exhaustion=2026-04-24 10:45:00 exit_price=2314.54
- #91 BTCUSDT LONG sl_hit: actual=-0.600% sim=-0.269% delta=+0.331% entry_dec=2026-05-17 11:30:00 exhaustion=2026-05-17 13:15:00 exit_price=78259.2
- #148 ETHUSDT LONG sl_hit: actual=-1.121% sim=-0.796% delta=+0.325% entry_dec=2026-06-08 22:45:00 exhaustion=2026-06-09 00:00:00 exit_price=1684.77
- #72 ETHUSDT SHORT timeout: actual=-0.881% sim=-0.563% delta=+0.319% entry_dec=2026-05-12 17:15:00 exhaustion=2026-05-12 19:30:00 exit_price=2282.13
- #112 BTCUSDT LONG timeout: actual=-0.546% sim=-0.271% delta=+0.274% entry_dec=2026-05-29 08:15:00 exhaustion=2026-05-29 10:30:00 exit_price=73576.5
- #75 ETHUSDT SHORT sl_hit: actual=-0.600% sim=-0.329% delta=+0.271% entry_dec=2026-05-13 23:30:00 exhaustion=2026-05-14 00:15:00 exit_price=2262.66
- #23 BTCUSDT SHORT sl_hit: actual=-0.987% sim=-0.721% delta=+0.266% entry_dec=2026-04-23 12:15:00 exhaustion=2026-04-23 14:45:00 exit_price=78132.8
- #11 BTCUSDT SHORT timeout: actual=-0.608% sim=-0.353% delta=+0.255% entry_dec=2026-04-20 00:15:00 exhaustion=2026-04-20 02:00:00 exit_price=74346.4
- #24 ETHUSDT SHORT timeout: actual=-0.845% sim=-0.591% delta=+0.253% entry_dec=2026-04-23 19:15:00 exhaustion=2026-04-23 20:45:00 exit_price=2324.08
- #154 BTCUSDT SHORT sl_hit: actual=-0.859% sim=-0.609% delta=+0.250% entry_dec=2026-06-10 10:45:00 exhaustion=2026-06-10 12:30:00 exit_price=61660.0
- #34 BTCUSDT SHORT sl_hit: actual=-0.600% sim=-0.354% delta=+0.246% entry_dec=2026-04-28 19:15:00 exhaustion=2026-04-28 19:45:00 exit_price=76293.5
- #9 BTCUSDT SHORT timeout: actual=-0.493% sim=-0.250% delta=+0.243% entry_dec=2026-04-19 08:45:00 exhaustion=2026-04-19 11:15:00 exit_price=75331.5
- #134 BTCUSDT SHORT timeout: actual=-0.120% sim=+0.120% delta=+0.239% entry_dec=2026-06-06 12:00:00 exhaustion=2026-06-06 12:15:00 exit_price=60698.3

## Maiores pioras com next_open
- #133 ETHUSDT SHORT timeout: actual=+0.824% sim=-1.020% delta=-1.844% entry_dec=2026-06-06 07:00:00 exhaustion=2026-06-06 07:45:00 exit_price=1574.54
- #147 ETHUSDT LONG tp2_hit: actual=+1.221% sim=-0.433% delta=-1.654% entry_dec=2026-06-08 18:00:00 exhaustion=2026-06-08 20:30:00 exit_price=1685.82
- #129 BTCUSDT SHORT tp1_hit: actual=+0.749% sim=-0.870% delta=-1.619% entry_dec=2026-06-05 04:15:00 exhaustion=2026-06-05 05:00:00 exit_price=63356.6
- #14 ETHUSDT LONG tp2_hit: actual=+0.650% sim=-0.259% delta=-0.909% entry_dec=2026-04-20 15:30:00 exhaustion=2026-04-20 16:30:00 exit_price=2305.69
- #130 BTCUSDT SHORT timeout: actual=-0.257% sim=-1.160% delta=-0.903% entry_dec=2026-06-05 07:30:00 exhaustion=2026-06-05 07:45:00 exit_price=63075.5
- #153 BTCUSDT SHORT tp1_hit: actual=+0.343% sim=-0.528% delta=-0.872% entry_dec=2026-06-10 06:30:00 exhaustion=2026-06-10 07:15:00 exit_price=61614.8
- #44 BTCUSDT LONG tp2_hit: actual=+0.650% sim=-0.168% delta=-0.818% entry_dec=2026-05-02 17:45:00 exhaustion=2026-05-02 18:15:00 exit_price=78360.4
- #150 BTCUSDT SHORT timeout: actual=-0.207% sim=-0.978% delta=-0.770% entry_dec=2026-06-09 18:00:00 exhaustion=2026-06-09 20:00:00 exit_price=62186.8
- #58 ETHUSDT SHORT tp1_hit: actual=+0.362% sim=-0.277% delta=-0.639% entry_dec=2026-05-07 11:30:00 exhaustion=2026-05-07 12:30:00 exit_price=2332.22
- #135 ETHUSDT SHORT timeout: actual=+0.107% sim=-0.481% delta=-0.588% entry_dec=2026-06-06 16:30:00 exhaustion=2026-06-06 17:00:00 exit_price=1561.61
- #22 BTCUSDT SHORT timeout: actual=-0.061% sim=-0.573% delta=-0.512% entry_dec=2026-04-23 04:45:00 exhaustion=2026-04-23 06:15:00 exit_price=78238.1
- #90 ETHUSDT LONG tp1_hit: actual=+0.376% sim=-0.127% delta=-0.502% entry_dec=2026-05-17 06:30:00 exhaustion=2026-05-17 06:45:00 exit_price=2184.03
- #18 ETHUSDT LONG timeout: actual=-0.789% sim=-1.172% delta=-0.382% entry_dec=2026-04-22 15:45:00 exhaustion=2026-04-22 16:45:00 exit_price=2385.37
- #15 BTCUSDT LONG timeout: actual=-0.157% sim=-0.533% delta=-0.377% entry_dec=2026-04-20 22:00:00 exhaustion=2026-04-20 23:30:00 exit_price=75732.9
- #128 ETHUSDT SHORT tp1_hit: actual=+0.777% sim=+0.435% delta=-0.343% entry_dec=2026-06-04 23:45:00 exhaustion=2026-06-05 00:45:00 exit_price=1758.52
- #140 BTCUSDT LONG timeout: actual=-1.120% sim=-1.370% delta=-0.250% entry_dec=2026-06-07 10:00:00 exhaustion=2026-06-07 12:30:00 exit_price=61623.8
- #113 BTCUSDT LONG timeout: actual=-0.519% sim=-0.764% delta=-0.245% entry_dec=2026-05-29 18:30:00 exhaustion=2026-05-29 18:45:00 exit_price=73342.9
- #35 ETHUSDT LONG timeout: actual=-0.221% sim=-0.354% delta=-0.133% entry_dec=2026-04-28 21:15:00 exhaustion=2026-04-28 21:30:00 exit_price=2286.35
- #61 BTCUSDT LONG sl_hit: actual=-0.600% sim=-0.729% delta=-0.129% entry_dec=2026-05-08 12:45:00 exhaustion=2026-05-08 13:15:00 exit_price=79569.5
- #1 BTCUSDT LONG timeout: actual=-0.247% sim=-0.355% delta=-0.107% entry_dec=2026-04-16 04:00:00 exhaustion=2026-04-16 07:45:00 exit_price=74667.7
- #67 BTCUSDT LONG sl_hit: actual=-0.670% sim=-0.743% delta=-0.073% entry_dec=2026-05-10 18:45:00 exhaustion=2026-05-10 20:30:00 exit_price=80757.1
- #62 BTCUSDT LONG sl_hit: actual=-0.600% sim=-0.659% delta=-0.059% entry_dec=2026-05-08 14:30:00 exhaustion=2026-05-08 15:15:00 exit_price=79683.4
- #96 BTCUSDT SHORT timeout: actual=-0.406% sim=-0.427% delta=-0.021% entry_dec=2026-05-18 17:15:00 exhaustion=2026-05-18 19:30:00 exit_price=76861.0
- #60 ETHUSDT SHORT timeout: actual=-0.004% sim=+0.002% delta=+0.006% entry_dec=2026-05-08 04:15:00 exhaustion=2026-05-08 08:00:00 exit_price=2280.24
- #110 ETHUSDT SHORT sl_hit: actual=-0.677% sim=-0.652% delta=+0.025% entry_dec=2026-05-28 15:15:00 exhaustion=2026-05-28 16:15:00 exit_price=1997.9

## Trades discutidos
- #146 ETHUSDT LONG: actual=-0.982%, entry_dec=2026-06-08 16:30:00, first_exh=2026-06-08 17:00:00, current_close=-0.912% @ 1677.74; next_open=-0.912% @ 1677.73; next_close=-0.458% @ 1685.42
- #148 ETHUSDT LONG: actual=-1.121%, entry_dec=2026-06-08 22:45:00, first_exh=2026-06-09 00:00:00, current_close=-0.795% @ 1684.78; next_open=-0.796% @ 1684.77; next_close=-1.399% @ 1674.53
- #154 BTCUSDT SHORT: actual=-0.859%, entry_dec=2026-06-10 10:45:00, first_exh=2026-06-10 12:30:00, current_close=-0.609% @ 61660.0; next_open=-0.609% @ 61660.0; next_close=-0.399% @ 61531.7
- #156 BTCUSDT LONG: actual=-1.606%, entry_dec=2026-06-10 17:15:00, first_exh=2026-06-10 17:45:00, current_close=-0.440% @ 61944.5; next_open=-0.440% @ 61944.4; next_close=-0.463% @ 61930.2

## Refinamentos observáveis testados

Preço usado: `next_open` após o primeiro `trend_exhaustion`.

- all trend_exhaustion: changed=55, improved=32, worsened=23, sim=-5.0244%, delta=-1.7941%
- only if unrealized gross <= 0 at next_open: changed=50, improved=28, worsened=22, sim=-5.8755%, delta=-2.6452%
- only if unrealized net <= 0 at next_open: changed=51, improved=29, worsened=22, sim=-5.3734%, delta=-2.1431%
- entry regime WEAK_TREND only: changed=31, improved=17, worsened=14, sim=-1.4844%, delta=+1.7459%
- WEAK_TREND and unrealized gross <= 0: changed=28, improved=15, worsened=13, sim=-2.0899%, delta=+1.1404%
- WEAK_TREND and unrealized net <= 0: changed=29, improved=16, worsened=13, sim=-1.5878%, delta=+1.6425%
- age <= 1 candles: changed=7, improved=3, worsened=4, sim=-3.3759%, delta=-0.1456%
- age <= 2 candles: changed=18, improved=11, worsened=7, sim=-0.8871%, delta=+2.3432%
- age <= 3 candles: changed=24, improved=13, worsened=11, sim=-4.8422%, delta=-1.6119%
- age <= 4 candles: changed=29, improved=14, worsened=15, sim=-7.0898%, delta=-3.8595%
- age <= 6 candles: changed=34, improved=17, worsened=17, sim=-6.8973%, delta=-3.6670%
- age <= 8 candles: changed=41, improved=22, worsened=19, sim=-5.4346%, delta=-2.2043%

Melhor refinamento nesta amostra: `age <= 2 candles`, delta=+2.3432%.

Mudanças principais nesse refinamento:

Melhorias:
- #156 BTCUSDT LONG WEAK_TREND timeout: actual=-1.606%, sim=-0.440%, delta=+1.165%
- #68 BTCUSDT LONG WEAK_TREND timeout: actual=-1.482%, sim=-0.510%, delta=+0.972%
- #53 ETHUSDT SHORT WEAK_TREND sl_hit: actual=-1.172%, sim=-0.214%, delta=+0.957%
- #92 BTCUSDT SHORT WEAK_TREND timeout: actual=-0.435%, sim=+0.011%, delta=+0.446%
- #55 ETHUSDT LONG TRENDING sl_hit: actual=-0.807%, sim=-0.366%, delta=+0.441%
- #57 BTCUSDT LONG TRENDING sl_hit: actual=-1.126%, sim=-0.745%, delta=+0.382%
- #136 ETHUSDT SHORT WEAK_TREND sl_hit: actual=-0.790%, sim=-0.414%, delta=+0.376%
- #25 ETHUSDT SHORT WEAK_TREND sl_hit: actual=-0.680%, sim=-0.314%, delta=+0.366%

Piores danos:
- #130 BTCUSDT SHORT WEAK_TREND timeout: actual=-0.257%, sim=-1.160%, delta=-0.903%
- #44 BTCUSDT LONG WEAK_TREND tp2_hit: actual=+0.650%, sim=-0.168%, delta=-0.818%
- #135 ETHUSDT SHORT WEAK_TREND timeout: actual=+0.107%, sim=-0.481%, delta=-0.588%
- #90 ETHUSDT LONG WEAK_TREND tp1_hit: actual=+0.376%, sim=-0.127%, delta=-0.502%
- #113 BTCUSDT LONG WEAK_TREND timeout: actual=-0.519%, sim=-0.764%, delta=-0.245%
- #35 ETHUSDT LONG WEAK_TREND timeout: actual=-0.221%, sim=-0.354%, delta=-0.133%
- #61 BTCUSDT LONG WEAK_TREND sl_hit: actual=-0.600%, sim=-0.729%, delta=-0.129%
- #146 ETHUSDT LONG TRENDING sl_hit: actual=-0.982%, sim=-0.912%, delta=+0.070%

## Leitura fria

- A hipótese ampla `exit-on-trend_exhaustion` usando `next_open` deu delta=-1.7941%. Isso não é GO operacional.
- O sinal ajuda bastante em vários `sl_hit`, mas também corta winners e alguns timeouts bons.
- Segmentos/refinamentos positivos nesta mesma amostra devem ser tratados como hipótese, não como regra, porque foram encontrados depois de olhar os resultados.
- Próximo passo protocolar, se continuar: mini-EXP congelado com critérios antes de nova simulação/validação. Não alterar o executor direto.

Verdict: DADO INSUFICIENTE para mudança operacional; hipótese útil para EXP, especialmente se pré-registrar `WEAK_TREND`/idade do exhaustion sem tunar após resultado.
