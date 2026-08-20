# Autópsia: near-TP misses e trend_exhaustion pós-entrada

Fonte: `runtime/baseline/bot.db`, tabela `momentum_trades` e `momentum_decisions`.
Janela: trades `id <= 156`, para bater com o relatório visual original de 156 trades.

Importante: análise descritiva. Não é mudança operacional. Não vira filtro sem mini-spec e forward/backtest escopado.

## Higiene metodológica

- Unidade principal: execução real em `momentum_trades`, não ciclos de sinal.
- `MFE/TP1` = `mfe_pct / distância percentual da entrada até TP1`.
- Falha near-TP = trade com `exit_reason in ('sl_hit', 'timeout')` que atingiu pelo menos X% do caminho até TP1.
- Estimativas de política são aproximadas porque `momentum_trades` guarda MFE/MAE agregados, não a ordem intratrade dos eventos. Sem path intrabar/candle-a-candle, não dá para provar que uma regra teria sido executável exatamente naquele ponto.
- Custos aproximados nas simulações: 10 bps, coerente com `flat_taker` observado.

## Base

- Trades analisados: 156
- Net total: -3.2303%
- Gross total: +12.3697%
- WR net > 0: 55.1%

## Near-TP failures

MFE >= threshold * TP1 e `exit_reason` em `sl_hit` ou `timeout`:

- >=70% TP1: reached=94, failures=20, winners=74, failure_net_sum=-9.72%, reached_actual_net=+25.15%
- >=80% TP1: reached=85, failures=11, winners=74, failure_net_sum=-5.91%, reached_actual_net=+28.96%
- >=90% TP1: reached=78, failures=4, winners=74, failure_net_sum=-2.23%, reached_actual_net=+32.65%
- >=95% TP1: reached=76, failures=2, winners=74, failure_net_sum=-1.56%, reached_actual_net=+33.32%
- >=99% TP1: reached=75, failures=1, winners=74, failure_net_sum=-1.12%, reached_actual_net=+33.76%

### Falhas >=80% TP1

- #148 ETHUSDT LONG sl_hit net=-1.12%, MFE/TP1=99.7%
- #92 BTCUSDT SHORT timeout net=-0.43%, MFE/TP1=97.1%
- #67 BTCUSDT LONG sl_hit net=-0.67%, MFE/TP1=91.8%
- #60 ETHUSDT SHORT timeout net=-0.00%, MFE/TP1=90.9%
- #20 ETHUSDT LONG sl_hit net=-0.60%, MFE/TP1=85.7%
- #17 BTCUSDT LONG timeout net=+0.14%, MFE/TP1=85.4%
- #9 BTCUSDT SHORT timeout net=-0.49%, MFE/TP1=84.6%
- #112 BTCUSDT LONG timeout net=-0.55%, MFE/TP1=84.6%
- #96 BTCUSDT SHORT timeout net=-0.41%, MFE/TP1=83.3%
- #33 ETHUSDT SHORT sl_hit net=-0.92%, MFE/TP1=81.3%
- #154 BTCUSDT SHORT sl_hit net=-0.86%, MFE/TP1=81.1%

## Estimativa de política: sair no threshold

Política hipotética: se MFE >= threshold*TP1, sair nesse ponto para todos os trades que chegaram lá.
Aproximada; path/order desconhecido.

- th=70%: changed=94, fail_help=20, winner_hurt=74, actual=-3.23%, sim=-0.59%, delta=+2.64%
- th=80%: changed=85, fail_help=11, winner_hurt=74, actual=-3.23%, sim=-3.65%, delta=-0.42%
- th=90%: changed=78, fail_help=4, winner_hurt=74, actual=-3.23%, sim=-5.55%, delta=-2.32%
- th=95%: changed=76, fail_help=2, winner_hurt=74, actual=-3.23%, sim=-4.87%, delta=-1.64%
- th=99%: changed=75, fail_help=1, winner_hurt=74, actual=-3.23%, sim=-3.84%, delta=-0.61%

