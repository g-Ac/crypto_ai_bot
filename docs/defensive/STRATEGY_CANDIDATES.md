# STRATEGY CANDIDATES — Sistema de Trading Defensivo

**Data:** 2026-04-14
**Status:** Candidatas definidas, aguardando validacao empirica

---

## Decisao

| Papel | Estrategia |
|---|---|
| **Candidata principal** | CFER Enhanced (Compression → Failed Expansion → Reversion com trap confirmation) |
| **Benchmark obrigatorio** | RAVR (Regime-Aware Value Reversion) |
| **Fora da V1** | AVDR (Anchored VWAP Displacement Reversion) |

CFER NAO esta congelada como vencedora. O backtest comparativo decide. Se RAVR (mais simples) performar igual ou melhor, a camada de trap nao esta agregando valor e a V1 deve ser RAVR.

---

## Candidata 1: CFER Enhanced — Structural Trap Reversion

### Hipotese de edge

A maioria das tentativas de breakout FALHA. Quando o mercado comprime (range apertado, volatilidade caindo) e depois tenta expandir, os traders posicionam-se para breakout. Se a expansao falha, esses traders ficam PRESOS — e a liquidacao forcada dessas posicoes gera momentum reverso previsivel.

O edge explora um vies comportamental: traders entram em breakouts. Quando falham, sao forcados a sair com loss, amplificando a reversao.

**Diferencial sobre Bollinger fade generico:** a camada de trap confirmation usando microestrutura. Nao basta o preco voltar para dentro da banda — precisa de EVIDENCIA de que dinheiro real entrou no breakout e agora esta preso.

### 5 camadas do sinal

```
CAMADA 1: COMPRESSAO (setup obrigatorio)
    |
    v
CAMADA 2: TENTATIVA DE BREAKOUT (trigger)
    |
    v
CAMADA 3: TRAP CONFIRMATION (o edge — microestrutura)
    |
    v
CAMADA 4: RECLAIM DO RANGE (confirmacao)
    |
    v
CAMADA 5: REGIME + SESSION FILTER (contexto)
```

---

### Camada 1 — Compressao (Setup)

Nao e "BB esta apertado". E compressao real, mensuravel, em declinio ativo.

**Condicoes (TODAS obrigatorias):**

| Indicador | Condicao | Timeframe | Existe no projeto? |
|---|---|---|---|
| BB Width | Em declinio por >= 6 candles consecutivos | 15m | Sim (htf.py, scalping_data.py) |
| BB Width | Abaixo do percentil 20 dos ultimos 100 periodos | 15m | Parcial (precisa percentile) |
| ATR(14) | Em declinio (confirmando queda de vol) | 15m | Sim (execution_layer.py) |
| Volume medio | Em declinio ou estavel (energia acumulando) | 15m | Sim (indicators.py) |

**Calculo:**

```python
bb_width_pct = (bb_upper - bb_lower) / bb_mid * 100
bb_width_declining = all(bb_width[i] > bb_width[i+1] for i in range(-7, -1))
bb_width_percentile = percentile_rank(bb_width[-1], bb_width[-100:])
compression = bb_width_declining AND bb_width_percentile < 20

atr_declining = atr[-1] < atr[-4]  # ATR caiu nos ultimos 4 periodos
volume_not_expanding = volume[-1] <= volume_sma20[-1] * 1.2

setup_valid = compression AND atr_declining AND volume_not_expanding
```

**Por que essas condicoes:**
- BB Width em declinio = volatilidade ATIVAMENTE contraindo (nao apenas "baixa")
- Percentil 20 = compressao no quintil inferior historico (raro, significativo)
- ATR confirmando = nao e apenas range apertado, e volatilidade real baixa
- Volume estavel/baixo = energia acumulando, nao dissipando

Sem compressao valida, nenhum sinal e gerado. Isso filtra ~80-90% do tempo.

---

### Camada 2 — Tentativa de Breakout (Trigger)

O mercado tenta sair do range de compressao.

**Condicoes (TODAS obrigatorias):**

| Indicador | Condicao | Detalhe |
|---|---|---|
| Preco | Close fora da BB upper OU lower (15m) | Breakout confirmado por close, nao apenas wick |
| Volume | Spike > 1.5x media 20 periodos no candle de break | Confirma que houve participacao |
| Direcao | Registrar: UP (acima BB upper) ou DOWN (abaixo BB lower) | Determina direcao do trap |

