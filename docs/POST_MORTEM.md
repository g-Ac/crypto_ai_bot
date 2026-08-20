# Post-mortem — crypto_ai_bot

**Período:** 25/03/2026 → 12/08/2026 (~4,5 meses)
**Encerrado em:** 2026-08-12
**Motivo do encerramento:** objetivo respondido (negativamente) + esgotamento do apetite de continuar
**Status final:** trading desligado · coleta de dados mantida · código congelado

---

## 1. A pergunta

> "Dá para construir uma fonte de renda automática operando cripto?"

Era essa. Não era "aprender Python", não era "montar um dashboard bonito". O objetivo
declarado era renda automática. Tudo que se segue julga esse objetivo.

## 2. A resposta

**Não — nem pela via direcional, nem pelas vias que não exigem prever direção.**

E o benchmark que resume os 4,5 meses melhor que qualquer outro número:

| Estratégia | Retorno (16/04 → 02/08) | Max drawdown |
|---|---|---|
| Momentum Pullback v1.1 (o bot) | **−20,40%** | — |
| BTC buy-and-hold | −14,96% | — |
| ETH buy-and-hold | −19,77% | — |
| **50% BTC / 50% caixa** | **~−7,5%** | **~−15%** |

Uma carteira que qualquer pessoa monta em 5 minutos dominou 4,5 meses de engenharia
**nas duas dimensões** — mais retorno e menos drawdown. O bot ainda ficou 74,5% do tempo
fora do mercado, ou seja: assumiu o risco de estar errado sem capturar o prêmio de estar
exposto.

## 3. O placar

| Frente | Resultado |
|---|---|
| Experimentos formais (EXP-001…EXP-017) | **16 abertos: 7 NO-GO, 5 DEAD, 1 GO parcial (só mini-spec), 1 em coleta, 1 reservado, 1 em paper — morto** |
| Hipóteses do `edge_detective` | **849+ testadas, 0 sobreviventes** |
| Técnicas de chartismo (SMC, Wyckoff, Elliott, Preço/Volume) | **4/4 mortas empiricamente** |
| Lab forward pré-registrado (2 batches, marco 01/08) | **7 hipóteses congeladas, 7 NO-GO** |
| Momentum v1.1 em paper | 299 trades, fee acumulada **US$ 302,84**, win rate líquido **50,2%** |
| GO operacional produzido | **zero** |

## 4. Por que falhou — três mecanismos independentes

Não foi um motivo só, e essa é a parte que vale guardar.

**(a) A direção é ruído.** EXP-013 mediu diretamente: timing não-significante, direção
≈ acaso. O win rate final de 50,2% é a confirmação mais limpa possível — o bot acertava
exatamente metade, que é o que se espera de uma moeda.

**(b) A taxa come o edge antes de ele existir.** Fee de 10 bps round-trip contra um edge
bruto de ~5 bps por trade: a corretora ganhava 2x o que a estratégia gerava. O bot fez
**+3,48% bruto e −26,42% líquido** (soma de percentuais por trade). Não perdemos para o
mercado; perdemos para o custo de operar. Invariante que vale levar:
`custo_anual/capital = exposição_média × (custo_bps / horas_de_hold) × 8760`.
O momentum queimava **4,28 bps por hora exposta**.

**(c) As alternativas delta-neutras também não pagaram.** Isto é o que amplia a conclusão
para além do óbvio "não dá pra prever preço". Funding harvest: NO-GO. Funding-conditioning:
NO-GO de margem. Basis, liquidações, LSR, open interest: NO-GO. E o VRP das opções — a
última carta, que colhe prêmio sem apostar direção — mostrou na leitura descritiva de
julho o perfil clássico: **mediana positiva, média negativa**, caudas de −0,39 e −0,48.
Junta moeda na frente do trator.

**(d) Bônus desconfortável: a régua era cega.** O retro de poder de 04/08 descobriu que os
7 NO-GO do marco não provaram ausência de efeito — provaram falta de resolução. As 28
criptos do painel são correlacionadas (ρ≈0,50) e eram contadas como independentes: design
effect de 1,5x a 8x. O MDE80 ficava em 20-76 bps contra 12 bps de custo, com poder mediano
de ~9%. Pior: sob efeito verdadeiro zero, a régua produzia **6,5% a 27% de falso GO**.
Ou seja, o instrumento estava quebrado nas duas direções. Isso não muda a conclusão geral
(reforçada por outras 849 hipóteses e pelo benchmark do item 2), mas é a lição
metodológica mais cara do projeto.

## 5. O que ficou provado (e é transferível)

1. **Frequência domina taxa como alavanca de custo.** Não adianta caçar corretora barata
   se a estratégia opera demais.
2. **"Beta de regime" é o erro nº 1.** Quase todo NO-GO morreu assim: a estratégia parecia
   funcionar porque o regime a favorecia. Edge real sobrevive à inversão de regime.