Leitura: proteção/take antecipado por MFE perto de TP1 não é GO automático. O único threshold que melhora nessa simulação bruta é 70%, mas ele corta 94 trades e prejudica muitos winners. 80/90/95/99 pioram ou ficam fracos. O #148 é visualmente irritante, mas isolado demais para justificar regra.

## Trades discutidos

- #154 BTCUSDT SHORT: sl_hit, net=-0.8585%, MFE=+0.7837%, TP1move=0.9666%, MFE/TP1=81.08%.
  - Classe: near-TP moderado. Chegou perto, mas não o suficiente. Não sustenta regra por si só.

- #148 ETHUSDT LONG: sl_hit, net=-1.1209%, MFE=+1.0539%, TP1move=1.0568%, MFE/TP1=99.72%.
  - Classe: near-TP extremo. Quase TP1 no centavo. Melhor exemplo para estudar, mas é 1 caso em 156 no threshold >=99%.

- #146 ETHUSDT LONG: sl_hit, net=-0.9821%, MFE=+0.3707%, TP1move=0.8720%, MFE/TP1=42.51%.
  - Classe: falha de entrada/contexto ou continuação fraca. Não é near-TP.

- #156 BTCUSDT LONG: timeout, net=-1.6059%, MFE=+0.0579%, TP1move=1.1294%, MFE/TP1=5.13%.
  - Classe: sem follow-through. Não é near-TP.

## trend_exhaustion/regime_blocked pós-entrada

Associação descritiva entre presença de sinais pós-entrada em `momentum_decisions` e resultado do trade:

- trend_exhaustion=False, regime_blocked=False: n=95, WR=75.8%, net_sum=+22.66%, avg=+0.238%
- trend_exhaustion=False, regime_blocked=True: n=7, WR=57.1%, net_sum=-1.98%, avg=-0.283%
- trend_exhaustion=True, regime_blocked=False: n=50, WR=18.0%, net_sum=-23.01%, avg=-0.460%
- trend_exhaustion=True, regime_blocked=True: n=4, WR=25.0%, net_sum=-0.90%, avg=-0.224%

Leitura: `trend_exhaustion` pós-entrada tem associação muito forte com trades ruins. Isso não prova uma regra de saída ainda, porque é sinal pós-entrada e precisa de preço/path no momento do evento. Mas é uma hipótese mais promissora que near-TP protection.

## Conclusão fria

1. Near-TP protection não passa como GO nessa medição bruta.
   - O caso #148 dói, mas é exceção no threshold extremo.
   - Sair em 80/90/95/99% do caminho até TP1 não melhora a soma aproximada.
   - 70% melhora no agregado bruto, mas mexe em muitos winners; alto risco de overfit/estragar convexidade.

2. A família mais promissora para próxima investigação é `trend_exhaustion` pós-entrada.
   - Trades sem trend_exhaustion pós-entrada: WR 75.8%, net +22.66%.
   - Trades com trend_exhaustion: WR ~18%, net -23.01% na classe principal.
   - Próximo passo correto: medir uma política de saída no primeiro `trend_exhaustion`, usando preço/candle disponível naquele timestamp, não apenas MFE/MAE agregado.

3. Separação dos trades discutidos:
   - #148 e #154: near-TP / quase deu certo.
   - #146 e #156: problema de continuação/contexto, não near-TP.

## Próximo experimento sugerido

EXP candidato: "exit-on-trend-exhaustion pós-entrada".

Antes de codar regra no bot:

- Definir critérios congelados.
- Reconstruir preço no timestamp do primeiro `trend_exhaustion` após entrada.
- Simular saída no close desse candle ou próximo preço executável conservador.
- Comparar contra resultado real, com fees.
- Separar por symbol/direction/regime/session.
- Verificar se melhora vem de poucos outliers ou de distribuição robusta.

Verdict atual: DADO INSUFICIENTE para mudança operacional; hipótese de `trend_exhaustion` merece medição específica.
