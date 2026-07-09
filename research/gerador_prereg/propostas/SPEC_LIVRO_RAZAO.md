I've read all the real code. Now I have what I need to ground the spec: `colhedor.colher()` (BH-FDR per `batch_id`, writes `verdict` with the exact fields listed), `schema` (`validate` allows extra top-level keys; `new_frozen` signature; `_corte_amanha` logic in gerador; `rewrite`/`append` revalidate), `catalogo` (`spec_signature` excludes `side` and fee → discovery and confirmation share signature naturally; `build_trades` re-instantiates from spec), and `stats.summarize` (returns only scalars — no median/std, so tail-aware allocation must re-run `build_trades`). Here is the synthesized spec.

---

# SPEC — Livro-Razão / Carteira de Apostas + Automação da Mesa

Módulo: `research/gerador_prereg/` (Gerador-Seletor de Hipóteses)
Data: 2026-07-08 · Arquiteto-chefe: síntese das lentes minimalista / rigor-estatístico / gestor-de-portfólio
Regra-mãe: **o `journal.jsonl` é a única fonte de verdade congelada. O livro-razão é uma VIEW derivada. Não duplicar verdade, não prever preço, não mexer na régua congelada.**

## 0. Princípio de síntese (por que este desenho e não os dois puros)

| Conflito | Design 1 (minimalista) | Design 2 (gestor) | **Decisão** |
|---|---|---|---|
| Persistência de estado | zero estado mutável, tudo deriva do journal | `carteira.jsonl` carry-state | **Design 1 vence.** O estado é 100% derivável do journal via `spec_signature` (máx. 1 descoberta + 1 confirmação por assinatura, garantido pela topologia). Nenhum `carteira.jsonl`. Zero bug de sincronia. |
| Batch da confirmação | `CONF-YYYYMMDD` (compartilhado) | `CONF-<hash8>` (batch de 1) | **Design 1 vence (mais rigor).** Batch compartilhado faz o BH-FDR do colhedor pagar multiplicidade entre as confirmações simultâneas. Batch-de-1 passaria trivialmente — mais fraco. |
| Régua de confirmação | idêntica + consistência de sinal | mais dura (p≤0.05) | **Design 1 vence (anti-goalpost).** Não invento threshold mais duro (isso é mover a trave). A força vem de graça de exigir DOIS passes independentes (FDR efetiva ≈ 0.10×0.10 ≈ 0.01) + pooled>0. |
| Alocação | downside-Kelly `mu/dd²` | Kelly empírico + ES + de-correlação | **Núcleo do Design 1** (downside-dev, concreto e barato no Pi) + **ruin-guard do Design 2** (worst-loss) + **de-correlação como passo opcional tardio**. |
| Demissão / cluster | fora de escopo | dentro | **Fora do escopo atual.** Só faz sentido depois que a carteira existe (pós-01/08). YAGNI agora. |

---

## 1. Decisão de escopo — o que se constrói AGORA vs. o que espera 01/08

**Verdicts REAIS só chegam em 01/08.** Tudo abaixo é buildável e testável HOJE com verdicts sintéticos (dicts hand-crafted no mesmo formato que o colhedor grava), zero dependência de dado real.

### Construir AGORA (pré-01/08) — funções PURAS, testadas com verdicts sintéticos
1. `livro_razao.build_book(recs)` — reducer puro journal → estados por hipótese. **Implementável imediatamente, é o passo 1.**
2. `confirmador.freeze_confirmations(recs, agora)` — congela CONF- pré-registros para candidatas. Idempotente. Testável com verdict sintético (não precisa colher real).
3. Resolução de confirmação dentro do `build_book` (candidata → na_carteira | rejeitada_conf).
4. `livro_razao.allocate(dist_by_label)` — fórmula cauda-aware, função pura de arrays `ret_net_bps` sintéticos.
5. CLI + render `carteira.json` (glue; único passo que toca `build_trades` com panels reais no marco — testado com panels-fixture sintético).

