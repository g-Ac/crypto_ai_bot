# BACKTEST SPEC — Sistema de Trading Defensivo

**Data:** 2026-04-14
**Status:** Especificacao V1

---

## Principio

O backtest existe para falsificar hipoteses, nao para confirmar narrativas.
Um backtest "bonito" sem rigor de execucao e pior que nenhum backtest — gera falsa confianca.

---

## Duas camadas de teste (obrigatorio)

O CFER Enhanced depende de dados de microestrutura (OI, liquidacoes, funding, basis) que tem historico mais curto e irregular que OHLCV. Para evitar comparar periodos de duracao diferente e tirar conclusao errada, o backtest e dividido em duas camadas:

### Camada 1: CFER Baseline

Usa **apenas OHLCV + BB + ATR + regime**. Sem trap layer.

```
Pipeline Baseline:
  1. Regime gate (RANGING/WEAK_TREND)
  2. Compressao (BB Width declining + percentil + ATR declining)
  3. Breakout (close fora BB + volume spike)
  4. Reclaim (close volta dentro da BB em 1-3 candles)
  5. Entry na direcao oposta ao breakout falhado
  6. SL/TP via ATR
```

**Dados necessarios:** candles 15m e 1h (para regime). Disponivel para periodos longos.
**Periodo alvo:** 6-12 meses de historico.

### Camada 2: CFER Enhanced

Baseline + trap scoring via microestrutura.

```
Pipeline Enhanced = Baseline + :
  3.5. Trap confirmation (OI, liquidacoes, funding, basis)
       Pelo menos 1 evidencia primaria (score >= 30)
       OU combinacao de secundarias (score >= 40)
```

**Dados necessarios:** OHLCV + OI historico + funding rate historico + liquidacoes + basis.
**Periodo alvo:** limitado ao periodo em que microestrutura esta disponivel.

### Regra de comparacao

```
OBRIGATORIO:
  - Baseline e Enhanced DEVEM ser comparados no MESMO periodo sobreposto
  - Se Enhanced so tem 2 meses de dados micro, comparar Baseline nesses mesmos 2 meses
  - NAO comparar Baseline de 12 meses com Enhanced de 2 meses

RESULTADO ESPERADO:
  - Se Enhanced > Baseline no periodo sobreposto → trap layer agrega
  - Se Enhanced ~= Baseline → simplificar (trap nao se paga)
  - Se Enhanced < Baseline → trap esta atrapalhando (investigar)

COMPLEMENTO:
  - Baseline roda tambem no periodo longo (6-12m) para validar robustez estrutural
  - Enhanced roda no periodo curto + forward test / paper para validar trap
```

### RAVR como benchmark

RAVR roda nos mesmos periodos que Baseline e Enhanced para triangulacao:

```
Comparacao obrigatoria:
  Baseline vs Enhanced vs RAVR (no periodo sobreposto)

Se RAVR > Enhanced → a complexidade do CFER nao se justifica
Se RAVR > Baseline → mean reversion simples e melhor que failed breakout
Se Baseline > RAVR > Enhanced → trap esta prejudicando
```

---

## Signal engine: paridade backtest/live

O backtest DEVE usar os mesmos modulos do live:

```
compression_detector.py  → IDENTICO
breakout_detector.py     → IDENTICO
trap_detector.py         → IDENTICO
defensive_trader.py      → IDENTICO (logica de decisao)
ravr_trader.py           → IDENTICO
execution_layer.py       → IDENTICO (calculo de SL/TP)
risk_manager.py          → IDENTICO (checks de risco)
```

O que difere:
- **data_loader.py** substitui API calls por leitura de CSV/parquet
- **backtest_engine.py** substitui espera por iteracao candle-a-candle
- **Fill simulation** substitui execucao real por fill simulado com slippage

**Proibicao explicita:** NAO criar logica de sinal duplicada para backtest. Se algo mudar no signal engine, muda nos dois.

---

## Zero lookahead (regra inviolavel)

