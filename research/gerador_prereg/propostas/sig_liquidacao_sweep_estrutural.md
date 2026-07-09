---
id: PROP-20260701-01
tipo: proposta_primitiva
modo: B
status: frozen_no_journal  # PR-20260701-001 · batch B-20260701 · marco 2026-08-01
journal_eligible: consumado_2026-07-01
side_semantics: validado_2026-07-01  # BUY=long_liq (venda forçada) · SELL=short_liq
blocked_by: []  # tudo resolvido; agora é forward-only até 01/08 (NÃO re-rodar, NÃO ajustar)
created_at: 2026-07-01
batch: B-liquidacao-01
primitiva: sig_liquidacao_sweep_estrutural
mecanismo_familia: exaustao_forcados + ancora_estrutural
fronteira: liquidacao_tick_level
marco_alvo: 2026-08-01  # corrigido 02/07 (era 13/07 no rascunho; o congelado no journal é 01/08)
scores: {mecanismo: 3, anti_beta: 2, novidade: 3, causalidade: 3, fee_r: 3, diversidade: 3, total: 17}
---

# Proposta — `sig_liquidacao_sweep_estrutural`

> ✅ **CONGELADA no journal** — `PR-20260701-001` · batch `B-20260701` · marco **01/08/2026** · corte forward 02/07.
> Jornada: side (Etapa 0) → feed corrigido → mechanism review → implementada+testada → dry-run densidade → congelada (2026-07-01).
> **Agora é forward-only:** ninguém toca até o colhedor julgar em 01/08. NÃO re-rodar, NÃO ajustar a régua.

## Spec cravada (mechanism review · 2026-07-01)

| decisão | valor |
|---|---|
| timeframe | **4h** (reamostrar panels horários → 4h; o exit conta barras de 4h) |
| fundo válido | pivô **3 candles/lado** |
| gatilho | notional de venda forçada (`side=BUY`) na perfuração ≥ **P90 rolling(30) causal** (shift 1) |
| rejeição | close volta pra dentro em **≤ 2 candles** de 4h |
| direção · entrada · stop | long · close da rejeição · abaixo da mínima da varredura |
| **saída** | **por tempo, `bars=24` = 24 HORAS (6 candles de 4h)** — o que está congelado no journal. *(O rascunho desta tabela dizia "8 barras de 4h ~32h"; o valor final aprovado na spec técnica foi 24h, dentro do param_space da engine. Corrigido 02/07 — o journal sempre foi 24h.)* |
| escopo | **só o caso-base** (P95/TFs/alvo estrutural → 2º batch se sobreviver) |
| custo · densidade | 12 bps · ≥ 30 eventos independentes |

> Nota: com saída por tempo o perfil vira "retorno médio em 24h" (não "erra muito/acerta grande");
> o perfil de alvo grande volta com o alvo estrutural no 2º batch.

## Mecanismo (por que deveria pagar)

Num **fundo de 4h válido** — onde stops de longs se acumulam — um **pico de venda forçada**
(longs liquidados) esgota a oferta inelástica **de uma vez**. Os vendedores forçados vendem
independente de preço e **param quando a posição acaba**; quando param, some a pressão → vácuo.
Se o preço então **fecha de volta pra dentro** do range (rejeição), tende a reverter em direção ao
topo oposto. É fluxo forçado **+** âncora estrutural — não desenho de preço.

**Quem é forçado a quê:** longs alavancados com stop no fundo, liquidados à força pela engine.

## Desenho da primitiva (candidata)

Detecta, de forma causal:
1. **fundo válido** = pivô de baixa em candles de 4h **já fechados** (shift);
2. **pico de venda forçada** = `notional` de venda forçada agregado numa janela curta na
   perfuração ≥ **P90 causal** (percentil computado só com dados `< t`, expanding);
3. **rejeição** = `close` volta pra dentro (acima do fundo perfurado) em **≤ 2 candles**;
4. **direção** = long (reversão); **alvo** = topo estrutural oposto.

## Campos que lê

- `k_liquidations`: `event_ts`, `side`, `notional`, `symbol`
- `k_prices`: OHLC em 4h (pivôs, close de rejeição)

## Como garante causalidade

- pivô via candles **fechados** (`shift`), nunca o candle em formação;
- P90 **expanding causal** (`shift(1)` — só distribuição passada);
- rejeição lida no `close` do candle atual (informação disponível em `t`).
- ✅ **`side` validado (Etapa 0):** venda forçada de long = **`side=BUY`** (Bybit `allLiquidation`
  = lado da posição; 97% dos BUY após queda). ⚠️ o comentário em `bybit_liquidation_feed.py:11`
  ainda diz "lado da ordem" — corrigir antes de codar a primitiva.

## Horizonte esperado

4h+ (alvo estrutural; teto sugerido 24 barras). Perfil **"erra muito, acerta grande"**.

## Principal modo de falha

**Quebra estrutural real** (não varredura): o fundo cede, a rejeição é temporária, o preço continua
caindo. O filtro "close de volta pra dentro" mitiga mas não elimina. É a origem do "erra muito".

## Scores (rubrica §8)

| mec | anti-β | nov | caus | fee/R | div | **total** |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 3 | 2 | 3 | 3 | 3 | 3 | **17/18** |

**why_selected:** mecanismo duplo (esgotamento de forçados + stops estruturais como combustível);
a condição de rejeição a protege de ser puro beta — não dispara em qualquer queda, só quando há
reação real no nível.
