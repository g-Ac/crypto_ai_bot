# MINI-MOLDURA — Gerador de Pré-Registros (forward-only)

**Status:** CONGELADO 2026-06-18 (moldura de processo, não experimento ativo).
**Origem:** sessão 2026-06-18. O Gabriel propôs um "gerador de hipóteses congeladas"
para o regime forward-only. Esta moldura crava o desenho antes do código.
**Relacionados:** `vault/2026-06-17-juiz-forward-prereg.md`, `research/exp018_directional_force/PREREGISTRO.md`,
memórias `project_juiz_forward`, `feedback_prereg_verificador_dado_real`, `feedback_pressao_financeira_claude`.

---

## Papel (o que ISTO É)

Substitui o anti-padrão "loop que re-roda hipóteses contra o passado" — vigiar N testes no
tempo ≈ ~80% de chance de GO falso por viés temporal (o motivo do Juiz Forward existir).

**NÃO é máquina de achar edge. É máquina de DISCIPLINA.** Transforma "tive uma ideia, deixa eu
backtestar no passado" (o anti-padrão que já matou 5+ experimentos por viés/seleção) em "tive uma
ideia, congelo a régua ex-ante e espero o forward". O `journal.jsonl` é o compromisso público; o
BH-FDR por `batch_id` conta a multiplicidade honestamente.

Justifica-se em **dois papéis** — ambos honestos:
1. **Espaço novo:** hipóteses com primitivas que o Juiz (EXP-100/101/102) **não** cobre —
   sequência de candles, reação a nível, funding-flip, divergência OI×preço, hora-de-sessão,
   regime de vol. Nunca uma re-amostragem do grid de 146 células (isso só inflaria multiplicidade).
2. **Disciplina de processo:** toda ideia futura entra por aqui — congelada antes de ver o forward.

## O que ISTO NÃO É

- **Não emite veredito olhando o passado.** O gerador nunca vê o forward; só o colhedor julga, no marco.
- **Não toca o Juiz congelado** (`research/juiz_forward/judge.py`, EXP-100/101/102, marco 01/08).
- **Não executa ordens nem altera os dados de coleta** (`k_*` em `runtime/baseline/bot.db`, só-leitura).
- **Não autoriza ligar nada operacional.** Candidato = sinal de vida → investigação dedicada, não GO.

---

## Arquitetura (a separação que mata o viés)

```
GERADOR (pode usar criatividade/Claude)          COLHEDOR (Python puro, SEM Claude)
─────────────────────────────────────            ──────────────────────────────────
- lê journal, conta o batch                       - dispara no marco (cron idempotente)
- amostra 1 combinação NOVA e diversa             - lê journal: frozen com marco <= hoje
- congela cortes ex-ante (regra, custo,           - re-instancia cada spec do catálogo
  corte forward, métrica, limiar, n_min)          - mede no forward (corte_ts estritamente futuro)
- grava linha frozen, verdict=null                - BH-FDR conjunto por batch_id (q=0.10)
- NUNCA olha o dado forward                        - grava verdict; idempotente por flag
```

A criatividade vive no gerador; o julgamento é **mecânico**. Como o colhedor é Python puro e
determinístico, o veredito não depende de ninguém "olhar o gráfico" no marco → sem viés de seleção.

---

## Catálogo fechado de primitivas (a trava anti-viés)

`signal`/`filter`/`exit` só podem vir de um **catálogo finito, já codado e testado**. O gerador
**compõe**; **nunca escreve código novo por ciclo**. É isso que torna o colhedor auto-executável.
Cada primitiva carrega um `rationale` (tese mecanicista a priori) — nada de caixa-preta sem lógica.
Adicionar primitiva nova = tarefa de engenharia à parte (codar + testar 1 vez), fora do ciclo.

| Tipo | Primitiva | Rationale a priori (resumo) |
|---|---|---|
| signal | `sequencia_candles` | streaks de N candles mesma cor → exaustão (reversão) ou ímpeto (continuação) |
| signal | `reacao_nivel` | toque + rejeição de máx/mín de janela = suporte/resistência → reversão local |
| signal | `funding_flip` | funding cruza zero/extremo = virada de crowding → correção do desbalanço |
| signal | `oi_preco_div` | OI sobe c/ preço caindo (shorts) ou cai c/ preço subindo (cobertura) → direcional |
| filter | `hora_sessao` | liquidez/comportamento variam por sessão UTC (ásia/europa/us) |
| filter | `vol_regime` | edges de momentum/reversão dependem do regime de vol realizada (causal) |
| exit | `horizonte` | saída no close de entry + H barras (reusa engine validada do EXP-100) |