```
A cada candle[t]:
  - So pode usar dados de candle[0] a candle[t]
  - NUNCA acessar candle[t+1] ou posterior
  - NUNCA usar high/low do candle atual para decisao de entry
    (entry = close do candle de confirmacao, nao intra-candle)
  
Verificacao:
  - candles_5m sao usados SOMENTE para simular fill APOS decisao no 15m
  - O sinal e gerado no close do candle 15m
  - A execucao simulada usa candles 5m do PROXIMO periodo
  - Nunca usar informacao do candle 15m que ainda nao fechou
```

### Timeframes de operacao

```
Signal:    15m — compressao, breakout, reclaim, regime context
Execution: 5m  — simulacao de fill, SL/TP check, gestao de posicao
Regime:    1h  — classificacao HTF (ADX, BB Width, ATR)

Fluxo no backtest:
  1. A cada candle 15m fechado: avaliar pipeline de sinal
  2. Se sinal valido: registrar entry no PROXIMO candle 5m
  3. A cada candle 5m: verificar SL/TP/timeout em posicoes abertas
  4. A cada candle 1h: recalcular regime
```

---

## Custos e slippage

### Fee model

```
fee_per_side = 0.04%  (Binance maker)
round_trip = 0.08%

Aplicar em TODA abertura e fechamento de posicao.
Incluir fee de parcial em TP1 (50% da posicao).

total_cost_trade = (entry_fee + exit_fee) * position_size
Se TP1 parcial: total_cost = entry_fee + tp1_fee(50%) + tp2_fee(50%)
```

### Slippage model

```
SLIPPAGE NORMAL:
  Entries em condicoes normais: 0.02%
  Exits em TP: 0.02%
  
SLIPPAGE ELEVADO (failed breakout):
  Entries no candle de reclaim: 0.05%
  Exits em SL: 0.05%
  
  Motivo: o candle de reclaim e um momento de reversao rapida.
  A liquidez no book e pior. O fill real sera pior que o close do candle.
  
SLIPPAGE EM REGIME SHIFT EXIT:
  0.03% (urgencia de saida mas nao panico)

Aplicacao:
  LONG entry:  entry_price = candle.close * (1 + slippage)
  LONG exit:   exit_price  = candle.close * (1 - slippage)
  SHORT entry: entry_price = candle.close * (1 - slippage)
  SHORT exit:  exit_price  = candle.close * (1 + slippage)
  
  Slippage SEMPRE contra o trader. Nunca a favor.
```

---

## Dados historicos

### Fontes

| Dado | Fonte | Formato | Resolucao |
|---|---|---|---|
| OHLCV 15m | Binance Spot klines API | CSV/parquet | 15 min |
| OHLCV 5m | Binance Spot klines API | CSV/parquet | 5 min |
| OHLCV 1h | Binance Spot klines API | CSV/parquet | 1 hora |
| OI historico | Binance /futures/data/openInterestHist | CSV | 5 min |
| Funding rate | Binance /fapi/v1/fundingRate | CSV | 8 horas |
| Liquidacoes | market_microstructure table (bot.db) | SQLite | ~5 min |
| Basis spread | Calculado: (futures_close - spot_close) / spot_close | Derivado | 5 min |

### Validacao de dados (obrigatoria antes de rodar backtest)

```
CHECKS DE QUALIDADE:
  1. Gaps: nao mais que 2 candles consecutivos faltando
     Se gap > 2: interpolar ou marcar periodo como invalido
  2. Zeros: preco ou volume = 0 → candle invalido
  3. Outliers: price_change > 20% em 1 candle → verificar manualmente
  4. Timestamps: monotonicamente crescentes, sem duplicatas
  5. Completude: cobertura >= 95% no periodo declarado
  
REPORT DE QUALIDADE:
  Gerar relatorio antes do backtest com:
  - Total candles / candles faltando / % cobertura
  - Gaps maiores que 2 periodos (listar)
  - Periodos invalidos excluidos
  - Datas de inicio e fim efetivas
```

### Periodos

