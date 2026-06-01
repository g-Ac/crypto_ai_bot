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
    # NB: pandas 3.0 default mudou pra datetime64[us]; .timestamp() é robusto a unit.
    df["t"] = pd.to_datetime(df["ts_txt"], utc=True).map(pd.Timestamp.timestamp).astype("int64")
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