### Esperar 01/08 (dado real, nenhum código novo)
- Os verdicts reais das 7 descobertas frozen preenchidos pelo colhedor no cron do marco.
- A primeira execução real do `confirmador` sobre candidatas reais.
- A carteira só deixa de ser vazia quando uma hipótese CONFIRMAR (2º forward), ou seja **não antes de ~01/09**. **Carteira vazia é estado VÁLIDO, não erro** — renderizar `{hipoteses:[], sleeve_total:0}` normalmente.

### Mínimo viável (o que precisa existir para o dono "apostar racionalmente")
`build_book` (estado) + `confirmador` (a trava descoberta→confirmação) + `allocate` (o tamanho). Sem esses três não há carteira. De-correlação, demissão, e a automação da mesa (Bloco 2) são incrementos posteriores.

---

## 2. Data model — arquivos exatos e como deriva sem duplicar verdade

### Fonte de verdade (intocada)
`research/gerador_prereg/journal.jsonl` — 1 linha = 1 pré-registro. Writers permanecem **três**: `gerador` (descobertas), `confirmador` (confirmações, NOVO), `colhedor` (verdicts). **`livro_razao` NUNCA escreve no journal.**

### Chave de identidade de uma hipótese
`cat.spec_signature(spec)` — já existe, canônica, **exclui `side` e fee** (verificado no código: `parts = [signal, kv(signal_params), filter, kv(filter_params), universe, "H{bars}"]`). Descoberta e confirmação da mesma tese têm spec byte-idêntica → **mesma signature automaticamente**. Distinguem-se pelo `batch_id` (`B-*` = descoberta, `CONF-*` = confirmação).

**Garantia de unicidade** (a topologia que substitui qualquer contador): o `gerador` dedup por signature (`usadas`) → no máx. 1 descoberta por assinatura. O `confirmador` é idempotente por assinatura → no máx. 1 confirmação. Logo **cada assinatura tem no máximo {1 descoberta + 1 confirmação}, para sempre**. Isso é a trava anti-"re-rodar até passar" embutida na estrutura.

### Convenção de confirmação no journal
- `batch_id = "CONF-YYYYMMDD"` (dia do congelamento da confirmação, compartilhado entre confirmações do mesmo cohort).
- Campo novo OPCIONAL `confirms = <id da descoberta>` (proveniência legível). **Não é necessário para a lógica** (a signature já liga os dois); `schema.validate` aceita chaves extras no top-level (verificado: só exige as REQUIRED presentes, não rejeita extras). Recomendado por auditabilidade.
- `corte_ts`, `marco` distintos da descoberta (§4).

### Artefato derivado (regenerável, NUNCA lido de volta como verdade)
`research/gerador_prereg/carteira.json` — irmão de `resultado.json`, marcado `"derived": true`. Estrutura:
```json
{
  "gerado_em": "<iso>",
  "hoje": "<date>",
  "hipoteses": [
    {"label": "<spec_signature>", "estado": "na_carteira",
     "forwards": [{"batch_id":"B-20260618","n":42,"expectancy_net_bps":31.2,"p_value":0.03,"passes_fdr":true},
                  {"batch_id":"CONF-20260801","n":38,"expectancy_net_bps":27.5,"p_value":0.04,"passes_fdr":true}],
     "alloc": {"mu_bps": 29.1, "dd_bps": 61.0, "n": 80, "kelly": 0.078,
               "shrink": 0.727, "alloc_weight": 0.014, "alloc_pct": 1.0, "motivo": "ok"}}
  ],
  "sleeve_total": 0.014,
  "caixa": 0.986
}
```
Tudo em `hipoteses[].forwards` e `alloc` é **re-derivado** de `recs` + `cat.build_trades` no momento do render. Nada é fonte de verdade.

### Sobre `bot.db`
**Não tocar.** O livro-razão vive em JSONL/JSON como o resto do módulo (git-friendly, escala de dezenas de hipóteses, e mantém visível que só o journal é verdade). `exp100` lê `bot.db` read-only só para `k_prices`/`k_liquidations` via `datamod.load_panel()`.

### O único ajuste upstream opcional
Adicionar `median_bps` e `downside_dev_bps` ao dict de `stats.summarize` (2 números), para a alocação derivar do verdict sem re-rodar `build_trades`. **Decisão: NÃO fazer agora.** A alocação re-roda `cat.build_trades` só para os ~poucos membros da carteira no marco (barato no Pi, poucos membros). Mantém `summarize`/verdict congelados e o livro-razão como função pura do journal + panels. (Se no futuro a carteira crescer muito, reconsiderar — backward-compatible.)

