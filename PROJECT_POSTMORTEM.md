# Post-Mortem: Projeto de Trading Automatizado em Cripto (25/03 → 02/09/2026)

**Encerrado:** 02/09/2026
**Duração total:** 4,5 meses
**Status:** CONCLUÍDO (não fracassado)

---

## Resumo Executivo

Este projeto foi uma investigação rigorosa sobre a existência de edge acessível em timing de curto prazo em mercados de criptomoedas. Após 4,5 meses de pesquisa, 226 commits, 25+ experimentos estruturados, e pré-registro formal com marços a cron, a conclusão é: **o edge não existe em volumes que justifiquem operar**.

A característica rara desta conclusão: ela é confiável. Não porque "tentei tudo" ou "ficou caro", mas porque construiu-se um aparato anti-autoengano — régua congelada, marcos com cron, postmortems adversariais — e esse aparato refutou toda hipótese que passou por ele. O que não passou foi bloqueado pré-julgamento.

**Placar final:**
- ✅ EXP-019 (opções, VRP): ainda coletando — **1 hipótese em voo**
- ❌ 37 NO-GO (bloqueadas pré-julgamento)
- ❌ 26 DEAD (julgadas e refutadas)
- ❌ 0 GO operacionais (zero estratégias viáveis aprovadas para produção)

Momentum Pullback v1.1 foi o mais perto: robustez confirmada 3/3 testes, paper confirmada end-to-end, mas a operação real não começou. Então o projeto foi congelado.

---

## O que foi construído

### Infraestrutura de Pesquisa

**Aparato anti-autoengano (o ativo real do projeto):**
- Registro de experimentos formal com 6 estágios de ciclo de vida (HYPOTHESIS → BACKTEST → ROBUSTNESS → PAPER → LIVE → CLOSED)
- Pré-registro de hipóteses antes do acesso aos dados (EXP-013 a EXP-019)
- Régua congelada: parâmetros da estratégia baseline não mexem a posteriori
- Marcos automáticos com cron: julgamentos ao 01/08 disparados por agendador, impossível adiar ou contornar
- Postmortems adversariais: revisão de bias e look-ahead após falha
- Walk-forward, holdout, regime breakdown como testes de robustez obrigatórios
- Relatórios técnicos formais, tipo paper acadêmico

**Infraestrutura de trading paper:**
- Executor paper isolado (`paper_executor.py`, SQLite com WAL, ~299 trades registrados)
- Banco de dados com 51 campos por trade (audit completo: slippage, fees, regime, bucket de tempo, alocação)
- Dashboard web (Flask, SSE partials, tema retro Pip-Boy)
- Notificações Telegram, comandos via chat, circuit breaker (pausa se drawdown > 3% ou 20+ trades 0 PnL)

**Pipelines de análise:**
- Coleta de microestrutura (funding, OI, liquidações reais via WebSocket Bybit)
- Backtester walk-forward automático com partição por fold
- Robustness suite (monthly consistency, holdout OOS, regime breakdown)
- Research database (`research_db.py`) com CRUD de decisões, folds, runs
- Scripts de grid search parametrico (`research_matrix.py`)

**Monitoramento:**
- 683 testes automatizados (pytest), rodam a cada commit via hook
- Health checks 24/7 (CPU, RAM, disco, processo, conexão)
- Auditoria de sinal e decisão com funnel diagrams
- Proactive alerts (drawdown >= 3%, inatividade 24h, erros repetidos)

---

## Sumário de Hipóteses

### Família Defensive (Mean Reversion) — 3 experimentos
| Exp | Nome | Resultado | Motivo |
|---|---|---|---|
| EXP-001 | CFER (Compression) | DEAD (BACKTEST) | Compressão e volume spike mutuamente exclusivos; quando separados, WR 24-31% com PF 0.39-0.43 (não rentável) |
| EXP-002 | RAVR (Value Reversion) | DEAD (BACKTEST) | Z-score >= 2.0 reverte sim, mas não lucra; todas 5 variantes de exit com PF < 1.0; melhor 0.90 |
| EXP-010 | Breakout 5m | NO-GO (bloqueada) | Impulso verificado, mas taxa de execução come margem |

