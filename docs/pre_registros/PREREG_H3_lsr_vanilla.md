# Pré-registro — H3: Divergência Long/Short Ratio (top vs global) → retorno forward

**Status:** pré-registrado, não executado.
**Versão:** 1.1 (ajustado ao schema real do bot.db; desenho inalterado vs 1.0).
**Tipo:** experimento estrutural, paradigma de posicionamento. Vanilla (sem detecção de manipulação — isso é H4, backlog forward-only).
**Prioridade no lab:** #2 (depois de H1).
**Função secundária:** validação do harness estatístico (ver §10).

> Critério universal do lab (não renegociável): uma feature estrutural só passa GO se mostrar **lift incremental ao regime**, não na média agregada. Aplicado em §5 e §7.

---

## 1. Hipótese pré-registrada

Seja `D_t = z-score( top_ratio_t − global_ratio_t )` a divergência de posicionamento entre top traders e contas globais, normalizada em janela móvel.

- **H0 (nula):** o retorno forward em horizonte fixo é independente de `D_t`. A diferença de retorno médio entre o decil superior e o decil inferior de `D_t` é zero, dentro do erro amostral, em todos os estratos de regime.
- **H1 (alternativa, bidirecional pré-registrada):** existe diferença de retorno forward entre decil superior e inferior de `D_t`, **e essa diferença persiste dentro de pelo menos um estrato de regime** (não apenas no agregado).

Teste **bidirecional**: não temos prior direcional forte para o sinal vanilla. A narrativa "smart money lidera" prediria divergência positiva → retorno positivo, mas o prior de que o sinal já foi arbitrado é forte o suficiente para não comprometer um lado. Direção é reportada, não assumida.

---

## 2. Variáveis

| Papel | Definição |
|---|---|
| Independente | `D_t = z-score(top_ratio_t − global_ratio_t)`, z-score em janela móvel de **72h** (3 dias). Justificativa: dado horário, 72h = 72 amostras para estimar média/desvio — equilíbrio entre estacionariedade e responsividade; consome ~3d de burn-in dos 21d. |
| Dependente | Retorno forward log em horizonte **H = 4h**: `r_fwd = ln(close[t+H] / close[t])`. Justificativa do horizonte: LSR é sinal de posicionamento lento (atualização horária, mecânica crowd-vs-smart se resolve em horas). 4h é longo o bastante para o posicionamento resolver e curto o bastante para permitir janelas não-sobrepostas suficientes nos 21d. Horizontes 12h/24h ficam como robustez reportada, **não** como teste primário. |
| Controle | Regime, derivado deterministicamente das klines (ver §2.1) em UP / FLAT / DOWN. |

`top_ratio` e `global_ratio`: o ideal seria usar consistentemente o **mesmo tipo** de ratio dos dois lados (`topLongShortAccountRatio` vs `globalLongShortAccountRatio`), porque misturar "position ratio" com "account ratio" compara grandezas diferentes.

> **RESSALVA DE DADOS (assumida conscientemente).** A tabela `k_ratios` existente coletou `topLongShortPositionRatio` (top) vs `globalLongShortAccountRatio` (global) — ou seja, **mistura position com account**. Para o H3 vanilla isto é **aceito de propósito**: H3 já tem prior baixo de GO e serve de warm-up do harness. Se der inconclusivo (cenário provável), parte da explicação é honesta e barata — "comparou grandezas diferentes" — e não consome esforço futuro. Reconfigurar o collector para `topLongShortAccountRatio` e esperar acumular fica para um eventual H3-bis, **não** para este experimento. Esta inconsistência deve ser repetida no veredito final do H3.

### 2.1 Definição de regime (pré-comprometida, determinística)

Sobre cada símbolo, usando apenas klines até `t`:
- `slope_t` = retorno log acumulado nas trailing 48h.
- `band_t` = desvio-padrão dos retornos log horários nas trailing 48h, escalado por √48.
- Regime: `UP` se `slope_t > +0.5·band_t`; `DOWN` se `slope_t < −0.5·band_t`; senão `FLAT`.

