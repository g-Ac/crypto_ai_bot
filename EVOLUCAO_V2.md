# EVOLUCAO V2 — Plano Estrategico Completo
# Crypto AI Bot — De Indicadores Tecnicos para Market Microstructure

Data: 08 de abril de 2026
Autor: Segundo Cerebro (Claude) + Gabriel
Status: PLANEJAMENTO — nenhuma alteracao de codigo ainda

---

## 1. GOAL FINAL

Construir um bot de trading autonomo que opera 24/7 em Binance Futures com **expectativa positiva comprovada por backtest** e **validada em paper trading** antes de qualquer capital real.

### Metricas de sucesso para considerar o bot "pronto"

| Metrica              | Minimo aceitavel | Alvo ideal    |
|----------------------|------------------|---------------|
| Expectancy por trade | > $0 (positiva)  | > $2/trade    |
| Win Rate             | > 35%            | > 45%         |
| Profit Factor        | > 1.2            | > 1.5         |
| Max Drawdown         | < 15%            | < 10%         |
| Sharpe Ratio         | > 0.5            | > 1.0         |
| Amostra backtest     | 200+ trades      | 500+ trades   |
| Amostra paper        | 50+ trades       | 100+ trades   |
| Periodo validacao    | 90 dias          | 180 dias      |

### O que "pronto" significa
O bot so avanca para capital real quando TODAS as metricas minimas forem atingidas simultaneamente no backtest E confirmadas em pelo menos 30 dias de paper trading com resultados consistentes.

---

## 2. DIAGNOSTICO — POR QUE ESTAMOS AQUI

### 2.1 O que funciona (MANTER)

**Infraestrutura (nota: 9/10)**
- Raspberry Pi 4 rodando 24/7 estavel (CPU 1.5%, RAM 19.9%, temp 38.5C)
- Supervisor com auto-restart e backoff exponencial
- Deploy automatizado via deploy.sh + systemd
- SQLite WAL mode para escrita concorrente
- Dashboard Flask com 5 tabs incluindo AI Brain
- Telegram com 9 comandos bidirecionais, rate limiting, retry
- Circuit breaker por sistema (5% perda diaria ou 20 trades)
- Logs rotativos, state files com backup

**Gestao de risco (nota: 8/10)**
- Position sizing baseado em ATR (2% risco por trade)
- Stop loss dinamico com floor de 2%
- Max 50% do capital em margem
- Circuit breaker independente por sistema
- Fees centralizadas em config.py (corrigido 08/04)

**Observabilidade (nota: 7/10)**
- Funil do scalping visivel por simbolo/dia
- AI Brain tab com decisoes, reviews, pattern memory
- Validation audit por sistema
- Equity curve e system leaderboard no dashboard

**Codigo (nota: 8/10)**
- Todos os 7 bugs criticos (C1-C7) corrigidos
- Todos os 11 itens alto (A1-A11) corrigidos
- Handoffs documentados (.claude/handoffs/)
- Fees centralizadas, sem hardcodes

### 2.2 O que falhou (SUBSTITUIR)

**Motores de sinal do scalping — TODOS FALHARAM**

Evidencia: backtest parametrico de 180 dias, BTCUSDT + ETHUSDT

| Motor           | Resultado                                           | Veredito     |
|-----------------|-----------------------------------------------------|--------------|
| Volume Breakout | 0 sinais em TODAS as 60 combinacoes de parametros   | MORTO        |
| RSI/BB Reversal | 5 sinais em 180 dias, 99.99% bloqueio               | INVIAVEL     |
| EMA Crossover   | 246 sinais mas WR 25%, expectativa -$5 a -$8/trade  | SEM EDGE     |

**Confluencia 2/3 — IMPOSSIVEL**
Zero ocorrencias de 2 ou mais motores concordando em 180 dias. O sistema de confluencia nunca poderia ter funcionado com esses motores.

**Backtest de saida — TODAS as variantes perdem**
Com confluencia relaxada (1/3), 218 trades testados em 4 estrategias de saida:
- Partial 1.0x ATR: expectativa -$7.27/trade
- Partial 1.5x ATR: expectativa -$7.68/trade
- Full TP2: expectativa -$6.74/trade
- Trailing Stop: expectativa -$5.09/trade (menos pior)

Conclusao: o problema NAO e a estrategia de saida. E a qualidade de entrada.