---

## 3. Máquina de estados — transições e quem dispara

Estados por IDENTIDADE (`spec_signature`), todos DERIVADOS pelo reducer exceto onde marcado "escreve journal":

```
proposta ─(gerador.gerar; escreve journal frozen)→ frozen
frozen ─(implícito: corte_ts passou, marco não venceu)→ em_forward
em_forward ─(colhedor.colher no marco; escreve verdict, status=judged)→ judged
judged ─(build_book, leitura)→ candidata        [is_candidato==true]
judged ─(build_book, leitura)→ rejeitada        [n>=n_min & !is_candidato]  ⟂ terminal
judged ─(build_book, leitura)→ dado_insuficiente [n<n_min]                   ⟂ terminal (re-dim só humano)
candidata ─(confirmador.freeze_confirmations; escreve journal CONF- frozen)→ em_confirmacao
em_confirmacao ─(colhedor.colher no marco2; escreve verdict)→ [conf judged]
[conf judged] ─(build_book, leitura)→ na_carteira      [regra §4 passa]
[conf judged] ─(build_book, leitura)→ rejeitada_conf   [regra §4 falha]    ⟂ terminal
[conf judged] ─(build_book, leitura)→ dado_insuf_conf  [conf n<n_min]      ⟂ terminal (re-dim só humano)
```

**Quem dispara cada escrita no journal (3 writers, resto é leitura pura):**
| Transição | Disparador | Cron |
|---|---|---|
| proposta→frozen | `gerador.gerar()` | `scripts/gerador_prereg_trigger.py` (existe) |
| em_forward→judged | `colhedor.colher()` | `scripts/juiz_forward_trigger.py` (existe) |
| candidata→em_confirmacao | `confirmador.freeze_confirmations()` | `scripts/livro_razao_trigger.py` (NOVO, roda DEPOIS do colhedor no marco) |
| todas as classificações de estado + render | `livro_razao.build_book()` / `.render()` | mesmo trigger, e/ou CLI on-demand |

**Terminais (⟂):** `rejeitada`, `rejeitada_conf` mantêm a signature no journal → `gerador` não re-propõe (dedup) e `confirmador` não re-confirma (CONF já existe ou descoberta rejeitada nunca vira candidata). `dado_insuficiente*` é terminal automático; **re-dimensionamento só por decisão HUMANA** (protocolo NOTA_VRP), nunca pelo confirmador — é isso que impede garimpo por janela.

---

## 4. Descoberta → Confirmação — o coração da honestidade

### O 2º forward É um pré-registro novo auto-congelado? **Sim.**
`confirmador.freeze_confirmations(recs, agora)`:
1. Deriva as **candidatas** direto do journal (não de `resultado.json`): registros `judged`, batch não-`CONF-`, `verdict.is_candidato == true`, **sem** CONF-record irmão (mesma signature). Auto-contido.
2. Para cada candidata sem confirmação, monta um pré-registro via `schema.new_frozen(...)` com:
   - **spec BYTE-IDÊNTICA** à da descoberta (replicação, não nova busca) — mesmo `signal`/`params`/`filter`/`side`/`exit`/`universe`.
   - `corte_ts = _corte_amanha(agora)` (meia-noite UTC do dia seguinte). Reusa a lógica do gerador; `schema.validate` já **rejeita corte não-estritamente-futuro vs created_at = mata o viés temporal** (verificado, linha 98-99 do schema).
   - **Janela disjunta garantida:** a confirmação é congelada NO/APÓS o marco da descoberta (01/08), então `corte2 = 02/08 > marco_descoberta (01/08)`. O forward de confirmação `[corte2, marco2)` é estritamente posterior ao forward da descoberta `[corte1, marco1)`. Independência = dado que não existia no 1º julgamento.
   - `batch_id = "CONF-YYYYMMDD"` (compartilhado no cohort → BH-FDR paga multiplicidade entre confirmações simultâneas).
   - `marco = marco_conf` (default: próximo marco mensal, ex. `2026-09-01`; parametrizável).
   - `confirms = <disc_id>` (proveniência, opcional).
   - `schema.append(journal, rec)` (revalida).