```python
breakout_up = candle.close > bb_upper AND candle.volume > volume_sma20 * 1.5
breakout_down = candle.close < bb_lower AND candle.volume > volume_sma20 * 1.5
breakout_direction = "UP" if breakout_up else "DOWN" if breakout_down else None
```

**Nota:** se nao houver volume spike no breakout, nao e um breakout real — e ruido. Ignorar.

---

### Camada 3 — Trap Confirmation (O Edge)

**Esta e a camada que separa o sistema de um Bollinger fade generico.**

Apos o breakout, buscamos EVIDENCIA de que dinheiro real entrou E agora esta preso. Usamos os dados de microestrutura que o projeto ja coleta.

**Precisa de pelo menos 1 sinal de trap dos seguintes:**

#### Trap A — OI Trap (mais limpo)

```
DURANTE o breakout:
  OI expandiu (oi_change_1h_pct > 0.3%)
  → Novas posicoes entraram (dinheiro real)

APOS o reclaim:
  OI comeca a cair (oi_change mais recente negativo)
  → Essas posicoes estao sendo fechadas com loss
  → Traders presos saindo

oi_trap = (oi_expanded_on_breakout AND oi_declining_after)
```

**Por que funciona:** OI expandindo no breakout = nao foi apenas stop hunt, pessoas realmente abriram posicoes. OI caindo depois = essas posicoes estao fechando (loss). Isso cria pressao na direcao oposta ao breakout.

#### Trap B — Liquidation Trap (mais agressivo)

```
APOS o reclaim do range:
  Liquidacoes disparam NA DIRECAO do breakout
  
  Se breakout foi UP (longs abriram):
    liquidation_vol_long > threshold ($50k para BTC)
    → Longs sendo liquidados = venda forcada

  Se breakout foi DOWN (shorts abriram):
    liquidation_vol_short > threshold ($50k para BTC)
    → Shorts sendo liquidados = compra forcada

liq_trap = liquidation_in_breakout_direction > LIQUIDATION_THRESHOLD
```

**Por que funciona:** liquidacoes forcadas geram momentum mecanico. Nao e opiniao — e ordens de mercado obrigatorias da exchange.

#### Trap C — Crowding Trap (mais lento, mais confiavel)

```
DURANTE ou APOS o breakout:
  Funding rate shifta na direcao do breakout
  
  Se breakout UP:
    funding_rate > 0.01% (longs pagando para manter)
    E/OU ls_ratio_top > 1.5 (mais longs do que shorts entre top traders)
    → Crowd posicionou na direcao do breakout
    → Se breakout falha, todo mundo esta no lado errado

  Se breakout DOWN:
    funding_rate < -0.005%
    E/OU ls_ratio_top < 0.7
    → Crowd posicionou short

crowding_trap = (funding_extreme_in_breakout_dir OR ls_ratio_extreme_in_breakout_dir)
```

**Por que funciona:** quando a maioria esta de um lado e o breakout falha, a saida em massa cria pressao de reversao. E a mesma logica do FundingEngine (M1) mas contextualizada ao setup de trap.

#### Trap D — Basis Divergence (complementar)

```
DURANTE o breakout:
  Se breakout UP:
    basis_spread expandiu (futures ficaram mais caros que spot)
    → Retail entrou via futures (FOMO)
    → Se basis reverte apos falha, confirma que era FOMO, nao convicao

  basis_trap = (basis_expanded_on_breakout AND basis_reverting_after)
```

**Por que funciona:** expansao de basis no breakout = retail alavancado entrando. Reversao de basis = essa posicao sendo desfeita.

### Classificacao de evidencias

As evidencias de trap se dividem em duas categorias:

**Primarias (observacao direta de dinheiro preso):**
- Trap A — OI Trap: ve posicoes entrando e saindo (dado mais limpo)
- Trap B — Liquidation Trap: ve liquidacoes forcadas (dado mais mecanico)

**Secundarias (proxy de posicionamento):**
- Trap C — Crowding Trap: ve posicionamento da crowd (dado mais lento, indireto)
- Trap D — Basis Divergence: ve sentimento retail (dado complementar)

Uma evidencia primaria sozinha pode confirmar trap. Secundarias precisam de combinacao ou de primaria junto.

### Scoring de trap confirmation

**HIPOTESE INICIAL.** Os pesos abaixo sao ponto de partida, nao verdade. Serao validados por ablation no backtest.

