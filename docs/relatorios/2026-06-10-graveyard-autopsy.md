# Relatório — Graveyard Autopsy 2026-06

Data: 2026-06-10
Status: FECHADO
Pre-registro: `docs/pre_registros/PREREG_graveyard_autopsy_2026_06.md`

## Veredito executivo

A autópsia respondeu a pergunta principal: o lab não desistiu cedo de operar; as estratégias foram mortas com recibo.

A conclusão central é:

> Price-action morreu por estrutura. Microestrutura morreu por condição.

Isso separa duas classes que não devem ser tratadas como equivalentes:

- price-action/mean reversion curto: entrada com pouca informação + custo/latência comendo edge pequeno;
- microestrutura/funding: hipótese mecânica ainda possível, mas condicionada a regime, margem e forward-only.

Nenhum GO operacional foi produzido. Nenhuma reabertura foi autorizada.

## 1. Price-action morreu por estrutura

O padrão se repetiu em versões diferentes:

- CFER/RAVR tentaram transformar compressão/reversão em edge operável e falharam por falta de expectativa líquida;
- pair/stat-arb mostrou que z-score bonito não paga quatro execuções quando a hipótese mecânica não justifica custo bruto suficiente;
- v1.1 mostrou que existe um núcleo que acerta rápido, mas ele não paga a cauda, o relógio e o custo;
- trend-following diário foi inconclusivo e selou a linha BTC/ETH/SOL por falta de robustez, não por falta de tentativa;
- liquidity sweep LINK foi rejeitada a priori porque herdava a mesma anatomia: stop apertado torna fee parte grande demais do R.

A morte não é “PF baixo isolado”. É convergência estrutural: sinal fraco/atrasado + custo real + cauda negativa.

## 2. Leitura do v1.1

A leitura útil do v1.1 não é “PF 0.92, morreu”.

A leitura correta é:

> Existe um núcleo que acerta rápido, mas ele não paga a cauda, o relógio e o custo.

Achados principais da autópsia:

- 47% dos trades foram acertos limpos;
- acertos bons resolvem rápido, em média ~6 velas;
- ruins se arrastam por ~10–14 velas;
- apenas 8 trades mudaram de sinal por fee individualmente;
- o custo matou o agregado por mil cortes, não por um único trade;
- junho mudou a composição;
- BTC foi pior que ETH;
- classe B parece “timeout problem”, mas isso não autoriza mexer no timeout.

### Velocidade como assinatura

Registro autorizado:

> Trades bons do v1.1 tendem a resolver rápido; isso pode ser uma assinatura de qualidade, mas qualquer uso operacional exige novo pré-registro e validação forward.

Registro proibido:

- “vamos reduzir timeout”;
- “vamos sair cedo se não andar rápido”;
- “vamos retunar saída no histórico”.

Se um dia virar experimento, deve ser hipótese nova de time-to-resolution, forward-only, sem mexer no v1.1 histórico.

## 3. WEAK_TREND > TRENDING

Achado exploratório recorrente, possivelmente artefato do gate ADX ou de entrada tardia em tendências fortes.

Não é acionável sem walk-forward categórico.

Este achado não autoriza filtro por regime, retune do ADX, nem reabertura do v1.1.

## 4. Pairs/stat-arb

A régua mínima para reabrir família com anatomia de custo comparável ao pair BTC/ETH é:

> A hipótese mecânica precisa justificar edge bruto a priori >= 2x o custo total de ciclo antes de qualquer backtest.

No caso pair/stat-arb, o ciclo carrega múltiplas execuções. Z-score bonito sem mecanismo que pague esse custo não merece novo backtest.

A regra é proporcional: o número exato depende da fee/slippage e da anatomia de execução, mas a exigência geral é a mesma — primeiro plausibilidade mecânica quantificada, depois backtest.

## 5. Microestrutura morreu por condição

Microestrutura não morreu do mesmo jeito que price-action.

As falhas registradas foram por margem, regime, janela, drift temporal ou condição insuficiente. Isso não autoriza operar agora, mas justifica não classificar toda microestrutura como “morta estrutural”.

Consequência de fila:

- Funding BTC continua 1º da fila pós-pausa.
- Não há abertura de experimento novo agora.
- Validação futura precisa ser forward-only e pré-registrada.

## 6. Registry backfill

Backfill autorizado no `docs/EXPERIMENT_REGISTRY.md` para lacunas históricas.

Procedência marcada explicitamente:

> Registry backfill source: session memory / decision note / postmortem; added during Graveyard Autopsy 2026-06 for completeness.

Para BE50/PB25/session/hourly e breakout 5m, a regra foi registrar número, decisão, fonte, status fechado e link para este relatório — sem embelezar e sem fingir que todos têm o mesmo grau de auditoria.

## 7. EXP-009

EXP-009 fica selado como:

> NO-GO / insufficient NW + temporal drift; no further collection authorized absent new mechanism.

A pergunta aberta não compete mais com a fila atual.

## 8. Cláusula de reabertura

Cláusula aprovada para a Constituição:

> Experimentos mortos não são reabertos por performance histórica, tuning ou melhoria retrospectiva de métricas. Só reabrem se uma autópsia, dado novo out-of-sample ou mudança estrutural de mercado identificar hipótese mecânica nova, não testada, com plausibilidade quantificada de sobreviver a custo. Para estratégias com ciclo de execução comparável ao caso pairs/stat-arb, a régua mínima é edge bruto a priori >= 2x o custo total de ciclo. Toda reabertura exige pré-registro e validação forward-only.

## Estado final do lab

- Fase F maker-shadow rodando em observação.
- Graveyard fechado e documentado.
- Price-action encerrado salvo hipótese mecânica nova.
- Funding BTC segue 1º da fila pós-pausa.
- Nada de abrir EXP novo por causa da autópsia agora.