```
PERIODO LONGO (Baseline + RAVR):
  Inicio: o mais antigo disponivel (alvo: 6-12 meses)
  Fim: data atual - 1 semana (reservar ultima semana para validacao manual)
  
PERIODO CURTO (Enhanced):
  Inicio: data mais antiga com microestrutura disponivel no bot.db
  Fim: mesmo do periodo longo
  
  Nota: o bot coleta microestrutura desde que esta rodando.
  market_microstructure table tem dados reais.
  Periodo provavel: 1-2 semanas (curto).
  Se insuficiente: coletar por 2-4 semanas antes de rodar Enhanced.
```

---

## Walk-forward validation

```
DIVISAO:
  Periodo total dividido em N janelas (minimo 4)
  Cada janela: 70% treino + 30% teste
  Janelas sobrepostas (rolling window)
  
  Exemplo com 6 meses de dados (Baseline):
    Janela 1: treino meses 1-3, teste mes 4
    Janela 2: treino meses 2-4, teste mes 5
    Janela 3: treino meses 3-5, teste mes 6
    Janela 4: treino meses 1-4, teste meses 5-6 (final)
  
REGRA:
  Parametros NAO SAO otimizados entre janelas.
  O objetivo e verificar ESTABILIDADE, nao encontrar o "melhor periodo".
  Mesma config em todas as janelas.
  
METRICA DE CONSISTENCIA:
  PF positivo em >= 3 de 4 janelas = consistente
  PF positivo em < 3 de 4 janelas = instavel (investigar ou rejeitar)
```

---

## Breakdowns obrigatorios

Cada backtest DEVE gerar metricas separadas por:

### 1. Por ativo

```
| Ativo | Trades | WR | PF | Expectancy | DD | Avg Hold |
|-------|--------|----|----|------------|-----|----------|
| BTCUSDT | ... |
| ETHUSDT | ... |
```

### 2. Por regime

```
| Regime | Trades | WR | PF | Expectancy | Nota |
|--------|--------|----|----|------------|------|
| RANGING     | ... | | | | Regime primario — deve ser positivo |
| WEAK_TREND  | ... | | | | Regime secundario |
| (outros)    | ... | | | | Devem ser zero (regime gate) |
```

### 3. Por direcao (LONG vs SHORT)

```
| Direcao | Trades | WR | PF | Avg Win | Avg Loss |
|---------|--------|----|----|---------|----------|
| LONG    | ... |
| SHORT   | ... |
```

Se uma direcao e consistentemente negativa, considerar desabilitar.

### 4. Por sessao

```
| Sessao | Trades | WR | PF | Expectancy |
|--------|--------|----|----|------------|
| Asia (00-08)   | ... |
| Europe (08-14) | ... |
| US (14-21)     | ... |
| Dead (21-00)   | ... |
```

### 5. Por exit reason

```
| Exit Reason | Count | % | Avg PnL | Contribuicao PnL |
|-------------|-------|---|---------|-------------------|
| tp1         | ... |
| tp2         | ... |
| sl          | ... |
| timeout     | ... |
| regime_shift| ... |
```

### 6. Por camada do trap score (apenas Enhanced)

```
| Trap Evidence | Trades com | WR com | PF com | Trades sem | WR sem | PF sem |
|---------------|-----------|--------|--------|------------|--------|--------|
| oi_trap       | ... |
| liq_trap      | ... |
| crowding_trap | ... |
| basis_trap    | ... |
```

Esta tabela e o resultado da ablation. Se uma evidencia nao muda PF quando presente vs ausente, ela nao esta agregando.

---

## Metricas obrigatorias

### Hard gates (decidem go/no-go)

| Metrica | Calculo | Uso |
|---|---|---|
| **Profit Factor** | gross_wins / gross_losses | Gate principal |
| **Expectancy** | (WR * avg_win) - ((1-WR) * avg_loss) | Gate principal |
| **Max Drawdown** | max(peak_equity - trough_equity) / peak_equity | Gate de risco |
| **Sample Size** | total trades OOS | Gate de significancia |
| **Walk-Forward Consistency** | PF positivo em N de M janelas | Gate de estabilidade |
| **Regime Stability** | PF por regime no periodo OOS | Gate de contexto |
| **Backtest-Paper Deviation** | |metrica_paper - metrica_backtest| / metrica_backtest | Gate de realismo |

