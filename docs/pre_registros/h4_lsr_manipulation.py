"""h4_lsr_manipulation.py — runner EXP-012 (H4 indução manipulativa via LSR, Variante A).

Pré-registro: PREREG_H4_lsr_manipulation.md (selado 2026-05-29).

================================================================================
⚠️  UNIDADE CRÍTICA — ANTI-FOOTGUN  ⚠️
================================================================================
O `gap` do H4 é diferença de **TAXA DE REVERSÃO** (proporção, ou pontos
percentuais), NÃO bps de retorno como no H1.

  decile_gap(trap_score, labels_binarios) → valor em [-1, +1]
  0.10 = 10pp = piso de GO pré-comprometido

O parâmetro `min_gap_bps` do `assemble_verdict` é agnóstico de unidade.
O runner passa `min_gap_bps=0.10` SEM multiplicar por 1e4. Errar isso faz o
piso virar 1000× o pretendido (1000pp em vez de 10pp).

Não converter `gap` para bps no relatório. Reportar como `gap_proportion`.
================================================================================

Hipótese: top extremo + crowd convergindo na mesma direção → reversão forward.
Unidade de julgamento: PER_ENTITY com require_entities=2 (BTC e ETH ambos).
Direção pré-comprometida: "pos" (gap >= +0.10).
Bonferroni: max_p = 0.05/2 = 0.025 (2 entidades).
Holdout: 60% IS para calibrar `k`, 40% OOS para julgamento.
Não-contaminação: bucket_ts > 1780012800 (2026-05-29 00:00 UTC).

NÃO executar enquanto janela < 45 dias após marco — gate de poder retorna
inconclusivo. Apparatus (lab_harness 1.1.0, reversal_labeler) já validado.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import Optional

import numpy as np
import pandas as pd

# lab_harness vive na raiz do projeto
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# reversal_labeler vive no mesmo diretório
_PRE_REG = os.path.abspath(os.path.dirname(__file__))
if _PRE_REG not in sys.path:
    sys.path.insert(0, _PRE_REG)

from lab_harness import (  # noqa: E402
    JudgmentUnit,
    assemble_verdict,
    decile_gap,
    perm_gap_delta_strat,
    perm_gap_strat,
    spearman,
)
from reversal_labeler import compute_baseline_rate, label_reversals  # noqa: E402


CONFIG = {
    # ---- dados ----
    "db_path": "/home/pi/crypto_ai_bot/runtime/baseline/bot.db",
    "klines_table": "k_prices",
    "ratios_table": "k_ratios",
    "rt_top_source": "top_position",        # topLongShortPositionRatio (Binance)
    "rt_global_source": "global_account",   # globalLongShortAccountRatio (Binance)
    "rt_value_col": "long_short_ratio",     # coluna numérica real

    # ---- marco de não-contaminação (EXP-008 §10.3) ----
    # epoch s de 2026-05-29 00:00 UTC = 1780012800. H4 só lê bucket_ts > marco.
    "marco_no_contamination_s": 1_780_012_800,

    # ---- entidades ----
    "symbols": ["BTCUSDT", "ETHUSDT"],   # par mínimo para require_entities=2

    # ---- features (lag 1 anti-lookahead) ----
    "z_window_h": 72,
    "vel_window_h": 12,
    "vel_norm_window_h": 72,
    "feature_lag_h": 1,

    # ---- regime (mesma definição do PREREG_H3 §2.1) ----
    "regime_lookback_h": 48,
    "regime_band_k": 0.5,

    # ---- labeler ----
    "labeler_N": 12,
    "labeler_vol_window": 96,
    "labeler_M": 12,
    # PREREG v1.1: calibração de k POR BASELINE (não por gap, que tinha viés de
    # seleção pró-confound). Escolha pré-comprometida: k cuja baseline pooled IS
    # cai em [baseline_target_min, baseline_target_max]; tie-breaker = maior k
    # (labeler mais discriminativo). Se nenhum candidato cai na faixa →
    # inconclusivo (labeler não consegue produzir baseline alvo nestes dados).
    "labeler_k_candidates": [1.5, 2.0, 2.5, 3.0],
    "baseline_target_min": 0.10,
    "baseline_target_max": 0.15,

    # ---- estatística ----
    "decile_frac": 0.10,
    "holdout_frac": 0.60,
    "n_perm": 10_000,

    # ---- gate de poder (§11) ----
    "min_window_days": 45,
    "min_stratum_n": 30,
    # Sanity SECUNDÁRIA (labeler não-degenerado); discriminador PRIMÁRIO de
    # vol-confound passou a ser o placebo de continuação (§6.3 do PREREG v1.1).
    "preprobe_baseline_min": 0.05,
    "preprobe_baseline_max": 0.25,
    "preprobe_baseline_ratio_max": 2.0,
    "preprobe_min_n_per_regime": 50,

    # ---- diagnóstico de vol (reporta, NÃO gate) ----
    "vol_diag_n_terciles": 3,
    "vol_diag_min_per_tercile": 20,

    # ---- veredito (§8) ----
    # ⚠️ ATENÇÃO ÀS UNIDADES:
    #   min_gap_proportion: 0.10 = 10pp (proporção; NÃO bps). É passado direto.
    #   alpha_per_test: 0.05 POR TESTE (reversal e delta separadamente).
    #
    # POR QUE NÃO BONFERRONI (PREREG v1.1 §8): o GO é uma CONJUNÇÃO
    #   (rev_BTC ∧ rev_ETH ∧ delta_BTC ∧ delta_ETH, todos exigidos via require=2).
    # Conjunção é auto-conservadora: sob H0 global, P(GO falso) ≤ α^k onde k é
    # o número de testes ANDed (≤ α^2 ≈ 0.0025 com α=0.05 e require=2).
    # Bonferroni protege UNIÃO ("declarar vitória se QUALQUER de N der sig"),
    # NÃO interseção. Aplicar 0.05/N à conjunção empilha conservadorismo,
    # fabrica inconclusivos falsos, e mata sinal real onde o gargalo é poder
    # (gate de ≥30 eventos/estrato no H4 forward-only).
    #
    # PRÉ-CONDIÇÃO p/ usar α=0.05 sem correção: regime entra SÓ como estrato
    # da permutação (1 p pooled por entidade), sem gate "passa em ≥1 regime"
    # (que seria união e exigiria Bonferroni). Auditado e confirmado.
    "min_gap_proportion": 0.10,
    "alpha_per_test": 0.05,

    # ---- classificação interpretativa GO_marginal vs GO limpo (§8) ----
    # Não é gate novo (não adiciona permutação); reporta natureza da assimetria.
    # Se delta_lift < ratio_threshold * reversal_lift em ≥1 entidade → marca
    # GO_marginal:vol_dominant (passa estatística, mas componente de manipulação
    # fino vs vol — exige replicação forward antes de qualquer peso).
    "go_marginal_delta_ratio": 0.5,

    # ---- determinismo ----
    "seed": 20_260_529,
}


# ----------------------------------------------------------------------
# Carga (filtra marco de não-contaminação)
# ----------------------------------------------------------------------
def _load_prices(con, marco_s: int) -> pd.DataFrame:
    q = (f"SELECT symbol, bucket_ts AS t, close_price AS close "
         f"FROM {CONFIG['klines_table']} WHERE bucket_ts > ?")
    df = pd.read_sql_query(q, con, params=(marco_s,))
    df["t"] = pd.to_datetime(df["t"], unit="s", utc=True)
    return df.sort_values(["symbol", "t"])


def _load_ratios_pivot(con, marco_s: int) -> pd.DataFrame:
    q = (f"SELECT symbol, bucket_ts AS t, source, "
         f"{CONFIG['rt_value_col']} AS val FROM {CONFIG['ratios_table']} "
         f"WHERE bucket_ts > ? AND source IN (?, ?)")
    df = pd.read_sql_query(q, con, params=(marco_s, CONFIG["rt_top_source"],
                                           CONFIG["rt_global_source"]))
    df["t"] = pd.to_datetime(df["t"], unit="s", utc=True)
    top = (df[df["source"] == CONFIG["rt_top_source"]][["symbol", "t", "val"]]
           .rename(columns={"val": "top"}))
    glob = (df[df["source"] == CONFIG["rt_global_source"]][["symbol", "t", "val"]]
            .rename(columns={"val": "glob"}))
    piv = pd.merge(top, glob, on=["symbol", "t"], how="inner")
    return piv.sort_values(["symbol", "t"])


def build_panel():
    con = sqlite3.connect(CONFIG["db_path"])
    try:
        kl = _load_prices(con, CONFIG["marco_no_contamination_s"])
        lsr = _load_ratios_pivot(con, CONFIG["marco_no_contamination_s"])
    finally:
        con.close()
    return kl, lsr


# ----------------------------------------------------------------------
# Features só-passado
# ----------------------------------------------------------------------
def compute_features(prices: pd.Series, top: pd.Series, glob: pd.Series) -> pd.DataFrame:
    """Calcula top_z, vel_global, trap_score, regime — todas trailing + lag 1.

    Args:
      prices: pd.Series indexada por timestamp horário, close prices.
      top: pd.Series indexada por timestamp horário, top LSR.
      glob: pd.Series indexada por timestamp horário, global LSR.

    Returns: DataFrame com colunas {top_z, vel_global, trap_score, regime},
             indexado pelo mesmo timestamp horário. Valores antes do warmup vêm NaN.
    """
    if not (prices.index.equals(top.index) and prices.index.equals(glob.index)):
        raise ValueError("prices, top, glob precisam ter índices idênticos")
    lag = CONFIG["feature_lag_h"]

    # top_z (trailing 72h)
    w = CONFIG["z_window_h"]
    mu_top = top.rolling(w).mean()
    sd_top = top.rolling(w).std(ddof=0)
    top_z = (top - mu_top) / sd_top.replace(0, np.nan)
    top_z = top_z.shift(lag)

    # vel_global: Δglob em window vel, normalizada por desvio trailing maior
    vw = CONFIG["vel_window_h"]
    nw = CONFIG["vel_norm_window_h"]
    delta = glob.diff(vw)
    norm = glob.diff().rolling(nw).std(ddof=0) * np.sqrt(vw)
    vel_global = delta / norm.replace(0, np.nan)
    vel_global = vel_global.shift(lag)

    # trap_score: produto (co-ocorrência de extremos alinhados)
    trap_score = top_z * vel_global

    # regime (igual H3 §2.1)
    rb = CONFIG["regime_lookback_h"]
    logret = np.log(prices).diff()
    slope = np.log(prices).diff(rb)
    band = logret.rolling(rb).std(ddof=0) * np.sqrt(rb)
    kf = CONFIG["regime_band_k"]
    regime = pd.Series("FLAT", index=prices.index)
    regime[slope > kf * band] = "UP"
    regime[slope < -kf * band] = "DOWN"
    regime = regime.shift(lag)

    return pd.DataFrame({
        "top_z": top_z,
        "vel_global": vel_global,
        "trap_score": trap_score,
        "regime": regime,
    })


# ----------------------------------------------------------------------
# Gate de poder (§11)
# ----------------------------------------------------------------------
def gate_window(idx: pd.DatetimeIndex) -> tuple[bool, str]:
    """Recebe DatetimeIndex; aprova se span >= min_window_days."""
    if len(idx) < 2:
        days = 0.0
    else:
        days = (idx.max() - idx.min()).total_seconds() / 86400.0
    if days < CONFIG["min_window_days"]:
        return False, (f"janela={days:.1f}d < {CONFIG['min_window_days']}d "
                       f"(forward-only desde marco)")
    return True, f"janela={days:.1f}d ok"


def gate_stratum(oos: pd.DataFrame) -> dict:
    """Conta n OOS válidos por regime; retorna dict de status."""
    out = {}
    for reg in oos["regime"].dropna().unique():
        n = int((oos["regime"] == reg).sum())
        out[str(reg)] = {"n": n, "ok": n >= CONFIG["min_stratum_n"]}
    return out


# ----------------------------------------------------------------------
# Placebo de continuação (PREREG v1.1 §6.3 — discriminador vol-confound)
# ----------------------------------------------------------------------
def label_continuations(price, k, N, vol_window, M, noise_k=0.1) -> np.ndarray:
    """Espelho direcional de `reversal_labeler.label_reversals`.

    Rotula 1 quando há excursão FAVORÁVEL (na direção PRÉVIA) >= k·σ em N candles.
    Mesmos k/N/σ/M/banda morta que `label_reversals` — é o placebo simétrico.

    Lógica (espelho de label_reversals):
      - se prior > 0 (subiu antes): continuação = future.max() >= +k·σ_N (alta futura)
      - se prior < 0 (caiu antes):  continuação = future.min() <= -k·σ_N (queda futura)

    Sob vol pura simétrica: rates(reversal) ≈ rates(continuation). Sob manipulação
    direcional (assinatura H4): trap_score amplifica reversal mas NÃO continuation.
    GO requer reversal passar E continuation NÃO passar (§7/§8 do PREREG v1.1).
    """
    price = pd.Series(price).astype(float).reset_index(drop=True)
    n = len(price)
    labels = np.zeros(n, dtype=bool)
    if n < max(vol_window, M) + N + 1:
        return labels

    logp = np.log(price.values)
    ret = np.diff(logp, prepend=logp[0])
    vol_local = pd.Series(ret).rolling(vol_window).std(ddof=0).values
    prior = logp - np.concatenate([np.full(M, np.nan), logp[:-M]])

    start = max(vol_window, M)
    end = n - N
    for t in range(start, end):
        sig = vol_local[t]
        if not np.isfinite(sig) or sig <= 0:
            continue
        sigN = sig * np.sqrt(N)
        d = prior[t]
        if not np.isfinite(d):
            continue
        if abs(d) < noise_k * sigN:
            continue
        future = logp[t + 1: t + N + 1] - logp[t]
        if d > 0:                       # subiu antes → continuação = alta futura
            if future.max() >= k * sigN:
                labels[t] = True
        else:                           # caiu antes → continuação = queda futura
            if future.min() <= -k * sigN:
                labels[t] = True
    return labels


# ----------------------------------------------------------------------
# Seleção de k via BASELINE (PREREG v1.1 §6.1) — substitui calibração por gap
# ----------------------------------------------------------------------
def select_k_by_baseline_on_IS(price_IS: pd.Series) -> tuple[Optional[float], list[tuple]]:
    """Seleciona k cujo baseline pooled IS cai em [baseline_target_min, max].

    Critério: NUNCA usa gap (que tem viés pró-confound). Usa apenas a taxa marginal
    de reversão no IS. Tie-breaker: maior k (labeler mais discriminativo, menos
    rótulos triviais por excursões pequenas).

    Returns:
      (k_star, candidates_log) — k_star é None se nenhum candidato cai na faixa.
      candidates_log é lista de (k, baseline_pooled) para diagnóstico.
    """
    cfg = CONFIG
    results = []
    for k in cfg["labeler_k_candidates"]:
        labels = label_reversals(price_IS.values, k=k,
                                 N=cfg["labeler_N"],
                                 vol_window=cfg["labeler_vol_window"],
                                 M=cfg["labeler_M"])
        # baseline pooled = taxa marginal (ignora bordas não-rotuláveis ⇒ usa média)
        base = float(labels.mean())
        results.append((k, base))

    eligible = [(k, b) for k, b in results
                if cfg["baseline_target_min"] <= b <= cfg["baseline_target_max"]]
    if not eligible:
        return None, results
    # tie-breaker: MAIOR k
    k_star = max(k for k, _ in eligible)
    return float(k_star), results


# ----------------------------------------------------------------------
# Diagnóstico vol-tercile (PREREG v1.1 §9 modo de falha #7) — reporta, NÃO gate
# ----------------------------------------------------------------------
def vol_tercile_diagnostic(panel_oos: pd.DataFrame, trap_score: np.ndarray,
                           labels: np.ndarray) -> dict:
    """Reporta `decile_gap(trap_score, labels)` dentro de terciles de vol local.

    Vol local = desvio rolling 96h de logret (mesmo `vol_window` do labeler).
    Reportado por tercile {low, mid, high}; se efeito se concentra em 'high',
    é sinal forte de vol-confound (eyeball, não bloqueante).
    """
    cfg = CONFIG
    logret = np.log(panel_oos["close"].astype(float)).diff()
    vol_local = logret.rolling(cfg["labeler_vol_window"]).std(ddof=0)
    if vol_local.notna().sum() < 60:
        return {"warning": "vol_local com warm-up insuficiente"}

    try:
        terciles = pd.qcut(vol_local, cfg["vol_diag_n_terciles"],
                           labels=["low", "mid", "high"], duplicates="drop")
    except ValueError as e:
        return {"warning": f"qcut falhou: {e}"}

    out = {}
    for t_label in ["low", "mid", "high"]:
        mask = (terciles == t_label).values & np.isfinite(trap_score) & np.isfinite(labels)
        n = int(mask.sum())
        if n < cfg["vol_diag_min_per_tercile"]:
            out[t_label] = {"n": n, "gap": None, "warning": "n insuficiente"}
            continue
        g = decile_gap(trap_score[mask], labels[mask].astype(float), cfg["decile_frac"])
        out[t_label] = {"n": n, "gap": (None if np.isnan(g) else float(g))}
    return out


# ----------------------------------------------------------------------
# Pipeline por entidade
# ----------------------------------------------------------------------
def per_symbol_panel(sym: str, kl: pd.DataFrame, lsr: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Constrói panel horário {close, top, glob, features, regime} para um símbolo."""
    k = kl[kl["symbol"] == sym].set_index("t")
    l = lsr[lsr["symbol"] == sym].set_index("t")[["top", "glob"]]
    if len(k) == 0 or len(l) == 0:
        return None
    # grade horária comum (1h)
    k = k[["close"]].asfreq("1h")
    k["close"] = k["close"].astype(float).ffill()
    l = l.reindex(k.index).astype(float).ffill()
    feats = compute_features(k["close"], l["top"], l["glob"])
    panel = pd.concat([k["close"], l, feats], axis=1)
    panel["symbol"] = sym
    return panel


