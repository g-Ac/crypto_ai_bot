# Pré-registro — H1: Funding como overlay de exaustão/crowding sobre sinais momentum-pullback

**Status:** pré-registrado, não executado.
**Versão:** 1.1 (ajustado ao schema real do bot.db; desenho inalterado vs 1.0).
**Tipo:** experimento estrutural, paradigma de funding/posicionamento. Conditioning (não estratégia standalone).
**Prioridade no lab:** #1.
**Pré-condição operacional:** rodar **depois** de H3 ter validado o harness (§10 do pré-registro H3).

> Critério universal do lab (não renegociável): a feature só passa GO se mostrar **lift incremental ao regime**, não na média agregada. É o eixo central deste experimento — funding é colinear com regime, então o teste É a separação dos dois (§5, §6, §7).

---

## 1. Hipótese pré-registrada

Para a população de sinais de entrada momentum-pullback (dataset `momentum_shadow_outcomes`), seja `F_s = z-score` do funding rate perp no instante do sinal `s`, normalizado em janela trailing.

- **H0 (nula):** o resultado forward do trade (R / retorno) é independente de `F_s`, em todos os estratos de regime.
- **H1 (alternativa, direcional pré-registrada):** sinais disparados com `F_s` em percentil extremo **positivo** (longs alavancados aglomerados) têm expectancy forward **menor** que sinais em funding neutro, **e o efeito persiste intra-regime**.

Teste **unidirecional** (high funding → pior). A direção é pré-comprometida porque o mecanismo (crowding/custo de carrego de longs) prediz sinal claro, ao contrário do H3 vanilla. Caso o efeito apareça com sinal invertido, é tratado como **não-confirmação** da hipótese (não como descoberta — isso seria garimpo de direção).

---

## 2. Mecanismo causal (pré-registrado para evitar reinterpretação post-hoc)