Re-usa, sem alterar: `exp100_screening.backtest` (medição), `exp100_screening.stats` (BH-FDR),
`exp100_screening.data` (panel). Os 4 sinais e 5 filtros do EXP-100 ficam **fora** deste catálogo
(o Juiz já os varre) — aqui só entra o que é genuinamente espaço novo.

---

## Schema do `journal.jsonl` (1 linha auto-executável = EXP-018 destilado)

| Campo | Conteúdo | Preenche |
|---|---|---|
| `id` | `PR-AAAAMMDD-NNN` | gerador |
| `created_at` | ISO-8601 UTC (congelamento) | gerador |
| `batch_id` / `n_no_batch` | lote + posição no lote | gerador |
| `status` | `frozen` → `judged` / `skipped` | gerador → colhedor |
| `hypothesis` | tese falsificável (1 frase) | gerador |
| `motivation` | observável + rationales das primitivas | gerador |
| `spec.signal` / `spec.signal_params` | primitiva ∈ catálogo + params fixos | gerador |
| `spec.filter` / `spec.filter_params` | primitiva ∈ catálogo (ou `nenhum`) | gerador |
| `spec.side` | `long` / `short` / `auto` (do sinal) | gerador |
| `spec.exit` | `{type:"horizonte", bars:H}` | gerador |
| `spec.universe` | `todos` / `memes` / `large_cap` | gerador |
| `spec.fee_bps_roundtrip` = 10 · `spec.slippage_bps` = 2 | custos travados (total 12 bps) | gerador |
| `forward.corte_ts` | epoch UTC estritamente futuro vs `created_at` | gerador |
| `forward.marco` | data em que o colhedor pode rodar | gerador |
| `forward.metric` = `expectancy_net_bps` | métrica do colhedor | gerador |
| `forward.threshold` = 0 · `forward.n_min` = 30 · `forward.p_method` = `bootstrap` | régua | gerador |
| `verdict` | `null` até o marco; depois objeto do colhedor | **só colhedor** |

---

## Contrato do colhedor

- **Corte forward:** só `bucket_ts >= forward.corte_ts` (dado que não existia no congelamento).
- **Custo:** `fee_bps_roundtrip + slippage_bps` (12 bps) passado à engine `trade_returns`.
- **Métrica/candidato:** `expectancy_net_bps > threshold` **E** passa BH-FDR (q=0.10) sobre os
  p-values do **mesmo `batch_id`** **E** `n >= n_min`.
- **Veredito do batch:** `DADO-INSUFICIENTE` (dias forward < mínimo) · `GO-INVESTIGAR` (≥1 candidato)
  · `NO-GO` (0 candidatos). **GO-INVESTIGAR ≠ GO operacional** — abre investigação dedicada.
- **Aceito sem re-rodar.** Mudar a régua depois de ver o dado = experimento novo, não este.

## Marcos

| Marco | Para | Por quê |
|---|---|---|
| **2026-08-01** (default) | price-action/estrutura hourly | alinhado ao Juiz Forward; ~44d+ de forward genuíno |
| 2026-09-01 | força direcional (EXP-018) | respeita pausa 90d + coleta até ~13/07 |
| 2026-07-13 | liquidação tick-level | **fora deste catálogo** (hourly-invisível; marco próprio) |

Este catálogo usa só o panel hourly (que acumula sozinho) → marco natural = **2026-08-01**.

## Guard-rails

Tudo net · janela sempre declarada · corte estritamente futuro · primitiva ∈ catálogo ·
`motivation` = tese a priori, nunca padrão "visto" no histórico (senão é p-hacking) ·
forward-only · colhedor idempotente · validação só com fixtures sintéticas até o marco
(`feedback_prereg_verificador_dado_real`: ver NO-GO sintético não contamina; stealth fabrica GO).

## Decisões cravadas (2026-06-18, sessão autônoma)

1. **Papel** = disciplina de processo + espaço novo (não mineração do passado).
2. **Isolamento:** diretório próprio `research/gerador_prereg/`; **não** encosta no `judge.py`.
3. **Números:** cap `N = 5` por lote ("poucos e diversos"); `slippage = 2 bps`; `exit = horizonte fixo`.
