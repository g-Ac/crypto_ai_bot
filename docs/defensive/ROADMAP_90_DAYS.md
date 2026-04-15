# ROADMAP 90 DIAS — Sistema de Trading Defensivo

**Data:** 2026-04-14
**Status:** Planejamento

---

## Premissas

- Frequencia esperada: 2-5 trades/semana (sistema seletivo)
- Dados de microestrutura historica disponiveis: ~1-2 semanas (curto)
- Microestrutura precisa ser coletada por mais tempo antes de validar Enhanced
- Backtest Baseline pode rodar com historico longo (6-12 meses)
- Backtest Enhanced depende de acumular dados de micro
- Raspberry Pi com recursos limitados
- Gabriel valida gates manualmente

---

## Visao geral

```
Semanas 1-3:   INFRAESTRUTURA + DADOS
Semanas 4-6:   BACKTEST BASELINE + RAVR
Semanas 7-8:   BACKTEST ENHANCED + ABLATION
Semanas 9-12:  PAPER TRADING
Semana 13:     GO/NO-GO PARA REAL
```

---

## Fase 1 — Infraestrutura + Dados (Semanas 1-3)

### Semana 1: Estrutura base

| # | Tarefa | Entregavel | Criterio de done |
|---|---|---|---|
| 1.1 | Criar namespace `defensive/` com modulos vazios | Arquivos com interfaces definidas | Imports funcionam, testes skeleton passam |
| 1.2 | Implementar `value_reference.py` (VWAP rolling, z-score, percentile) | Modulo funcional | Testes unitarios passam |
| 1.3 | Implementar `compression_detector.py` | Modulo funcional | Testes com dados sinteticos passam |
| 1.4 | Implementar `breakout_detector.py` | Modulo funcional | Testes passam |
| 1.5 | Adicionar tabelas DB (`defensive_trades`, `defensive_decisions`) | Schema criado | Testes de insert/query passam |

### Semana 2: Signal engine + trap

| # | Tarefa | Entregavel | Criterio de done |
|---|---|---|---|
| 2.1 | Implementar `trap_detector.py` com 4 evidencias | Modulo funcional | Testes de scoring e degraded mode passam |
| 2.2 | Implementar `defensive_trader.py` (pipeline CFER completo) | Orquestrador funcional | Pipeline end-to-end com dados sinteticos |
| 2.3 | Implementar `ravr_trader.py` (benchmark) | Pipeline RAVR funcional | Testes passam |
| 2.4 | Implementar `defensive/config.py` (DefensiveConfig) | Config com defaults | Todos os parametros documentados |
| 2.5 | Adicionar `FeatureAvailability` e degraded mode | Flags funcionais | Testes de fallback passam |

### Semana 3: Backtest engine + ingestao de dados

| # | Tarefa | Entregavel | Criterio de done |
|---|---|---|---|
| 3.1 | Implementar `backtest/data_loader.py` | Ingestao de CSV com validacao | Relatorio de qualidade gerado |
| 3.2 | Baixar historico OHLCV 15m/5m/1h (BTC, ETH, 6-12 meses) | CSVs em `data/` | Cobertura >= 95%, gaps documentados |
| 3.3 | Implementar `backtest/backtest_engine.py` | Motor funcional | Roda Baseline end-to-end com dados reais |
| 3.4 | Implementar `backtest/metrics.py` | Calculo de PF, expectancy, DD, MAE/MFE | Validado com trades conhecidos |
| 3.5 | Iniciar coleta ativa de microestrutura para Enhanced | Dados acumulando em bot.db | Verificar cobertura diaria |

**Gate da Fase 1:** tudo compila, testes passam, Baseline roda end-to-end com dados reais mesmo que metricas sejam ruins.

---

## Fase 2 — Backtest Baseline + RAVR (Semanas 4-6)

### Semana 4: Backtest Baseline completo

| # | Tarefa | Entregavel | Criterio de done |
|---|---|---|---|
| 4.1 | Rodar Baseline em periodo longo (6-12m) BTC + ETH | Relatorio de metricas | PF, expectancy, DD, breakdowns |
| 4.2 | Rodar RAVR no mesmo periodo | Relatorio de metricas | Comparativo direto |
| 4.3 | Breakdown por ativo, regime, direcao, sessao | Tabelas completas | Todos os breakdowns do BACKTEST_SPEC |
| 4.4 | Analise: Baseline tem edge? RAVR tem edge? | Documento de analise | Conclusao honesta (pode ser "nao") |

### Semana 5: Walk-forward + calibracao

| # | Tarefa | Entregavel | Criterio de done |
|---|---|---|---|
| 5.1 | Implementar `backtest/walk_forward.py` | Walk-forward funcional | 4 janelas minimo |
| 5.2 | Walk-forward do Baseline | PF por janela | Consistente em >= 3 de 4 |
| 5.3 | Walk-forward do RAVR | PF por janela | Comparativo |
| 5.4 | Se Baseline inconsistente: investigar por que | Documento de investigacao | Acao corretiva ou rejeicao |