**Agent Trader — IA como rubber stamp**
- Haiku recebia dados pre-filtrados COM decisao ja tomada ("Decisao: BUY")
- Confidence media de 97.7/100 — aprovava tudo
- 14 posicoes orfas em 3 bancos de dados
- Performance real estimada: ~17% WR
- CORRIGIDO em 08/04: prompt redesenhado, decisao removida do input, regime ADX adicionado, thresholds por regime

### 2.3 Causa raiz

Os 3 motores atuais sao baseados em **indicadores tecnicos classicos** (RSI, Bollinger Bands, EMA, Volume) que medem a mesma coisa: **preco historico**. Esses indicadores:
- Sao lagging (olham para tras)
- Sao universalmente usados (edge ja foi arbitrado pelo mercado)
- Nao capturam posicionamento, fluxo, ou sentimento
- Geram "confluencia falsa" porque sao correlacionados entre si

A confluencia de 3 motores que medem a mesma coisa e como pedir segunda opiniao ao mesmo medico 3 vezes. Nao adiciona informacao nova.

---

## 3. NOVA ARQUITETURA — MARKET MICROSTRUCTURE

### 3.1 Principio fundamental

Trocar indicadores de **preco historico** por dados de **posicionamento e fluxo** — informacao sobre o que os traders estao FAZENDO agora e onde serao FORCADOS a agir.

### 3.2 Arquitetura hibrida em 5 camadas

```
Dados de Mercado (Binance API — REST + WebSocket)
        |
   +----v----+
   | CAMADA 1 |  REGIME GATE
   | ADX + Vol|  Classifica: TRENDING / WEAK_TREND / RANGING / CHOPPY
   | + Sessao |  Decide quais motores podem rodar
   +----+----+
        |
   +----v---------------------------------+
   | CAMADA 2   MOTORES ALGORITMICOS      |
   |                                       |
   | M1: Funding Rate + Long/Short Ratio  |  <- Posicionamento
   | M2: Liquidation Cascade + OI Diverg. |  <- Fluxo forcado
   | M3: Basis Spread + Session Timing    |  <- Estrutura de mercado
   |                                       |
   | Cada motor gera score 0-100          |
   +----+---------------------------------+
        |
   +----v--------+
   | CAMADA 3     |  CONFLUENCIA + SCORING
   | 2/3 motores  |  Gera: direcao, confianca agregada, sizing sugerido
   | score > thr  |
   +----+---------+
        |
   +----v----+
   | CAMADA 4 |  HAIKU VETO (reformado)
   | IA como  |  Recebe sinal qualificado + contexto
   | filtro   |  Busca razoes para REJEITAR (nao para aprovar)
   | final    |  Thresholds por regime: 75/80/85
   +----+----+
        |
   +----v----+
   | CAMADA 5 |  RISK MANAGER (existente)
   | Position |  ATR-based sizing, 2% risco, max 50% margem
   | sizing   |  Circuit breaker, cooldown, max positions
   +----+----+
        |
   +----v----+
   | EXECUCAO |  Paper primeiro, real depois
   +---------+
```

### 3.3 Por que essa arquitetura funciona

Cada camada faz o que e naturalmente boa:
- **Algoritmos** detectam condicoes numericas objetivas (rapido, barato, backtestavel)
- **Regime gate** evita operar no contexto errado (motor de momentum em mercado ranging)
- **IA** raciocina sobre contexto e excecoes (noticias, correlacao, sequencia de trades)
- **Risk manager** limita dano independente de tudo (ja existe e funciona)

### 3.4 Por que os novos motores tem edge

| Dado                 | O que mede                        | Por que tem edge                                          |
|----------------------|-----------------------------------|-----------------------------------------------------------|
| Funding Rate         | Custo de manter posicao           | Quando todos pagam caro pra ficar long, shortar e +EV     |
| Long/Short Ratio     | Posicionamento dos top traders    | Crowded trades revertem — nao ha comprador marginal       |
| Liquidacoes          | Vendas/compras FORCADAS           | Cascata de liquidacao gera momentum previsivel            |
| Open Interest        | Dinheiro entrando/saindo          | OI divergindo de preco = movimento fraco, vai reverter    |
| Basis Spread         | Premium futures vs spot           | Premium extremo = euforia/panico, tende a normalizar      |
| Session Timing       | Horario de mercado                | Funding cobrado a cada 8h cria padroes de posicionamento  |

