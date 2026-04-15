# RISK FRAMEWORK — Sistema de Trading Defensivo

**Data:** 2026-04-14
**Status:** Especificacao V1

---

## Filosofia de risco

Este sistema trata o no-trade como posicao default. Operar e a excecao, nao a regra.
O objetivo nao e maximizar trades nem win rate. E minimizar fragilidade e preservar capital.

Risco e gerenciado em 4 camadas: trade, dia, semana, e sistema.

---

## Camada 1 — Risco por trade

| Parametro | Valor V1 | Notas |
|---|---|---|
| Risk por trade | 0.5% a 0.75% do capital | Ultra-conservador. Subir so com evidencia |
| Max posicoes simultaneas | 1 | Na V1 real. Backtest pode testar com 2 |
| Leverage maximo | 3x | Mesmo com confluencia alta |
| SL obrigatorio | Sim, definido antes da entrada | Nunca operar sem SL pre-definido |
| SL maximo permitido | 2.5% do preco de entrada | Se SL calculado > 2.5%, nao opera |
| RR minimo | 2.0 | Nunca entrar com RR < 2.0 |
| Position sizing | Kelly fracional (0.25 Kelly) ou fixo 0.5% | O menor dos dois |

### Regras adicionais da fase real 1

- **Sem aumento de mao apos sequencia de wins** — martingale reverso nao autorizado
- **Sem reentrada no mesmo lado apos stop** — 6 candles de cooldown direcional
- **Cooldown apos 2 losses seguidos** — proximo sinal ignorado, reset diario

### Calculo de position size

```
risk_amount = capital * risk_pct  (ex: $1000 * 0.5% = $5)
sl_distance = |entry_price - sl_price| / entry_price
position_size = risk_amount / sl_distance
margin_required = position_size / leverage

Se margin_required > 30% do capital → reduzir position_size
```

---

## Camada 2 — Limites diarios

| Parametro | Valor V1 | Acao |
|---|---|---|
| Max daily loss | 1.5% do capital | Pausa automatica ate proximo dia UTC |
| Max trades por dia | 3 | Mesmo com setups validos apos o 3o |
| Cooldown apos 2 losses seguidos | Obrigatorio | Pular proximo sinal, esperar reset |
| Reset de contadores | 00:00 UTC | Novo dia = contadores zerados |

### Logica do cooldown

```
Se last_2_trades == [LOSS, LOSS]:
    cooldown_active = True
    proximo sinal valido = IGNORADO
    cooldown_reset quando:
        - proximo dia UTC, OU
        - 1 trade vencedor em outro subsistema (pump) -- NAO, manter isolado
    cooldown_reset: proximo dia UTC apenas
```

O cooldown NAO se propaga entre subsistemas. Uma sequencia de losses no pump nao afeta o defensivo e vice-versa.

---

## Camada 3 — Limites semanais

| Parametro | Valor V1 | Acao |
|---|---|---|
| Max weekly loss | 3% do capital | Pausa ate segunda-feira 00:00 UTC |
| Max weekly trades | 15 | Hard cap |
| Min win rate semanal (alerta) | 35% | Alerta Telegram, nao pausa automatica |

---

## Camada 4 — Circuit breaker (sistema)

| Parametro | Valor V1 | Acao |
|---|---|---|
| Max drawdown desde inicio | 8% | **DESLIGA** sistema defensivo completamente |
| Max drawdown rolling 30 dias | 5% | Pausa ate revisao manual |
| Perda acumulada sem win | 5 trades | Pausa + alerta para revisao |

### Logica do circuit breaker

```
NIVEL 1 - ALERTA:
  3 losses seguidos OU weekly WR < 35%
  → Telegram alert + log
  → Continua operando

NIVEL 2 - PAUSA DIARIA:
  Daily loss >= 1.5% OU 2 losses seguidos (cooldown)
  → Para de abrir posicoes hoje
  → Gerencia posicoes abertas normalmente
  → Reset: proximo dia UTC

NIVEL 3 - PAUSA SEMANAL:
  Weekly loss >= 3% OU max weekly trades atingido
  → Para de abrir posicoes esta semana
  → Gerencia posicoes abertas normalmente
  → Reset: segunda-feira 00:00 UTC

NIVEL 4 - DESLIGAMENTO:
  Drawdown desde inicio >= 8% OU 5 losses seguidos sem win
  → Para TUDO
  → Alerta critico Telegram
  → Requer intervencao manual do Gabriel para religar
  → Antes de religar: revisar se hipotese estrategica ainda e valida
```

---

## Kill switches (inegociaveis)

Alem do circuit breaker financeiro, 3 kill switches de infraestrutura:

### Kill switch 1 — Data Quality

```
Se QUALQUER condicao:
  - Microestrutura com dados stale (> 5 min sem update)
  - Candles com gaps > 2 periodos consecutivos
  - OI retornando zero ou NaN
  - Funding rate retornando None por > 3 ciclos
  - Divergencia > 1% entre preco do candle e preco da microestrutura
ENTAO:
  → Bloquear NOVAS entradas
  → Gerenciar posicoes abertas com SL/TP existentes
  → Alerta Telegram: "[DATA] Dados degradados — defensive pausado"
  → Registrar no decision log: outcome = "data_quality_kill"
  → Retomar automaticamente quando dados voltarem ao normal por >= 3 ciclos
```

### Kill switch 2 — Latency / Exchange Failure

