"""test_h4.py — unit tests do EXP-012 (H4 indução manipulativa via LSR).

Cobertura conforme PREREG §5, §6, §11:
  1. Anti-lookahead das features: verdade só-passado, estável sob truncamento futuro.
  2. Construção do trap_score = top_z * vel_global; semântica de co-extremos alinhados.
  3. Gate de poder: dispara inconclusivo quando janela<45d ou estrato<30.
  4. Assertion anti-contaminação: marco bloqueia bucket_ts <= 1780012800.

Roda standalone: `python test_h4.py` (caminho relativo a docs/pre_registros/).
Importa lab_harness e reversal_labeler já validados.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

# h4 vive em docs/pre_registros; lab_harness na raiz do projeto.
_HERE = os.path.abspath(os.path.dirname(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
for p in (_HERE, _REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import h4_lsr_manipulation as h4  # noqa: E402


# ----------------------------------------------------------------------
# Helpers de fixture sintética
# ----------------------------------------------------------------------
def _mk_series(n: int, seed: int = 0, start_ts: str = "2026-06-01 00:00",
               freq: str = "1h") -> tuple[pd.Series, pd.Series, pd.Series]:
    """Gera prices/top/glob horários sintéticos sem padrão estrutural."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start_ts, periods=n, freq=freq, tz="UTC")
    log_ret = rng.normal(0, 0.005, n)
    prices = pd.Series(100.0 * np.exp(np.cumsum(log_ret)), index=idx)
    top = pd.Series(1.0 + 0.3 * rng.standard_normal(n).cumsum() / np.sqrt(np.arange(1, n + 1)),
                    index=idx).clip(lower=0.1)
    glob = pd.Series(1.0 + 0.2 * rng.standard_normal(n).cumsum() / np.sqrt(np.arange(1, n + 1)),
                     index=idx).clip(lower=0.1)
    return prices, top, glob


# ----------------------------------------------------------------------
# (1) Anti-lookahead: features estáveis sob truncamento futuro
# ----------------------------------------------------------------------
def test_top_z_estavel_sob_truncamento_futuro():
    """`top_z` em t<cut deve ser idêntico com ou sem dados após cut."""
    n = 400
    prices, top, glob = _mk_series(n, seed=11)
    full = h4.compute_features(prices, top, glob)
    cut = 250
    trunc = h4.compute_features(prices.iloc[:cut], top.iloc[:cut], glob.iloc[:cut])

    # Compara só a região onde ambos têm valor finito
    common_idx = full.index[:cut]
    full_z = full.loc[common_idx, "top_z"].values
    trunc_z = trunc["top_z"].values
    mask = np.isfinite(full_z) & np.isfinite(trunc_z)
    assert mask.sum() > 0, "esperava algum valor finito após warm-up"
    assert np.allclose(full_z[mask], trunc_z[mask], equal_nan=True), (
        "top_z mudou ao truncar futuro — violação de anti-lookahead"
    )


def test_vel_global_estavel_sob_truncamento_futuro():
    n = 400
    prices, top, glob = _mk_series(n, seed=12)
    full = h4.compute_features(prices, top, glob)
    cut = 250
    trunc = h4.compute_features(prices.iloc[:cut], top.iloc[:cut], glob.iloc[:cut])

    common_idx = full.index[:cut]
    full_v = full.loc[common_idx, "vel_global"].values
    trunc_v = trunc["vel_global"].values
    mask = np.isfinite(full_v) & np.isfinite(trunc_v)
    assert mask.sum() > 0
    assert np.allclose(full_v[mask], trunc_v[mask], equal_nan=True), (
        "vel_global mudou ao truncar futuro — violação de anti-lookahead"
    )


def test_regime_estavel_sob_truncamento_futuro():
    n = 400
    prices, top, glob = _mk_series(n, seed=13)
    full = h4.compute_features(prices, top, glob)
    cut = 250
    trunc = h4.compute_features(prices.iloc[:cut], top.iloc[:cut], glob.iloc[:cut])

    common_idx = full.index[:cut]
    full_r = full.loc[common_idx, "regime"].values
    trunc_r = trunc["regime"].values
    # comparar elementos válidos (não-NaN) — regime é string
    mask = pd.notna(full_r) & pd.notna(trunc_r)
    assert mask.sum() > 0
    assert (full_r[mask] == trunc_r[mask]).all(), (
        "regime mudou ao truncar futuro"
    )