Crucialmente: esses dados medem coisas DIFERENTES e INDEPENDENTES entre si. Funding mede custo, liquidacoes medem fluxo forcado, OI mede posicionamento. Confluencia real.

---

## 4. ESPECIFICACAO DOS 3 NOVOS MOTORES

### 4.1 Motor 1: Funding Rate + Long/Short Ratio

**Logica:** Quando o mercado esta desequilibrado (muitos longs ou shorts) e pagando caro para manter posicao, a reversao tem edge estatistico.

**Dados necessarios (Binance API):**
- `GET /fapi/v1/fundingRate` — historico de funding (a cada 8h)
- `GET /fapi/v1/premiumIndex` — funding rate atual em tempo real
- `GET /futures/data/globalLongShortAccountRatio` — ratio L/S de todas as contas
- `GET /futures/data/topLongShortAccountRatio` — ratio L/S dos top traders

**Condicoes de sinal SHORT (funding extremo positivo):**
1. Funding rate atual > 0.03% (longs pagando premium alto)
2. Long/Short ratio top traders > 65% long
3. Funding rate subindo nos ultimos 3 periodos (tendencia de crowding)
4. Regime NAO e TRENDING forte para cima (ADX > 30 + preco subindo = trend pode continuar apesar de funding)

**Condicoes de sinal LONG (funding extremo negativo):**
1. Funding rate atual < -0.02% (shorts pagando premium)
2. Long/Short ratio top traders > 60% short
3. Funding rate caindo nos ultimos 3 periodos
4. Regime NAO e TRENDING forte para baixo

**Score (0-100):**
- Funding magnitude: 0-40 pontos (quanto mais extremo, maior)
- L/S ratio desequilibrio: 0-30 pontos
- Tendencia de crowding (3 periodos): 0-20 pontos
- Alinhamento com regime: 0-10 pontos

**Timeframe:** Atualizado a cada ciclo (5 min). Funding muda a cada 8h mas o rate estimado muda continuamente.

**Filtros (quando NAO gerar sinal):**
- ADX > 35 e preco na direcao do funding (trend forte pode ignorar funding)
- Funding entre -0.01% e 0.02% (zona neutra, sem edge)
- Menos de 2h para o proximo pagamento de funding (posicoes ja estao se ajustando)

### 4.2 Motor 2: Liquidation Cascade + OI Divergence

**Logica:** Quando liquidacoes em massa ocorrem, geram momentum forcado na direcao oposta. Quando OI diverge do preco, o movimento e fraco e tende a reverter.

**Dados necessarios (Binance API):**
- `GET /fapi/v1/forceOrders` — liquidacoes recentes em tempo real
- `GET /fapi/v1/openInterest` — OI atual
- `GET /futures/data/openInterestHist` — OI historico (5min, 15min, 1h)
- OHLCV para calcular divergencia

**Condicoes de sinal LONG (liquidacao de shorts + acumulacao):**
1. Volume de liquidacoes SHORT nos ultimos 15min > threshold (calibrar via backtest)
2. OI aumentando enquanto preco esta estavel ou subindo (dinheiro novo entrando)
3. Preco acima do VWAP do periodo

**Condicoes de sinal SHORT (liquidacao de longs + distribuicao):**
1. Volume de liquidacoes LONG nos ultimos 15min > threshold
2. OI diminuindo enquanto preco sobe (distribuicao — smart money saindo)
3. OU: preco cai E OI sobe (novos shorts entrando com forca)

**Score (0-100):**
- Magnitude de liquidacoes: 0-40 pontos (normalizado pelo volume diario)
- OI divergencia magnitude: 0-30 pontos
- Velocidade da divergencia: 0-20 pontos (divergiu em 5min vs 1h)
- Direcao alinhada com regime: 0-10 pontos

**Timeframe:** Checado a cada ciclo. Liquidacoes sao eventos em real-time. OI comparado em janelas de 15min, 1h, 4h.

**Filtros:**
- OI mudou menos de 0.5% na ultima hora (mercado parado, sem informacao)
- Liquidacoes concentradas em moedas small-cap (nao relevante para BTC/ETH)
- Preco em range apertado (<0.3% na ultima hora) com OI estavel (sem setup)

### 4.3 Motor 3: Basis Spread + Session Timing

**Logica:** O premium de futures sobre spot reflete sentimento agregado. Sessoes de mercado (Asia, Europa, US) e horarios de funding criam padroes previssiveis de posicionamento.