```
trap_score = 0

# Primarias
Se oi_trap:        trap_score += 35   (HIPOTESE — peso inicial)
Se liq_trap:       trap_score += 30   (HIPOTESE — peso inicial)

# Secundarias
Se crowding_trap:  trap_score += 25   (HIPOTESE — peso inicial)
Se basis_trap:     trap_score += 15   (HIPOTESE — peso inicial)

# Confirmacao
Se trap_score >= 60: trap_confirmed = True (multiplos sinais)
Se trap_score >= 30 AND (oi_trap OR liq_trap): trap_confirmed = True (primaria forte)
Se trap_score >= 40 AND NOT (oi_trap OR liq_trap): trap_confirmed = True (secundarias combinadas)
Senao: trap_confirmed = False
```

**Threshold minimo: trap_score >= 30 com pelo menos 1 evidencia primaria, OU >= 40 com secundarias combinadas.**
Sem trap confirmation, NAO opera. E isso que distingue o sistema de um Bollinger fade.

### Plano de ablation (validacao dos pesos)

O backtest DEVE rodar estas variantes para validar que a trap layer agrega valor:

| Variante | O que testa | Resultado esperado |
|---|---|---|
| CFER_baseline | Sem trap layer (compressao + breakout + reclaim apenas) | Baseline: se isso ja funciona bem, trap e custo |
| CFER_trap_simple | Trap com peso uniforme (25/25/25/25) | Pesos importam? |
| CFER_trap_full | Trap com pesos hipotese (35/30/25/15) | Versao principal |
| CFER_no_OI | Trap sem OI (0/30/25/15) | OI contribui? |
| CFER_no_liq | Trap sem liquidation (35/0/25/15) | Liquidation contribui? |
| CFER_no_secondary | Trap so com primarias (35/30/0/0) | Secundarias contribuem? |
| CFER_no_primary | Trap so com secundarias (0/0/25/15) | Primarias sao necessarias? |

Se CFER_baseline performar igual a CFER_trap_full, a trap layer NAO esta agregando — simplificar para RAVR.
Se alguma evidencia individual nao agrega em ablation, remover.

### Feature dependency e degraded mode

**Problema:** em live, os dados de microestrutura podem falhar (API timeout, WebSocket down, dados stale). O sistema precisa saber operar com dados parciais sem divergir do backtest.

| Dado | Fonte | Probabilidade de falha | Se falhar |
|---|---|---|---|
| OI (oi_change_1h_pct) | Binance API /fapi/v1/openInterest | Baixa | oi_trap = False (indisponivel, nao invalido) |
| Liquidacoes | WebSocket forceOrder + fallback aggTrades | Media (proxy 70% do tempo) | Se proxy: liq_trap score capeado em 20/30. Se indisponivel: liq_trap = False |
| Funding rate | Binance API /fapi/v1/fundingRate | Baixa | crowding_trap perde componente funding (usa so L/S ratio) |
| Basis spread | Binance API spot+futures ticker | Baixa | basis_trap = False |
| L/S ratio | Binance API /futures/data/ | Media | crowding_trap perde componente L/S (usa so funding) |

**Regra de degraded mode:**
- Cada evidencia de trap tem flag `available: bool` alem de `triggered: bool`
- Score so usa evidencias com `available = True`
- Se < 2 evidencias disponiveis: nao operar (dados insuficientes para confirmar trap)
- Decision log registra quais dados estavam disponiveis vs indisponiveis
- Backtest DEVE simular degraded mode para medir impacto

**Flag no TrapResult:**

```python
@dataclass
class TrapResult:
    confirmed: bool = False
    score: int = 0
    evidence: list = field(default_factory=list)
    available_evidence: list = field(default_factory=list)  # quais dados estavam disponiveis
    missing_evidence: list = field(default_factory=list)    # quais dados faltaram
    degraded: bool = False  # True se algum dado faltou
    ...
```

---

### Camada 4 — Reclaim do Range (Confirmacao)

O preco volta para dentro do range de compressao.

**Condicoes:**

```python
# Breakout UP que falhou:
reclaim = candle.close < bb_upper  # voltou para dentro
reclaim_window = 1 a 3 candles apos breakout (15m = 15 a 45 min)

# Breakout DOWN que falhou:
reclaim = candle.close > bb_lower  # voltou para dentro

# Timeout: se nao reclaimar em 3 candles, setup expirou
if candles_since_breakout > 3: setup_expired = True
```