# ----------------------------------------------------------------------
# (2) Construção do trap_score
# ----------------------------------------------------------------------
def test_trap_score_eh_produto_top_z_vel_global():
    """trap_score = top_z * vel_global elementwise."""
    n = 300
    prices, top, glob = _mk_series(n, seed=21)
    feats = h4.compute_features(prices, top, glob)
    expected = feats["top_z"] * feats["vel_global"]
    # comparar onde ambos são finitos
    mask = np.isfinite(expected) & np.isfinite(feats["trap_score"])
    assert mask.sum() > 0
    assert np.allclose(feats["trap_score"][mask], expected[mask], rtol=1e-12)


def test_trap_score_propaga_nan_quando_componente_eh_nan():
    """Se top_z ou vel_global é NaN num ponto, trap_score também é NaN.

    Propriedade do produto numpy: NaN * x = NaN. Isso garante que warm-up de
    qualquer componente bloqueia o trap_score (não há vazamento de valor
    parcial). Substitui o teste 'top_z zero ⇒ trap zero' que era impossível
    de honrar com fixture sintética (top quase-constante ainda dá top_z ~1
    pela divisão por sd quase-zero).
    """
    n = 200
    prices, top, glob = _mk_series(n, seed=22)
    feats = h4.compute_features(prices, top, glob)
    # nas primeiras barras (warm-up), top_z é NaN ⇒ trap_score deve ser NaN também
    warmup_mask = feats["top_z"].isna() | feats["vel_global"].isna()
    assert warmup_mask.sum() > 0, "esperava warm-up em fixture pequena"
    assert feats.loc[warmup_mask, "trap_score"].isna().all(), (
        "trap_score deveria ser NaN onde top_z OR vel_global é NaN"
    )


def test_trap_score_positivo_quando_top_e_vel_alinhados_positivamente():
    """top_z>0 + vel_global>0 → trap_score>0 (setup esperado da hipótese H4)."""
    n = 300
    rng = np.random.default_rng(23)
    idx = pd.date_range("2026-06-01", periods=n, freq="1h", tz="UTC")
    prices = pd.Series(100.0 + rng.normal(0, 0.5, n).cumsum(), index=idx)
    # top com upward drift forte (top_z será positivo no fim)
    top = pd.Series(1.0 + 0.005 * np.arange(n) + 0.01 * rng.standard_normal(n), index=idx)
    # glob com aceleração positiva (vel_global será positivo no fim)
    glob = pd.Series(1.0 + 0.001 * np.arange(n) ** 1.5 / 100 + 0.005 * rng.standard_normal(n),
                     index=idx)
    feats = h4.compute_features(prices, top, glob)
    # média do trap_score na metade final deve ser positiva (alinhamento)
    tail = feats["trap_score"].iloc[-50:].dropna()
    assert len(tail) >= 10
    assert tail.mean() > 0, (
        f"trap_score médio na cauda deveria ser positivo (top+vel ambos crescendo); "
        f"obs={tail.mean():.4g}"
    )


# ----------------------------------------------------------------------
# (3) Gate de poder
# ----------------------------------------------------------------------
def test_gate_window_dispara_inconclusivo_em_janela_curta():
    """Janela < 45d → gate_window retorna False."""
    idx = pd.date_range("2026-06-01", periods=10, freq="1h", tz="UTC")  # ~9h
    ok, motivo = h4.gate_window(idx)
    assert ok is False
    assert "janela" in motivo and "<" in motivo


def test_gate_window_aprova_janela_longa():
    idx = pd.date_range("2026-06-01", periods=24 * 50, freq="1h", tz="UTC")  # 50d
    ok, motivo = h4.gate_window(idx)
    assert ok is True


def test_gate_stratum_inconclusivo_quando_n_menor_que_30():
    oos = pd.DataFrame({
        "regime": ["UP"] * 25 + ["FLAT"] * 35 + ["DOWN"] * 10,
    })
    status = h4.gate_stratum(oos)
    assert status["UP"]["ok"] is False, "UP n=25 < 30"
    assert status["FLAT"]["ok"] is True, "FLAT n=35 >= 30"
    assert status["DOWN"]["ok"] is False, "DOWN n=10 < 30"


# ----------------------------------------------------------------------
# (4) Assertion anti-contaminação
# ----------------------------------------------------------------------
def test_marco_no_contamination_eh_pre_comprometido():
    """Marco está cravado como epoch s de 2026-05-29 00:00 UTC."""
    expected = int(pd.Timestamp("2026-05-29 00:00", tz="UTC").timestamp())
    assert h4.CONFIG["marco_no_contamination_s"] == expected, (
        f"marco esperado {expected}, configurado {h4.CONFIG['marco_no_contamination_s']}"
    )