**Dados necessarios (Binance API):**
- `GET /fapi/v1/ticker/price` — preco futures
- `GET /api/v3/ticker/price` — preco spot
- Calcular: basis = (futures - spot) / spot * 100
- Relogio UTC para classificar sessao

**Condicoes de sinal SHORT (euforia — basis alto):**
1. Basis > 0.05% (futures muito mais caro que spot — premium de euforia)
2. Basis expandindo nos ultimos 30min (aceleracao de premium)
3. Estamos nos ultimos 60min antes de pagamento de funding (00:00, 08:00, 16:00 UTC)
4. Sessao atual e a mais ativa para o ativo (US para BTC, Asia para altcoins)

**Condicoes de sinal LONG (panico — basis negativo):**
1. Basis < -0.03% (futures mais barato que spot — backwardation = panico)
2. Basis contraindo (voltando para zero) nos ultimos 15min
3. Sessao de alta liquidez (nao durante dead zone Asia para BTC)

**Score (0-100):**
- Magnitude do basis: 0-35 pontos
- Velocidade de mudanca do basis: 0-25 pontos
- Alinhamento com sessao: 0-20 pontos
- Proximidade do pagamento de funding: 0-20 pontos (mais proximo = mais forte)

**Timeframe:** Checado a cada ciclo. Basis calculado em tempo real. Sessao e horario de funding sao constantes.

**Classificacao de sessoes:**
- Asia: 00:00-08:00 UTC (Tokyo/Shanghai dominam)
- Europa: 08:00-14:00 UTC (London + Frankfurt)
- US: 14:00-21:00 UTC (NY + Chicago)
- Dead zone: 21:00-00:00 UTC (baixa liquidez, evitar)

**Filtros:**
- Basis entre -0.02% e 0.03% (zona neutra, sem distorcao)
- Dead zone (21:00-00:00 UTC) — so operar com score > 80
- Volatilidade muito baixa (ATR 1h < 0.1%) — basis pode ficar distorcido sem reverter

---

## 5. CAMADA 1 — REGIME GATE (aprimorado)

### Classificacao atual (implementada 08/04)
- ADX >= 25: TRENDING
- ADX 20-25: WEAK_TREND
- ADX < 20: RANGING

### Classificacao aprimorada (implementar)
Adicionar volatilidade e BB Width para distinguir RANGING de CHOPPY:

| ADX    | BB Width | Classificacao | Motores permitidos       |
|--------|----------|---------------|--------------------------|
| >= 25  | > 1.5%   | TRENDING      | Todos                    |
| >= 25  | < 1.5%   | WEAK_TREND    | M1 + M3 (nao M2)        |
| < 25   | > 2.0%   | VOLATILE      | M2 (liquidacoes) apenas  |
| < 25   | 0.8-2.0% | RANGING       | M1 + M3                  |
| < 25   | < 0.8%   | CHOPPY        | NENHUM — nao operar      |

Logica: em mercado CHOPPY (sem direcao e sem volatilidade), nenhuma estrategia tem edge. Melhor ficar de fora.

---

## 6. CAMADA 4 — HAIKU VETO (ja reformado)

### Status atual (implementado 08/04)
- Prompt redesenhado: "ULTIMO FILTRO — default e rejeitar"
- Decisao removida do input (Haiku decide independente)
- ADX regime incluido no contexto
- Thresholds por regime: 75 (trending), 80 (weak trend), 85 (ranging)
- Cross-validation: se Haiku discorda da direcao, trade rejeitado

### Melhorias para V2 (implementar com novos motores)
1. Incluir no contexto: funding rate, OI, basis spread (dados dos novos motores)
2. Incluir historico: "Dos ultimos 10 trades aprovados, 6 foram winners"
3. Anti-correlacao: "Ja tem 1 posicao LONG em BTC. Aprovar outro LONG aumenta exposicao."
4. Limitar: maximo 3 aprovacoes por dia por direcao (evitar overtrading)

---

## 7. PLANO DE IMPLEMENTACAO — FASES

### FASE 1: Data Layer — Coletar dados novos (2-3 dias)
**Objetivo:** Criar infraestrutura para coletar e armazenar os dados que os novos motores precisam, SEM alterar a logica de trading.

