# Pré-registro — H4: Indução manipulativa via LSR (Variante A) → reversão forward

**Status:** pré-registrado, **não executado** (forward-only, aguardando amadurecimento de janela).
**Versão:** 1.1 (desenho endurecido após red-team — selado 2026-05-29, antes de qualquer execução com dados reais).
**Tipo:** estrutural / posicionamento. **Hipótese principal** (mecanismo causal claro). NÃO é warm-up.
**Identificador no registry:** EXP-012.
**Pré-condição operacional:** rodar **somente** sobre dados coletados após 2026-05-29 00:00 UTC (regra de não-contaminação cravada no EXP-008/H3). Roda **depois** do H3 e H1 selados — apparatus estatístico (`lab_harness` ≥ 1.2.0) e labeler (`reversal_labeler`) já validados em testes unitários.

> **Critério universal do lab (não renegociável):** uma feature estrutural só passa GO se mostrar **lift incremental ao regime**, não na média agregada. Operacionalizado pela **unidade `PER_ENTITY` com `require_entities=2`** (lição EXP-011) e estratificação por regime em toda permutação. PREREG v1.1 endurece um segundo flanco: **lift incremental ao confound de vol** — operacionalizado pelo placebo de continuação testado via diferença pareada (§6.3).

---

## 1. Hipótese pré-registrada

Em janelas em que (a) top traders perpétuos ficam em posicionamento extremo (top LSR z-score |alto|) **e** (b) o crowd (global LSR) está convergindo aceleradamente na **mesma direção** do top, a probabilidade de reversão forward (na direção contrária ao posicionamento esticado) é **estritamente maior** do que a probabilidade de reversão em janelas sem essa co-ocorrência — **E** essa elevação é assimétrica vs continuação (descarta vol-confound).

Formalmente: seja `trap_score_t` (definido em §3), `R_t ∈ {0,1}` o rótulo de reversão forward via `reversal_labeler.label_reversals`, e `C_t ∈ {0,1}` o rótulo de continuação forward via `label_continuations` (placebo simétrico, §6.3).

- **H0 (nula):** o efeito de `trap_score` sobre reversão e continuação é igual: `P(R=1|trap top) − P(R=1|trap bot) = P(C=1|trap top) − P(C=1|trap bot)`, em ambas as entidades testadas.
- **H1 (alternativa, DIRECIONAL pré-registrada):** `decile_gap(trap, R) − decile_gap(trap, C) > 0` (assimetria positiva: trap discrimina R mais que C), em **ambas** as entidades, **e** `decile_gap(trap, R) >= +0.10` (10pp) por entidade.

Direção pré-comprometida via `assemble_verdict(..., direction="pos")`. Gap negativo significativo é **não-confirmação**, não descoberta.

---

## 2. Mecanismo causal (pré-registrado para evitar reinterpretação post-hoc)

Indução manipulativa: quando o crowd entra rápido no mesmo lado de uma posição já esticada (whales/top traders), forma-se concentração de stops do mesmo lado. Esse setup gera assimetria de liquidez que **convida** movimento contrário (squeeze, sweep, reversão). Diferente do H3 vanilla, o H4 isola a **co-ocorrência** `top extremo + crowd convergindo na mesma direção` — assinatura específica de "armadilha".

Crucialmente **ortogonal ao regime e à volatilidade local**: a hipótese é que a co-ocorrência atua intra-regime, e produz reversão sem produzir continuação simétrica. Se o efeito só existir porque `trap_score` proxia regime, falha pelo lift incremental ao regime (§5, §6.5). Se só existir porque proxia vol, falha pela assimetria delta (§6.3, §8).

---

## 3. Variáveis