def evaluate_entity(sym: str, panel: pd.DataFrame, rng: np.random.Generator) -> dict:
    """Roda holdout + seleção k via baseline + pré-probe + reversal + continuação placebo.

    PREREG v1.1: o veredito por entidade reporta {reversal, continuation, vol_diag}.
    GO requer (julgado em run()): reversal passa AND continuation NÃO passa AND
    pré-probe sanity ok. Bug-fix Q1: preprobe_ok=False bloqueia o teste principal
    (return inconclusivo ANTES de tocar OOS).
    """
    cfg = CONFIG
    panel = panel.dropna(subset=["close", "top", "glob"]).copy()
    n_total = len(panel)
    if n_total < 100:
        return {"status": "inconclusivo", "motivo": f"n_total={n_total} < 100"}

    cut = int(n_total * cfg["holdout_frac"])
    panel_IS = panel.iloc[:cut].copy()
    panel_OOS = panel.iloc[cut:].copy()

    N = cfg["labeler_N"]
    if len(panel_IS) <= N + cfg["labeler_vol_window"] + 10:
        return {"status": "inconclusivo", "motivo": f"IS curto demais ({len(panel_IS)})"}

    # Seleção de k VIA BASELINE (PREREG v1.1 §6.1) — sem viés pró-confound.
    # Descarta últimas N do IS pra evitar vazamento de futuro IS→OOS via labeler.
    price_IS_safe = panel_IS["close"].iloc[:-N]
    k_star, calib_log = select_k_by_baseline_on_IS(price_IS_safe)
    if k_star is None:
        return {"status": "inconclusivo",
                "motivo": (f"nenhum k em {cfg['labeler_k_candidates']} produz "
                           f"baseline em [{cfg['baseline_target_min']}, "
                           f"{cfg['baseline_target_max']}]"),
                "k_calibration_baselines": {str(k): float(b) for k, b in calib_log}}

    # Pré-probe sanity (§6.2): baseline ∈ [0.05,0.25] E sem variação >2× entre regimes.
    # Q1 bug-fix: preprobe_ok=False → return INCONCLUSIVO ANTES do teste principal.
    labels_IS_full = label_reversals(panel_IS["close"].values, k=k_star,
                                     N=N, vol_window=cfg["labeler_vol_window"],
                                     M=cfg["labeler_M"])
    baseline = compute_baseline_rate(labels_IS_full, panel_IS["regime"])
    preprobe_ok, preprobe_motivo = _check_preprobe_baseline(baseline, panel_IS["regime"])
    if not preprobe_ok:
        return {"status": "inconclusivo",
                "motivo": (f"pré-probe falhou: {preprobe_motivo} — labeler "
                           f"suspeito de proxiar vol-normal"),
                "classe": "inconclusivo:labeler_suspeito",
                "k_star": k_star,
                "k_calibration_baselines": {str(k): float(b) for k, b in calib_log},
                "preprobe_ok": False,
                "preprobe_baseline": baseline}

    # OOS: rotular reversal E continuation com PARÂMETROS IDÊNTICOS (apples-to-apples).
    # CRAVADO (PREREG v1.1 §3, §6.3): k/N/vol_window/M são compartilhados; senão a
    # comparação `delta = gap(rev) − gap(con)` não é apples-to-apples.
    if len(panel_OOS) <= N + cfg["labeler_vol_window"] + 10:
        return {"status": "inconclusivo", "motivo": f"OOS curto demais ({len(panel_OOS)})",
                "k_star": k_star}
    _label_kwargs = dict(k=k_star, N=N, vol_window=cfg["labeler_vol_window"],
                         M=cfg["labeler_M"])
    reversal_OOS = label_reversals(panel_OOS["close"].values, **_label_kwargs)
    continuation_OOS = label_continuations(panel_OOS["close"].values, **_label_kwargs)

    oos = panel_OOS.copy()
    oos["rev_label"] = reversal_OOS.astype(float)
    oos["con_label"] = continuation_OOS.astype(float)
    oos_valid = oos.dropna(subset=["trap_score", "regime", "rev_label", "con_label"]).copy()
    oos_valid = oos_valid.iloc[:-N] if len(oos_valid) > N else oos_valid

    strat_status = gate_stratum(oos_valid)
    if sum(1 for v in strat_status.values() if v["ok"]) == 0:
        return {"status": "inconclusivo", "motivo": "nenhum estrato com n>=30",
                "k_star": k_star, "preprobe_ok": True,
                "regime_n": strat_status}

    feat = oos_valid["trap_score"].values
    rev = oos_valid["rev_label"].values
    con = oos_valid["con_label"].values
    reg = oos_valid["regime"].values
    if len(feat) < 20:
        return {"status": "inconclusivo", "motivo": f"n OOS válido={len(feat)} < 20",
                "k_star": k_star, "regime_n": strat_status}

    # Teste principal: trap_score vs reversal (alvo da hipótese H4)
    obs_rev, p_rev, _ = perm_gap_strat(feat, rev, reg,
                                       frac=cfg["decile_frac"],
                                       n_perm=cfg["n_perm"],
                                       tail="greater", rng=rng)
    # Continuation: descritivo flag (NÃO gate isolado — ver PREREG v1.1 §6.3)
    obs_con, p_con, _ = perm_gap_strat(feat, con, reg,
                                       frac=cfg["decile_frac"],
                                       n_perm=cfg["n_perm"],
                                       tail="greater", rng=rng)
    # Gate (b) PREREG v1.1: teste pareado da DIFERENÇA delta = gap(rev) − gap(con).
    # Permutação pareada estratificada preserva correlação intrínseca rev↔con
    # (ambos vêm do mesmo price/k/σ) — isola a ASSIMETRIA, não a correlação base.
    # Sob H4 genuíno: trap discrimina rev mais que con → delta > 0 significativo.
    # Sob vol-confound: ambos respondem igualmente → delta ≈ 0 não-significativo.
    obs_delta, p_delta, _ = perm_gap_delta_strat(feat, rev, con, reg,
                                                 frac=cfg["decile_frac"],
                                                 n_perm=cfg["n_perm"],
                                                 tail="greater", rng=rng)

    # Diagnóstico vol-tercile (reporta, NÃO gate)
    vol_diag = vol_tercile_diagnostic(oos_valid, feat, rev)

    rho_rev = spearman(feat, rev)
    rho_con = spearman(feat, con)

    return {
        "status": "tested",
        "k_star": float(k_star),
        "k_calibration_baselines": {str(k): float(b) for k, b in calib_log},
        "preprobe_ok": True,
        "preprobe_baseline": baseline,
        "n_oos_valid": int(len(feat)),
        "regime_n": strat_status,
        # ⚠️ "gap_bps" é nome legado do campo; a UNIDADE é proporção (PREREG §3, §8 #3)
        "reversal": {"gap_bps": float(obs_rev), "p": float(p_rev)},
        "continuation": {"gap_bps": float(obs_con), "p": float(p_con)},
        # delta com unidade proporção também (gap_rev − gap_con, ambos proporção)
        "delta": {"gap_bps": float(obs_delta), "p": float(p_delta)},
        "vol_diag_reversal": vol_diag,
        "spearman_oos_reversal": None if np.isnan(rho_rev) else float(rho_rev),
        "spearman_oos_continuation": None if np.isnan(rho_con) else float(rho_con),
    }