**Tarefas:**
1. Criar `market_data.py` — modulo centralizado para buscar dados da Binance:
   - `get_funding_rate(symbol)` — rate atual e historico
   - `get_long_short_ratio(symbol)` — ratio L/S top traders e global
   - `get_liquidations(symbol, minutes=15)` — liquidacoes recentes
   - `get_open_interest(symbol)` — OI atual e historico
   - `get_basis_spread(symbol)` — futures vs spot price
   - Cache em memoria com TTL (evitar rate limit da Binance)
   
2. Criar tabela `market_microstructure` no SQLite:
   - timestamp, symbol, funding_rate, ls_ratio_top, ls_ratio_global
   - liquidation_volume_long, liquidation_volume_short
   - open_interest, open_interest_change_1h, open_interest_change_4h
   - basis_spread_pct, session (asia/europe/us/dead)
   - Registrar a cada ciclo (5 min) para construir historico

3. Integrar coleta no `main.py`:
   - A cada ciclo, apos buscar candles, buscar dados de microestrutura
   - Gravar na tabela
   - NAO usar para trading ainda — apenas coletar

**Criterio de aceite:** 24h de dados coletados sem erro, tabela populando corretamente.

### FASE 2: Novos Motores — Implementar os 3 motores (3-5 dias)
**Objetivo:** Criar os 3 novos motores como modulos independentes, backtesta-los isoladamente.

**Tarefas:**
1. Criar `funding_engine.py` — Motor 1 (Funding + L/S Ratio)
   - Seguir spec da secao 4.1
   - Input: dados de `market_data.py`
   - Output: `EngineSignal(direction, score, metadata)`
   - Usar mesmo tipo `EngineSignal` de `signal_types.py`

2. Criar `liquidation_engine.py` — Motor 2 (Liquidations + OI)
   - Seguir spec da secao 4.2
   - Mesmo pattern de input/output

3. Criar `basis_engine.py` — Motor 3 (Basis + Session)
   - Seguir spec da secao 4.3
   - Mesmo pattern de input/output

4. Criar `backtest_microstructure.py`:
   - Backtester especifico para os novos motores
   - Usa dados historicos da Binance (funding, OI, liquidations tem historico via API)
   - Testa cada motor ISOLADO primeiro
   - Depois testa confluencia 2/3
   - Output: mesmas metricas do backtest anterior (WR, expectancy, PF, drawdown, Sharpe)

5. Rodar backtest parametrico dos novos motores:
   - Varrer thresholds de cada motor
   - 180 dias, BTCUSDT + ETHUSDT
   - Encontrar combinacoes com expectativa positiva

**Criterio de aceite:** pelo menos 1 motor com expectativa positiva no backtest. Se nenhum tiver, parar e reavaliar antes de continuar.

### FASE 3: Integracao — Conectar ao sistema existente (2-3 dias)
**Objetivo:** Substituir os motores antigos pelos novos no fluxo de scalping.

**Tarefas:**
1. Atualizar `confluence.py`:
   - Importar os 3 novos motores em vez dos antigos
   - Manter mesma interface de score (0-3)
   - Adicionar score continuo (0-100) como soma ponderada dos motores

2. Atualizar regime gate em `htf.py`:
   - Implementar classificacao aprimorada (secao 5)
   - Regime controla quais motores rodam

3. Atualizar `scalping_trader.py`:
   - Usar novos motores via confluence
   - Manter toda a logica de execucao, position management, parciais

4. Atualizar prompt do Haiku em `trade_agents.py`:
   - Incluir dados de microestrutura no contexto
   - Manter logica de veto reformada

5. Atualizar dashboard:
   - Mostrar funding rate, OI, basis no painel
   - Funil de decisao atualizado para novos motores

**Criterio de aceite:** bot rodando com novos motores em modo paper, gerando sinais e executando trades.

### FASE 4: Validacao Paper (7-14 dias)
**Objetivo:** Rodar o bot com novos motores em paper trading e coletar dados reais.

**Metas:**
- 50+ trades paper
- Comparar metricas reais vs backtest
- Ajustar thresholds se necessario (sem overfitting)
- Monitorar via dashboard e Telegram

**Criterio de aceite:** metricas de paper trading dentro de 1 desvio padrao do backtest.

### FASE 5: Go/No-Go (1 dia)
**Objetivo:** Decidir se o bot esta pronto para capital real.

