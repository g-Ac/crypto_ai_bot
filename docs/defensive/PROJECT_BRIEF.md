# PROJECT BRIEF — Sistema de Trading Defensivo

**Data:** 2026-04-14
**Status:** Hipotese em validacao
**Autor:** Gabriel + Claude (socio tecnico)

---

## Contexto do problema

O crypto_ai_bot atual opera com dois subsistemas ativos:

**Pump Scanner** — carro-chefe. 153 trades em 8 dias, +78.15% PnL acumulado, profit factor 1.32. Problema: 64% dos trades sao perdedores. O sistema sobrevive porque 4 trades (2.6%) geraram +127% de contribuicao via fat-tails. Drawdown maximo de -47%. Sem esses outliers raros, o sistema fica negativo. Fragilidade alta.

**Scalping** — bem construido mas quase inoperante. 6 trades fechados em 8 dias. Taxa de conversao sinal-para-trade de 0.15% (14 trades em 9.494 avaliacoes). O funil de regime gate + confluencia de 3 motores + 12 checks de risco cria barreira tao alta que o sistema raramente opera.

**O gap:** nao existe um sistema que gere renda base consistente com drawdown controlado. O pump depende de outliers; o scalping nao opera. A equity curve e dominada por volatilidade do pump.

---

## Por que nao melhorar pump/scalp em vez de criar algo novo

Pump e scalping operam na familia de edge "caca de movimento" — momentum, breakout, cascata. Essa familia tem caracteristicas intrinsecas:

- Win rate naturalmente baixo (pump: 36%)
- Dependencia de fat-tails para compensar perdas frequentes
- Drawdowns severos entre os outliers
- Fragilidade: se o regime muda e outliers nao aparecem, sangra

Melhorar os parametros do pump nao muda a natureza do edge. Reduzir o filtro do scalping gera mais trades mas com qualidade menor.

O que falta e uma **terceira familia de edge**: nao caca de movimento, mas caca de deslocamento exagerado em contexto permissivo e retorno para valor. Menos trades, mais seletiva, mais contextual, mais defensiva.

---

## Objetivo declarado

Construir um sistema **defensivo, seletivo, de baixa fragilidade**, focado em **preservacao de capital** com **no-trade agressivo**. O objetivo NAO e "trade seguro e assertivo" — seguranca absoluta nao existe em trading. O objetivo e reduzir fragilidade, controlar drawdown e operar apenas quando o contexto e explicitamente favoravel.

---

## Nao-objetivos (o que este sistema NAO busca)

- **Maximizar win rate** — win rate alto sem RR favoravel e ilusao
- **Operar o tempo todo** — a maioria do tempo deve ser no-trade
- **Depender de alavancagem** — leverage e ferramenta, nao estrategia
- **Depender de sinais visuais subjetivos** — nada de "parece um martelo" ou "RSI parece sobrevendido"
- **Crescer PnL cedo via otimizacao** — otimizar parametros cedo e overfitting disfarado
- **Competir com o pump em retorno bruto** — pump opera fat-tails, este sistema opera consistencia
- **Parecer sofisticado** — complexidade sem edge mensuravel e custo, nao feature

---

## Perfil desejado do novo sistema

| Caracteristica | Pump (referencia) | Sistema defensivo (objetivo) |
|---|---|---|
| Familia de edge | Momentum / fat-tail | Deslocamento / retorno ao valor |
| Win rate esperado | 36% | 50-60% |
| Frequencia | ~19 trades/dia | 2-5 trades/semana |
| Drawdown max | -47% | < -10% |
| Profit factor | 1.32 | > 1.5 |
| Dependencia de outliers | Total | Minima |
| Risk por trade | 2% | 0.5-0.75% |
| Max posicoes | 5 | 1 |

---

## Restricoes de capital

- Capital inicial pequeno e precioso
- Perda irrecuperavel no inicio inviabiliza o projeto
- Prioridade absoluta: preservacao de capital sobre agressividade
- Escalar parametros de risco somente apos evidencia empirica

---

## Criterios de sucesso

Detalhes completos nos Go/No-Go Gates abaixo e no ROADMAP_90_DAYS.md.

Resumo: hard gates sao PF, expectancy, DD, sample size, walk-forward, regime stability e desvio backtest-paper. Win rate e metrica contextual (soft), nao gate dominante. Sample sizes ajustados para a baixa frequencia esperada (2-5 trades/semana).

---

## O que o sistema VAI fazer

- Operar BTC e ETH em Binance Futures (paper primeiro, real depois)
- Detectar deslocamentos exagerados em contexto de mercado permissivo
- Usar dados de microestrutura (OI, liquidacoes, funding, basis) como confirmacao
- Aplicar regime gate rigoroso (so operar em RANGING/WEAK_TREND)
- Usar logica agressiva de nao-trade (a maioria do tempo = nao opera)
- Gerenciar risco com limites duros e inviolaveis
- Auditar cada decisao com o framework existente (51+ campos)
- Gerar relatorios comparativos entre candidatas (CFER vs RAVR)