### Metricas de qualidade (informativas, nao bloqueantes)

| Metrica | Calculo | O que revela |
|---|---|---|
| **Win Rate** | wins / total_trades | Contexto — nao gate |
| **Avg RR Realizado** | avg_win_pct / avg_loss_pct | Qualidade do sizing |
| **MAE (Max Adverse Excursion)** | max drawdown DENTRO de cada trade antes do exit | Quao perto do SL os trades passam |
| **MFE (Max Favorable Excursion)** | max profit DENTRO de cada trade antes do exit | Quanto lucro esta sendo deixado na mesa |
| **Hold Time** | media e mediana de duracao dos trades (em candles) | Setup esta expirando? |
| **No-Trade Rate** | ciclos sem trade / total ciclos | Seletividade (alvo: 85-98%) |
| **Reason Codes** | distribuicao de outcomes no decision log | Onde os sinais estao sendo bloqueados |
| **Trap Layer Contribution** | PF(Enhanced) - PF(Baseline) no periodo sobreposto | A trap esta pagando sua complexidade? |

### MAE / MFE (detalhamento)

```
Para cada trade fechado:
  MAE = pior PnL% alcancado durante o trade (antes de fechar)
  MFE = melhor PnL% alcancado durante o trade (antes de fechar)
  
  Calcular usando candles 5m entre entry e exit.
  
  Analise:
  - Se MAE medio proximo do SL → SL esta muito apertado
  - Se MFE medio >> TP realizado → esta saindo cedo demais
  - Se MFE medio ~= TP realizado → saida esta no ponto
  - Distribuicao de MAE/MFE por exit_reason revela se SL/TP estao calibrados
```

---

## Limitacoes conhecidas

| Limitacao | Impacto | Mitigacao |
|---|---|---|
| Microestrutura historica curta | Enhanced backtest com poucos dados | Coletar 2-4 semanas antes de validar Enhanced |
| Liquidacoes via proxy (aggTrades) | Score de liq_trap capeado no historico | Aceitar e registrar; trap score com liq_is_proxy = cap |
| Sem order book historico | Nao simula depth impact | Usar slippage conservador como proxy |
| Regime calculado em hindsight | Regime detection usa dados futuros se nao cuidar | Usar APENAS candles 1h ja fechados para regime |
| Funding rate em intervalos de 8h | Resolucao baixa para trap timing preciso | Interpolar ou usar ultimo valor disponivel |
| Volume de 5m pode divergir de volume real (wash trading) | Volume spike falso positivo | Nao otimizar threshold de volume; usar default da literatura |

---

## Formato de saida

O backtest gera um relatorio em markdown ou JSON com:

```
SECAO 1: Resumo executivo
  - Estrategia testada (Baseline / Enhanced / RAVR)
  - Periodo
  - Total trades / WR / PF / Expectancy / Max DD
  - Veredicto: PASS / FAIL / REVIEW

SECAO 2: Comparativo Baseline vs Enhanced vs RAVR
  - Tabela lado a lado no periodo sobreposto
  - Delta de PF, expectancy, DD
  - Conclusao: trap layer agrega? sim/nao/inconclusivo

SECAO 3: Breakdowns
  - Por ativo, regime, direcao, sessao, exit reason
  - Tabela de ablation (Enhanced)

SECAO 4: Distribuicao de trades
  - Histograma de PnL%
  - MAE/MFE scatter
  - Equity curve

SECAO 5: Walk-forward
  - PF por janela
  - Consistencia

SECAO 6: Decision funnel
  - Total ciclos avaliados
  - Bloqueados por: regime / compressao / breakout / trap / reclaim / risco
  - Conversao sinal → trade

SECAO 7: Metadados
  - config_hash, param_version, git_sha
  - Data de execucao
  - Periodo de dados
  - Qualidade dos dados (gaps, cobertura)
```