**Checklist:**
- [ ] Expectancy positiva no backtest (180 dias)?
- [ ] Expectancy positiva no paper (50+ trades)?
- [ ] Profit Factor > 1.2 em ambos?
- [ ] Max Drawdown < 15% em ambos?
- [ ] Nenhum bug critico aberto?
- [ ] Risk manager testado com edge cases?
- [ ] Circuit breaker funcionando?
- [ ] Backup do estado automatizado?

Se TODOS marcados: proceder com capital real minimo ($100-200).
Se qualquer um falhar: voltar para fase relevante.

---

## 8. MOTORES ANTIGOS — DISPOSICAO

### O que fazer com volume_breakout.py, rsi_bb_reversal.py, ema_crossover.py

**NAO DELETAR.** Mover para pasta `archive/engines_v1/` com README explicando:
- Quando foram criados
- Por que falharam (com dados do backtest parametrico)
- Thresholds testados e resultados
- Licao aprendida

Motivo: servem como documentacao do que nao funciona. Evita que alguem no futuro tente a mesma abordagem.

### Arquivos que mudam de papel
- `confluence.py` — refatorar para usar novos motores
- `scalping_data.py` — expandir para buscar dados de microestrutura (ou substituir por `market_data.py`)
- `estrategia.md` — SUBSTITUIDO por este documento

---

## 9. ENDPOINTS BINANCE NECESSARIOS

Todos os dados necessarios estao disponiveis na API publica da Binance (sem autenticacao):

| Endpoint                                          | Dado                    | Rate Limit         |
|---------------------------------------------------|-------------------------|---------------------|
| GET /fapi/v1/premiumIndex                         | Funding rate atual      | 10 req/s            |
| GET /fapi/v1/fundingRate                          | Funding historico       | 10 req/s            |
| GET /futures/data/globalLongShortAccountRatio      | L/S ratio global        | 10 req/5min         |
| GET /futures/data/topLongShortAccountRatio         | L/S ratio top traders   | 10 req/5min         |
| GET /fapi/v1/forceOrders                          | Liquidacoes recentes    | 10 req/s            |
| GET /fapi/v1/openInterest                         | OI atual                | 10 req/s            |
| GET /futures/data/openInterestHist                 | OI historico            | 10 req/5min         |
| GET /fapi/v1/ticker/price                         | Preco futures           | 10 req/s            |
| GET /api/v3/ticker/price                          | Preco spot              | 10 req/s            |

**Rate limit total estimado por ciclo (5 min):**
- 6 symbols x 9 endpoints = 54 requests
- Binance permite 1200 req/min para IP nao autenticado
- Margem ampla. Sem risco de rate limit.

**Nota:** Alguns endpoints de dados historicos (globalLongShortAccountRatio, openInterestHist) tem limite de 10 req/5min. O ciclo de 5min do bot fica dentro do limite.

---

## 10. RISCOS E MITIGACOES

| Risco                                          | Probabilidade | Impacto | Mitigacao                                           |
|------------------------------------------------|---------------|---------|-----------------------------------------------------|
| Novos motores tambem nao tem edge              | Media         | Alto    | Backtest antes de integrar. Go/no-go na Fase 2      |
| Dados de microestrutura insuficientes historico | Baixa         | Medio   | Binance tem historico de funding e OI. Liquidacoes podem ser limitadas |
| Pi nao aguenta carga extra de API calls        | Baixa         | Baixo   | 54 requests extras por ciclo e trivial para o Pi     |
| Overfitting nos parametros dos novos motores   | Media         | Alto    | Walk-forward testing, out-of-sample validation       |
| Binance muda ou remove endpoints               | Baixa         | Alto    | Monitorar changelogs. Ter fallback para operar sem dados indisponiveis |
| Haiku fica mais caro ou lento                  | Baixa         | Medio   | IA e camada de veto, nao de decisao. Bot funciona sem ela (menos filtrado) |

---

## 11. CRONOGRAMA ESTIMADO

| Fase   | Duracao    | Dependencia        | Pode paralelizar?       |
|--------|------------|--------------------|--------------------------|
| Fase 1 | 2-3 dias   | Nenhuma            | -                        |
| Fase 2 | 3-5 dias   | Fase 1 completa    | Motores podem ser paralelos |
| Fase 3 | 2-3 dias   | Fase 2 + backtest OK | -                      |
| Fase 4 | 7-14 dias  | Fase 3 completa    | -                        |
| Fase 5 | 1 dia      | Fase 4 completa    | -                        |
| **Total** | **15-26 dias** |              |                          |

---

## 12. DECISOES PENDENTES