**Entrada:**
- **Direcao:** oposta ao breakout falhado
  - Breakout UP falhou → SHORT (preco vai reverter para baixo)
  - Breakout DOWN falhou → LONG (preco vai reverter para cima)
- **Preco de entrada:** close do candle de reclaim
- **SL:** alem do extremo do breakout + 0.5 * ATR buffer
- **TP1:** BB midline (meio do range / VWAP)
- **TP2:** BB oposta (fundo/topo do range)

---

### Camada 5 — Filtros de Contexto

| Filtro | Condicao permissiva | Condicao bloqueante |
|---|---|---|
| Regime | RANGING, WEAK_TREND | TRENDING, VOLATILE, CHOPPY |
| Sessao | Europe (08-14 UTC), US (14-21 UTC) | Dead (21-00 UTC): threshold elevado |
| Sessao | Asia (00-08 UTC): threshold elevado (trap_score >= 45) | — |
| ATR | ATR < 50% acima da media | ATR >= 50% acima: bloqueado |
| Daily loss | < 1.5% | >= 1.5%: bloqueado |
| Cooldown | Sem 2 losses consecutivos | 2 losses: bloqueado |

---

### Fluxo completo resumido

```
TEMPO 0: Compressao detectada
  BB Width ↓ 6+ candles, percentil < 20, ATR ↓, volume estavel
  → Setup ARMADO (sem acao, apenas monitorar)

TEMPO 1: Breakout tentado
  Close fora da BB + volume spike 1.5x
  → Registrar direcao, monitorar microestrutura

TEMPO 1-3 candles: Avaliar trap
  OI expandiu? Liquidacoes? Funding shifted? Basis expandiu?
  → Se sim: trap evidence coletada

TEMPO 2-4 candles: Reclaim do range
  Close volta para dentro da BB
  → Se trap_confirmed + reclaim = SINAL VALIDO

TEMPO 2-4 candles: Entry
  Entrar na direcao oposta ao breakout
  SL alem do extremo, TP1 no meio, TP2 no oposto

TEMPO 2-16 candles: Gestao
  Monitorar SL/TP1/TP2/regime shift/timeout
```

---

### Metricas esperadas (HIPOTESE — validar no backtest)

| Metrica | Estimativa | Base da estimativa |
|---|---|---|
| Frequencia | 2-4 trades/semana | Compressao significativa em BTC/ETH ~3-5x/semana |
| Win rate | 55-65% | Failed breakouts > successful breakouts em ranging |
| Avg win | 0.8-1.5% | Distancia meio-do-range a partir da BB |
| Avg loss | 0.4-0.8% | SL apertado (extremo do breakout) |
| RR medio | 1.5:1 a 2.5:1 | TP no range, SL no extremo |
| Profit factor | 1.5-2.5 | Estimativa baseada em WR * RR |
| Max drawdown | 5-10% | Estimativa conservadora |

**HIPOTESE.** Esses numeros serao validados ou refutados pelo backtest. Nao otimizar para atingi-los.

---

## Candidata 2: RAVR — Regime-Aware Value Reversion (Benchmark)

### Hipotese de edge

Em regimes de consolidacao (RANGING/WEAK_TREND), o preco oscila ao redor de um "valor justo" (VWAP, media). Quando o deslocamento e estatisticamente extremo (z-score alto), a reversao para o valor e mais provavel que a continuacao. O edge e temporal: funciona em regimes especificos, nao em todos.

### Logica de sinal

```
1. Regime gate
   RANGING / WEAK_TREND → permissivo
   Outros → bloqueado

2. Referencia de valor
   - VWAP rolling (sessao atual OU ultimas 24h)
   - BB midline (20 periodos) como fallback

3. Deslocamento
   z_score = (price - vwap) / std(price, 50)
   
   Se z_score >= 2.0 → preco significativamente ACIMA do valor → SHORT candidato
   Se z_score <= -2.0 → preco significativamente ABAIXO do valor → LONG candidato
   Se |z_score| < 2.0 → sem sinal

4. Filtro de volume
   Se volume CRESCENTE no extremo → possivel breakout real → nao opera
   Se volume DECRESCENTE/estavel → exaustao → opera

5. Entrada
   Candle de confirmacao: primeiro close em direcao ao valor
   (nao entrar no pico do deslocamento)
   
   SL: alem do extremo do deslocamento + ATR buffer
   TP: VWAP (retorno ao valor)
   Timeout: 12 candles (3h em 15m)

6. Contexto (mesmo do CFER)
   Session, ATR, daily loss, cooldown
```