3. **BYPASSA de propósito o dedup `spec_signature` do gerador.** A confirmação é a ÚNICA re-congelada sancionada do mesmo spec. Consequência estrutural: como a signature já está em `usadas`, o gerador nunca re-propõe aquele spec como descoberta nova → cada spec recebe no máx. descoberta + 1 confirmação. **Documentar forte: se o confirmador aplicasse o dedup cru do gerador, a confirmação seria bloqueada e a hipótese jamais confirmaria.**
4. **Idempotente:** pula qualquer candidata que já tenha CONF-record com sua signature (rodar 2× → 1 confirmação).

### A régua de confirmação — IDÊNTICA à descoberta + 2 gates, NÃO mais dura
O mesmo `colhedor` julga o CONF-record no marco2 (mede só `bucket_ts >= corte2`, aplica BH-FDR no batch `CONF-`). **Zero código novo no colhedor.** Régua de entrada na carteira, aplicada por `build_book` (leitura):
1. **Barra dura idêntica** (a que o próprio colhedor já aplica): `conf.verdict.is_candidato == true` (⇔ `n >= n_min` **e** `expectancy_net_bps > threshold(=0)` **e** `passes_fdr` no batch CONF-).
2. **Pooled > 0:** expectancy da UNIÃO das janelas forward (re-medida, §5) `> 0`. Guarda contra confirmação que passou raspando enquanto a descoberta decaiu.
3. **Consistência de sinal:** subsumida por (1)+(2) — ambos os forwards têm expectancy `> 0` (threshold=0), então o sinal já é consistente. Documentar a intenção.

**Por que NÃO invento p≤0.05:** mover a trave é goalpost-moving. A força extra vem **de graça** de exigir DOIS passes independentes em janelas disjuntas: FDR efetiva ≈ 0.10 × 0.10 ≈ 0.01. Lucrou uma vez nunca basta — por construção, não por threshold ad-hoc.

**Por que NÃO vira re-rodar-até-passar:** (a) exatamente 1 tentativa de confirmação por candidata; (b) a MÁQUINA escolhe quando testar (dia seguinte ao marco), não o humano; (c) falha → `rejeitada_conf` terminal, signature permanece no journal → nunca re-congelada. Uma tese que falhou a confirmação só pode voltar como **primitiva/variação DISTINTA** (signature diferente), jamais como a idêntica.

---

## 5. Alocação cauda-aware — UMA fórmula concreta

Para cada membro `na_carteira`, o livro re-instancia a spec via `cat.build_trades(spec, forward_panels)` sobre **TODO o forward desde o corte da descoberta** (`corte1`) — uma única medição contínua do track record out-of-sample (evita o bug de concatenar duas janelas medidas separadamente). Vetor `r` = `ret_net_bps` (bps). `R = r / 1e4` (retorno fracionário por trade).

```python
N0     = 30      # meia-vida da evidência (n=30→shrink .5, n=90→.75)
KFRAC  = 0.25    # quarter-Kelly (full-Kelly pressupõe estacionariedade que não existe)
W_CAP  = 0.25    # nenhum edge isolado > 25% do sleeve

mu = mean(R)
dd = sqrt(mean(minimum(R, 0)**2))     # downside deviation — SÓ a cauda esquerda entra
n  = len(R)
shrink = n / (n + N0)                  # força do track record

if mu <= 0:
    w = 0.0                            # VETO: mata "mediana+ com média−" (o caso-veneno do VRP)
elif dd == 0:
    w = W_CAP * shrink                 # sem perdas: capado+shrunk (não Kelly→∞), conservador
else:
    kelly = mu / dd**2                 # downside-Kelly: aposta MENOS quando a cauda é gorda
    w = min(KFRAC * kelly * shrink, W_CAP)

# ruin-guard (dominância de cauda): um único trade apaga o pnl cumulativo do edge
if mu > 0 and abs(min(R)) > mu * n:
    w = 0.0

alloc_weight_i = w                      # fração ABSOLUTA do sleeve
```