# ----------------------------------------------------------------------
# (5) Compute_features valida índices alinhados
# ----------------------------------------------------------------------
def test_compute_features_exige_indices_iguais():
    n = 200
    prices, top, glob = _mk_series(n, seed=33)
    # quebrar alinhamento
    glob_misaligned = glob.iloc[1:]
    with pytest.raises(ValueError, match="índices idênticos"):
        h4.compute_features(prices, top, glob_misaligned)


# ----------------------------------------------------------------------
# (6) Unidade: o min_gap_proportion não é bps
# ----------------------------------------------------------------------
def test_min_gap_proportion_eh_proporcao_nao_bps():
    """⚠️ Anti-footgun: min_gap_proportion=0.10 é 10pp, NÃO 0.001%."""
    assert h4.CONFIG["min_gap_proportion"] == 0.10, (
        "10pp é o piso pré-comprometido — não confundir com bps"
    )
    # Sanity: se alguém multiplicar por 1e4 por engano, daria 1000 (= 100000pp absurdo)
    assert h4.CONFIG["min_gap_proportion"] * 1e4 == 1000.0


# ----------------------------------------------------------------------
# (7) Seleção de k via BASELINE (PREREG v1.1) — NÃO por gap
# ----------------------------------------------------------------------
def test_select_k_by_baseline_retorna_k_dentro_da_faixa_ou_none():
    """Critério: baseline pooled ∈ [baseline_target_min, max]; tie-breaker = maior k.
    NUNCA usa gap (que tinha viés pró-confound)."""
    # Fixture com fat-tails moderadas (próxima de cripto real)
    rng = np.random.default_rng(44)
    n = 600
    log_ret = rng.normal(0, 0.01, n) * rng.standard_t(df=4, size=n) / 2
    prices = pd.Series(100.0 * np.exp(np.cumsum(log_ret)),
                       index=pd.date_range("2026-06-01", periods=n, freq="1h", tz="UTC"))
    k_star, calib_log = h4.select_k_by_baseline_on_IS(prices)
    # calib_log sempre presente
    assert {k for k, _ in calib_log} == set(h4.CONFIG["labeler_k_candidates"])
    # k_star ou é None (nenhum candidato cai) ou está no grid
    assert k_star is None or k_star in h4.CONFIG["labeler_k_candidates"]
    # Se k_star existe, baseline deve estar na faixa
    if k_star is not None:
        b = dict(calib_log)[k_star]
        assert h4.CONFIG["baseline_target_min"] <= b <= h4.CONFIG["baseline_target_max"]


def test_select_k_tie_breaker_eh_maior_k():
    """Se múltiplos k caem na faixa, escolhe o MAIOR (mais discriminativo)."""
    # Stub: monkey-patch label_reversals temporariamente pra forçar baselines conhecidas.
    import reversal_labeler
    original = reversal_labeler.label_reversals

    def fake_label_reversals(price, k, **kwargs):
        # Retorna labels com baseline correspondente: k=1.5→0.20, k=2.0→0.12, k=2.5→0.11, k=3.0→0.04
        rates = {1.5: 0.20, 2.0: 0.12, 2.5: 0.11, 3.0: 0.04}
        rate = rates.get(k, 0.0)
        n = len(price)
        labels = np.zeros(n, dtype=bool)
        # Marca o primeiro `rate*n` elementos como True
        n_true = int(round(rate * n))
        labels[:n_true] = True
        return labels

    try:
        reversal_labeler.label_reversals = fake_label_reversals
        # Re-import h4 não funciona; monkey-patch direto h4 também
        h4.label_reversals = fake_label_reversals

        prices = pd.Series(np.linspace(100, 110, 200),
                           index=pd.date_range("2026-06-01", periods=200, freq="1h", tz="UTC"))
        k_star, calib_log = h4.select_k_by_baseline_on_IS(prices)
        # Faixa default [0.10, 0.15] → elegíveis: k=2.0 (0.12) e k=2.5 (0.11)
        # Tie-breaker: maior → k=2.5
        assert k_star == 2.5, f"esperava k=2.5 (tie-breaker maior), obteve {k_star}"
    finally:
        reversal_labeler.label_reversals = original
        h4.label_reversals = original