### Semana 6: Ajustes + relatorio comparativo

| # | Tarefa | Entregavel | Criterio de done |
|---|---|---|---|
| 6.1 | Se necessario: ajustar parametros e re-rodar (maximo 1 iteracao) | Backtest atualizado | Documentar o que mudou e por que |
| 6.2 | Implementar `backtest/report.py` | Relatorio formatado | Todas as secoes do BACKTEST_SPEC |
| 6.3 | Relatorio comparativo Baseline vs RAVR (periodo longo) | Documento final | Gabriel valida |
| 6.4 | Verificar cobertura de microestrutura acumulada | Status dos dados | >= 3 semanas de micro? |

**Gate da Fase 2:**
- Baseline E/OU RAVR mostram edge (PF > 1.0 OOS)?
  - Se SIM: seguir para Fase 3 (Enhanced)
  - Se NAO: investigar. Pode ser que o edge nao exista neste formato. PARAR e reavaliar antes de continuar.
- Microestrutura acumulada por >= 3 semanas?
  - Se SIM: seguir para Enhanced backtest
  - Se NAO: estender coleta, continuar analisando Baseline

---

## Fase 3 — Backtest Enhanced + Ablation (Semanas 7-8)

### Semana 7: Enhanced backtest

| # | Tarefa | Entregavel | Criterio de done |
|---|---|---|---|
| 7.1 | Preparar dados de micro do bot.db para backtest | CSV/parquet com OI, funding, liq, basis | Cobertura >= 90% no periodo |
| 7.2 | Rodar Enhanced no periodo sobreposto | Metricas no MESMO periodo que Baseline | Comparavel |
| 7.3 | Rodar Baseline no MESMO periodo curto (controle) | Metricas pareadas | Delta Enhanced vs Baseline |
| 7.4 | Rodar RAVR no MESMO periodo curto (triangulacao) | Metricas pareadas | Triangulacao completa |

### Semana 8: Ablation + decisao

| # | Tarefa | Entregavel | Criterio de done |
|---|---|---|---|
| 8.1 | Rodar 7 variantes de ablation (BACKTEST_SPEC) | Metricas por variante | Tabela de contribuicao por camada |
| 8.2 | Analise: trap layer agrega? Quais evidencias? | Documento de analise | Conclusao baseada em dados |
| 8.3 | Decisao formal: V1 = CFER Enhanced, Baseline, ou RAVR | DECISIONS_LOG atualizado | Gabriel aprova |
| 8.4 | Se Enhanced vence: fixar config e congelar para paper | Config final | param_version = "v1.0" |

**Gate da Fase 3 (Research → Paper):**

| Criterio | Threshold | Tipo |
|---|---|---|
| Profit factor OOS | > 1.3 | Hard gate |
| Expectancy OOS | > 0.1% por trade | Hard gate |
| Max drawdown OOS | < 15% | Hard gate |
| Sample size OOS | >= 30 trades (periodo sobreposto) | Hard gate |
| Walk-forward consistency | PF > 0 em >= 3 de 4 janelas (Baseline longo) | Hard gate |
| Regime stability | PF positivo em RANGING | Hard gate |
| Trap layer vs baseline (Enhanced) | Documentado | Hard gate (documentacao, nao metrica) |
| Win rate | > 40% | Soft (informativo) |
| Backtest-paper readiness | Kill switches implementados e testados | Hard gate |

**Se gate passa:** avanca para Paper.
**Se gate falha:** voltar a Fase 2, investigar, ou pivotar estrategia.

---

## Fase 4 — Paper Trading (Semanas 9-12)

### Semana 9: Integracao live

| # | Tarefa | Entregavel | Criterio de done |
|---|---|---|---|
| 9.1 | Integrar `defensive_trader` no `main.py` | DEFENSIVE_ENABLED funcional | Bot roda sem crash com flag ativa |
| 9.2 | Integrar kill switches (data quality, latency, regime flip) | Kill switches ativos | Testados em condicoes simuladas |
| 9.3 | Adicionar alertas Telegram para defensive | Notificacoes de trade/block | Gabriel recebe alerts |
| 9.4 | Ativar paper trading com DEFENSIVE_ENABLED=true | Sistema rodando 24/7 | Decisions sendo registradas no DB |

### Semanas 10-12: Operacao paper + monitoramento

| # | Tarefa | Criterio |
|---|---|---|
| 10.1 | Monitorar decisions diariamente | Decision log preenchido |
| 10.2 | Verificar semanalmente: PF, expectancy, DD, no-trade rate | Relatorio semanal |
| 10.3 | Verificar paridade com backtest | Desvio < 25% em PF e DD |
| 10.4 | Verificar kill switches em acao | Pelo menos 1 data_quality_kill registrado (dados falharam e sistema respondeu) |
| 10.5 | Ajustar SOMENTE se bug ou divergencia grave | Qualquer ajuste documentado no DECISIONS_LOG |