### Diferenca fundamental vs CFER

| Aspecto | CFER Enhanced | RAVR |
|---|---|---|
| Setup | Compressao (evento especifico) | Qualquer momento em regime permissivo |
| Trigger | Breakout falhado | Deslocamento estatistico (z-score) |
| Confirmacao | Trap via microestrutura (OI, liq, funding) | Volume em declinio (mais simples) |
| Edge source | Comportamental (traders presos) | Estatistico (reversao a media) |
| Complexidade | Media-alta (5 camadas) | Baixa-media (3 camadas) |
| Params livres | ~5-6 (compression, trap scoring) | ~3-4 (z-score threshold, VWAP period) |

### Metricas esperadas (HIPOTESE)

| Metrica | Estimativa |
|---|---|
| Frequencia | 3-6 trades/semana (mais frequente que CFER) |
| Win rate | 50-58% |
| Avg win | 0.6-1.2% |
| Avg loss | 0.4-0.7% |
| RR medio | 1.3:1 a 2.0:1 |
| Profit factor | 1.3-1.8 |

### Por que RAVR como benchmark e nao candidata principal

1. Mais simples = baseline natural para comparacao
2. Se CFER (com trap) nao bater RAVR (sem trap), a complexidade extra nao se paga
3. RAVR pode acabar sendo a V1 se os dados mostrarem que a camada de trap nao agrega
4. Mantendo RAVR vivo, impedimos apego emocional a narrativa do CFER

---

## Candidata 3: AVDR — Anchored VWAP Displacement (Fora da V1)

### Por que esta fora

1. **Complexidade de dados:** precisa de VWAP calculado a partir de multiplos pontos de ancora (session open, swing points, weekly open). O projeto so tem VWAP inline de 12 candles em `liquidation_engine.py` — insuficiente.

2. **Deteccao de swing points:** requer logica de deteccao automatica de swing high/low. Nao existe no projeto. Implementar bem e nao trivial e introduz subjetividade.

3. **Volume de alta resolucao:** VWAP preciso requer candles de 1m ou tick data para periodos longos (sessao inteira). O projeto usa primariamente 5m e 15m.

4. **Risco de overfitting na selecao de ancoras:** quais pontos de ancora usar, quais thresholds por ancora — cada ancora e um grau de liberdade adicional. Com 3-4 ancoras e thresholds por ancora, o espaco de parametros cresce rapido.

5. **Estimativa de implementacao:** 3-4 semanas adicionais vs CFER/RAVR. Nao justifica para V1.

### Quando reconsiderar

- Se CFER e RAVR falharem no backtest (nenhuma mostra edge)
- Se o projeto escalar para pares mais liquidos com dados de tick
- Se a infraestrutura de VWAP for construida como subproduto de outra evolucao

---

## Matriz comparativa final

| Criterio | CFER Enhanced | RAVR | AVDR |
|---|---|---|---|
| **Hipotese de edge** | Behavioral trap | Statistical reversion | Multi-anchor confluence |
| **Regime ideal** | RANGING, WEAK_TREND | RANGING, WEAK_TREND | RANGING |
| **Frequencia esperada** | 2-4/semana | 3-6/semana | 1-3/semana |
| **Fee sensitivity** | Baixa | Moderada-baixa | Baixa |
| **Overfitting risk** | Baixo (padrao estrutural) | Baixo-moderado | Moderado |
| **Complexidade** | Media-alta (trap layer) | Baixa-media | Alta |
| **Explicabilidade** | Muito alta | Alta | Alta |
| **Reuso de infra** | ~85% | ~80% | ~50% |
| **Failure mode principal** | Breakout real | Trend continuation | Anchor error |
| **Preservacao de capital** | Muito forte | Forte | Forte |
| **Implementacao (estimativa)** | 2 semanas | 1 semana | 3-4 semanas |
| **Decisao** | **Candidata principal** | **Benchmark** | **Fora da V1** |

---

## Criterios para decidir entre CFER e RAVR apos backtest

CFER vence se:
- Profit factor >= 1.2x o de RAVR
- Max drawdown <= RAVR
- Metricas consistentes entre periodos OOS

RAVR vence se:
- Profit factor >= CFER (mesmo sem trap layer)
- Win rate >= CFER
- Menor variancia entre periodos

Empate tecnico:
- Se performance similar (±10%), escolher RAVR (mais simples = mais robusto)

**Os dados decidem, nao a narrativa.**