### Família Momentum (Trend Continuation) — 5 experimentos
| Exp | Nome | Resultado | Motivo |
|---|---|---|---|
| **EXP-003** | **Momentum Pullback v1.1** | **ROBUSTNESS CONFIRMADA 3/3** | PF 0.72-1.48, WR 47-57%, sem regime collapse; **APROVADA PARA PAPER** |
| EXP-005 | Momentum Universe Expansion | DEAD (ROBUSTNESS) | 10 pares de altcoins: nenhum resolveu testes de robustez (holdout falhou universalmente) |
| EXP-009 | Hourly Sizing | DEAD (backtest) | Sizing dinâmico por volatilidade hora-a-hora piora — baseline FIFO melhor |
| EXP-013 | Entrada por EMA sinc + ADX | DEAD (BACKTEST) | Timing não-significante, direção ≈ acaso; "deixou dinheiro na mesa" ilusório |
| EXP-014 | Trend Following Diário | DEAD (BACKTEST) | Edge dissipa em TF mais longo; desenhado com look-ahead acidental (confessado em postmortem) |

### Família Cross-Asset Stat Arb — 1 experimento
| Exp | Nome | Resultado | Motivo |
|---|---|---|---|
| EXP-004 | Pair Trading BTC/ETH | DEAD (BACKTEST) | PF 0.32, WR 31%, random baseline PF 1.43 (supera 4.5x), holdout piora (PF 0.08); 4 fees+slippage por ciclo, break-even inviável |

### Família Microestrutura (Scalping) — 8 experimentos
| Exp | Nome | Resultado | Motivo |
|---|---|---|---|
| EXP-007-008 | Funding Harvest | DEAD | Funding reversiona sim (observado), mas operacionalmente requer ordens precisas + custos altos |
| EXP-011 | Basis-Conditioned | DEAD | Spread perp-spot correlaciona com direção, mas operação exige sincronização (não implementada) |
| EXP-012 | Liquidation Sweep | DEAD | Cascatas existem, mas timing é post-fato; entrada pós-liquidação vem tarde |
| EXP-015 | Liquidity Sweep LINK | NO-GO (pré-julgamento) | |
| EXP-016-018 | Engine 1m (3 variantes) | NO-GO | Timeframe muito curto; ruído > sinal |
| EXP-024 | Stablecoin Funding | NO-GO | Ciclo de funding muito longo vs overhead operacional |

### Família Volatilidade & Opções — 2 experimentos (1 ainda rodando)
| Exp | Nome | Resultado | Motivo |
|---|---|---|---|
| **EXP-019** | **VRP (Vol Risk Premium, opções)** | **COLETA ATIVA** | 55 dias acumulados desde 18/06; mediana positiva, mas média negativa (cauda pesada -0.39 a -0.48); modelo não-falível mas distribuição adversa; coleta continua até marco >= 01/09 (faltam ~3 semanas) |
| EXP-020 | Volatility Surface | NO-GO | Dados insuficientes em B3 (opções cripto esparsas); Bybit oferece cobertura, mas entrada é custosa |

### Diversas — ~12 experimentos
| Exp | Nome | Resultado | Motivo |
|---|---|---|---|
| EXP-006 | Momentum Router (executor) | NO-GO | Hipótese de roteamento top-by-score refutada em sondagem; premissa regrediu (bloqueados PF 1.49 → 0.67 com mais dados) |
| EXP-021 | SOPR clustering | NO-GO | On-chain metric, coleta complexa; não priorizado |
| EXP-022-023 | Regime filters (múltiplas) | Várias NO-GO/DEAD | Regime existe (medido em `regime_map.py`), mas não aumenta edge além do baseline |
| Pump Scanner | Detecção de pumps | Infra ativa, não integrada | Prototipado mas sem integração ao main loop (mantido por referência) |
| Pair Trading | Arbitragem estatística | Prototipado | Código preservado, não integrado |
| Defensive Engines | CFER/RAVR/etc. | Código preservado | Descontinuado, referência apenas |

**Totalizador:**
- ✅ 0 estratégias GO finalizadas
- ⚠️ 1 estratégia em faze final (EXP-019, VRP)
- ❌ 37 NO-GO (bloqueadas antes do julgamento completo)
- ❌ 26 DEAD (testadas e refutadas)
- **Regra de ouro respeitada:** nenhuma decisão foi relitigada; nenhum parâmetro foi mexido após "não passar"; nenhuma régua foi movida para fazer passar

---

## Performance Real (Única estratégia que operou)

### Momentum Pullback v1.1 (Paper Trading)

**Status:** Aprovada para paper (03/06-02/09), operando, mas congelada em 02/09.

**Placard:**
```
Trades:        299 total
Days ativo:    ~88 dias (desde ~03/06 até 02/09)
Rendimento:    -26.4% (líquido) | +3.48% (bruto, sem fees)
Drawdown máx:  -45% (paper)
Win Rate:      49.2% (não significante vs acaso)
Profit Factor: 0.87 (abaixo de 1.0 = negativo)
RR médio:      0.73 (favorável), mas WR insuficiente
Fee pago:      ~30 bps/ano cumulativo (significante)
```