Normalização do sleeve (caixa é posição válida — lab forward-only, sem alavancagem):
```python
S = sum(alloc_weight_i)
if S > 1.0:                             # escala para caber
    alloc_weight_i *= 1.0 / S
caixa = max(0.0, 1.0 - sum(alloc_weight_i))
alloc_pct_i = alloc_weight_i / sum(alloc_weight_i)   # convicção relativa (0 se todos 0)
```

**Por que downside-dev e não sigma total:** distribuição com upside gordo NÃO é punida (queremos assimetria positiva); só a variância de PERDA reduz a aposta. É exatamente a leitura do VRP: `dd²` explode com caudas de perda raras e profundas → `kelly` colapsa. O veto `mu<=0` mata o padrão "mediana+ média−" (parece bom no meio, sangra na cauda). O `shrink` codifica "quanto track record" — mais trades independentes acumulados = aposta maior.

**De-correlação (passo OPCIONAL, incremento pós-carteira):** quando ≥2 membros existirem, alinhar séries de `ret` por bucket `entry_ts`, calcular corr par-a-par; se corr > 0.5 e sobreposição ≥ k_min buckets, dividir peso por `sqrt(tamanho_cluster)` (duas teses de liquidação podem ser o MESMO risco). **Não no MVP** — com sobreposição pequena a corr é instável; tratar como não-correlacionado (conservador) até haver dado.

---

## 6. Automação da mesa (Bloco 2) — escopo honesto

Fronteira: as **MÃOS** da mesa automatizam sem LLM; o **CÉREBRO criativo** fica pluggable.

### Automatizável AGORA (Python puro determinístico, cron-safe, roda headless no Pi, $0)
Novo `research/gerador_prereg/mesa.py`, fino, sobre o `gerador`:
- **Gate de congelamento:** `schema.validate` (primitiva ∈ catálogo, param válido, corte estritamente futuro) — já é 90% da guarda.
- **Curadoria contra cemitério + catálogo:** `cemiterio` = view DERIVADA (fold do journal: signatures com `verdict.is_candidato==false` NO-GO, `rejeitada_conf`; + signatures já no journal). A mesa RECUSA congelar qualquer signature no cemitério ou já registrada. Causalidade é garantida por construção (só primitivas causais do catálogo) — "olha ≥ t" nunca passa, não precisa de juiz de causalidade.
- **Gate de FORMATO:** valida a shape do template de saída (≤3 selecionadas por batch, `hypothesis`/`motivation` presentes, mecanismos distintos por signature) antes de permitir freeze.
- **Orquestração sob demanda:** `mesa.py` consome `propostas/*.json` (o dir `propostas/` já existe), roda a triagem mecanizável (dedup, catálogo, cemitério, formato) e congela os sobreviventes via `gerador`. Cron gera batches on-demand. + `confirmador` (100% determinístico).

### Pluggable (exige criatividade/julgamento → Claude API OU humano-no-loop)
- **GERAÇÃO de hipóteses novas com mecanismo** (a tese "quem é forçado a quê").
- **Escrever primitiva NOVA** em `catalogo.py` (função causal nova) — código criativo; o layer determinístico só COMPÕE primitivas existentes. Primitiva nova = PR humano/LLM, validado por schema + testes antes de entrar no catálogo.
- **Crítica anti-beta-de-regime e scoring da rubrica** (mecanismo/anti-beta/novidade) — é JULGAMENTO, não mecanizável.

**Interface pluggable:** humano ou Claude larga um dict-candidato em `propostas/`; o gate determinístico valida + congela. `anthropic` é dep do projeto → step LLM opcional atrás de flag, **default = humano-drop-file** ($0, offline). **O AI gate local llama.cpp está DESATIVADO e é fraco demais para geração — NÃO usar.** **NENHUM agente prevê preço:** a mesa gera RÉGUAS ex-ante; o colhedor/mercado julga no marco.

---

## 7. Build order — passos numerados, cada um com o teste que o prova

Todos os arquivos em `research/gerador_prereg/`. Testes em `tests/`. Passos 1-4 são funções PURAS, testáveis HOJE com verdicts sintéticos (o hook PostToolUse roda pytest sozinho).