3. **Dimensionar poder ANTES de congelar hipótese.** `PR-20260701-001` tinha poder
   estatístico zero desde o congelamento (16 trades, 0,54/dia) — só descobrimos no retro.
   Piso de contagem (`n_min=30`) não substitui piso de poder.
4. **Bootstrap iid mente quando os dados são correlacionados.** Use bloco.
5. **Dado de produção contaminado por teste existe.** 464 linhas de fixture sintética
   (BTC@85000) foram gravadas no `bot.db` real por testes antigos e tiveram que ser
   removidas antes de julgar a Fase F. Sempre auditar antes de julgar.
6. **Fixar a régua antes e não mexer é o que separa pesquisa de autoengano.** Em 01/08,
   sete hipóteses foram julgadas por um cron e **nenhuma foi relitigada**. Esse aparato
   funcionou — inclusive contra quem o construiu. É a coisa mais valiosa que este repo
   contém.

## 6. O que sobrou de valor

**Dataset de microestrutura de cripto (204 MB, o ativo principal):**

| Tabela | Registros | Janela |
|---|---|---|
| `k_liquidations` | 189.362 | tick-level, 14 símbolos |
| `k_ratios` (LSR) | 133.393 | — |
| `k_prices` | 67.900 | 28 símbolos, 09/04 → hoje |
| `k_open_interest` | 64.508 | — |
| `k_basis` | 56.484 | — |
| `k_options_snapshot_agg` | 48.930 | BTC/ETH, desde 18/06 |
| `k_funding_rates` | 18.436 | — |
| `k_options_features` | 2.464 | GEX, gamma flip, skew, DVOL |
| `momentum_decisions` | 21.774 | 32 campos de auditoria cada |

Liquidação tick-level e cadeia de opções histórica são caros de comprar
(Kaiko/Amberdata/Laevitas cobram por isso). **A coleta segue ligada** — cron horário,
custo operacional zero.

**Infraestrutura reaproveitável fora de trading:**

- `supervisor.py` — processos gerenciados com auto-restart e backoff exponencial
- `telegram_notifier.py` + `telegram_commands.py` — bot de comandos e alertas
- `dashboard_server.py` — Flask + SSE + auth + streaming de logs
- watchdogs via systemd timers + `flock` nos crons
- `research/gerador_prereg/` + `juiz_forward` + `livro_razao` — **framework genérico de
  pré-registro e julgamento forward.** Não tem nada de trading nele: serve para qualquer
  contexto em que se queira testar hipóteses sem se enganar (A/B de produto, experimento
  de marketing, avaliação de feature).
- ~100 arquivos de teste com padrão de revisão adversarial multi-agente

## 7. Estado no encerramento

| Item | Estado |
|---|---|
| `MOMENTUM_TRADER_ENABLED` | **false** (desligado 12/08) |
| Serviço `cryptobot` | ativo (dashboard + ciclo, sem operar) |
| Coletores (`k_collector`, `options_collector`, liquidações) | **ligados**, cron horário |
| Triggers do lab (juiz, gerador, livro-razão) | ligados e idempotentes; nada vencido |
| Carteira do livro-razão | vazia — estado válido (só popula com confirmação em 2º forward) |
| Capital | 100% paper. **Nunca houve execução real.** |

## 8. Se você voltar

Não recomece pelo código. Recomece por estas três perguntas, nesta ordem:

1. **O benchmark mudou?** Se a resposta continuar "50% BTC / 50% caixa ganha", pare aqui.
   Qualquer coisa que você construir precisa bater isso, e bater com folga suficiente para
   pagar o seu tempo.
2. **A régua tem poder?** Antes de congelar qualquer hipótese nova, conserte o
   dimensionamento (bootstrap de bloco por dia, piso de poder no lugar de `n_min`, gate de
   viabilidade ex-ante, residualização contra o mercado — rende ~9x resolução na mesma
   janela). Os consertos estão especificados no retro de 04/08 e **nenhum foi aplicado**.
   Há também um bug conhecido: `colhedor.py` filtra `bucket_ts >= corte_ts` sem teto
   superior, então re-rodar depois do marco varre dado que não existia no julgamento.
3. **A hipótese tem mecanismo?** 849 hipóteses sem mecanismo morreram. As que chegaram
   mais longe tinham uma história causal antes do backtest.

E a carta que ficou na mesa: **EXP-019 (VRP/opções)**, com coleta desde 18/06 acumulando
sozinha. Marco previsto ≥01/09. Não foi julgada — não por falta de dado, mas porque
julgá-la com a régua atual seria repetir o erro do marco 01/08.

---

## Nota final

Este projeto não fracassou: ele **terminou**. Fez uma pergunta cara, respondeu com rigor
raro, e a resposta foi "não". O custo foi 4,5 meses e zero dinheiro real — a alternativa
usual é descobrir a mesma coisa em três anos com a conta no vermelho.

O que sobrevive não é o bot. É saber como não se enganar.