Esta definição é autossuficiente (só klines). Se o bot expõe um label de regime canônico (TRENDING/WEAK_TREND), ele pode substituir esta função — mas o pré-registro fixa **esta** definição para reprodutibilidade do H3 standalone.

---

## 3. Dataset

- Fonte: `bot.db` (`/home/pi/crypto_ai_bot/runtime/baseline/bot.db`), tabelas **`k_prices`** (preço) + **`k_ratios`** (long/short), backfill existente, 14 símbolos. Timestamps em **`bucket_ts` (segundos)**. `k_ratios` é formato long (pivot via coluna `source`).
- **Pooling vs por-símbolo — decisão pré-comprometida:** julgamento primário **por-símbolo com exigência de consistência direcional**, não pooled.
  - Motivo: os 14 símbolos co-movem fortemente com BTC. Um teste de permutação pooled trataria observações cross-section como independentes e **infla a significância** (n efetivo ≪ n nominal).
  - Procedimento: computa-se o efeito por símbolo; exige-se concordância de direção em **≥ 9 dos 14** símbolos (teste binomial sob H0 de 50/50 daria p≈0.09 para 9/14, p≈0.03 para 10/14 — ver §7). O resultado pooled é reportado apenas como **descritivo**, nunca como evidência primária.
- Janelas **não-sobrepostas** (stride = H = 4h) para que a permutação simples seja válida (observações quase-independentes; evita o falso-positivo de autocorrelação por janelas sobrepostas). 21d horário → ~126 janelas não-sobrepostas por símbolo.

---

## 4. Anti-lookahead (regra de timestamp explícita)

- A feature `D_t` em `t` usa **apenas** observações de ratio com timestamp `≤ t`.
- O retorno forward é medido sobre `(t, t+H]`. Portanto a feature **não** contém informação da janela de retorno.
- **Defasagem de publicação:** aplica-se lag de segurança de **1 barra** — a feature usada para prever o retorno em `(t, t+H]` é `D_{t−1h}` (ratio conhecido na barra anterior). Isso protege contra o ratio da barra `t` ainda não estar publicado/consolidado no instante de decisão.
- z-score de `D`: média e desvio calculados **somente** sobre a janela trailing de 72h terminando em `t−1h`. Sem centragem global.

---

## 5. Estatística

### Pré-probe (kill barato — rodar ISTO antes de qualquer apparatus)
1. **Spearman** `rho(D, r_fwd)`, pooled e por-símbolo, com IC bootstrap.
2. **Decis extremos:** retorno forward médio no top 10% de `D` vs bottom 10% vs miolo (decis 4–7).
- **Kill:** se |rho| < 0.05 com IC cruzando zero **e** o spread top-vs-bottom decil está dentro de ±1 erro-padrão de zero → NO-GO imediato, não construir o teste principal.

### Teste principal
- Estatística: `spread = média(r_fwd | top decil de D) − média(r_fwd | bottom decil de D)`.
- **Permutação 10k** (`numpy.random`): embaralhar a associação `D → r_fwd`, recomputar `spread`, montar distribuição nula. p bidirecional = fração de |spread_nulo| ≥ |spread_obs|.

### Estratificação por regime (obrigatória)
- Repetir Spearman, decis e permutação **dentro** de cada estrato (UP/FLAT/DOWN).
- **Exigência:** o efeito tem de persistir (mesmo sinal, magnitude relevante, p significativo) em **≥ 1 estrato**, não apenas no agregado. Efeito que só existe no agregado e some em todos os estratos = beta de regime disfarçado → NO-GO.
- Estratos com n < 30 janelas não-sobrepostas são marcados **inconclusivos** (= NO-GO para aquele estrato).

---

## 6. Holdout temporal (pré-comprometido)

- Ordenar cronologicamente. **Primeiros 60%** das janelas: única fatia onde qualquer hiperparâmetro pode ser escolhido (janela de z-score, cortes de decil, thresholds de regime).
- **Últimos 40%:** fatia de julgamento. Métricas de GO/NO-GO são lidas **só** aqui.
- A data de corte (índice 60%) é gravada na saída e nunca movida após a primeira execução.

---

## 7. GO/NO-GO numérico (pré-comprometido)