Funding é o custo que longs pagam a shorts. Funding persistentemente alto = posicionamento alavancado long aglomerado. Entrar comprado num momentum quando o livro já está esticado eleva risco de squeeze/reversão → degrada o retorno forward. Crucialmente **ortogonal ao regime**: dentro de uma mesma tendência de alta, funding separa tendência "saudável" de "superaquecida". Se o efeito só existir porque funding proxia regime, a hipótese **falha** (§6, modo de falha #1).

---

## 3. Variáveis

| Papel | Definição |
|---|---|
| Independente (primária) | `F_s = z-score` do funding rate, janela trailing de **30 períodos de funding** (= 30 × 8h = 240h = 10 dias). |
| Independente (secundária) | nível bruto do funding `f_s` (para checar efeito de cauda além do z-score). |
| Dependente | resultado forward do sinal: **`pnl_pct` (percentual)** presente em `momentum_shadow_outcomes`. Conversão para bps: `1% = 100 bps`. |
| Controle | regime no instante do sinal — **label do bot**: `TRENDING` / `WEAK_TREND` (não UP/FLAT/DOWN; esses são do H3 §2.1, usado só quando não há label do bot). |

---

## 4. Dataset

- `momentum_shadow_outcomes` em `bot.db`: **737 linhas, das quais 537 completas** (`complete=1`). BTC e ETH. **Filtro obrigatório `complete=1`** — sem ele, `pnl_pct` vem NaN para ~200 sinais. Resultado por sinal é **`pnl_pct` (percentual; 1.0 = 1%)**, não R-multiple — a leitura da magnitude usa `outcome_to_bps = 100` (1% = 100 bps).
- Timestamp do sinal: **`decision_timestamp` TEXT `'YYYY-MM-DD HH:MM:SS'` (UTC)** — parseado para epoch segundos.
- Funding: **leitura local** da tabela **`k_funding_rates`** no mesmo `bot.db` (~89d × 14 símbolos já coletados). `funding_time` em **segundos**. **Sem API, sem rede, sem cache, sem rate limit** — elimina toda a complexidade de fetch do desenho original; mais barato e mais reprodutível.

---

## 5. Anti-lookahead de funding (regra explícita + teste unitário)

Funding na Binance liquida em **00:00 / 08:00 / 16:00 UTC**. Em `k_funding_rates`, `funding_time = T` (em **segundos**) representa a liquidação em `T`. Toda a aritmética de slot usa `SLOT_SEC = 28800` (8h em segundos).

**Regra pré-comprometida (slot-exclusion, conservadora):** para um sinal em `s`, usa-se o último funding que liquidou **antes da abertura do slot de 8h que contém `s`**.

- Seja `slot_open(s)` = maior fronteira de 8h ≤ `s`.
- `funding_usado(s)` = registro de funding com maior `funding_time` **estritamente menor** que `slot_open(s)`.

Consequências (todas testadas):
- Sinal **08:01 UTC** → `slot_open` = 08:00 → usa funding **00:00** (NÃO 08:00). ✅ (edge case obrigatório do pré-registro)
- Sinal **08:00:00 exato** → `slot_open` = 08:00 → usa funding **00:00**.
- Sinal **07:59 UTC** → `slot_open` = 00:00 → usa funding **16:00 do dia anterior** (deliberadamente conservador; nunca usa o funding que liquidou no slot corrente nem no slot imediatamente anterior à decisão dentro da mesma janela de liquidação).

Esta regra é intencionalmente mais conservadora que "último funding com `funding_time < s`", para blindar contra defasagem de publicação/consolidação. Documentado para que possa ser relaxado num experimento futuro, **não** neste.

O z-score `F_s` usa os 30 fundings imediatamente anteriores a `funding_usado(s)` (inclusive), todos com `funding_time < slot_open(s)`.

---

## 6. Estatística

### Pré-probe expandida (kill barato — funding pode agir só nas caudas)
1. **Spearman** `rho(F, R)` — global e por-símbolo.
2. **Decis/extremos:** R médio no top 10% de `F` vs bottom 10% vs miolo. **Esta etapa é tão importante quanto o Spearman**: se o efeito de crowding for não-linear (só morde em funding extremo), o Spearman pode ser ~0 enquanto o decil superior está claramente degradado. Os dois são reportados; o decil pode disparar GO mesmo com Spearman fraco.
- **Kill:** se Spearman ~0 **E** o decil superior de `F` não está abaixo do miolo por ao menos 1 erro-padrão → NO-GO sem construir o teste pleno.

### Teste principal
- Estatística: `gap = média(R | top decil de F) − média(R | bottom decil de F)`. Sob H1 (direcional), espera-se `gap < 0`.
- **Permutação estratificada por regime 10k:** embaralhar `F → R` **dentro de cada estrato de regime** (preserva composição de regime, isola o efeito incremental). p unidirecional.

### Estratificação por regime (obrigatória)
- Estratos: `{BTC,ETH} × {TRENDING, WEAK_TREND}` (vocabulário do bot).
- Efeito tem de persistir em **≥ 1 estrato** com n ≥ n_min, não só no agregado.
- **n mínimo por estrato = 30** sinais. Justificativa: abaixo de ~30, a média de `pnl_pct` num decil (≤ 3 sinais por cauda) é dominada por outliers.
- **Contagem real dos estratos (completos):** BTC×TRENDING = 166; BTC×WEAK_TREND = 116; ETH×TRENDING = 166; ETH×WEAK_TREND = 91. **Todos ≥ 30 → poder respeitado em todos os estratos.** Ainda assim, o decil de um estrato de n=91 tem ~9 sinais por cauda — magnitude por estrato deve ser lida com esse ruído em mente. Estratos eventualmente abaixo de 30 (caso o filtro mude) viram inconclusivos, com aviso explícito na saída.

---

## 7. Holdout temporal (pré-comprometido)

- Sinais ordenados cronologicamente. **Primeiros 60%:** escolha de hiperparâmetros (janela do z-score, cortes de decil). **Últimos 40%:** julgamento.
- Data de corte gravada na saída, imutável após a primeira execução.

---

## 8. GO/NO-GO numérico (pré-comprometido)

GO exige **todas** as condições, na fatia de julgamento (40% OOS):

1. **Magnitude:** |gap| de expectancy entre decil superior e inferior de `F` ≥ **50 bps por trade, líquido em paper** (piso elevado de 30→50 deliberadamente, para dar colchão à degradação paper→vivo de 30–80%; 50 bps paper degradam a ~10–35 bps vivo, ainda acima de ruído de custo).
2. **Direção:** `gap < 0` (high funding → pior), consistente com H1.
3. **Significância:** p-permutação unidirecional estratificada < **0.05**.
4. **Persistência de sinal:** mesma direção in-sample (60%) e OOS (40%).
5. **Lift incremental ao regime:** condições (1)+(2)+(3) satisfeitas em **≥ 1 estrato** (símbolo×regime) com n ≥ 30. Se o efeito existe no agregado mas some em **todos** os estratos → é beta de regime → **NO-GO** (modo de falha #1).
6. **Convergência cross-símbolo:** BTC e ETH mostram `gap` de **mesmo sinal** (tratamento da colinearidade BTC↔ETH — §modo de falha #2). Se só um símbolo carrega o efeito, marca-se **inconclusivo**, não GO.

Qualquer condição falha → **NO-GO**. Estratos finos demais dominando → **inconclusivo = NO-GO**.

---

## 9. Modo de falha esperado

1. **Colinearidade funding ↔ regime (mais provável).** Funding alto coincide com tendência de alta; o "efeito" agregado é só beta de regime. **Detecção:** comparar `gap` agregado vs intra-regime. Se `gap` agregado é forte mas some/zera dentro de cada estrato → morreu. É exatamente a condição (5).
2. **Colinearidade BTC ↔ ETH.** Funding de BTC e ETH co-movem; os 537 sinais completos **não** são 537 amostras independentes. **Tratamento pré-comprometido:** rodar por símbolo separadamente e exigir convergência de sinal (condição 6); **não** contar como 2 amostras independentes na narrativa de poder. (SE clusterizado seria alternativa, mas requer scipy/statsmodels; convergência de sinal é o substituto leve para o Pi.)
3. **Não-linearidade ignorada pelo z-score.** Crowding pode só morder no top 5%, não monotonicamente. **Detecção/cobertura:** a pré-probe de decil (§6) captura isso mesmo com Spearman ~0.
4. **Subpoder após estratificar.** Risco **reduzido** com o schema real: os 4 estratos symbol×regime têm 166/116/166/91 ≥ 30, então todos são avaliáveis. Persiste a cautela de que o decil de um estrato de ~91 tem ~9 sinais por cauda — efeito pequeno ainda pode ser engolido por ruído. **Detecção:** aviso de n_min na saída; magnitude por estrato lida com IC em mente.

---

## 10. Código (pronto para o Pi)

> **Roda 100% offline** — funding é leitura local de `k_funding_rates`. Sem rede, sem scipy. Confirmar nomes de coluna de `k_funding_rates` se diferirem de `funding_time`/`funding_rate`.

```python
# h1_funding_conditioning.py  — Python 3.11, pandas + numpy + sqlite3
# Funding é LEITURA LOCAL de k_funding_rates (mesmo bot.db). Sem rede, sem cache, sem API.
import sqlite3
import json
import numpy as np
import pandas as pd

CONFIG = {
    "bot_db": "/home/pi/crypto_ai_bot/runtime/baseline/bot.db",
    "shadow_table": "momentum_shadow_outcomes",
    # ---- colunas do shadow set (schema real) ----
    "sh_symbol": "symbol",
    "sh_time_txt": "decision_timestamp",   # TEXT 'YYYY-MM-DD HH:MM:SS' (UTC) -> parsear
    "sh_outcome": "pnl_pct",               # PERCENTUAL (1.0 = 1%), NÃO R-multiple
    "sh_regime": "regime",                 # label do bot: TRENDING / WEAK_TREND
    "sh_complete_col": "complete",         # filtrar complete=1 (537/737 completos)
    "symbols": ["BTCUSDT", "ETHUSDT"],
    # ---- funding local (k_funding_rates no mesmo bot.db) ----
    "funding_table": "k_funding_rates",
    "fr_symbol": "symbol",
    "fr_time_s": "funding_time",           # epoch SEGUNDOS
    "fr_rate": "funding_rate",
    # ---- conversão de unidade do outcome ----
    "outcome_to_bps": 100.0,               # pnl_pct(%) -> bps: 1% = 100 bps
    # ---- parâmetros pré-registrados ----
    "z_periods": 30,                 # 30 x 8h = 10d
    "decile_frac": 0.10,
    "holdout_frac": 0.60,
    "n_perm": 10000,
    "min_stratum_n": 30,
    "go_gap_bps": 50.0,              # piso líquido em paper (colchão p/ slippage)
    "go_p": 0.05,
    "seed": 20260528,
}
RNG = np.random.default_rng(CONFIG["seed"])
SLOT_SEC = 8 * 3600              # 28800; funding_time está em SEGUNDOS


# ----------------------------------------------------------------------
# Funding: leitura local de k_funding_rates (sem rede)
# ----------------------------------------------------------------------
def load_funding(con, symbol):
    q = (f"SELECT {CONFIG['fr_time_s']} AS funding_time, {CONFIG['fr_rate']} AS funding_rate "
         f"FROM {CONFIG['funding_table']} WHERE {CONFIG['fr_symbol']}=? "
         f"ORDER BY {CONFIG['fr_time_s']}")
    return pd.read_sql_query(q, con, params=(symbol,))


# ----------------------------------------------------------------------
# Anti-lookahead: slot-exclusion + z-score  (tudo em SEGUNDOS)
# ----------------------------------------------------------------------
def funding_feature(signal_s, fdf):
    """Retorna (z, raw) do funding sob a regra slot-exclusion. NaN se histórico insuficiente.
    signal_s e funding_time em epoch SEGUNDOS."""
    slot_open = (signal_s // SLOT_SEC) * SLOT_SEC
    elig = fdf[fdf["funding_time"] < slot_open]
    if len(elig) < CONFIG["z_periods"] + 1:
        return np.nan, np.nan
    window = elig["funding_rate"].iloc[-CONFIG["z_periods"]:].values
    raw = window[-1]
    mu, sd = window.mean(), window.std(ddof=0)
    z = (raw - mu) / sd if sd > 0 else np.nan
    return z, raw


# (teste unitário do edge case 08:01 -> 00:00 está em test_h1.py, §11)


# ----------------------------------------------------------------------
# Estatística (reaproveita helpers do harness H3)
# ----------------------------------------------------------------------
def _rankdata(a):
    a = np.asarray(a, float)
    order = a.argsort()
    ranks = np.empty(len(a), float); ranks[order] = np.arange(1, len(a) + 1)
    _, inv, cnt = np.unique(a, return_inverse=True, return_counts=True)
    return (np.bincount(inv, weights=ranks) / cnt)[inv]


def spearman(x, y):
    if len(x) < 5: return np.nan
    rx, ry = _rankdata(x), _rankdata(y); rx -= rx.mean(); ry -= ry.mean()
    den = np.sqrt((rx**2).sum() * (ry**2).sum())
    return float((rx * ry).sum() / den) if den > 0 else np.nan


def decile_gap(F, R, frac):
    n = len(F)
    if n < 20: return np.nan
    k = max(1, int(round(n * frac)))
    order = np.argsort(F)
    return float(R[order[-k:]].mean() - R[order[:k]].mean())  # top - bottom


def perm_strat(F, R, regime, frac, n_perm):
    """Permutação estratificada por regime: embaralha F->R dentro de cada estrato."""
    obs = decile_gap(F, R, frac)
    if np.isnan(obs): return obs, np.nan
    regs = np.asarray(regime)
    null = np.empty(n_perm)
    idx_by_reg = [np.where(regs == r)[0] for r in np.unique(regs)]
    for i in range(n_perm):
        Rp = R.copy()
        for idx in idx_by_reg:
            Rp[idx] = R[RNG.permutation(idx)]
        null[i] = decile_gap(F, Rp, frac)
    p_one = float((null <= obs).mean())  # H1: gap < 0
    return obs, p_one


# ----------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------
def build_signals():
    con = sqlite3.connect(CONFIG["bot_db"])
    q = (f"SELECT {CONFIG['sh_symbol']} AS symbol, {CONFIG['sh_time_txt']} AS ts_txt, "
         f"{CONFIG['sh_outcome']} AS R, {CONFIG['sh_regime']} AS regime "
         f"FROM {CONFIG['shadow_table']} WHERE {CONFIG['sh_complete_col']}=1")  # só sinais completos
    df = pd.read_sql_query(q, con)
    df = df[df["symbol"].isin(CONFIG["symbols"])].copy()
    # decision_timestamp é TEXT 'YYYY-MM-DD HH:MM:SS' (UTC) -> epoch SEGUNDOS
    df["t"] = pd.to_datetime(df["ts_txt"], utc=True).astype("int64") // 10**9
    df = df.sort_values("t").reset_index(drop=True)

    # funding é leitura local do mesmo bot.db (sem rede)
    fund = {s: load_funding(con, s) for s in CONFIG["symbols"]}
    con.close()

    z, raw = [], []
    for _, row in df.iterrows():
        zz, rr = funding_feature(int(row["t"]), fund[row["symbol"]])
        z.append(zz); raw.append(rr)
    df["F"] = z; df["F_raw"] = raw
    return df.dropna(subset=["F", "R"]).reset_index(drop=True)


def run():
    df = build_signals()
    cut = int(len(df) * CONFIG["holdout_frac"])
    is_df, oos = df.iloc[:cut], df.iloc[cut:]

    metrics = {"preprobe": {}, "strata_oos": {}, "by_symbol_oos": {}}
    metrics["preprobe"]["spearman_is"] = spearman(is_df["F"].values, is_df["R"].values)
    g_is = decile_gap(is_df["F"].values, is_df["R"].values, CONFIG["decile_frac"])
    metrics["preprobe"]["decile_gap_is_bps"] = None if np.isnan(g_is) else g_is * CONFIG["outcome_to_bps"]

    gap_oos, p_oos = perm_strat(oos["F"].values, oos["R"].values, oos["regime"].values,
                                CONFIG["decile_frac"], CONFIG["n_perm"])

    # por símbolo (colinearidade BTC<->ETH)
    sym_signs = {}
    for s in CONFIG["symbols"]:
        sub = oos[oos["symbol"] == s]
        g = decile_gap(sub["F"].values, sub["R"].values, CONFIG["decile_frac"]) if len(sub) >= 20 else np.nan
        metrics["by_symbol_oos"][s] = None if np.isnan(g) else g * CONFIG["outcome_to_bps"]
        if not np.isnan(g): sym_signs[s] = np.sign(g)

    # estratos symbol x regime
    strat_pass = False
    for s in CONFIG["symbols"]:
        for reg in sorted(oos["regime"].dropna().unique()):
            sub = oos[(oos["symbol"] == s) & (oos["regime"] == reg)]
            key = f"{s}:{reg}"
            if len(sub) < CONFIG["min_stratum_n"]:
                metrics["strata_oos"][key] = {"n": int(len(sub)), "status": "inconclusivo"}
                continue
            g, p = perm_strat(sub["F"].values, sub["R"].values, sub["regime"].values,
                              CONFIG["decile_frac"], CONFIG["n_perm"])
            ok = (g * CONFIG["outcome_to_bps"] <= -CONFIG["go_gap_bps"]) and (p < CONFIG["go_p"])
            metrics["strata_oos"][key] = {"n": int(len(sub)), "gap_bps": g * CONFIG["outcome_to_bps"],
                                          "p": p, "ok": bool(ok)}
            strat_pass = strat_pass or ok

    gap_bps = gap_oos * CONFIG["outcome_to_bps"] if not np.isnan(gap_oos) else np.nan
    cond_mag = (not np.isnan(gap_bps)) and abs(gap_bps) >= CONFIG["go_gap_bps"]
    cond_dir = (not np.isnan(gap_bps)) and gap_bps < 0
    cond_p = (not np.isnan(p_oos)) and p_oos < CONFIG["go_p"]
    cond_sign = (not np.isnan(g_is)) and np.sign(g_is) == np.sign(gap_oos)
    cond_conv = len(sym_signs) == len(CONFIG["symbols"]) and len(set(sym_signs.values())) == 1

    passou = bool(cond_mag and cond_dir and cond_p and cond_sign and strat_pass and cond_conv)
    motivo = []
    if not cond_mag: motivo.append(f"magnitude<{CONFIG['go_gap_bps']}bps (gap={gap_bps:.1f})")
    if not cond_dir: motivo.append("direção errada (gap>=0; high funding não piorou)")
    if not cond_p: motivo.append(f"p={p_oos}")
    if not cond_sign: motivo.append("sinal não persiste IS->OOS")
    if not strat_pass: motivo.append("não persiste em nenhum estrato (provável beta de regime)")
    if not cond_conv: motivo.append("BTC e ETH não convergem em sinal")

    return {
        "passou": passou,
        "metricas": {
            "gap_oos_bps": None if np.isnan(gap_bps) else gap_bps,
            "p_perm_oos": None if np.isnan(p_oos) else p_oos,
            "n_sinais_usados": int(len(df)),
            "data_corte": str(df.iloc[cut]["t"]) if cut < len(df) else None,
            **metrics,
        },
        "motivo": "GO" if passou else "; ".join(motivo),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
```

---

## 11. Teste unitário do anti-lookahead (obrigatório antes de rodar)

```python
# test_h1.py — pytest opcional; roda standalone com `python test_h1.py`
import pandas as pd
from h1_funding_conditioning import funding_feature, SLOT_SEC, CONFIG

def _mk_funding():
    # fundings liquidados às 00:00, 08:00, 16:00 UTC — tudo em epoch SEGUNDOS
    base = 1_700_000_000            # epoch segundos qualquer
    base = (base // SLOT_SEC) * SLOT_SEC  # alinha à fronteira de 8h (00/08/16 UTC)
    times = [base + i * SLOT_SEC for i in range(CONFIG["z_periods"] + 5)]
    rates = [0.0001 * (i + 1) for i in range(len(times))]  # crescentes, distinguíveis
    return pd.DataFrame({"funding_time": times, "funding_rate": rates}), base

def test_0801_usa_slot_anterior():
    fdf, base = _mk_funding()
    last_boundary = fdf["funding_time"].iloc[-1]  # uma fronteira de 8h
    signal_0801 = last_boundary + 60              # +60s => "08:01" em relação ao slot
    z, raw = funding_feature(signal_0801, fdf)
    # slot_open = last_boundary; deve usar o funding ANTERIOR a last_boundary
    raw_esperado = fdf[fdf["funding_time"] < last_boundary]["funding_rate"].iloc[-1]
    assert raw == raw_esperado, f"08:01 deveria usar funding do slot anterior, usou {raw}"
    print("OK: sinal +1min após fronteira usa o funding do slot anterior (00:00, não 08:00)")

def test_fronteira_exata_usa_anterior():
    fdf, base = _mk_funding()
    boundary = fdf["funding_time"].iloc[-1]
    z, raw = funding_feature(boundary, fdf)  # 08:00:00 exato
    raw_esperado = fdf[fdf["funding_time"] < boundary]["funding_rate"].iloc[-1]
    assert raw == raw_esperado
    print("OK: fronteira exata exclui o funding que liquida nela")

if __name__ == "__main__":
    test_0801_usa_slot_anterior()
    test_fronteira_exata_usa_anterior()
    print("todos os testes de anti-lookahead passaram")
```