**Gate da Fase 4 (Paper → Real Pequeno):**

| Criterio | Threshold | Tipo |
|---|---|---|
| Tempo em paper | >= 4 semanas continuas | Hard gate |
| Trades em paper | >= 15 | Hard gate |
| Profit factor paper | > 1.2 | Hard gate |
| Expectancy paper | > 0 | Hard gate |
| Max drawdown paper | < 10% | Hard gate |
| Desvio paper vs backtest | PF e DD dentro de 25% | Hard gate |
| Circuit breaker nivel 3+ | Zero ocorrencias | Hard gate |
| Kill switches testados | Pelo menos data_quality e regime_shift dispararam | Hard gate |
| Bugs criticos | Zero | Hard gate |
| Win rate | Informativo | Soft |
| No-trade rate | 85-98% | Soft |
| Aprovacao Gabriel | Sim | **Hard gate** |

**Nota sobre sample size:** Com 2-5 trades/semana e 4 semanas, esperamos 8-20 trades. O gate de 15 trades e realista para essa frequencia. Se a frequencia for menor que esperado, estender o paper ate atingir 15 trades (pode levar 5-6 semanas).

---

## Fase 5 — Go/No-Go e Real (Semana 13)

### Semana 13: Decisao

| # | Tarefa | Entregavel |
|---|---|---|
| 13.1 | Compilar relatorio final: backtest vs paper | Relatorio comparativo |
| 13.2 | Verificar todos os gates | Checklist go/no-go |
| 13.3 | Se GO: ativar real com 0.5% risk, 1 posicao, DEFENSIVE_STRATEGY=cfer | Bot em real |
| 13.4 | Se NO-GO: documentar por que e definir proximos passos | DECISIONS_LOG atualizado |

### Apos semana 13 (se real ativado):

```
Semanas 14-21 (8 semanas real):
  - Monitoramento continuo
  - Relatorio semanal
  - Gate de escala: 8 semanas + 25 trades + PF > 1.5 + DD < 8%
  
Semana 22+:
  - Se gate de escala passa: subir para V1.1 (0.75% risk)
  - Se nao: manter V1 ou pausar
```

**Gate de Real → Escala:**

| Criterio | Threshold | Tipo |
|---|---|---|
| Tempo em real | >= 8 semanas | Hard gate |
| Trades em real | >= 25 | Hard gate |
| Profit factor real | > 1.5 | Hard gate |
| Expectancy real | > 0.1% por trade | Hard gate |
| Max drawdown real | < 8% | Hard gate |
| Desvio real vs paper | PF e DD dentro de 20% | Hard gate |
| Circuit breaker nivel 4 | Zero desligamentos | Hard gate |
| Regime stability real | Positivo em RANGING | Hard gate |
| Win rate | Informativo | Soft |
| Aprovacao Gabriel | Sim | **Hard gate** |

---

## Cronograma visual

```
Semana  1  2  3  4  5  6  7  8  9  10 11 12 13
        |--------|--------|-----|-----------|--|
        INFRA    BASELINE  ENHN  PAPER       GO
        + DADOS  + RAVR    + ABL TRADING    /NO

Marcos:
  S3:  Baseline roda end-to-end ..................... ◆
  S6:  Relatorio comparativo Baseline vs RAVR ....... ◆
  S8:  Decisao CFER vs RAVR baseada em dados ........ ◆
  S9:  Paper trading ativo .......................... ◆
  S12: 4 semanas de paper completas ................. ◆
  S13: Go/No-Go para real .......................... ◆
```

---

## Riscos e contingencias

| Risco | Probabilidade | Impacto | Contingencia |
|---|---|---|---|
| Baseline nao mostra edge | Media | Alto | Investigar por que. Pode ser que failed breakout nao funcione em BTC/ETH. Pivotar para RAVR ou outra abordagem |
| Microestrutura insuficiente para Enhanced | Media | Medio | Estender coleta. Usar Baseline como V1 e Enhanced como V1.1 |
| Frequencia real muito menor que esperada | Media | Medio | Estender paper trading. Aceitar 15 trades em 5-6 semanas em vez de 4 |
| Paper diverge muito do backtest | Media | Alto | Investigar causa (data quality? slippage? regime shift?). Nao avancar para real ate resolver |
| Pi nao aguenta processamento extra | Baixa | Medio | Otimizar (cache, reduzir frequencia do defensive para 15min em vez de 5min) |
| Gabriel perde interesse em 90 dias | Media | Alto | Manter progresso visivel. Relatorios semanais curtos. Decisoes incrementais |