GO exige **todas** as condições abaixo, na fatia de julgamento (40% OOS):

1. **Magnitude:** spread top-vs-bottom decil de `r_fwd` ≥ **25 bps por janela de 4h, líquido** de um custo round-trip assumido de 15 bps (i.e., spread bruto ≥ 40 bps). Colchão de slippage: este já é o piso paper; degradação paper→vivo de 30–80% é absorvida exigindo-se que o sinal seja grande o bastante para sobreviver à degradação antes de qualquer trade real.
2. **Significância:** p-permutação bidirecional < **0.01** (mais estrito que 0.05 por causa da dependência cross-section residual).
3. **Persistência de sinal:** mesma direção do spread in-sample (60%) e OOS (40%).
4. **Persistência de regime:** condição (1)+(2) satisfeita em **≥ 1 estrato** de regime com n ≥ 30.
5. **Consistência cross-símbolo:** direção do efeito concordante em **≥ 9/14** símbolos.

Qualquer condição falha → **NO-GO**. Dados finos demais para avaliar (estratos abaixo de n mínimo, IC dominando) → **inconclusivo = NO-GO** (disciplina do lab: não promover ruído).

---

## 8. Modo de falha esperado

1. **Subpoder (21d).** Cenário mais provável. n não-sobreposto por símbolo ~126; após estratificar por 3 regimes, células ficam ~40 e o IC engole qualquer efeito modesto. → Inconclusivo. **Detecção precoce:** largura do IC do Spearman na pré-probe; se IC ocupa [−0.2, +0.2], o experimento não tem resolução.
2. **Dependência cross-section infla significância.** Pooled "passa" mas é só BTC + 13 betas. **Detecção:** breakdown por-símbolo; se só BTC mostra efeito e os alts são ruído em torno de zero, falha a condição (5).
3. **LSR já arbitrado (prior forte).** `rho ≈ 0`. **Detecção:** pré-probe Spearman.
4. **Confound de regime.** `D` proxia tendência; efeito agregado some intra-regime. **Detecção:** estratificação (§5).
5. **Inconsistência position/account (ver §2 ressalva).** O sinal pode ser ruído por comparar grandezas diferentes. **Detecção:** já esperado; se inconclusivo, é explicação suficiente e barata.

---

## 9. Código (pronto para o Pi)

> `CONFIG` já mapeado para o schema real (`bot.db` / `k_prices` / `k_ratios`). Confirmar apenas os 2 campos marcados `CONFIRMAR` (nome da coluna de valor e as strings exatas de `source` em `k_ratios`). Sem scipy; Spearman e permutação em numpy puro.