| Papel | Definição |
|---|---|
| **Independente 1** (`top_z`) | z-score do `top_position` (LSR top traders), janela trailing de **72h**, lag de **1 barra** anti-lookahead. |
| **Independente 2** (`vel_global`) | velocidade de convergência do `global_account` (LSR crowd): `Δ(global_account)` em janela trailing de **12h**, normalizado por desvio trailing de 72h. Lag de **1 barra**. |
| **Trap-score** (feature primária) | `trap_score = top_z * vel_global`. Captura **co-ocorrência de extremos alinhados**. Valor alto = setup de armadilha; valor próximo de zero ou negativo (sinais opostos) = não-setup. |
| **Dependente 1** (`R`) | rótulo binário 0/1 de reversão forward via `reversal_labeler.label_reversals(price, k, N=12, vol_window=96, M=12)`. Horizonte N=12 barras horárias. `k` selecionado em discovery 60% por BASELINE (§6.1). |
| **Dependente 2 (placebo)** (`C`) | rótulo binário 0/1 de **continuação** forward via `h4_lsr_manipulation.label_continuations(price, k, N, vol_window, M)`. **Espelho direcional** de `R`: continuação = excursão FAVORÁVEL >= k·σ_N na direção prévia, mesmos `k/N/vol_window/M`. **Identidade dos parâmetros é load-bearing** — sem ela, comparação `delta = gap(R) − gap(C)` não é apples-to-apples. Cravado em código (assert via `inspect.signature`) e em teste (`test_continuation_e_reversal_usam_parametros_identicos`). |
| **Controle** (`regime`) | UP / FLAT / DOWN, derivado deterministicamente do preço igual ao H3 §2.1: slope 48h vs band 48h escalada, threshold `0.5·band`. Lag de **1 barra**. |
| **Entidade** | símbolo. Inicialmente {`BTCUSDT`, `ETHUSDT`} — par mínimo para `require_entities=2`. |
| **Lifts reportados** (em pontos percentuais, pp) | `reversal_lift_pp = gap(trap, R) * 100`; `continuation_lift_pp = gap(trap, C) * 100`; `delta_lift_pp = (gap(trap, R) − gap(trap, C)) * 100`. Reportados por entidade no output. Usados na classe interpretativa GO_marginal (§8). |

> **⚠️ UNIDADE CRÍTICA (anti-footgun):** o `gap` do H4 é diferença de **TAXA DE REVERSÃO** (proporção/pontos percentuais), NÃO bps de retorno como no H1. `decile_gap` sobre alvo binário {0,1} devolve diferença de proporção: `0.10 = 10pp`. O parâmetro `min_gap_bps` de `assemble_verdict` é agnóstico de unidade — o runner passa `min_gap_bps=0.10` para o piso de +10pp e **NÃO multiplica por 1e4**. Documentado redundantemente no docstring do runner. Teste `test_min_gap_proportion_eh_proporcao_nao_bps` cobre.

---

## 4. Dataset

**Fonte:** `bot.db` em `/home/pi/crypto_ai_bot/runtime/baseline/bot.db`.
- `k_prices(symbol, bucket_ts, close_price)` — bucket_ts em **segundos**.
- `k_ratios(symbol, bucket_ts, source, long_short_ratio)` — `source ∈ {top_position, global_account}`. Pivot por source via SQL.

**Regra de não-contaminação (cravada no EXP-008 §10.3 — load-bearing, inalterada em v1.1):**

```
WHERE bucket_ts > 1780012800   -- epoch s para 2026-05-29 00:00 UTC
```

H4 só pode ser julgado em dados **coletados após o veredito do H3**. Qualquer sobreposição com o intervalo usado por EXP-008/H3 (até 2026-05-28) é forking-path — a "pista do FLAT" do H3 contaminaria H4. Janela esperada na maturação: ≥45 dias (gate de poder §11). Runner faz assertion `panel.t.min() > marco` antes de qualquer cálculo — modo de falha #6.

**Ressalva position×account** (herdada do H3 §2): `k_ratios` mistura `topLongShortPositionRatio` (top) com `globalLongShortAccountRatio` (global). Para o H4 isto é **aceito conscientemente** porque a hipótese é sobre **velocidade de convergência do crowd em direção ao top**, não sobre nível absoluto comparativo. Se H4 vier inconclusivo, é uma das explicações documentadas. Reconfigurar collector → eventual H4-bis forward-only, fora do escopo desta v1.1.

---

## 5. Anti-lookahead (regra de timestamp explícita)

Todas as features são **trailing puras**:
- `top_z` em `t` usa apenas observações de `top_position` com timestamp ≤ `t−1h` (lag de 1 barra).
- `vel_global` em `t` usa apenas `global_account` com timestamp ≤ `t−1h`.
- `regime` em `t` usa apenas preços ≤ `t−1h`.
- Os alvos `R_t` e `C_t` são construídos por `label_reversals`/`label_continuations`, que usam `price[t+1..t+N]` como **futuro** (uso de futuro intencional e correto — é o alvo).