def test_select_k_retorna_none_se_nenhum_candidato_na_faixa():
    """Se todos os k produzem baseline fora de [0.10, 0.15], retorna None (inconclusivo)."""
    import reversal_labeler
    original = reversal_labeler.label_reversals

    def fake_label_reversals(price, k, **kwargs):
        # Todos os k produzem baseline 0.50 (fora da faixa)
        n = len(price)
        labels = np.zeros(n, dtype=bool)
        labels[:n // 2] = True
        return labels

    try:
        reversal_labeler.label_reversals = fake_label_reversals
        h4.label_reversals = fake_label_reversals
        prices = pd.Series(np.linspace(100, 110, 200),
                           index=pd.date_range("2026-06-01", periods=200, freq="1h", tz="UTC"))
        k_star, calib_log = h4.select_k_by_baseline_on_IS(prices)
        assert k_star is None
        assert all(b == 0.5 for _, b in calib_log)
    finally:
        reversal_labeler.label_reversals = original
        h4.label_reversals = original


# ----------------------------------------------------------------------
# (8) label_continuations — placebo simétrico de label_reversals
# ----------------------------------------------------------------------
def test_label_continuations_eh_simetrico_em_vol_pura():
    """Sob random walk simétrico (vol pura, sem direção), taxas de reversal e
    continuation devem ser próximas em K seeds independentes.

    Propriedade estatística (não pontual): n=5000 + 5 seeds; mediana de ratio
    deve ficar < 2.0. Diagnóstico empírico (30 seeds): mediana=1.09, máx=1.88.
    Tolerância 2.0 com 80% de pass-rate é folga grande pra evitar flakiness.
    """
    cfg = h4.CONFIG
    from reversal_labeler import label_reversals
    K = 5
    ratios = []
    for seed in range(K):
        rng = np.random.default_rng(100 + seed)
        n = 5000
        log_ret = rng.normal(0, 0.01, n)
        prices = np.exp(np.cumsum(log_ret)) * 100
        rev = label_reversals(prices, k=2.0, N=cfg["labeler_N"],
                              vol_window=cfg["labeler_vol_window"], M=cfg["labeler_M"])
        con = h4.label_continuations(prices, k=2.0, N=cfg["labeler_N"],
                                     vol_window=cfg["labeler_vol_window"], M=cfg["labeler_M"])
        r, c = rev.mean(), con.mean()
        if r > 0 and c > 0:
            ratios.append(max(r, c) / min(r, c))

    assert len(ratios) >= K - 1, f"esperava ≥{K-1} seeds válidas, obteve {len(ratios)}"
    passes = sum(1 for r in ratios if r < 2.0)
    assert passes >= int(0.8 * K), (
        f"vol pura → simetria; {passes}/{K} seeds com ratio<2.0 "
        f"(ratios={[f'{r:.2f}' for r in ratios]})"
    )


def test_label_continuations_marca_continuacao_clara():
    """Subida limpa e estável → continuation (alta futura forte) deve marcar."""
    n = 200
    rng = np.random.default_rng(60)
    base = np.cumsum(rng.normal(0, 0.001, n)) + 0.0005 * np.arange(n)
    prices = np.exp(base) * 100
    # Injeta CONTINUAÇÃO forte (+8%) num ponto perto do fim da zona rotulável
    pump_at = 150
    prices[pump_at + 1:] *= 1.08
    con = h4.label_continuations(prices, k=2.0, N=12, vol_window=96, M=12)
    # Algum índice antes do pump deve marcar continuação
    assert con[pump_at - 11: pump_at + 1].any(), (
        "alta forte de 8% após uptrend deveria marcar continuação"
    )


# ----------------------------------------------------------------------
# (9) Bug-fix Q1: preprobe falha → entity_status='inconclusivo'
# ----------------------------------------------------------------------
def test_preprobe_falha_bloqueia_teste_principal():
    """Q1 bug-fix: se preprobe_ok=False, evaluate_entity retorna inconclusivo
    SEM rodar o teste principal (PREREG §8 condição 2)."""
    # Monkey-patch label_reversals pra forçar baseline desbalanceada (ratio >2× entre regimes)
    import reversal_labeler
    original = reversal_labeler.label_reversals

    def fake_label_reversals(price, k, **kwargs):
        # Marca primeiros 50% como True (vai criar baseline ~0.5 em todos os regimes,
        # FALHANDO a faixa [0.05, 0.25] do sanity)
        n = len(price)
        labels = np.zeros(n, dtype=bool)
        labels[:n // 2] = True
        return labels

    # Também precisamos forçar k_star a ser selecionado (mesmo com baseline fora da faixa,
    # pra testar o segundo gate). Vou mock select_k pra retornar k=2.0 ignorando faixa.
    original_select = h4.select_k_by_baseline_on_IS

    def fake_select_k(price_IS):
        return 2.0, [(2.0, 0.5)]

    # E precisamos panel sintético grande o suficiente
    rng = np.random.default_rng(70)
    n = 600
    idx = pd.date_range("2026-06-01", periods=n, freq="1h", tz="UTC")
    prices = pd.Series(100.0 + rng.normal(0, 0.5, n).cumsum(), index=idx)
    top = pd.Series(1.0 + 0.1 * rng.standard_normal(n).cumsum() / np.sqrt(np.arange(1, n + 1)),
                    index=idx)
    glob = pd.Series(1.0 + 0.1 * rng.standard_normal(n).cumsum() / np.sqrt(np.arange(1, n + 1)),
                     index=idx)
    feats = h4.compute_features(prices, top, glob)
    panel = pd.concat([prices.rename("close"),
                       pd.DataFrame({"top": top, "glob": glob}),
                       feats], axis=1)
    panel["symbol"] = "TESTUSDT"

    try:
        reversal_labeler.label_reversals = fake_label_reversals
        h4.label_reversals = fake_label_reversals
        h4.select_k_by_baseline_on_IS = fake_select_k
        rng_eval = np.random.default_rng(0)
        result = h4.evaluate_entity("TESTUSDT", panel, rng_eval)
    finally:
        reversal_labeler.label_reversals = original
        h4.label_reversals = original
        h4.select_k_by_baseline_on_IS = original_select

    assert result["status"] == "inconclusivo", (
        f"preprobe falho deveria bloquear; status={result['status']}"
    )
    assert "pré-probe" in result["motivo"] or "preprobe" in result["motivo"].lower()
    assert result.get("classe") == "inconclusivo:labeler_suspeito"
    # Teste principal NÃO rodou: nenhum campo reversal/continuation/delta
    assert "reversal" not in result
    assert "continuation" not in result
    assert "delta" not in result


# ----------------------------------------------------------------------
# (10) Q3 cobertura: per_symbol_panel com gaps de k_ratios
# ----------------------------------------------------------------------
def test_per_symbol_panel_handles_gaps_no_lsr_sem_lookahead():
    """k_ratios com 6 buckets consecutivos faltando + gaps irregulares: reindex+ffill
    não pode introduzir lookahead; features pós-ffill respeitam shift(1)."""
    sym = "TESTUSDT"
    rng = np.random.default_rng(80)
    n = 300
    idx_horario = pd.date_range("2026-06-01", periods=n, freq="1h", tz="UTC")
    # kl: timestamps contínuos
    kl = pd.DataFrame({
        "symbol": sym,
        "t": idx_horario,
        "close": 100.0 + rng.normal(0, 0.5, n).cumsum(),
    })
    # lsr: tira 6 buckets consecutivos (índices 100..105) + gaps irregulares (120, 145)
    drop_idx = set(range(100, 106)) | {120, 145}
    keep = [i for i in range(n) if i not in drop_idx]
    lsr = pd.DataFrame({
        "symbol": sym,
        "t": idx_horario[keep],
        "top": 1.0 + rng.standard_normal(len(keep)).cumsum() / np.sqrt(np.arange(1, len(keep) + 1)),
        "glob": 1.0 + 0.5 * rng.standard_normal(len(keep)).cumsum() / np.sqrt(np.arange(1, len(keep) + 1)),
    })

    # Roda per_symbol_panel
    panel_full = h4.per_symbol_panel(sym, kl, lsr)
    assert panel_full is not None
    assert len(panel_full) == n, "asfreq('1h') deve produzir grade contínua"

    # Anti-lookahead: features computadas com cauda futura truncada devem coincidir
    # com as features no passado, ATÉ os pontos onde o warm-up de janelas permite.
    cut = 250
    kl_trunc = kl.iloc[:cut].copy()
    lsr_trunc = lsr[lsr["t"] < idx_horario[cut]].copy()
    panel_trunc = h4.per_symbol_panel(sym, kl_trunc, lsr_trunc)
    assert panel_trunc is not None

    common = panel_full.index[:cut]
    for col in ("top_z", "vel_global", "trap_score"):
        full_v = panel_full.loc[common, col].values
        trunc_v = panel_trunc[col].values
        mask = np.isfinite(full_v) & np.isfinite(trunc_v)
        if mask.sum() == 0:
            continue
        assert np.allclose(full_v[mask], trunc_v[mask]), (
            f"{col}: truncar futuro mudou valor no passado — vazamento via ffill"
        )

    # Verificação extra: shift(1) preservado mesmo após ffill — features em t
    # não dependem de top/glob[t] (devem usar t-1 pelo lag explícito).
    # Substituir top[t] e glob[t] por NaN não deve alterar features em t-1.
    panel_alt = panel_full.copy()
    test_t = 200
    panel_alt.loc[panel_alt.index[test_t], ["top", "glob"]] = np.nan
    # Recomputar features a partir do panel_alt
    feats_alt = h4.compute_features(panel_alt["close"], panel_alt["top"], panel_alt["glob"])
    # Em t-1=199, features não dependem de t=200 (regra do shift(1) + rolling trailing)
    for col in ("top_z", "vel_global"):
        v_orig = panel_full[col].iloc[test_t - 1]
        v_alt = feats_alt[col].iloc[test_t - 1]
        if pd.notna(v_orig) and pd.notna(v_alt):
            assert v_orig == v_alt, (
                f"{col}[t-1] mudou ao apagar top/glob[t] — lag(1) não está protegendo"
            )


# ----------------------------------------------------------------------
# (11) Veredito v1.1: delta como gate (cenários de composição)
# ----------------------------------------------------------------------
def _build_run_result(per_entity_results: dict) -> dict:
    """Replica a composição de veredito do run() (PREREG v1.1: α=0.05 sem Bonferroni,
    classe interpretativa GO_marginal:vol_dominant) sem rodar pipeline real."""
    from lab_harness import JudgmentUnit, assemble_verdict
    cfg = h4.CONFIG
    max_p = cfg["alpha_per_test"]  # 0.05, sem Bonferroni (conjunção)

    per_entity_reversal = {}
    per_entity_delta = {}
    per_entity_continuation = {}
    per_entity_lifts_pp = {}
    for sym, r in per_entity_results.items():
        if r.get("status") == "tested":
            per_entity_reversal[sym] = {"gap_bps": r["reversal"]["gap_bps"],
                                        "p": r["reversal"]["p"]}
            per_entity_delta[sym] = {"gap_bps": r["delta"]["gap_bps"],
                                     "p": r["delta"]["p"]}
            per_entity_continuation[sym] = {"gap_bps": r["continuation"]["gap_bps"],
                                            "p": r["continuation"]["p"]}
            per_entity_lifts_pp[sym] = {
                "reversal_lift_pp": r["reversal"]["gap_bps"] * 100.0,
                "continuation_lift_pp": r["continuation"]["gap_bps"] * 100.0,
                "delta_lift_pp": r["delta"]["gap_bps"] * 100.0,
            }
        else:
            per_entity_reversal[sym] = {"gap_bps": None, "p": None}
            per_entity_delta[sym] = {"gap_bps": None, "p": None}
            per_entity_continuation[sym] = {"gap_bps": None, "p": None}

    v_rev = assemble_verdict(per_entity_reversal, None, JudgmentUnit.PER_ENTITY,
                             min_gap_bps=cfg["min_gap_proportion"],
                             max_p=max_p, require_entities=2, direction="pos")
    v_delta = assemble_verdict(per_entity_delta, None, JudgmentUnit.PER_ENTITY,
                               min_gap_bps=0.0,
                               max_p=max_p, require_entities=2, direction="pos")
    v_con = assemble_verdict(per_entity_continuation, None, JudgmentUnit.PER_ENTITY,
                             min_gap_bps=cfg["min_gap_proportion"],
                             max_p=max_p, require_entities=2, direction="pos")

    passou = bool(v_rev["passou"] and v_delta["passou"])
    # Classe interpretativa
    classe = None
    delta_strong = True
    if passou:
        ratio_threshold = cfg["go_marginal_delta_ratio"]
        for sym, lifts in per_entity_lifts_pp.items():
            if lifts["reversal_lift_pp"] > 0:
                if lifts["delta_lift_pp"] / lifts["reversal_lift_pp"] < ratio_threshold:
                    delta_strong = False
                    break
            else:
                delta_strong = False
                break
        if not delta_strong:
            classe = "GO_marginal:vol_dominant"
        elif v_con["passou"]:
            classe = "GO_with_continuation_flag"
        else:
            classe = "GO"

    return {"v_rev": v_rev, "v_delta": v_delta, "v_con": v_con,
            "passou": passou, "classe": classe,
            "per_entity_lifts_pp": per_entity_lifts_pp,
            "delta_strong": delta_strong}


def test_veredito_GO_rev_passa_delta_passa_con_nao():
    """Cenário canônico GO: reversal passa, delta significativo, continuation não passa."""
    per = {
        "BTCUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.15, "p": 0.001},
                    "continuation": {"gap_bps": 0.03, "p": 0.20},
                    "delta": {"gap_bps": 0.12, "p": 0.002}},
        "ETHUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.13, "p": 0.005},
                    "continuation": {"gap_bps": 0.02, "p": 0.30},
                    "delta": {"gap_bps": 0.11, "p": 0.008}},
    }
    out = _build_run_result(per)
    assert out["passou"] is True
    assert out["v_rev"]["passou"] is True
    assert out["v_delta"]["passou"] is True
    assert out["v_con"]["passou"] is False  # flag descritivo


