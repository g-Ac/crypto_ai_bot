# PREREG — Graveyard Autopsy 2026-06

Data: 2026-06-10
Status: FECHADO / AUDITORIA DOCUMENTAL
Tipo: autópsia de estratégias mortas, não experimento de reabertura

## Pergunta

O histórico de estratégias mortas do lab contém aprendizado reutilizável suficiente para:

1. distinguir morte estrutural de morte condicional;
2. impedir relitígio infinito de price-action/mean reversion/microestrutura;
3. portar lacunas históricas para o `docs/EXPERIMENT_REGISTRY.md`;
4. definir cláusula explícita de reabertura na Constituição do lab.

## Escopo autorizado

Inclui:

- v1.1 / price-action / momentum pullback;
- CFER/RAVR/BE50/PB25/session/hourly/breakout 5m;
- pair/stat-arb BTC/ETH;
- microestrutura/funding/LSR/EXP-009;
- notas de decisão, memória de sessão, relatórios e registry já existentes.

Exclui:

- novo backtest para tentar salvar estratégia morta;
- tuning de timeout, saída, filtro, sessão, símbolo ou regime;
- abertura de EXP novo derivado da autópsia;
- mudança na fila pós-pausa.

## Critérios de interpretação

A autópsia só pode produzir três tipos de saída:

1. aprendizado histórico;
2. regra de governança;
3. lacuna de registro a ser preenchida.

A autópsia não pode produzir GO operacional.

## Hipóteses a auditar

### H1 — Price-action morreu por estrutura

Critério: múltiplas versões independentes convergem para o mesmo padrão: entrada com pouca informação + custo/latência consumindo edge pequeno.

Se confirmado, price-action curto fica encerrado salvo hipótese mecânica nova que altere a anatomia de custo.

### H2 — Microestrutura morreu por condição, não pela mesma estrutura

Critério: falhas atribuídas a margem, regime, janela ou condição de mercado, sem equivaler à morte estrutural de price-action puro.

Se confirmado, microestrutura pode permanecer na fila somente quando houver hipótese mecânica nova e validação forward-only. Funding BTC continua 1º da fila pós-pausa.

### H3 — Velocidade/time-to-resolution é assinatura exploratória, não autorização de tuning

Critério: trades bons do v1.1 tendem a resolver rápido, mas qualquer uso operacional exigiria pré-registro novo e validação forward.

Resultado permitido: registrar hipótese viva sem ação.

Resultado proibido: reduzir timeout, sair cedo se não andar rápido, ou reabrir v1.1 histórico para tuning.

### H4 — WEAK_TREND > TRENDING é achado recorrente, não filtro acionável

Critério: apareceu em mais de uma fonte, mas pode ser artefato de ADX/gate/entrada tardia.

Resultado permitido: caveat no relatório.

Resultado proibido: filtro categórico sem walk-forward.

### H5 — Pairs/stat-arb exige régua mecânica antes de backtest

Critério: estratégias com anatomia de custo parecida ao pair BTC/ETH precisam justificar edge bruto a priori >= 2x custo total de ciclo antes de qualquer backtest.

## Procedência dos dados

Registry backfill source: session memory / decision note / postmortem; added during Graveyard Autopsy 2026-06 for completeness.

## Pré-compromissos

- Nada de reabrir price-action/momentum/mean reversion agora.
- Nada de transformar velocidade em tuning de timeout.
- Nada de mudar fila pós-pausa.
- EXP-009 pode ser selado como NO-GO / insufficient NW + temporal drift.
- Funding BTC continua 1º da fila pós-pausa.