**Testes unitários obrigatórios** (`test_h4.py`):
1. `top_z`, `vel_global`, `regime` **estáveis sob truncamento futuro**: features em `t < cut−N` idênticas com ou sem cauda futura.
2. `trap_score` propaga NaN quando qualquer componente é NaN (warm-up bloqueia o composto).
3. `per_symbol_panel` resiliente a gaps em `k_ratios` (reindex+ffill não introduz lookahead; `shift(1)` protege contra valor `t` vazar para feature em `t−1`).

---

## 6. Estatística

### 6.1 Seleção de `k` (parâmetro do labeler) — por BASELINE, só no discovery

`k` é o único hiperparâmetro com escolha permitida. v1.1 endurece vs v1.0: **a calibração NUNCA usa gap** (que tinha viés pró-confound — `argmax(gap_IS)` favorece o `k` que maximiza o eventual confound vol-normal). Em v1.1, a calibração usa **apenas a taxa marginal de reversão** no IS.

**Grid pré-comprometido:** `k ∈ {1.5, 2.0, 2.5, 3.0}`.

**Procedimento (rodado somente no IS = primeiros 60%, descartando últimas N=12 para evitar vazamento IS→OOS via labeler):**

1. Para cada k candidato: rotular IS via `label_reversals(price_IS_safe, k=k, N=12, vol_window=96, M=12)`.
2. Calcular `baseline_pooled = labels.mean()`.
3. **Elegíveis:** k tais que `baseline_pooled ∈ [0.10, 0.15]` (faixa alvo pré-comprometida).
4. **k\* = max(elegíveis)** — tie-breaker é o **maior** k (labeler mais discriminativo, menos rótulos triviais por excursões pequenas).
5. **Se nenhum candidato cai na faixa:** retorna `k_star=None` → entidade vira **inconclusiva**. Não escolhe "o mais próximo" (isso flexibilizaria demais).

`k*` e os baselines de todos os candidatos são gravados em `metricas.per_entity[sym].k_calibration_baselines` antes de tocar OOS.

### 6.2 Pré-probe sanity (kill barato, piso secundário)

Em v1.1, a pré-probe `[0.05, 0.25] + ratio<2× entre regimes` foi rebaixada de discriminador primário de vol-confound (papel transferido para o placebo de continuação, §6.3) para **sanity de labeler não-degenerado**:

1. Aplicar `compute_baseline_rate(labels_IS, regime_IS)`.
2. **Kill se baseline cair fora de [0.05, 0.25] em algum regime** com n ≥ 50, **OU** ratio max/min > 2× entre regimes válidos.
3. Falha → entidade **inconclusiva classe `inconclusivo:labeler_suspeito`** (não consome gatilho de pausa do lab). Bug-fix Q1 do red-team: o runner aplica `return` early antes do teste principal se preprobe falha (PREREG v1.0 deixava preprobe sem efeito; v1.1 corrigido — `test_preprobe_falha_bloqueia_teste_principal` cobre).

### 6.3 Placebo de continuação — teste pareado da DIFERENÇA (gate principal contra vol-confound)

Definição: `continuation_labeler` (em `h4_lsr_manipulation.label_continuations`) é o espelho direcional simétrico de `reversal_labeler.label_reversals`:

- Reversal: prior > 0 (subiu antes) → marca se `future.min() <= -k·σ_N` (queda futura).
- Continuação: prior > 0 → marca se `future.max() >= +k·σ_N` (alta futura).

Mesmos `k/N/vol_window/M/noise_k`. **Identidade load-bearing**: a comparação só é apples-to-apples sob parâmetros idênticos. Cravado em `_label_kwargs` (compartilhado entre as duas chamadas) e em teste de assinatura.

**Justificativa do desenho:** sob vol pura simétrica, `P(reversal) ≈ P(continuação)` (random walk não distingue direção do futuro condicional ao prior). Sob manipulação direcional (assinatura H4), `trap_score` amplifica reversal mas não continuation — assimetria positiva esperada.

**Estatística:** `delta = decile_gap(trap, R) − decile_gap(trap, C)`, no pool inteiro (decis sobre todos os pontos).