def test_veredito_vol_confounded_rev_passa_delta_nao():
    """Cenário vol-confound: reversal passa MAS delta não-significativo. NÃO é GO."""
    per = {
        "BTCUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.15, "p": 0.001},
                    "continuation": {"gap_bps": 0.14, "p": 0.002},  # passa também
                    "delta": {"gap_bps": 0.01, "p": 0.40}},          # mas delta morre
        "ETHUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.13, "p": 0.005},
                    "continuation": {"gap_bps": 0.12, "p": 0.008},
                    "delta": {"gap_bps": 0.01, "p": 0.42}},
    }
    out = _build_run_result(per)
    assert out["passou"] is False, (
        "reversal passa mas delta não-significativo ⇒ NÃO é GO (vol-confound)"
    )
    assert out["v_rev"]["passou"] is True
    assert out["v_delta"]["passou"] is False
    assert out["v_con"]["passou"] is True


def test_veredito_inconclusivo_uma_entidade_falha():
    """require_entities=2: se uma entidade é inconclusiva, sem GO."""
    per = {
        "BTCUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.15, "p": 0.001},
                    "continuation": {"gap_bps": 0.03, "p": 0.20},
                    "delta": {"gap_bps": 0.12, "p": 0.002}},
        "ETHUSDT": {"status": "inconclusivo", "motivo": "n<30"},
    }
    out = _build_run_result(per)
    assert out["passou"] is False
    # reversal passa só pra BTC (1/2 entidades) → require=2 → NO-GO
    assert out["v_rev"]["n_pass"] == 1
    assert out["v_delta"]["n_pass"] == 1