def _check_preprobe_baseline(baseline: dict, regime_IS: pd.Series) -> tuple[bool, str]:
    """Aplica regras §6.2: baseline em [0.05, 0.25], sem variação >2× entre regimes."""
    cfg = CONFIG
    counts = regime_IS.value_counts().to_dict()
    rates_qualifying = {r: rate for r, rate in baseline.items()
                        if counts.get(r, 0) >= cfg["preprobe_min_n_per_regime"]}
    if not rates_qualifying:
        return True, "preprobe pulado (nenhum regime com n>=50 no IS)"
    for r, rate in rates_qualifying.items():
        if not (cfg["preprobe_baseline_min"] <= rate <= cfg["preprobe_baseline_max"]):
            return False, (f"regime {r}: baseline={rate:.3f} fora de "
                           f"[{cfg['preprobe_baseline_min']}, "
                           f"{cfg['preprobe_baseline_max']}]")
    rates = list(rates_qualifying.values())
    if min(rates) > 0:
        ratio = max(rates) / min(rates)
        if ratio > cfg["preprobe_baseline_ratio_max"]:
            return False, (f"variação baseline entre regimes={ratio:.2f}× > "
                           f"{cfg['preprobe_baseline_ratio_max']}×")
    return True, "ok"


# ----------------------------------------------------------------------
# Top-level run
# ----------------------------------------------------------------------
def run():
    cfg = CONFIG
    rng = np.random.default_rng(cfg["seed"])

    kl, lsr = build_panel()

    # Assertion anti-contaminação (modo de falha #6): nenhum t deve ser ≤ marco
    marco_ts = pd.Timestamp(cfg["marco_no_contamination_s"], unit="s", tz="UTC")
    if len(kl) > 0 and kl["t"].min() <= marco_ts:
        return {"passou": False, "motivo": (
            f"CONTAMINAÇÃO: kl.t.min={kl['t'].min()} <= marco={marco_ts}")}
    if len(lsr) > 0 and lsr["t"].min() <= marco_ts:
        return {"passou": False, "motivo": (
            f"CONTAMINAÇÃO: lsr.t.min={lsr['t'].min()} <= marco={marco_ts}")}

    # Gate global de janela
    if len(kl) == 0:
        return {"passou": False, "motivo": "k_prices vazio após filtro de marco",
                "classe": "inconclusivo:amostragem"}
    window_ok, window_motivo = gate_window(
        pd.DatetimeIndex(kl["t"].unique()))
    if not window_ok:
        return {"passou": False, "motivo": window_motivo,
                "classe": "inconclusivo:amostragem",
                "n_amostras": int(len(kl)),
                "symbols_presentes": sorted(kl["symbol"].unique().tolist())}

    # Loop por entidade — coleta reversal + continuation
    per_entity_results = {}
    inconclusivos = []
    for sym in cfg["symbols"]:
        panel = per_symbol_panel(sym, kl, lsr)
        if panel is None:
            inconclusivos.append(f"{sym}: sem dados pós-marco")
            per_entity_results[sym] = {"status": "inconclusivo",
                                       "motivo": "sem dados pós-marco"}
            continue
        result = evaluate_entity(sym, panel, rng)
        per_entity_results[sym] = result
        if result.get("status") != "tested":
            inconclusivos.append(f"{sym}: {result.get('motivo', 'desconhecido')}")

    # α=0.05 POR TESTE (sem Bonferroni — ver justificativa em CONFIG e PREREG §8).
    # Aplicado igual a reversal e delta. Conjunção (require=2 entidades × 2 testes)
    # já controla FWER << 0.05 sob H0 global.
    max_p = cfg["alpha_per_test"]

    # Compõe per_entity_stats pra reversal, continuation e delta separadamente.
    # Entidade inconclusiva → gap_bps=None, p=None (assemble_verdict trata como não-passou).
    per_entity_reversal = {}
    per_entity_continuation = {}
    per_entity_delta = {}
    for sym, r in per_entity_results.items():
        if r.get("status") == "tested":
            per_entity_reversal[sym] = {"gap_bps": r["reversal"]["gap_bps"],
                                        "p": r["reversal"]["p"]}
            per_entity_continuation[sym] = {"gap_bps": r["continuation"]["gap_bps"],
                                            "p": r["continuation"]["p"]}
            per_entity_delta[sym] = {"gap_bps": r["delta"]["gap_bps"],
                                     "p": r["delta"]["p"]}
        else:
            per_entity_reversal[sym] = {"gap_bps": None, "p": None}
            per_entity_continuation[sym] = {"gap_bps": None, "p": None}
            per_entity_delta[sym] = {"gap_bps": None, "p": None}

    # Veredito (a) — reversal passa seu próprio bar
    v_reversal = assemble_verdict(
        per_entity_stats=per_entity_reversal,
        aggregate_stat=None,
        unit=JudgmentUnit.PER_ENTITY,
        # ⚠️ min_gap_bps é PROPORÇÃO (10pp); nome legado — NÃO multiplicar por 1e4
        min_gap_bps=cfg["min_gap_proportion"],
        max_p=max_p,
        require_entities=2,
        direction="pos",
    )
    # Veredito (b) — delta de assimetria > 0 significativo (gate principal contra
    # vol-confound). PREREG v1.1 §6.3: sem piso de magnitude (min_gap_bps=0); só
    # direcional + significância.
    v_delta = assemble_verdict(
        per_entity_stats=per_entity_delta,
        aggregate_stat=None,
        unit=JudgmentUnit.PER_ENTITY,
        min_gap_bps=0.0,
        max_p=max_p,
        require_entities=2,
        direction="pos",
    )
    # Flag (c) descritivo — continuation passa o mesmo bar? (NÃO é gate isolado)
    v_continuation_flag = assemble_verdict(
        per_entity_stats=per_entity_continuation,
        aggregate_stat=None,
        unit=JudgmentUnit.PER_ENTITY,
        min_gap_bps=cfg["min_gap_proportion"],
        max_p=max_p,
        require_entities=2,
        direction="pos",
    )

    # Lifts reportados em pp por entidade (1 proporção = 100 pp)
    per_entity_lifts_pp = {}
    for sym, r in per_entity_results.items():
        if r.get("status") == "tested":
            per_entity_lifts_pp[sym] = {
                "reversal_lift_pp": r["reversal"]["gap_bps"] * 100.0,
                "continuation_lift_pp": r["continuation"]["gap_bps"] * 100.0,
                "delta_lift_pp": r["delta"]["gap_bps"] * 100.0,
            }

    # GO requer (a) reversal E (b) delta. (c) continuation é descritivo.
    rev_pass = bool(v_reversal["passou"])
    delta_pass = bool(v_delta["passou"])
    con_pass = bool(v_continuation_flag["passou"])
    passou = rev_pass and delta_pass

    # Classe interpretativa pré-comprometida (PREREG v1.1 §8): se passou estatística
    # MAS delta_lift < ratio * reversal_lift em ≥1 entidade → GO_marginal:vol_dominant.
    # Reporta natureza da assimetria, NÃO é gate adicional (sem permutação nova).
    delta_strong = True
    delta_ratio_per_entity = {}
    if passou:
        ratio_threshold = cfg["go_marginal_delta_ratio"]
        for sym, lifts in per_entity_lifts_pp.items():
            rev_lift = lifts["reversal_lift_pp"]
            del_lift = lifts["delta_lift_pp"]
            if rev_lift > 0:
                ratio = del_lift / rev_lift
                delta_ratio_per_entity[sym] = float(ratio)
                if ratio < ratio_threshold:
                    delta_strong = False
            else:
                # reversal_lift <= 0 não deveria acontecer se passou=True (direction="pos")
                delta_ratio_per_entity[sym] = None
                delta_strong = False

    # Componer motivo + classe
    if passou:
        base = (f"GO: reversal passa (≥+{cfg['min_gap_proportion']:.2f}, "
                f"p<{max_p:.3f}) E delta>0 significativo")
        if not delta_strong:
            motivo = (f"{base}; ATENÇÃO: delta_lift < "
                      f"{cfg['go_marginal_delta_ratio']:.1f}×reversal_lift em ≥1 "
                      f"entidade — componente de manipulação fino vs vol; "
                      f"exige replicação forward antes de qualquer peso "
                      f"(ratios={delta_ratio_per_entity})")
            classe = "GO_marginal:vol_dominant"
        elif con_pass:
            motivo = (f"{base}; FLAG descritivo: continuation também passa "
                      f"(delta sólido mas atípico)")
            classe = "GO_with_continuation_flag"
        else:
            motivo = base
            classe = "GO"
    elif rev_pass and not delta_pass:
        # Reversal passou MAS assimetria não significativa → vol-confound
        delta_ps = {k: v["p"] for k, v in per_entity_delta.items()}
        motivo = (f"vol-confounded: reversal passa mas delta não significativo "
                  f"(p_delta={delta_ps}) — feature pode estar proxiando vol "
                  f"(rev e con respondem similarmente)")
        classe = "vol_confounded"
    elif not rev_pass:
        motivo = f"reversal: {v_reversal['motivo']}"
        classe = ("inconclusivo:amostragem"
                  if any(any(s in i for s in ("janela", "n_total", "IS curto",
                                              "OOS curto", "sem dados"))
                         for i in inconclusivos)
                  else ("inconclusivo:labeler_suspeito"
                        if any("pré-probe" in i for i in inconclusivos)
                        else None))
    else:
        # delta passa mas reversal não — caminho raro/anômalo; sem GO
        motivo = (f"anômalo: delta passa mas reversal não — "
                  f"reversal motivo: {v_reversal['motivo']}")
        classe = "anomalo:delta_sem_reversal"

    if inconclusivos:
        motivo += f"; inconclusivos: {inconclusivos}"

    return {
        "passou": passou,
        "metricas": {
            "veredito_unidade": v_reversal.get("unidade"),
            "veredito_direction": v_reversal.get("direction"),
            "min_gap_proportion": cfg["min_gap_proportion"],
            "alpha_per_test": max_p,
            "bonferroni_aplicado": False,
            "bonferroni_justificativa": "conjunção (require=2) já controla FWER",
            "per_entity": per_entity_results,
            "per_entity_lifts_pp": per_entity_lifts_pp,
            "delta_ratio_per_entity": delta_ratio_per_entity,
            "delta_strong_threshold": cfg["go_marginal_delta_ratio"],
            "veredito_reversal": v_reversal,
            "veredito_delta": v_delta,
            "veredito_continuation_flag": v_continuation_flag,
        },
        "motivo": motivo,
        "classe": classe,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