```python
# h3_lsr_vanilla.py  — Python 3.11, pandas + numpy + sqlite3
import sqlite3
import numpy as np
import pandas as pd

# ----------------------------------------------------------------------
# CONFIG — mapeado ao schema real do bot.db
# ----------------------------------------------------------------------
CONFIG = {
    # ---- schema real (bot.db) ----
    "db_path": "/home/pi/crypto_ai_bot/runtime/baseline/bot.db",
    # klines -> tabela k_prices: (symbol, bucket_ts EM SEGUNDOS, close_price)
    "klines_table": "k_prices",
    "kl_symbol": "symbol",
    "kl_time_s": "bucket_ts",        # epoch SEGUNDOS (não ms)
    "kl_close": "close_price",
    # ratios -> tabela k_ratios: NÃO tem colunas top/global separadas.
    # Tem coluna `source` que distingue as séries -> pivot via SQL.
    "ratios_table": "k_ratios",
    "rt_symbol": "symbol",
    "rt_time_s": "bucket_ts",        # epoch SEGUNDOS
    "rt_source_col": "source",
    "rt_value_col": "ratio",         # <-- CONFIRMAR nome da coluna de valor em k_ratios
    "rt_top_source": "top_position",       # <-- CONFIRMAR string exata (topLongShortPositionRatio)
    "rt_global_source": "global_account",  # <-- CONFIRMAR string exata (globalLongShortAccountRatio)
    # RESSALVA (ver §2): os dados existentes misturam POSITION (top) com ACCOUNT (global).
    # Aceito para o H3 vanilla (warm-up de harness); documentado no veredito.
    # ---- parâmetros pré-registrados ----
    "symbols": None,                 # None = todos os distintos; ou lista de 14
    "z_window_h": 72,                # janela do z-score (horas)
    "horizon_h": 4,                  # H do retorno forward
    "feature_lag_h": 1,              # lag anti-lookahead (barras)
    "regime_lookback_h": 48,
    "regime_band_k": 0.5,
    "decile_frac": 0.10,             # top/bottom 10%
    "holdout_frac": 0.60,            # primeiros 60% = in-sample
    "n_perm": 10000,
    "min_stratum_n": 30,
    "go_net_spread_bps": 25.0,       # piso líquido
    "assumed_cost_bps": 15.0,        # custo round-trip assumido
    "go_p": 0.01,
    "consistency_min": 9,            # de 14
    "seed": 20260528,
}

RNG = np.random.default_rng(CONFIG["seed"])


# ----------------------------------------------------------------------
# Carga (schema real: k_prices + k_ratios long/pivot)
# ----------------------------------------------------------------------
def _load_prices(con):
    q = (f"SELECT {CONFIG['kl_symbol']} AS symbol, {CONFIG['kl_time_s']} AS t, "
         f"{CONFIG['kl_close']} AS close FROM {CONFIG['klines_table']}")
    df = pd.read_sql_query(q, con)
    df["t"] = pd.to_datetime(df["t"], unit="s", utc=True)   # bucket_ts em SEGUNDOS
    return df.sort_values(["symbol", "t"])


def _load_ratios_pivot(con):
    # k_ratios é "long": uma linha por (symbol, bucket_ts, source). Pivot via source.
    q = (f"SELECT {CONFIG['rt_symbol']} AS symbol, {CONFIG['rt_time_s']} AS t, "
         f"{CONFIG['rt_source_col']} AS source, {CONFIG['rt_value_col']} AS val "
         f"FROM {CONFIG['ratios_table']} WHERE {CONFIG['rt_source_col']} IN (?, ?)")
    df = pd.read_sql_query(q, con, params=(CONFIG["rt_top_source"], CONFIG["rt_global_source"]))
    df["t"] = pd.to_datetime(df["t"], unit="s", utc=True)
    top = (df[df["source"] == CONFIG["rt_top_source"]][["symbol", "t", "val"]]
           .rename(columns={"val": "top"}))
    glob = (df[df["source"] == CONFIG["rt_global_source"]][["symbol", "t", "val"]]
            .rename(columns={"val": "glob"}))
    # inner merge: exige mesmo bucket_ts nas duas séries (mesma cadência do collector)
    piv = pd.merge(top, glob, on=["symbol", "t"], how="inner")
    return piv.sort_values(["symbol", "t"])


def build_panel():
    con = sqlite3.connect(CONFIG["db_path"])
    kl = _load_prices(con)
    lsr = _load_ratios_pivot(con)
    con.close()
    syms = CONFIG["symbols"] or sorted(set(kl["symbol"]) & set(lsr["symbol"]))
    return kl, lsr, syms


# ----------------------------------------------------------------------
# Feature, regime, target por símbolo
# ----------------------------------------------------------------------
def per_symbol_frame(sym, kl, lsr):
    k = kl[kl["symbol"] == sym].set_index("t").asfreq("1h")  # grade horária
    k["close"] = k["close"].astype(float).ffill()
    l = (lsr[lsr["symbol"] == sym].set_index("t")[["top", "glob"]]
         .astype(float).reindex(k.index).ffill())

    raw = l["top"] - l["glob"]
    w = CONFIG["z_window_h"]
    mu = raw.rolling(w).mean()
    sd = raw.rolling(w).std(ddof=0)
    D = (raw - mu) / sd.replace(0, np.nan)
    # lag anti-lookahead
    D = D.shift(CONFIG["feature_lag_h"])

    # regime (só passado)
    rb = CONFIG["regime_lookback_h"]
    logret = np.log(k["close"]).diff()
    slope = np.log(k["close"]).diff(rb)
    band = logret.rolling(rb).std(ddof=0) * np.sqrt(rb)
    kf = CONFIG["regime_band_k"]
    regime = pd.Series("FLAT", index=k.index)
    regime[slope > kf * band] = "UP"
    regime[slope < -kf * band] = "DOWN"
    regime = regime.shift(CONFIG["feature_lag_h"])

    # target forward não-sobreposto
    H = CONFIG["horizon_h"]
    fwd = np.log(k["close"].shift(-H) / k["close"])

    out = pd.DataFrame({"D": D, "regime": regime, "fwd": fwd}).dropna()
    out = out.iloc[::H]  # stride = H -> janelas não-sobrepostas
    out["symbol"] = sym
    return out


# ----------------------------------------------------------------------
# Estatística (numpy puro)
# ----------------------------------------------------------------------
def _rankdata(a):
    a = np.asarray(a, float)
    order = a.argsort()
    ranks = np.empty(len(a), float)
    ranks[order] = np.arange(1, len(a) + 1)
    # média de ranks em empates
    _, inv, cnt = np.unique(a, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=ranks)
    return (sums / cnt)[inv]


def spearman(x, y):
    if len(x) < 5:
        return np.nan
    rx, ry = _rankdata(x), _rankdata(y)
    rx -= rx.mean(); ry -= ry.mean()
    den = np.sqrt((rx**2).sum() * (ry**2).sum())
    return float((rx * ry).sum() / den) if den > 0 else np.nan


def decile_spread(D, fwd, frac):
    n = len(D)
    if n < 20:
        return np.nan, 0, 0
    k = max(1, int(round(n * frac)))
    order = np.argsort(D)
    bot = fwd[order[:k]].mean()
    top = fwd[order[-k:]].mean()
    return float(top - bot), k, k


def perm_pvalue(D, fwd, frac, n_perm):
    obs, _, _ = decile_spread(D, fwd, frac)
    if np.isnan(obs):
        return obs, np.nan
    null = np.empty(n_perm)
    for i in range(n_perm):
        s, _, _ = decile_spread(D, RNG.permutation(fwd), frac)
        null[i] = s
    p = float((np.abs(null) >= abs(obs)).mean())
    return obs, p


# ----------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------
def run():
    kl, lsr, syms = build_panel()
    frames = [per_symbol_frame(s, kl, lsr) for s in syms]
    frames = [f for f in frames if len(f) > 0]
    panel = pd.concat(frames, ignore_index=True)

    # split temporal por símbolo (mantém cronologia interna)
    def split(df):
        cut = int(len(df) * CONFIG["holdout_frac"])
        return df.iloc[:cut], df.iloc[cut:]

    metrics = {"per_symbol": {}, "regime_oos": {}, "preprobe": {}}
    signs_oos = []

    # ---- pré-probe (pooled, in-sample) ----
    is_pool = pd.concat([split(f)[0] for f in frames], ignore_index=True)
    metrics["preprobe"]["spearman_pooled_is"] = spearman(is_pool["D"].values, is_pool["fwd"].values)
    sp_is, _, _ = decile_spread(is_pool["D"].values, is_pool["fwd"].values, CONFIG["decile_frac"])
    metrics["preprobe"]["decile_spread_pooled_is_bps"] = None if np.isnan(sp_is) else sp_is * 1e4

    # ---- por símbolo (OOS) ----
    for f in frames:
        _, oos = split(f)
        if len(oos) < 20:
            continue
        sp, _, _ = decile_spread(oos["D"].values, oos["fwd"].values, CONFIG["decile_frac"])
        metrics["per_symbol"][f["symbol"].iloc[0]] = None if np.isnan(sp) else sp * 1e4
        if not np.isnan(sp):
            signs_oos.append(np.sign(sp))

    # ---- agregado OOS + permutação ----
    oos_pool = pd.concat([split(f)[1] for f in frames], ignore_index=True)
    spread_oos, p_oos = perm_pvalue(oos_pool["D"].values, oos_pool["fwd"].values,
                                    CONFIG["decile_frac"], CONFIG["n_perm"])
    spread_is, _, _ = decile_spread(is_pool["D"].values, is_pool["fwd"].values, CONFIG["decile_frac"])

    # ---- estratificação por regime (OOS) ----
    regime_pass = False
    for reg in ("UP", "FLAT", "DOWN"):
        sub = oos_pool[oos_pool["regime"] == reg]
        if len(sub) < CONFIG["min_stratum_n"]:
            metrics["regime_oos"][reg] = {"n": int(len(sub)), "status": "inconclusivo"}
            continue
        sp, p = perm_pvalue(sub["D"].values, sub["fwd"].values, CONFIG["decile_frac"], CONFIG["n_perm"])
        net = sp * 1e4 - CONFIG["assumed_cost_bps"]
        ok = (net >= CONFIG["go_net_spread_bps"]) and (p < CONFIG["go_p"])
        metrics["regime_oos"][reg] = {"n": int(len(sub)), "spread_bps": sp * 1e4,
                                      "net_bps": net, "p": p, "ok": bool(ok)}
        regime_pass = regime_pass or ok

    # ---- veredito ----
    net_agg = (spread_oos * 1e4 - CONFIG["assumed_cost_bps"]) if not np.isnan(spread_oos) else np.nan
    cond_mag = (not np.isnan(net_agg)) and net_agg >= CONFIG["go_net_spread_bps"]
    cond_p = (not np.isnan(p_oos)) and p_oos < CONFIG["go_p"]
    cond_sign = (not np.isnan(spread_is)) and np.sign(spread_is) == np.sign(spread_oos)
    n_consist = int(max(np.sum(np.array(signs_oos) > 0), np.sum(np.array(signs_oos) < 0))) if signs_oos else 0
    cond_consist = n_consist >= CONFIG["consistency_min"]

    passou = bool(cond_mag and cond_p and cond_sign and regime_pass and cond_consist)
    motivo = []
    if not cond_mag: motivo.append(f"magnitude OOS insuficiente (net={net_agg:.1f}bps)")
    if not cond_p: motivo.append(f"p-permutação={p_oos}")
    if not cond_sign: motivo.append("sinal não persiste IS->OOS")
    if not regime_pass: motivo.append("não persiste em nenhum estrato de regime")
    if not cond_consist: motivo.append(f"consistência cross-símbolo {n_consist}/14")

    return {
        "passou": passou,
        "metricas": {
            "spread_oos_bps": None if np.isnan(spread_oos) else spread_oos * 1e4,
            "net_oos_bps": None if np.isnan(net_agg) else net_agg,
            "p_perm_oos": None if np.isnan(p_oos) else p_oos,
            "consistencia_cross_simbolo": f"{n_consist}/14",
            **metrics,
        },
        "motivo": "GO" if passou else "; ".join(motivo),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
```