def test_veredito_GO_with_flag_se_delta_passa_e_con_tambem():
    """Caso raro: delta forte E continuation passa o bar próprio. Ainda é GO,
    com flag descritivo (motivo do run() acresce a observação)."""
    per = {
        "BTCUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.20, "p": 0.0005},
                    "continuation": {"gap_bps": 0.12, "p": 0.01},  # passa flag
                    "delta": {"gap_bps": 0.08, "p": 0.01}},         # delta passa
        "ETHUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.18, "p": 0.001},
                    "continuation": {"gap_bps": 0.11, "p": 0.02},
                    "delta": {"gap_bps": 0.07, "p": 0.015}},
    }
    out = _build_run_result(per)
    # delta gap=0.08 — passa o piso 0 (direction="pos") e p<0.025
    assert out["passou"] is True, "delta>0 sig E rev passa ⇒ GO (com flag descritivo)"
    assert out["v_con"]["passou"] is True  # flag


def test_continuation_e_reversal_usam_parametros_identicos():
    """Cravado PREREG v1.1 §6.3: continuation_labeler usa k/N/σ/M idênticos ao
    reversal_labeler para a comparação ser apples-to-apples."""
    # Inspect: label_continuations e label_reversals devem aceitar mesmos kwargs
    import inspect
    from reversal_labeler import label_reversals
    sig_rev = inspect.signature(label_reversals)
    sig_con = inspect.signature(h4.label_continuations)
    # Argumentos críticos do labeler
    for arg in ("k", "N", "vol_window", "M"):
        assert arg in sig_rev.parameters, f"label_reversals deveria ter {arg}"
        assert arg in sig_con.parameters, f"label_continuations deveria ter {arg}"


