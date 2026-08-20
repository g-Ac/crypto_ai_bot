# Nota de interpretação pré-registrada — batch B-20260701 (escrita ANTES do veredito)

**Data:** 2026-07-02 · **Escrita antes de qualquer dado forward ser olhado.**
**Papel:** compromisso de LEITURA do veredito de 01/08. NÃO altera a régua congelada
(journal intocado). Origem: revisão adversarial de 2026-07-02 (60 agentes, 6 dimensões),
que confirmou dois achados sobre o dimensionamento — não sobre a tese.

## O que a revisão confirmou (2 verificadores adversariais cada)

1. **A densidade do dry-run estava inflada ~2×.** A estimativa "~52 eventos em 30d" foi
   contada raw no painel cheio, sem simular o pipeline real do colhedor. Medição realista
   (corte do painel ANTES da primitiva + dedupe + trade_returns): **n esperado ~32-34** no
   forward de 30 dias para o sweep — colado no `n_min=30`.
2. **Warm-up estrutural:** o colhedor corta o painel em `corte_ts` antes da primitiva →
   `rolling(30)` em candles 4h + confirmação de pivô = **~5-8 dias do forward sem sinal**.
   Janela efetiva ≈ 22-25 dias, não 30.

Com dispersão de Poisson (σ≈6), a probabilidade do sweep fechar com **n < 30** é material
(~15-25%) mesmo se julho tiver a densidade de liquidações de junho.

## Compromisso de leitura (o que assino hoje)

| Cenário em 01/08 | Leitura pré-comprometida |
|---|---|
| Sweep com n ≥ 30, julgado | Veredito válido — aceitar como está (candidato ou NO-GO). |
| **Sweep com n < 30 (DADO-INSUFICIENTE)** | **Falha de DIMENSIONAMENTO da régua (minha), não da tese.** A tese não foi testada. Fica autorizado re-propor como pré-registro NOVO (batch novo, marco maior dimensionado com o pipeline completo: corte + warm-up + dedupe). NÃO é "re-rodar até passar": é corrigir uma régua comprovadamente mal calibrada ANTES de ver o resultado, com a correção registrada aqui, hoje. |
| Discriminante | Densidade ~67/sem → n esperado ≫ 30; sem risco de dimensionamento. Veredito aceito como está. |

## Caveat de outage (também pré-registrado)

`liq_sell_notional` usa `fillna(0)`: hora sem coleta = zero FALSO. O coletor Bybit já caiu
2× (~58h) em junho; o watchdog (30min) mitiga mas não elimina. **Compromisso:** ao ler o
veredito, verificar a cobertura do coletor no período forward (`k_liquidations` por dia).
Se houver gap > 12h dentro do forward, anotar no veredito que os thresholds rolling foram
contaminados por zeros falsos no trecho e ponderar a leitura (não invalida
automaticamente; registra a contaminação).

## O que esta nota NÃO autoriza

- Mexer no journal, nas primitivas, no n_min ou em qualquer código de medição antes de 01/08.
- Re-julgar um registro `judged`.
- Ler "DADO-INSUFICIENTE" do sweep como evidência contra (ou a favor) da tese.