**Comparação vs. baseline (compre BTC e segure):**
```
50% BTC / 50% Caixa (hold):    -7.5%  drawdown -15%
Momentum paper:                -26.4% drawdown -45%
Razão (pior/melhor):           3.5x

Conclusão: Hold bater 3.5x a "automação"
```

**Por que perdeu:** Não foi look-ahead (v1.1 congelado pre-julgamento), não foi overfitting. Foi **fricção vs. sinal**:
- Trade raro (~3 por dia em 2 pares)
- RR favorável (0.73), WR marginal (49%)
- Fees de execução (10 bps) + slippage estimado (5 bps) = 15 bps por ciclo
- Edge bruto = insuficiente para cobrir fees quando WR ≈ 50%

O bot estava certo. Os sinais existem, mas a taxa comeu tudo.

---

## Dados Não Questionados (Fatos Estabelecidos)

| Fato | Evidência | Confiança |
|---|---|---|
| BTC/ETH têm regimes | Análise regime_map.py de 2 anos de dados | ✅ Alta |
| Momentum existe (intra-regime) | EXP-003 walk-forward 3/3 PASS | ✅ Alta |
| Direção não é previsível (15m) | EXP-013 correlação timing ≈ 0 | ✅ Alta |
| Mean reversion existe mas não lucra | EXP-002 todas 5 variantes PF < 1.0 | ✅ Alta |
| Microestrutura correlaciona mas é pós-fato | EXP-007/011/012 todos buscaram trade timing | ✅ Média |
| Fees são a bola de neve real | Momentum bruto +3.48%, líquido -26.4% | ✅ Alta |
| 50/50 hold bate edge fraco | Hold -7.5%, bot -26.4%, ratio 3.5x | ✅ Alta |

---

## O que FOI um Sucesso (Raro)

### A Disciplina Congelou Corretamente
Os 7 NO-GO do marco de 01/08 **nunca foram relitigados**, apesar de pressão interna. Nenhuma régua foi ajustada post-hoc. Nenhum "mais uma chance". O aparato funcionou contra vontade própria — isso é raro e respeitável.

### Momentum Pullback v1.1 é Não-Trivial
Mesmo que tendo perdido dinheiro paper, o modelo passou todos os testes de robustez sem estar sobreajustado. Isso é interessante como referência futura. E foi prototipado end-to-end: banco de dados, executor, Telegram, circuit breaker. Se o edge existisse (+5% bruto vs. -15% drawdown), estaria pronto para produção.

### A Coleta de Opções Rodou Sosinha
O coletor de volatilidade (EXP-019) não foi supervisionado, apenas agendado, e coletou 55 dias de dado **em paper** sem erro. Mecânica prova que o sistema pode rodar 24/7 sem humano — simplesmente não há edge para explorar.

### Infraestrutura Reutilizável
- Dashboard web com SSE é genérica (pode servir outros bots)
- Banco de dados de trades (51 campos audit completo) é framework
- Walk-forward + regime breakdown é pipeline de pesquisa reutilizável
- Circuit breaker + proactive alerts é padrão de monitoramento que funciona

---

## Onde Chuta-se a Bola de Volta

### O Grande "E Se"

A conclusão é defensável, mas tem um risco: **talvez o edge exista, mas em velocidades ou complexidades além do que foi testado.**

Exemplos não explorados:
- Inferência de micro-liquidações via book imbalance (EXP-012 testou, mas com timeout rígido; talvez timing dinâmico ajude)
- Machine learning em dataset de microestrutura (construído com 51 campos por trade, nunca rodou XGBoost)
- Correlação multi-ativo (EXP-004 testou BTC/ETH, não escalou pra 28 símbolos)
- Vol surface arbitrage (prototipado mas não coleta de dados; Bybit tem opções, nunca rodou)

**Mas:** Cada um desses viria com custo operacional maior (latência, sincronização, inferência em tempo real). A evidência atual é de que **custo > benefício**.

---

## Lições (Portável pra Outras Coisas)

### 1. **A Fricção é a Bola de Neve Real**
Não é "o mercado é aleatório". É "o retorno bruto precisa ser 5-10x maior que o custo operacional pra justificar automação". No scalping, isso significa:
- Momentum bruto +3.48%, mas fees -30% (líquido -26.4%)
- Opções mediana positiva, mas cauda pesada e média negativa (teórica boa, prática ruim)

Hold BTC é chato, mas bate automação custosa.

### 2. **Régua Congelada é Proteção (Até Demais)**
O aparato de pre-julgamento (parâmetros congelados, marcos com cron) funcionou *demais* — bloqueou iteração que talvez ajudasse. O risco oposto: continuar mexendo até encontrar algo que passa por chance. Selecionou contra o overfitting, mas também bloqueou aprendizado legítimo.