```
Se QUALQUER condicao:
  - API Binance retornando erro (4xx/5xx) por > 2 tentativas consecutivas
  - Timeout de request > 10s por > 2 tentativas
  - WebSocket de liquidacoes desconectado por > 10 min
  - Latencia media do ciclo > 2x a media historica
ENTAO:
  → Bloquear NOVAS entradas
  → Posicoes abertas: manter SL/TP (nao fechar no escuro)
  → Alerta Telegram: "[INFRA] Exchange instavel — defensive pausado"
  → Registrar: outcome = "latency_kill"
  → Retomar quando API estavel por >= 5 min
```

### Kill switch 3 — Regime Flip During Operation

```
Se posicao aberta E:
  - Regime muda de RANGING/WEAK_TREND para TRENDING/VOLATILE/CHOPPY
ENTAO:
  → Fechar posicao no preco atual (nao esperar SL/TP)
  → Exit reason = "regime_shift"
  → Nao abrir novas posicoes ate proximo ciclo confirmar regime permissivo
  → Registrar: motivo + regime anterior + regime novo
```

Este kill switch ja existia na gestao de posicao, mas aqui esta explicitado como INEGOCIAVEL. Regime shift e fechamento imediato, sem excecao.

### Regra extra: sem reentrada no mesmo lado apos stop

```
Se trade fechou por SL:
  → Nao reentrar na MESMA direcao no MESMO par por 6 candles (1.5h em 15m)
  → Direcao oposta: permitida se setup valido
  → Motivo: evitar revenge trading mecanizado
```

---

## Filtros pre-trade (risk gate)

Antes de qualquer entrada, o trade deve passar por TODOS estes checks:

| # | Check | Threshold | Acao se falhar |
|---|---|---|---|
| 1 | Capital minimo | > $50 | Bloqueia |
| 2 | Regime permissivo | RANGING ou WEAK_TREND | Bloqueia |
| 3 | Posicao duplicada | Sem posicao aberta no mesmo par | Bloqueia |
| 4 | Max posicoes | <= 1 (V1) | Bloqueia |
| 5 | Cooldown ativo | Sem cooldown apos 2 losses | Bloqueia |
| 6 | Daily loss limit | < 1.5% | Bloqueia |
| 7 | Weekly loss limit | < 3% | Bloqueia |
| 8 | Circuit breaker | Nao ativo | Bloqueia |
| 9 | ATR elevado | ATR < 50% acima da media | Bloqueia |
| 10 | SL dentro do limite | SL <= 2.5% | Bloqueia |
| 11 | RR minimo | RR >= 2.0 | Bloqueia |
| 12 | Session filter | Nao em dead zone (21-00 UTC) sem override | Bloqueia ou threshold elevado |

Qualquer falha = trade bloqueado. Sem excecoes. Sem override manual.

---

## Gestao de posicao aberta

```
POSICAO ABERTA:
  |
  ├── Check SL a cada candle (5m ou 1m)
  |   └── Se atingido: fechar 100%, registrar loss
  |
  ├── Check TP1 (parcial 50%)
  |   └── Se atingido: fechar 50%, mover SL para breakeven
  |
  ├── Check TP2 (restante)
  |   └── Se atingido: fechar 100%, registrar win
  |
  ├── Check regime shift
  |   └── Se regime muda para TRENDING/VOLATILE/CHOPPY:
  |       fechar no preco atual (protecao de contexto)
  |
  └── Check timeout
      └── Se posicao aberta > 3h (12 candles 15m):
          fechar no preco atual (setup expirado)
```

### Regra de breakeven

Apos TP1 atingido:
- SL move para entry_price + 0.05% (pequeno buffer para nao ser stopado no breakeven exato)
- Isso garante que apos TP1, o trade nao vira loss

---

## Slippage e custos

| Parametro | Valor para backtest | Valor para paper | Valor para real |
|---|---|---|---|
| Fee por lado | 0.04% (maker) | 0.04% | Real da exchange |
| Slippage normal | 0.02% | 0.01% | Real |
| Slippage em failed breakout | 0.05% | 0.03% | Real |
| Round-trip cost total | ~0.12% a 0.18% | ~0.10% | Real |

**Nota importante:** slippage em candles de failed breakout e maior porque a liquidez e pior no momento de reversao. O backtest DEVE usar slippage elevado nesses candles.

---

## Metricas de monitoramento obrigatorias

| Metrica | Calculo | Alerta se |
|---|---|---|
| Profit factor | gross_wins / gross_losses | < 1.2 por 2 semanas |
| Win rate | wins / total_trades | < 40% por 2 semanas |
| Max drawdown rolling | max(peak - current) / peak | > 5% em 30 dias |
| Avg RR realizado | avg_win / avg_loss | < 1.5 |
| Taxa de no-trade | sinais avaliados / trades abertos | Alerta se < 90% (muito ativo) |
| Regime accuracy | WR por regime | Negativo em regime alvo (RANGING) |
| Session accuracy | WR por sessao | Negativo em sessao permitida |

---

## Escalacao de risco (quando subir)

NAO escalar risco antes de atender TODOS estes criterios:

1. Minimo 50 trades em paper com metricas dentro do alvo
2. Minimo 4 semanas de operacao continua sem circuit breaker nivel 3+
3. Profit factor > 1.5 out-of-sample
4. Max drawdown < 8% no periodo completo
5. Aprovacao explicita do Gabriel

### Niveis de escalacao

| Nivel | Risk/trade | Max posicoes | Requisito |
|---|---|---|---|
| V1 (inicio) | 0.5% | 1 | Nenhum |
| V1.1 | 0.75% | 1 | 50 trades + PF > 1.5 |
| V1.2 | 1.0% | 2 | 100 trades + PF > 1.5 + DD < 8% |
| V2 | 1.5% | 2 | 200 trades + PF > 1.8 + DD < 6% + 3 meses |
