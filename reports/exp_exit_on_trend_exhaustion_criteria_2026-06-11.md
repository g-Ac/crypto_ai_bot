# EXP: exit-on-trend_exhaustion pós-entrada

Status: FROZEN CRITERIA
Data: 2026-06-11
Projeto: crypto_ai_bot / Momentum Pullback v1.1

## Objetivo

Testar, sem alterar o bot, se `trend_exhaustion` pós-entrada pode ser usado como regra de saída defensiva para reduzir perdas sem destruir winners.

Este EXP nasce após autópsia descritiva dos trades `id <= 156`, portanto os resultados nesses 156 trades são DISCOVERY/IN-SAMPLE. Eles não podem justificar mudança operacional direta.

## Hipóteses travadas

Apenas duas hipóteses candidatas podem ser testadas neste EXP:

H1 — WEAK_TREND only

- Se um trade foi aberto com `momentum_trades.regime = 'WEAK_TREND'`, sair no primeiro `trend_exhaustion` detectado após a decisão de entrada e antes da saída real.
- Trades em `TRENDING` não são alterados.

H2 — early exhaustion <= 2 candles

- Sair no primeiro `trend_exhaustion` apenas se ele aparece até 2 candles de 15m após a decisão de entrada.
- O limite é exatamente `age_candles <= 2`.
- Não testar outros limites como 1, 3, 4, 6, 8 nesta rodada.

## Proibido nesta rodada

- Não testar novas combinações depois de ver resultado.
- Não alterar threshold de idade.
- Não adicionar filtros por símbolo, direção, session_bucket, PnL não-realizado, MFE, MAE ou exit_reason.
- Não usar `MFE/MAE` como condição de saída; são labels agregadas pós-trade.
- Não usar `exit_reason` como condição; isso é informação futura.
- Não editar este arquivo depois de rodar o EXP. Se precisar mudar critério, abrir EXP novo com novo arquivo e novo hash.

## Fonte de dados

Tabelas:

- `momentum_trades`: execuções fechadas, PnL real, entrada/saída, fees.
- `momentum_decisions`: eventos por ciclo, especialmente `outcome='trade'`, `blocked_by='none'`, `trend_exhaustion`.
- Binance Futures API 15m klines: preço executável estimado no `next_open` do candle posterior ao `trend_exhaustion`.

## Mapeamento temporal

- Entrada estimada do trade: `exit_timestamp - duration_candles * 15min`.
- Decisão de entrada: `momentum_decisions outcome='trade' AND blocked_by='none'` mais próxima da entrada estimada dentro de ±75min, mesmo `symbol` e mesma `direction`.
- Evento de saída simulado: primeiro `trend_exhaustion` após a decisão de entrada e antes da saída real.
- Preço de saída simulado primário: `next_open` do candle 15m seguinte ao timestamp do `trend_exhaustion`.
- Fees: usar `total_cost_bps` do trade original.

## Janelas

Discovery / in-sample:

- `momentum_trades.id <= 156`.
- Pode ser reportado como contexto, mas não decide GO.

Validation / out-of-sample:

- `momentum_trades.id > 156`.
- Rodar sempre que houver novos trades fechados.
- Verdict só pode ser emitido quando houver no mínimo:
  - 30 trades fechados OOS, e
  - 10 trades OOS com `trend_exhaustion` aplicável em pelo menos uma das duas hipóteses.

Se a amostra for menor que isso, verdict obrigatório: DADO INSUFICIENTE.

## Métricas obrigatórias

Para cada hipótese H1 e H2:

- número de trades OOS totais;
- número de trades alterados pela hipótese;
- número de trades melhorados;
- número de trades piorados;
- PnL net real total;
- PnL net simulado total;
- delta simulado - real;
- delta por exit_reason apenas como diagnóstico, não como filtro;
- lista dos 10 maiores ganhos e 10 maiores danos da hipótese.

## Critério de GO / NO-GO / DADO INSUFICIENTE

DADO INSUFICIENTE se:

- OOS tem menos de 30 trades fechados; ou
- a hipótese altera menos de 10 trades OOS; ou
- dados de preço faltam para qualquer trade alterado.

NO-GO se qualquer condição abaixo ocorrer:

- delta total OOS <= 0;
- a hipótese piora mais trades do que melhora;
- qualquer dano individual excede -1.25% de delta contra o resultado real;
- ganho total vem de 1 único trade responsável por mais de 50% do delta positivo.

GO apenas se todas as condições abaixo ocorrerem:

- OOS suficiente conforme mínimo acima;
- delta total OOS >= +2.0 pontos percentuais;
- improved >= worsened;
- nenhum dano individual <= -1.25%;
- maior contribuição positiva individual <= 50% do delta positivo total;
- resultado não depende apenas de um símbolo/direção: se houver pelo menos 2 grupos symbol_direction alterados, nenhum grupo único pode responder por mais de 80% do delta positivo.

## Saída esperada

O runner deve gerar:

- CSV por trade com resultado real e simulado para H1/H2.
- Markdown resumindo discovery, OOS, verdict por hipótese e motivos.

## Regra operacional

Mesmo se uma hipótese der GO, não implementar direto no executor nesta sessão. O GO autoriza apenas uma mini-spec de implementação separada, com testes e revisão do código de execução.