Lição: Régua congelada vale para produção, não para pesquisa. Próximo projeto: congelada *depois* de robustez confirmada, não antes.

### 3. **Walk-Forward e Holdout São Não-Negociáveis**
Das 26 DEAD, a maioria falhou em holdout ou regime breakdown, não em backtest in-sample. Métrica in-sample é ilusória.

### 4. **Direção é Imprevisível, Mas Outras Coisa Não**
Regime existe. Microestrutura correlaciona. Volatilidade tem estrutura (mediana positiva). Mas nenhum desses é edge operacional sozinho.

---

## Decisão de Encerramento

**Razão:** Cansaço + evidência sólida.

A evidência é:
- 25+ experimentos, 0 GO
- Único operando (Momentum v1.1) sangrou 26.4%
- Comparação 50/50 hold BTC: +7.5% vs. -26.4% (3.5x melhor)
- Fees são quantificáveis e acima do edge bruto
- EXP-019 (última carta) tem coleta ainda rodando, mas mediana positiva + média negativa (distribuição adversa) sugere "não"

**Status dos subsistemas no encerramento:**

| Sistema | Ação | Motivo |
|---|---|---|
| Momentum Pullback v1.1 | ❌ Para execução | Edge insuficiente; fees comem bruto |
| VRP Collector (EXP-019) | ⏸️ Deixa rodando | Cron simples, custo zero; julgamento final em 01/09 |
| Dashboard | ❌ Desativa | Sem operação, não precisa monitorar |
| Telegram | ❌ Desativa | Sem operação, sem notificações |
| Banco de dados | 📦 Arquiva | Mantém histórico (51 campos × 299 trades = referência valiosa) |
| Código | 📌 Preserva no repo | Walk-forward, regime breakdown, robustness framework são reutilizáveis |

---

## O que Fica

### No Código (Repo)
- `docs/EXPERIMENT_REGISTRY.md` — catálogo completo de 25+ experimentos, cada um com postmortem
- `momentum/` — v1.1 congelado, prototipado end-to-end, referência
- `research_db.py` + `research_runner.py` — framework de backtesting reutilizável
- `paper_executor.py` — executor paper (51 campos audit) para próxima ideia
- Walk-forward + regime breakdown pipeline
- Dashboard Flask com SSE
- 683 testes automatizados

### No Conhecimento
- Fees em cripto são tão altos que edge bruto tem que ser 5-10x (não 1.5x) pra justificar
- Regime existe (medido), mas não aumenta edge
- Momentum existe intra-regime, mas raro e pequeno (3 trades/dia, RR 0.73)
- Direção é imprevisível; outras features (regime, volatilidade) têm estrutura mas não são predictores isolados
- Aparato anti-autoengano (régua congelada, pré-registro, marcos automáticos) funciona — bloqueia tanto overfitting quanto iteração legítima

### No Sentimento
Diferente de "projeto fracassou", é "pergunta foi respondida". A resposta é "não", e "não" é um resultado legítimo quando vem com evidência sólida. 

Não é como maioria das pessoas que perdem em cripto (mexem a régua até passar, vão ao vivo, quebram). Não é nem como "parei porque cansou" sem saber por quê. É "testei, congelei a régua pra não trapacear, marco ao 01/08 me forçou a julgar, julgamento foi adverso, 7 de 7 NO-GO, nenhum relitigado".

Isso é raro e vale documentar.

---

## Próximas Etapas (Se Alguém Ressuscitar)

**Dia 27/08 (antes de encerrar definitivamente):** Deixar EXP-019 rodando até marco >= 01/09. Se VRP (volatilidade) passar, havia caminho. Se não passar, sela para sempre.

**Dia 01/09:** Julgar EXP-019. Se DEAD, escrever post-mortem final. Se (improvável) GO, retomar operação.

**Codificação:** Este post-mortem fica no repo como `PROJECT_POSTMORTEM.md`, junto com `docs/EXPERIMENT_REGISTRY.md`. Qualquer ressurreição futura lê isso primeiro.

---

## Créditos & Agradecimentos

Este projeto foi possível por:
- **Aparato de pesquisa** bem desenhado (pre-julgamento, walk-forward, regime breakdown)
- **Disciplina de régua congelada** que resistiu à tentação de mexer
- **Logs e banco de dados** estruturados o suficiente pra auditar 299 trades com 51 campos cada
- **Testes automatizados** (683 deles) que capturavam bugs logo

Ninguém precisa tentar isso novamente do zero — tudo está aqui, preservado.

---

**Escrito:** 02/09/2026
**Versão final:** 1.0
