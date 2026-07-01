# Propostas de Primitiva (Modo B) — pré-catálogo, NÃO-journal

Este diretório guarda **propostas de primitiva nova** geradas pela mesa (Gerador-Seletor,
ver `../BRIEFING_AGENTES.md` §8). Uma proposta é uma **tese + desenho de primitiva candidata**,
**não** um sinal aprovado e **não** um pré-registro executável.

> Regra dura: **nada aqui toca `journal.jsonl`.** Uma proposta só vira hipótese congelável depois
> de passar por (1) validação de dados que a bloqueia, (2) revisão humana do mecanismo, (3) entrada
> no `catalogo.py` como primitiva causal. Só então o gerador pode congelá-la.

## Ciclo de vida

```
proposta (aqui)  ──►  Etapa 0: validação de dados  ──►  revisão humana do mecanismo
   proposal_only        (destrava blocked_by)              (aprova o desenho causal)
                                                                   │
                                                                   ▼
                                              primitiva no catalogo.py  ──►  gerador congela no journal
                                                                                (aí sim: forward-only)
```

## Status possíveis (no frontmatter de cada proposta)

| campo | significado |
|---|---|
| `status: proposal_only` | é só proposta; não é executável nem congelável |
| `journal_eligible: false` | proibido ir pro `journal.jsonl` neste estado |
| `blocked_by: <gate>` | o que precisa ser resolvido antes de avançar (ex.: `side_semantics_validation`) |

## Gate ativo

**`side_semantics_validation`** — o coletor grava o campo `side` de `k_liquidations` **cru**, sem
normalizar. A convenção (lado da ordem vs lado da posição) muda o sinal de toda tese de liquidação.
Precisa ser validado empiricamente antes de qualquer desenho definitivo. Ver
[`ETAPA_0_side_semantics.md`](ETAPA_0_side_semantics.md).

## Propostas atuais — batch `B-liquidacao-01` (2026-07-01)

| id | primitiva | família de mecanismo | scores | status |
|---|---|---|---|---|
| PROP-20260701-01 | `sig_liquidacao_sweep_estrutural` | exaustão + âncora estrutural | 17/18 | ✅ CONGELADA — PR-20260701-001, marco 01/08 |
| PROP-20260701-02 | `sig_liquidacao_discriminante` | fluxo forçado vs repricing | 16/18 | ✅ CONGELADA — PR-20260701-002, marco 01/08 |

Fronteira: **liquidação tick-level** · marco-alvo: **13/07/2026**.