Antes de comecar a Fase 1, precisamos decidir:

1. **Quantos symbols?** Manter 6 (BTC, ETH, SOL, BNB, XRP, DOGE) ou focar em 2-3 com mais liquidez?
   - Recomendacao: comecar com BTC + ETH apenas (mais liquidez, mais dados, backtest mais rapido)
   - Expandir para outros apos validacao

2. **Capital por sistema?** Atualmente $285/sistema ($1k total)
   - Recomendacao: concentrar em scalping V2 ($800) + Agent reformado ($150) + Pump ($50)
   - Paper trader desativado (redundante com paper mode do scalping)

3. **Manter pump scanner?** Esta gerando trades mas sem lucro
   - Recomendacao: manter com capital minimo. E um sistema independente que pode melhorar separadamente

4. **Quando desligar motores antigos?** Imediatamente ou apos novos motores estarem validados?
   - Recomendacao: manter antigos em paralelo durante Fase 4 para comparacao A/B

---

## 13. APENDICE — PROMPTS PARA CLAUDE CODE

### Prompt Fase 1 — Data Layer
```
## Tarefa: Criar camada de coleta de dados de microestrutura

### Contexto
Estamos substituindo os motores de scalping baseados em indicadores tecnicos 
(RSI, BB, EMA) por motores baseados em dados de microestrutura de mercado 
(funding rate, liquidacoes, open interest, basis spread). 

Documentacao completa da evolucao: EVOLUCAO_V2.md (ler secoes 3, 4 e 9)

### O que criar

1. `market_data.py` — Modulo centralizado de coleta
   Funcoes necessarias:
   - get_funding_rate(symbol) -> dict com rate atual e historico 3 periodos
   - get_long_short_ratio(symbol) -> dict com top traders e global
   - get_liquidations(symbol, minutes=15) -> dict com volume long/short liquidado
   - get_open_interest(symbol) -> dict com OI atual e change 1h/4h
   - get_basis_spread(symbol) -> dict com spread futures-spot em %
   - get_market_session() -> str (asia/europe/us/dead) baseado em UTC
   
   Requisitos:
   - Cache em memoria com TTL de 30s (evitar rate limit)
   - Retry com backoff em caso de erro de API
   - Logging estruturado (nao print)
   - Type hints em todas as funcoes
   - Endpoints conforme secao 9 do EVOLUCAO_V2.md

2. Adicionar tabela `market_microstructure` em `database.py`:
   CREATE TABLE IF NOT EXISTS market_microstructure (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       timestamp TEXT NOT NULL,
       symbol TEXT NOT NULL,
       funding_rate REAL,
       funding_rate_predicted REAL,
       ls_ratio_top REAL,
       ls_ratio_global REAL,
       liquidation_vol_long REAL,
       liquidation_vol_short REAL,
       open_interest REAL,
       oi_change_1h_pct REAL,
       oi_change_4h_pct REAL,
       basis_spread_pct REAL,
       session TEXT
   );

3. Integrar no `main.py`:
   - Apos buscar candles de cada symbol, chamar market_data para coletar microestrutura
   - Gravar na tabela market_microstructure
   - NAO alterar logica de trading — apenas coletar dados
   - Log: "Microstructure data collected for {symbol}"

### Testes
- Rodar market_data.py standalone: python -c "from market_data import *; print(get_funding_rate('BTCUSDT'))"
- Verificar que todos os endpoints retornam dados validos
- Verificar que tabela esta sendo populada apos 1 ciclo

### Output
- market_data.py (novo)
- database.py (atualizado com nova tabela)
- main.py (atualizado com coleta)
- Teste manual confirmado
```

### Prompt Fase 2 — Motor 1 (Funding)
```
## Tarefa: Criar Motor 1 — Funding Rate + Long/Short Ratio

### Contexto
Ler EVOLUCAO_V2.md secao 4.1 para especificacao completa.
Este e o primeiro dos 3 novos motores de microestrutura.

### O que criar

1. `funding_engine.py`:
   - Classe FundingEngine com metodo analyze(symbol, market_data) -> EngineSignal
   - Seguir EXATAMENTE a especificacao da secao 4.1 do EVOLUCAO_V2.md
   - Score 0-100 com 4 componentes (funding magnitude, LS desequilibrio, crowding trend, regime)
   - Filtros de quando NAO gerar sinal
   - Usar EngineSignal de signal_types.py (adaptar se necessario)
   - Logging detalhado de cada componente do score

2. Testes unitarios em `tests/test_funding_engine.py`:
   - Test com funding extremo positivo -> sinal SHORT
   - Test com funding extremo negativo -> sinal LONG
   - Test com funding neutro -> sem sinal
   - Test com regime TRENDING forte na direcao -> filtrado
   - Test proximo ao horario de funding -> filtrado

### Output
- funding_engine.py (novo)
- tests/test_funding_engine.py (novo)
- signal_types.py (atualizado se necessario)
```