**Permutação:** `lab_harness.perm_gap_delta_strat(feat, R, C, regime, frac, n_perm, tail="greater", rng)` — **permutação pareada estratificada**: dentro de cada estrato de regime, embaralha os dois rótulos com a **mesma π** (mantém feature fixo). Preserva a correlação intrínseca entre R e C (ambos são funções determinísticas do mesmo `price/k/σ`) — o teste isola a **assimetria**, não a correlação base. `tail="greater"`: H1 é `delta > 0`.

**Por que o gate é a SIGNIFICÂNCIA DE DELTA, não "rev sig E con não-sig":**

Conjunção `(rev sig) AND (con não-sig)` é a falácia de significância — duas afirmações de significância separadas não constituem teste da diferença. Uma efeito que dá `p(rev)=0.04` e `p(con)=0.06` "passaria" no critério ingênuo, mas a diferença pode não ser significativa (delta intervalo de confiança contém zero). O teste correto é construir explicitamente a estatística `delta` e testá-la — é o que `perm_gap_delta_strat` faz. v1.0 do PREREG usava o critério ingênuo; v1.1 corrigido.

### 6.4 Conjunção, NÃO união — α=0.05 por teste, sem Bonferroni

O GO de H4 é **conjunção**: `rev_pass(BTC) ∧ rev_pass(ETH) ∧ delta_pass(BTC) ∧ delta_pass(ETH)`, via `require_entities=2` em ambos os vereditos. Sob H0 global, P(GO falso) ≤ α^k onde k é o número de testes ANDed — com α=0.05 e require=2, FWER ≤ 0.05² = 0.0025 (≤ 0.0025⁴ ≈ 6e−12 se contar 4 testes ANDed). 

Bonferroni protege **união** ("declarar vitória se QUALQUER de N testes for significativo"), **não** interseção. Aplicar `0.05/N` à conjunção empilha conservadorismo sobre conservadorismo. No H4, cujo gargalo declarado é poder (gate de ≥30 eventos/estrato, janela forward-only), Bonferroni 0.025 fabricaria inconclusivos falsos — mataria sinal real por timidez estatística.

**Cravado em v1.1: `alpha_per_test = 0.05`** para reversal e delta separadamente. Sem Bonferroni.

**Pré-condição auditada e confirmada** (sem a qual α=0.05 seria insuficiente): regime entra **apenas como estrato** da permutação (1 p pooled por entidade). `gate_stratum` (≥30 por regime) é **poder amostral**, não gate estatístico de união. Nenhum critério "passa em ≥1 regime" em lugar algum (que seria união e exigiria correção). Teste `test_alpha_per_test_eh_005_sem_bonferroni` + auditoria de código (`grep -n regime`) cobrem.

Teste de regressão: `test_caso_borderline_p_002_passa_com_alpha_005_mas_falharia_com_bonferroni_025` — demonstra concretamente o poder recuperado: p=0.02 em conjunção 2×2 passa α=0.05 (era inconclusivo com 0.025), e sob H0 global FWER ainda <<0.05.

### 6.5 Veredito via `assemble_verdict` (3 chamadas)

```python
v_rev = assemble_verdict(per_entity_reversal, None, JudgmentUnit.PER_ENTITY,
                         min_gap_bps=0.10,          # 10pp (proporção, NÃO bps)
                         max_p=0.05,                # sem Bonferroni (§6.4)
                         require_entities=2,
                         direction="pos")
v_delta = assemble_verdict(per_entity_delta, None, JudgmentUnit.PER_ENTITY,
                           min_gap_bps=0.0,         # sem piso de magnitude
                           max_p=0.05,              # sem Bonferroni
                           require_entities=2,
                           direction="pos")         # tail="greater" no perm
v_con_flag = assemble_verdict(per_entity_continuation, None, JudgmentUnit.PER_ENTITY,
                              min_gap_bps=0.10, max_p=0.05,
                              require_entities=2, direction="pos")  # descritivo
```

**GO = `v_rev.passou AND v_delta.passou`**. `v_con_flag` é descritivo (informa se continuação também passou o mesmo bar — atípico mas pode acontecer); NÃO entra no critério.