# ----------------------------------------------------------------------
# (12) Alpha=0.05 sem Bonferroni (PREREG v1.1 §8 — conjunção auto-conservadora)
# ----------------------------------------------------------------------
def test_alpha_per_test_eh_005_sem_bonferroni():
    """PREREG v1.1: GO é conjunção (rev_BTC ∧ rev_ETH ∧ delta_BTC ∧ delta_ETH);
    require=2 já controla FWER ≤ α². Bonferroni só protege união."""
    assert h4.CONFIG["alpha_per_test"] == 0.05, (
        "α=0.05 POR TESTE (sem Bonferroni 0.025); conjunção é auto-conservadora"
    )
    assert "alpha_family" not in h4.CONFIG, (
        "campo legado 'alpha_family' deveria ter sido renomeado para 'alpha_per_test'"
    )


def test_caso_borderline_p_002_passa_com_alpha_005_mas_falharia_com_bonferroni_025():
    """Demonstração do impacto: p=0.02 passa α=0.05 mas falha α/2=0.025.
    Sob conjunção, recuperar p=0.02 é poder, não falso-positivo."""
    per = {
        "BTCUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.13, "p": 0.02},   # entre 0.025 e 0.05
                    "continuation": {"gap_bps": 0.03, "p": 0.30},
                    "delta": {"gap_bps": 0.09, "p": 0.02}},      # idem
        "ETHUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.13, "p": 0.02},
                    "continuation": {"gap_bps": 0.03, "p": 0.30},
                    "delta": {"gap_bps": 0.09, "p": 0.02}},
    }
    out = _build_run_result(per)
    assert out["passou"] is True, (
        "p=0.02 em conjunção 2×2 deveria passar com α=0.05; Bonferroni 0.025 "
        "mataria sinal real sob H0 com FWER << 0.05"
    )