### Prompt Fase 2 — Motor 2 (Liquidacoes)
```
## Tarefa: Criar Motor 2 — Liquidation Cascade + OI Divergence

### Contexto
Ler EVOLUCAO_V2.md secao 4.2 para especificacao completa.

### O que criar

1. `liquidation_engine.py`:
   - Classe LiquidationEngine com metodo analyze(symbol, market_data, candles) -> EngineSignal
   - Seguir EXATAMENTE a especificacao da secao 4.2
   - Score 0-100 com 4 componentes
   - Detectar cascatas de liquidacao e divergencia preco/OI
   - Logging detalhado

2. Testes unitarios em `tests/test_liquidation_engine.py`:
   - Test cascata de liquidacoes SHORT -> sinal LONG
   - Test OI divergencia (preco sobe, OI cai) -> sinal SHORT
   - Test mercado parado -> sem sinal
   - Test liquidacoes pequenas -> filtrado

### Output
- liquidation_engine.py (novo)
- tests/test_liquidation_engine.py (novo)
```

### Prompt Fase 2 — Motor 3 (Basis)
```
## Tarefa: Criar Motor 3 — Basis Spread + Session Timing

### Contexto
Ler EVOLUCAO_V2.md secao 4.3 para especificacao completa.

### O que criar

1. `basis_engine.py`:
   - Classe BasisEngine com metodo analyze(symbol, market_data) -> EngineSignal
   - Seguir EXATAMENTE a especificacao da secao 4.3
   - Score 0-100 com 4 componentes
   - Classificacao de sessao (asia/europe/us/dead)
   - Timing relativo ao pagamento de funding
   - Logging detalhado

2. Testes unitarios em `tests/test_basis_engine.py`:
   - Test basis alto + sessao ativa -> sinal SHORT
   - Test basis negativo (backwardation) -> sinal LONG
   - Test dead zone -> filtrado/score reduzido
   - Test basis neutro -> sem sinal

### Output
- basis_engine.py (novo)
- tests/test_basis_engine.py (novo)
```

### Prompt Fase 2 — Backtest dos Novos Motores
```
## Tarefa: Criar backtest para motores de microestrutura

### Contexto
Os 3 novos motores (funding_engine, liquidation_engine, basis_engine) 
precisam ser backtestados antes de integrar ao bot.

### O que criar

1. `backtest_microstructure.py`:
   - Baixar dados historicos de funding, OI, liquidacoes via API Binance
   - Testar cada motor ISOLADO com varredura de parametros
   - Testar confluencia 2/3 com melhores parametros
   - Exit strategy: trailing stop (melhor do backtest anterior)
   - 180 dias, BTCUSDT + ETHUSDT
   
   Output:
   - reports/microstructure/motor1_funding_results.csv
   - reports/microstructure/motor2_liquidation_results.csv
   - reports/microstructure/motor3_basis_results.csv
   - reports/microstructure/confluence_results.csv
   - reports/microstructure/summary.md (top combinacoes, go/no-go)

2. Metricas por combinacao:
   - Total signals, trades executados
   - Win Rate, Avg Win, Avg Loss
   - Expectancy, Total P&L, Profit Factor
   - Max Drawdown, Sharpe
   - Fees incluidas (0.08% round trip)

### IMPORTANTE
- Se dados historicos de liquidacoes forem limitados na API, documentar 
  e usar proxy (ex: volume extremo como aproximacao)
- Rodar no PC (nao na Pi)
- Salvar progresso parcial
```

---

## 14. CONTROLE DE VERSAO DESTE DOCUMENTO

| Data       | Versao | Alteracao                                     |
|------------|--------|-----------------------------------------------|
| 2026-04-08 | 1.0    | Criacao do documento com plano completo        |

---

Fim do documento. Quando iniciar a implementacao, marcar cada fase como INICIADA/COMPLETA aqui.