---

## 10. Adicional H3 — validação do harness

H3 é o **primeiro** experimento a usar este harness; bugs encontrados aqui poupam H1/H2/H4. Checklist a verificar antes de confiar no veredito:

1. **Números fazem sentido?** Spread em bps na faixa plausível (não milhares de bps; não exatamente 0). Spearman ∈ [−1, 1]. Contagens de janela coerentes (~126/símbolo antes do split).
2. **Holdout respeitado?** Imprimir a data de corte e confirmar que nenhuma estatística de julgamento toca o in-sample. Confirmar que `feature_lag_h` está aplicado (sem leakage de timestamp): a feature em `t` deve ter timestamp `< t`.
3. **Permutação distribui como esperado?** A distribuição nula de `spread` deve ter **média ≈ 0** e ser aproximadamente simétrica. Se a média do nulo não for ~0, há viés no estimador (provável bug de alinhamento). Adicionar um print temporário de `null.mean(), null.std()` para auditar.
4. **Janelas não-sobrepostas?** Confirmar `iloc[::H]` reduz a contagem por ~4×. Se não, a independência assumida pela permutação está violada.
5. **Sanity de sinal nulo:** rodar uma vez com `fwd` aleatório (shuffle global pré-pipeline) e confirmar que o pipeline retorna NO-GO com p≈uniforme. Se "passar" com ruído, o harness está quebrado — **não prosseguir para H1**.