### Passo 1 — `livro_razao.build_book(recs) -> dict` (IMPLEMENTÁVEL IMEDIATAMENTE)
Reducer PURO: agrupa `recs` por `cat.spec_signature(r["spec"])`; para cada assinatura separa descoberta (batch não-`CONF-`) e confirmação (batch `CONF-`); classifica estado por `status` + `verdict`:
- descoberta `frozen` → `frozen`/`em_forward`
- descoberta `judged`: `is_candidato` → `candidata`; `n<n_min` → `dado_insuficiente`; senão `rejeitada`
- (confirmação resolvida no passo 3)
Sem alocação, sem confirmação ainda.
**Teste `test_livro_razao.py`:** recs hand-crafted com verdicts sintéticos (um candidata, um rejeitada `n=50 is_candidato=false`, um `n=12` dado_insuficiente, um frozen sem verdict) → assert estado correto por assinatura. Zero dado real.

### Passo 2 — `confirmador.freeze_confirmations(recs, agora) -> list[novos_ids]`
Dada candidata sem CONF-record, monta+valida+append CONF frozen (`schema.new_frozen`, `corte=_corte_amanha`, batch `CONF-YYYYMMDD`, `confirms=disc_id`, marco_conf).
**Teste `test_confirmador.py`:** (a) idempotência — roda 2× → exatamente 1 CONF-record; (b) `corte_ts` estritamente futuro (passa `schema.validate`); (c) mesma signature que a descoberta; (d) bypass do dedup — congela apesar da signature já existir; (e) candidata que já tem CONF → no-op. Verdict sintético.

### Passo 3 — resolução de confirmação no `build_book`
Assinatura com CONF-record `judged` → `na_carteira` se (regra §4: `conf.is_candidato && pooled>0`) senão `rejeitada_conf`; CONF `frozen` → `em_confirmacao`; CONF `n<n_min` → `dado_insuf_conf`.
**Teste:** cadeia sintética descoberta→confirmação, 2 forwards — caso confirma (→na_carteira) e caso falha-confirmação (→rejeitada_conf); assert `rejeitada_conf` é terminal (não re-promove).

### Passo 4 — `livro_razao.allocate(dist_by_label) -> dict[label, alloc]`
Função PURA da fórmula §5, recebe arrays `ret_net_bps` sintéticos por label.
**Teste:** (a) mediana+ com média− → `w=0`; (b) cauda gorda (`dd` grande) → kelly pequeno; (c) `n` pequeno → shrink puxa; (d) teto `W_CAP`; (e) ruin-guard (um trade > mu·n) → `w=0`; (f) normalização soma ≤ 1 e caixa = resto; (g) todos zero → carteira vazia válida.

### Passo 5 — CLI + render `carteira.json`
Glue fino: `read_journal → build_book →` para labels `na_carteira` carrega panels (`datamod.load_panel`) + `cat.build_trades` (forward desde `corte1`) → `allocate` → escreve `carteira.json`. Único passo que toca dado real.
**Teste de integração:** journal sintético + panels-fixture (dict de DataFrames pequenos) → `carteira.json` bem-formado; e caso carteira-vazia → `{hipoteses:[], sleeve_total:0, caixa:1.0}` sem erro.

### Passo 6 — `scripts/livro_razao_trigger.py` (cron glue, espelha `gerador_prereg_trigger.py`)
Roda DEPOIS do colhedor no marco: `confirmador.freeze_confirmations` → `build_book` → render → notifica Telegram. Idempotente.
**Teste end-to-end sintético:** freeze→judge→promote→judge-conf→confirm→allocate, tudo com fixtures, zero `bot.db`.

### Passo 7 (Bloco 2) — `mesa.py` + cemitério derivado
`cemiterio(recs)` (fold NO-GO + rejeitada_conf + signatures usadas) + wrapper sobre `gerador.gerar` que recusa signatures mortas + gate de formato de `propostas/`.
**Teste:** spec no cemitério é recusada; fila esgotada → SKIPPED; primitiva nova exige PR (não auto-gerada).

### Passo 8 (opcional, tardio) — de-correlação no `allocate`
Só quando ≥2 membros. Guardado por sobreposição mínima. Não no MVP.

---

## 8. O que NÃO fazer (armadilhas)