## O que o sistema NAO VAI fazer

- Perseguir preco ou operar momentum
- Usar sinais frageis ou puramente visuais (RSI + candle confirmation)
- Operar em regimes hostis (TRENDING forte, VOLATILE, CHOPPY)
- Otimizar parametros prematuramente (thresholds da literatura primeiro)
- Executar em capital real antes de validacao completa
- Substituir pump ou scalping — e complementar, nao substituto
- Depender de IA/LLM para decisoes de entrada

---

## Fases do desenvolvimento

| Fase | Descricao | Criterio de avanco |
|---|---|---|
| 0 | Auditoria + mapa de reaproveitamento | Completo |
| 1 | Estrategia: candidatas + decisao | CFER+trap lider, RAVR benchmark. Completo |
| 2 | Documentacao: brief + risk + architecture | Este documento |
| 3 | Backtest engine + dados historicos | Motor funcional com metricas |
| 4 | Backtest comparativo CFER vs RAVR | Dados para decidir V1 |
| 5 | Paper trading da estrategia vencedora | 4 semanas minimo |
| 6 | Execucao real (se criterios atendidos) | Validacao completa |

---

## Go / No-Go Gates

Criterios OBJETIVOS para avancar entre fases. Sem atalhos.

### Gate 1: Research → Paper Trading

| Criterio | Threshold | Tipo |
|---|---|---|
| Profit factor OOS | > 1.3 | **Hard gate** |
| Expectancy OOS | > 0.1% por trade | **Hard gate** |
| Max drawdown OOS | < 15% | **Hard gate** |
| Sample size OOS | >= 30 trades (periodo sobreposto) | **Hard gate** |
| Walk-forward consistency | PF positivo em >= 3 de 4 janelas | **Hard gate** |
| Regime stability | PF positivo em RANGING | **Hard gate** |
| Baseline vs Enhanced documentado | Comparativo no mesmo periodo | **Hard gate** |
| CFER vs RAVR documentado | Relatorio comparativo completo | **Hard gate** |
| Win rate | Informativo | Soft |
| Taxa de no-trade | > 85% | Soft |

**Se todos hard gates passam:** avanca para paper.
**Se ablation mostra trap nao agrega:** usar RAVR como V1 (mais simples).

### Gate 2: Paper Trading → Real Pequeno

| Criterio | Threshold | Tipo |
|---|---|---|
| Tempo em paper | >= 4 semanas continuas | **Hard gate** |
| Trades em paper | >= 15 | **Hard gate** |
| Profit factor paper | > 1.2 | **Hard gate** |
| Expectancy paper | > 0 | **Hard gate** |
| Max drawdown paper | < 10% | **Hard gate** |
| Desvio paper vs backtest | PF e DD dentro de 25% | **Hard gate** |
| Circuit breaker nivel 3+ | Zero ocorrencias | **Hard gate** |
| Bugs criticos | Zero | **Hard gate** |
| Kill switches testados | Data quality + regime flip dispararam | **Hard gate** |
| Aprovacao Gabriel | Sim | **Hard gate** |
| Win rate | Informativo | Soft |
| No-trade rate | 85-98% | Soft |

**Se frequencia < esperado:** estender paper ate atingir 15 trades (pode levar 5-6 semanas).

### Gate 3: Real Pequeno → Escala

| Criterio | Threshold | Tipo |
|---|---|---|
| Tempo em real | >= 8 semanas | **Hard gate** |
| Trades em real | >= 25 | **Hard gate** |
| Profit factor real | > 1.5 | **Hard gate** |
| Expectancy real | > 0.1% por trade | **Hard gate** |
| Max drawdown real | < 8% | **Hard gate** |
| Desvio real vs paper | PF e DD dentro de 20% | **Hard gate** |
| Circuit breaker nivel 4 | Zero desligamentos | **Hard gate** |
| Regime stability real | Positivo em RANGING | **Hard gate** |
| Aprovacao Gabriel | Sim | **Hard gate** |
| Win rate | Informativo | Soft |

**Se todos passam:** escalar conforme niveis de escalacao do RISK_FRAMEWORK (V1 → V1.1 → V1.2 → V2).

---

## Decisoes ja tomadas

| # | Decisao | Razao |
|---|---|---|
| D1 | Integrar no repo existente, com isolamento forte | Reutilizar 80-85% da infra (regime, microestrutura, risk, DB, audit) |
| D2 | CFER com trap confirmation como candidata principal | Menor overfitting, maior reuso, edge comportamental |
| D3 | RAVR como benchmark obrigatorio | Impedir apego a narrativa; dados decidem |
| D4 | AVDR fora da V1 | Complexidade alta, precisa de dados que nao existem |
| D5 | Backtest-first (nao code-first) | Validar hipotese antes de investir em infra de execucao |
| D6 | 0.5-0.75% risk por trade na V1 real | Capital precioso, ultra-conservador no inicio |
