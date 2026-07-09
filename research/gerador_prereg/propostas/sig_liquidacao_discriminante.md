---
id: PROP-20260701-02
tipo: proposta_primitiva
modo: B
status: frozen_no_journal  # PR-20260701-002 · batch B-20260701 · marco 2026-08-01
journal_eligible: consumado_2026-07-01
side_semantics: validado_2026-07-01  # BUY=long_liq (venda forçada) · SELL=short_liq
blocked_by: []  # CONGELADA — forward-only até 01/08 (FDR sobre 2 com a sweep no B-20260701)
created_at: 2026-07-01
batch: B-liquidacao-01
primitiva: sig_liquidacao_discriminante
mecanismo_familia: discriminante_fluxo_forcado_vs_repricing
fronteira: liquidacao_tick_level
marco_alvo: 2026-08-01  # corrigido 02/07 (era 13/07 no rascunho; o congelado no journal é 01/08)
scores: {mecanismo: 3, anti_beta: 2, novidade: 3, causalidade: 3, fee_r: 2, diversidade: 3, total: 16}
---

# Proposta — `sig_liquidacao_discriminante`

> ✅ **CONGELADA no journal** — `PR-20260701-002` · batch `B-20260701` · marco **01/08/2026** · corte forward 02/07.
> Mesmo caminho da sweep: side → feed → mechanism review → primitiva causal + 4 testes → dry-run densidade (~67 ev/sem) → congelada.
> FDR sobre 2 com a sweep (mesmo batch). **Forward-only:** ninguém toca até 01/08.

## Mecanismo (por que deveria pagar)

Duas quedas podem ser **idênticas no gráfico** e ter causas opostas:
- queda **com** venda forçada (liquidação alta) = venda **inelástica e temporária** (o forçado
  vende sem olhar preço e para quando a posição acaba) → **overshoot** → tende a **reverter**;
- queda **sem** liquidação = venda **voluntária/informada** (repricing de valor) → tende a **continuar**.

A liquidação é usada como **discriminante da qualidade do movimento** — informação que o preço
sozinho não carrega. Não é gatilho de clímax; é um **classificador** do que causou a queda.

**Quem é forçado a quê:** separa quem *foi obrigado* a vender (alavancado liquidado) de quem
*escolheu* vender (reprecificação informada).

## Desenho da primitiva (candidata)

De forma causal:
1. detecta **queda** de janela fechada (retorno `< -X`, via z causal);
2. mede **intensidade de venda forçada** simultânea (`notional` de liquidação na mesma janela);
3. se queda **com** liquidação alta (≥ **P75 causal**) → **long** (aposta na reversão do overshoot);
4. se queda **sem** liquidação (< P25) → **não opera** (ou short — a decidir na revisão).

## Campos que lê

- `k_liquidations`: `notional` da venda forçada por janela
- `k_prices`: retorno da janela

## Como garante causalidade

- retorno de **janela fechada** (nunca a barra em formação);
- percentis P25/P75 **expanding causais** (`shift(1)`);
- ✅ **`side` validado (Etapa 0):** venda forçada = **`side=BUY`** (long liquidado; 97% após queda).
  ⚠️ corrigir o comentário em `bybit_liquidation_feed.py:11` ("lado da ordem" → "lado da posição") antes de codar.

## Horizonte esperado

~8h (reversão do overshoot). Menos "cauda" que a sweep estrutural; movimento mais modesto.

## Principal modo de falha

**Capitulação genuína**: liquidação alta acompanha queda que **continua** (não reverte) — o
discriminante confunde clímax de pânico com **começo** de quebra. Além disso, o limiar "com/sem
liquidação" (P75/P25) pode ser arbitrário — a definir com cuidado na revisão.

## Scores (rubrica §8)

| mec | anti-β | nov | caus | fee/R | div | **total** |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 3 | 2 | 3 | 3 | 2 | 3 | **16/18** |

**why_selected:** mecanismo **distinto** da sweep estrutural (não é esgotamento-clímax; é separar
fluxo forçado de fluxo informado). Cria informação nova onde o preço é ambíguo. `fee_r=2` porque o
alvo (reversão de overshoot) é mais modesto que o alvo estrutural da PROP-01.