A combinação `direction="pos" + require_entities=2` garante automaticamente que BTC e ETH precisam estar **ambos** no lado positivo (lição EXP-011 cristalizada no `lab_harness` 1.1.0+). Direções opostas significativas nunca contam juntas.

---

## 7. Holdout temporal (pré-comprometido)

- Janelas horárias ordenadas cronologicamente por símbolo.
- **Primeiros 60% (IS):** única fatia onde `k` pode ser selecionado (§6.1), e onde a pré-probe sanity (§6.2) é avaliada.
- **Últimos 40% (OOS):** fatia de julgamento. Estatísticas de reversal, delta e continuation são lidas **apenas aqui**.
- Data de corte (índice 60%) gravada na saída e **imutável após primeira execução**.

---

## 8. GO/NO-GO numérico (pré-comprometido)

**GO requer todas as condições, na fatia OOS:**

1. **Gate de poder satisfeito** (§11, load-bearing inalterado): janela total ≥ 45 dias **e** ≥ 30 eventos válidos por estrato (símbolo × regime).
2. **Pré-probe sanity OK** (§6.2): taxa de reversão IS ∈ [0.05, 0.25] em todos os regimes com n≥50, sem variação >2× entre regimes. Falha → `inconclusivo:labeler_suspeito` (bug-fix Q1 do red-team: bloqueia teste principal).
3. **Condição (a) — reversal passa seu próprio bar:** `v_rev.passou == True` ⇔ ambas entidades (BTC, ETH) têm `gap(trap, R) >= +0.10` (10pp) **e** `p_rev < 0.05`.
4. **Condição (b) — assimetria delta é significativa (gate principal):** `v_delta.passou == True` ⇔ ambas entidades têm `delta = gap(trap, R) − gap(trap, C) > 0` (direção pré-comprometida) **e** `p_delta < 0.05` (teste pareado via `perm_gap_delta_strat`, §6.3). **Este é o gate; não é "rev sig E con não-sig".**
5. **Condição (c) — continuation flag (descritivo, NÃO bloqueia):** `v_con_flag` é reportado mas não entra no critério de GO. Se `con_flag.passou == True`, é classificado como atípico (`GO_with_continuation_flag`), não bloqueia.

**Significância estatística:** α=0.05 por teste, **sem Bonferroni** (§6.4). Justificativa cravada: GO é conjunção (4 testes ANDed via require=2), FWER já controlado por interseção; Bonferroni é correção para união e não se aplica aqui. Pré-condição (regime só como estrato, sem gate de união) auditada e confirmada.

**Classes de veredito enumeradas:**

| Classe | Condição |
|---|---|
| `GO` | (1)+(2)+(3)+(4) satisfeitos, (5) não dispara, `delta_lift_pp >= 0.5 × reversal_lift_pp` em **todas** entidades |
| `GO_with_continuation_flag` | mesmo que GO, MAS (5) dispara (`con_flag.passou`) — sólido mas atípico |
| `GO_marginal:vol_dominant` | (1)+(2)+(3)+(4) satisfeitos, MAS `delta_lift_pp < 0.5 × reversal_lift_pp` em **≥1** entidade. **Passa o gate estatístico**, mas componente de manipulação é fino vs vol — exige replicação forward antes de qualquer peso. Classe interpretativa (não gate adicional; sem permutação nova; reporta natureza, não bloqueia). |
| `vol_confounded` | (3) satisfeito mas (4) não — reversal passa mas assimetria delta não é significativa. NÃO é GO; feature pode estar proxiando vol simétrica. |
| `inconclusivo:amostragem` | (1) falha — janela ou estratos abaixo do gate de poder. Não consome gatilho de pausa do lab. |
| `inconclusivo:labeler_suspeito` | (2) falha — pré-probe baseline fora de faixa ou ratio>2× entre regimes. Não consome gatilho. |
| `anomalo:delta_sem_reversal` | (4) passa mas (3) não — caminho raro. Sem GO. |

**Threshold `0.5` da classe marginal:** pré-comprometido em CONFIG (`go_marginal_delta_ratio=0.5`). Razão: ratio dimensionless entre dois pp lifts da mesma escala; abaixo de 0.5 indica que metade ou mais do "sinal" agregado é vol simétrica (continuation contribui similarmente), tornando a interpretação "manipulação" frágil. **Não é gate adicional** — passa o GO formalmente, só classifica como marginal.