1. **Não criar `carteira.jsonl` nem tabela SQLite de estado.** O journal já determina 100% do estado via signature. Estado mutável duplicado = bug de sincronia garantido. A carteira é VIEW.
2. **Não mexer na régua congelada** — não alterar `colhedor`, `stats.summarize`, `schema` defaults (`N_MIN=30`, `THRESHOLD=0`, `FDR_Q=0.10`, custo 12 bps), nem os specs frozen. O livro-razão é uma CAMADA POR CIMA, read-only sobre o journal.
3. **Anti-goalpost:** não inventar threshold de confirmação mais duro (p≤0.05, PF mínimo, etc.). A força vem de DOIS passes independentes, não de trave móvel.
4. **Anti-garimpo:** exatamente 1 confirmação por candidata; falha é terminal; a máquina (não o humano) escolhe quando testar; `dado_insuficiente` re-dimensiona só por decisão humana explícita. Nunca re-congelar a signature idêntica.
5. **Não aplicar o dedup cru do gerador no confirmador** — bloquearia toda confirmação (a signature já está em `usadas`). O bypass é a única exceção sancionada; documentar forte no código.
6. **Não prever preço.** Nem no allocate (dimensiona edges existentes, não projeta retorno), nem na mesa (gera réguas ex-ante; o mercado julga no marco), nem em nenhum agente do Bloco 2.
7. **Não ligar geração criativa autônoma no Pi** (llama.cpp desativado/fraco) — reintroduz beta-de-regime disfarçado e regenera becos enterrados. Geração fica human/Claude-triggered; só o gate determinístico congela.
8. **Não concatenar as duas janelas forward medidas separadamente** para a alocação — re-medir a UNIÃO contínua desde `corte1` numa única passada de `build_trades` (evita overlap/dupla-contagem).
9. **Carteira vazia é estado válido** — por densidade forward baixa (lição NOTA_VRP), muitos labels fecham `dado_insuficiente` e a carteira pode ficar vazia por 1-2 marcos. Renderizar vazio, nunca erro.

---

### Arquivos entregáveis
- `research/gerador_prereg/livro_razao.py` (build_book, allocate, render) — NOVO
- `research/gerador_prereg/confirmador.py` (freeze_confirmations) — NOVO
- `research/gerador_prereg/mesa.py` (Bloco 2) — NOVO, posterior
- `research/gerador_prereg/carteira.json` — artefato gerado (derived)
- `scripts/livro_razao_trigger.py` — cron glue, NOVO
- `tests/test_livro_razao.py`, `tests/test_confirmador.py`, `tests/test_mesa.py` — NOVOS
- **Zero modificação** em `colhedor.py`, `schema.py`, `gerador.py`, `catalogo.py`, `stats.py`, `backtest.py`, `journal.jsonl`.
---

## CORREÇÃO 2026-07-08 (pós revisão adversarial — 14 agentes)

Dois findings confirmados (8 refutados pelo verificador). Ambos corrigidos; nada da régua congelada foi tocado.

1. **Gate pooled>0 agora RE-ROTULA** (não só veta o peso). `build_book` classifica `na_carteira`
   de forma *provisória* (não tem panels); `render()` finaliza: se o pooled contínuo (desde
   `corte1`) tem `mu <= 0`, rebaixa para `rejeitada_conf` (terminal, cemitério). Antes o rótulo
   `na_carteira` sobrevivia com peso 0 — dinheiro seguro, mas classificação mentindo.

2. **Fórmula de alocação trocada para fator-cauda SATURANTE.** O `mu/dd²` do design minimalista
   **degenerava ao teto** para qualquer edge realista (retornos de trade são frações pequenas →
   `dd²` minúsculo → kelly na casa das centenas → `w = W_CAP` sempre; cauda e shrink inertes).
   Adotado o `tail_factor = mu/(mu + λ·dd)` (lente "gestor de portfólio" do brainstorm), limitado
   em (0,1]: `w = W_CAP · tail_factor · shrink`. Agora cauda gorda e evidência (n) **de fato**
   movem o peso, como era a intenção. λ=1. Alocação NÃO é régua congelada (aplica só pós-01/09),
   então a troca é livre. Testes atualizados provam que o shrink move o peso (antes: asserção vácua).
