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
    "rt_value_col": "long_short_ratio",    # confirmado: k_ratios.long_short_ratio (REAL NOT NULL)
    "rt_top_source": "top_position",       # confirmado (topLongShortPositionRatio)
    "rt_global_source": "global_account",  # confirmado (globalLongShortAccountRatio)
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
