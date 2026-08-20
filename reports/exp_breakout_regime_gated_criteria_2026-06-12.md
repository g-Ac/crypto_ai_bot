# EXP: breakout_compression regime-gated shadow

Status: FROZEN CRITERIA
Data: 2026-06-12
Projeto: crypto_ai_bot / BreakoutEngine5m shadow

## Objetivo

Testar, sem alterar o bot, se o setup `compressão -> breakout confirmado -> continuação` só tem edge quando o regime maior já é direcional.

Este EXP nasce após dois relatórios discovery/read-only:

- `reports/breakout_compression_shadow_2026-06-12.md`
- `reports/breakout_regime_followthrough_autopsy_2026-06-12.md`

Os resultados desses relatórios são DISCOVERY/IN-SAMPLE. Eles não podem justificar mudança operacional direta.

## Hipótese travada

H1 — regime-gated breakout

- Usar exatamente o `BreakoutEngine5m` atual para detectar sinais.
- Não alterar parâmetros de lookback, range, BB bandwidth, volume, body, TP, SL ou timeout.
- Considerar elegível apenas sinal cujo regime aproximado no momento do sinal seja:
  - `TRENDING`, ou
  - `WEAK_TREND`.
- Sinais com regime `RANGING`, `VOLATILE`, `UNKNOWN` ou vazio são bloqueados no shadow.
- A simulação é serial por símbolo: não abre novo trade shadow no mesmo símbolo enquanto o anterior ainda estaria aberto.

## Proibido nesta rodada

- Não testar thresholds alternativos de volume/body/range/BB.
- Não alterar lookback mínimo/máximo.
- Não adicionar filtro por símbolo, direção, sessão, funding, OI, LSR, MFE/MAE, exit_reason ou liquidações.
- Não usar invalidação rápida nesta rodada; a autópsia discovery piorou o universo GOOD_REGIME.
- Não testar `TRENDING only` vs `WEAK_TREND only` como filtro operacional nesta rodada.
- Não editar este arquivo depois de rodar o EXP. Se precisar mudar critério, abrir EXP novo com novo arquivo e novo hash.

## Fonte de dados

- Binance Futures API 5m klines para BTCUSDT e ETHUSDT.
- `momentum_decisions` apenas como fonte aproximada de regime já existente.
- `BreakoutEngine5m` e `add_indicators_5m` do código atual.

## Mapeamento temporal

- Candle do sinal: candle 5m em que `BreakoutEngine5m.analyze()` retorna sinal válido.
- Entrada simulada: open do candle 5m seguinte ao candle do sinal.
- Regime aproximado: regime de `momentum_decisions` mais próximo do timestamp do sinal, mesmo símbolo, dentro de ±45min.
- Saída simulada: mesma lógica atual do breakout paper executor:
  - SL antes de TP no mesmo candle;
  - TP1 move stop para breakeven e posição segue;
  - TP2 fecha com preço blendado 50% TP1 + 50% TP2;
  - timeout em 60 candles de 5m;
  - custo diagnóstico round-trip: 0.10%.

## Janelas

Discovery / in-sample:

- 2026-05-13T00:00:00Z até 2026-06-12T00:00:00Z.
- Pode ser reportado como contexto, mas não decide GO.

Validation / out-of-sample:

- `start_ts >= 2026-06-12T00:00:00Z`.
- Rodar sempre que houver novos candles/regimes suficientes.
- Verdict só pode ser emitido quando houver no mínimo:
  - 30 trades shadow OOS preenchidos pela hipótese H1, e
  - pelo menos 10 trades OOS por símbolo combinado total não concentrado em um único dia.

Se a amostra for menor que isso, verdict obrigatório: DADO INSUFICIENTE.

## Métricas obrigatórias

Para discovery e OOS separadamente:

- número de sinais brutos do engine;
- número de sinais elegíveis por regime;
- número de trades shadow preenchidos;
- número de trades bloqueados por regime;
- PnL net total;
- PnL net médio e mediano;
- winrate;
- profit factor net;
- false breakout rate;
- TP1 hit rate;
- TP2 hit rate;
- timeout rate;
- resultado por símbolo;
- resultado por regime;
- resultado por direção;
- lista dos 10 maiores ganhos e 10 maiores danos;
- concentração do delta positivo por maior trade, maior dia e maior symbol_direction.

## Critério de GO / NO-GO / DADO INSUFICIENTE

DADO INSUFICIENTE se:

- OOS tem menos de 30 trades shadow preenchidos; ou
- dados de preço ou regime faltam para qualquer trade elegível; ou
- OOS tem trades concentrados em apenas 1 dia.

NO-GO se qualquer condição abaixo ocorrer:

- PnL net total OOS <= 0;
- PF net OOS < 1.20;
- winrate OOS < 40%;
- false breakout rate OOS > 60%;
- qualquer dano individual <= -1.25%;
- maior trade positivo responde por mais de 50% do lucro bruto positivo;
- maior dia responde por mais de 60% do lucro bruto positivo;
- se houver pelo menos 2 grupos symbol_direction, um único grupo responde por mais de 80% do lucro bruto positivo.

GO apenas se todas as condições abaixo ocorrerem:

- OOS suficiente conforme mínimo acima;
- PnL net total OOS > 0;
- PF net OOS >= 1.20;
- winrate OOS >= 40%;
- false breakout rate OOS <= 60%;
- nenhum dano individual <= -1.25%;
- concentração passa todos os limites acima.

## Saída esperada

O runner deve gerar:

- CSV por trade shadow com resultado simulado e regime usado.
- Markdown resumindo discovery, OOS, verdict e motivos.

## Regra operacional

Mesmo se H1 der GO, não implementar direto no executor nesta sessão. O GO autoriza apenas mini-spec separada de implementação/shadow-forward, com testes e revisão.