---

## 9. Modos de falha esperados

1. **Subpoder estrutural (janela curta).** Mais provável no curto prazo: janela imatura até ~13/07/2026 (45d após marco). **Detecção:** gate de poder §11; sai `inconclusivo:amostragem`.

2. **Confound vol-normal ≡ rótulo de reversão.** `reversal_labeler` rotula excursões adversas >= k·σ. Se k for baixo, rotula spikes normais de vol → label vira "alta volatilidade". `trap_score` pode covariar com vol → resposta circular. **Detecção primária (PREREG v1.1):** placebo de continuação testado via `perm_gap_delta_strat`. Sob vol simétrica, P(reversal) ≈ P(continuation) → `delta ≈ 0` → não-significativo → classe `vol_confounded`, **NÃO GO**. Pré-probe §6.2 funciona como sanity secundária.

3. **Lookahead via atualização retrospectiva de `k_ratios`.** Se o collector grava `bucket_ts` mas o valor é publicado N segundos depois, `vel_global` em `t` pode incluir informação publicada após `t`. **Detecção:** lag de 1 barra defensivo; testes unitários `test_top_z_estavel_sob_truncamento_futuro` + `test_vel_global_estavel_sob_truncamento_futuro` + `test_per_symbol_panel_handles_gaps_no_lsr_sem_lookahead` (cobre `reindex+ffill` com gaps).