# ----------------------------------------------------------------------
# (13) Classe interpretativa GO_marginal:vol_dominant (PREREG v1.1 §8)
# ----------------------------------------------------------------------
def test_GO_limpo_se_delta_lift_alto_em_ambas_entidades():
    """delta_lift >= 0.5 × reversal_lift em TODAS entidades → GO limpo."""
    per = {
        "BTCUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.12, "p": 0.001},
                    "continuation": {"gap_bps": 0.03, "p": 0.20},
                    "delta": {"gap_bps": 0.09, "p": 0.002}},     # 0.09/0.12 = 0.75 >= 0.5
        "ETHUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.14, "p": 0.001},
                    "continuation": {"gap_bps": 0.04, "p": 0.15},
                    "delta": {"gap_bps": 0.10, "p": 0.003}},     # 0.10/0.14 = 0.71 >= 0.5
    }
    out = _build_run_result(per)
    assert out["passou"] is True
    assert out["delta_strong"] is True
    assert out["classe"] == "GO", f"esperava GO limpo, obteve {out['classe']}"


def test_GO_marginal_vol_dominant_se_delta_lift_baixo_em_uma_entidade():
    """delta_lift < 0.5 × reversal_lift em ≥1 entidade → GO_marginal:vol_dominant.
    Passa estatística mas é sinalizado: componente de manipulação fino vs vol."""
    per = {
        "BTCUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.14, "p": 0.001},
                    "continuation": {"gap_bps": 0.11, "p": 0.005},
                    "delta": {"gap_bps": 0.03, "p": 0.04}},      # 0.03/0.14 = 0.21 < 0.5
        "ETHUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.13, "p": 0.002},
                    "continuation": {"gap_bps": 0.04, "p": 0.15},
                    "delta": {"gap_bps": 0.09, "p": 0.003}},     # 0.09/0.13 = 0.69 >= 0.5
    }
    out = _build_run_result(per)
    assert out["passou"] is True, "rev e delta passam — gate satisfeito"
    assert out["delta_strong"] is False, "BTC viola ratio 0.5 → marginal"
    assert out["classe"] == "GO_marginal:vol_dominant"


def test_GO_marginal_NAO_dispara_se_passou_eh_false():
    """Classe interpretativa só se aplica se passou=True."""
    per = {
        "BTCUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.05, "p": 0.20},    # rev não passa
                    "continuation": {"gap_bps": 0.02, "p": 0.30},
                    "delta": {"gap_bps": 0.03, "p": 0.20}},
        "ETHUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.05, "p": 0.20},
                    "continuation": {"gap_bps": 0.02, "p": 0.30},
                    "delta": {"gap_bps": 0.03, "p": 0.20}},
    }
    out = _build_run_result(per)
    assert out["passou"] is False
    assert out["classe"] is None, (
        f"classe interpretativa não deveria disparar se !passou; "
        f"obteve {out['classe']}"
    )


def test_lifts_pp_reportados_corretamente():
    """Lifts em pp = gap_bps * 100 (gap_bps é proporção)."""
    per = {
        "BTCUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.155, "p": 0.001},
                    "continuation": {"gap_bps": 0.031, "p": 0.20},
                    "delta": {"gap_bps": 0.124, "p": 0.002}},
        "ETHUSDT": {"status": "tested",
                    "reversal": {"gap_bps": 0.130, "p": 0.005},
                    "continuation": {"gap_bps": 0.020, "p": 0.30},
                    "delta": {"gap_bps": 0.110, "p": 0.008}},
    }
    out = _build_run_result(per)
    lifts = out["per_entity_lifts_pp"]
    assert lifts["BTCUSDT"]["reversal_lift_pp"] == pytest.approx(15.5)
    assert lifts["BTCUSDT"]["continuation_lift_pp"] == pytest.approx(3.1)
    assert lifts["BTCUSDT"]["delta_lift_pp"] == pytest.approx(12.4)
    assert lifts["ETHUSDT"]["delta_lift_pp"] == pytest.approx(11.0)


if __name__ == "__main__":
    import subprocess
    r = subprocess.run([sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"])
    sys.exit(r.returncode)