4. **`trap_score` proxia volatilidade local intra-regime.** Se `top_z` e `vel_global` ambos cresceram em janelas voláteis, o produto vira proxy de "tudo está agitado". Permutação estratificada por regime remove confound entre regimes, **mas não dentro**. **Detecção:** mesmo placebo de continuação (§6.3) atua aqui — vol intra-regime afeta R e C igualmente, delta → 0; e diagnóstico vol-tercile (§9 #7) reporta lift por tercile de vol local como eyeball secundário.

5. **Convergência espúria BTC×ETH (colinearidade cripto).** Sob H0, BTC e ETH podem mostrar gaps de mesmo sinal por puro co-movimento. `direction="pos" + require_entities=2` ainda permitiria GO espúrio se beta-cripto estiver presente. **Detecção:** o delta pareado é menos sensível a beta porque a comparação é intra-entidade (rev vs con no mesmo símbolo). Sob beta puro, R e C teriam mesma resposta a trap → delta=0 → vol_confounded.

6. **Contaminação pelo marco insuficientemente filtrada.** Se merge de `k_prices` e `k_ratios` traz índice ≤ marco via reindex/ffill, contamina. **Detecção:** assertion no runner `panel.t.min() > marco` antes de qualquer cálculo; teste unitário `test_marco_no_contamination_eh_pre_comprometido`.

7. **(refinado em v1.1)** **Vol-confound intra-regime sem assimetria detectável.** Mesmo com o placebo, se a vol é proxy perfeita de trap dentro de cada regime, delta pode dar não-significativo por baixa potência (não por falsa assimetria zero). **Detecção primária:** `vol_tercile_diagnostic` reporta `decile_gap(trap, R)` por tercile {low, mid, high} de vol local trailing. Se efeito concentrado em `high` → eyeball de vol-confound mesmo quando delta passou (raro). Não é gate (não estilhaça n já fino); é flag pra interpretação.

8. **Ambos rótulos passam o bar (R e C significativos individualmente), mas delta não.** Esse era o caso que v1.0 do PREREG declarava `vol_confounded` por critério ingênuo "ambos passam". v1.1 corrige: este caso é capturado pelo teste pareado — delta não significativo → `vol_confounded` direto. Critério é matemático, não heurístico.

---

## 10. Código

- **Runner:** `docs/pre_registros/h4_lsr_manipulation.py` (importa `lab_harness` ≥1.2.0 e `reversal_labeler`; contém `label_continuations` local).
- **Testes unitários:** `docs/pre_registros/test_h4.py` (30 testes cobrindo features, gate, calibração, labeler, veredito, classes, lifts).
- **Apparatus reusado:**
  - `lab_harness.perm_gap_strat` — permutação estratificada para reversal e continuation isolados.
  - `lab_harness.perm_gap_delta_strat` — permutação pareada estratificada para delta (NOVO em 1.2.0).
  - `lab_harness.assemble_verdict(direction, require_entities)` — composição PER_ENTITY com direção pré-comprometida (1.1.0+).
  - `reversal_labeler.label_reversals` + `compute_baseline_rate` — intactos do EXP-008.

**Validação do apparatus (já feita):**
- `perm_gap_strat` e `perm_gap` bit-exact equivalentes a `h1.perm_strat` e `h3.perm_pvalue` (tol 1e-9) — testes em `tests/test_lab_harness.py`.
- `perm_gap_delta_strat`: 4 testes cobrindo delta=0 com labels iguais, assimetria plantada detectada, vol-confound simulado não detecta, NaN propaga.
- `label_continuations`: simetria sob vol pura (5 seeds, ratio<2.0); marca continuação clara após uptrend.
- `assemble_verdict(direction="pos", require_entities=2)` validado contra cenário EXP-011 espelhado.

---

## 11. Gate de poder (operacional — load-bearing, inalterado em v1.1)

Antes de rodar o teste principal, o runner verifica:

| Check | Critério | Falha → |
|---|---|---|
| **Janela** | `(max(bucket_ts) − min(bucket_ts)) / 86400 ≥ 45` dias | `inconclusivo:amostragem` |
| **n por estrato OOS** | ≥ 30 instâncias OOS válidas por (símbolo × regime) | inconclusivo no estrato; entidade só conta se ≥ 1 estrato sobrevive |
| **n por entidade total OOS** | ≥ 60 instâncias OOS válidas (≈ 2 estratos × 30) | entidade inconclusiva |

Se BTC ou ETH ficam inconclusivos pelo gate, `n_pass < 2` → veredito formal `inconclusivo:amostragem` (não NO-GO de descoberta — não consome gatilho de pausa do lab).

---

## 12. Disciplina

- Pré-registro **selado em 2026-05-29** antes de qualquer execução com dados reais. v1.1 incorpora endurecimentos do red-team realizados na mesma sessão de v1.0; o documento v1.0 nunca foi rodado contra dados — o desenho final selado é v1.1.
- Bug-fixes de implementação (e.g., schema mismatch, pandas version) são permitidos sem invalidar pré-registro; **mudanças de desenho** (variáveis, GO/NO-GO, regimes, holdout, α, identidade k/N/σ de rev↔con) invalidam e exigem novo PREREG_H4_v1.2.
- Close-before-open: H1 (EXP-011) selado em 2026-05-29; H4 (EXP-012) abre como pré-registro pré-comprometido para execução **forward-only**.
- Contagem no gatilho de pausa do lab: H4 é **NO-GO de descoberta real** se vier NO-GO genuíno (não warm-up). Conforme cláusula cravada no EXP-011: H4 NO-GO → pausa 90d automática. **Inconclusivo por gate de poder ou labeler-suspeito NÃO consome a contagem** — espera maturação ou re-pré-registro do labeler.

---

## Resumo das mudanças vs v1.0

| Item | v1.0 | v1.1 |
|---|---|---|
| Calibração de k | argmax(gap_IS) (viés pró-confound) | seleção por baseline ∈ [0.10, 0.15], tie-breaker maior k |
| Pré-probe baseline | discriminador primário de vol-confound | sanity secundária de labeler não-degenerado |
| Placebo de continuação | não existia | gate principal via teste pareado da diferença |
| Critério de vol-confound | "rev sig E con não-sig" (falácia de significância) | `delta = gap(R) − gap(C)` testado diretamente via `perm_gap_delta_strat` |
| α por teste | 0.025 (Bonferroni sobre conjunção) | 0.05 (conjunção é auto-conservadora; FWER ≤ α²) |
| Diagnóstico vol-tercile | não existia | reportado por entidade (flag, NÃO gate) |
| Lifts reportados | só "gap_bps" (proporção, confusing) | reversal_lift_pp + continuation_lift_pp + delta_lift_pp por entidade |
| Classes de veredito | GO / vol_confounded / inconclusivo | + GO_marginal:vol_dominant (delta < 0.5 × reversal) / GO_with_continuation_flag / anomalo:delta_sem_reversal |
| Bug do preprobe_ok ignorado | presente | corrigido (return early) |
| Cobertura de `per_symbol_panel` com gaps | ausente | teste unitário adicionado |
