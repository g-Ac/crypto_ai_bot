"""Testes do lab_harness.

Cobertura conforme spec:
  1. spearman ~1 monotônico, ~0 em ruído
  2. null_sanity centrado, sanity_null_ok
  3. sinal plantado detectado por perm_gap (p<0.01); ruído não (p>0.05)
  4. perm_gap_strat direcional (tail="less") detecta sinal negativo; ruído não
  5. assemble_verdict reproduz cenário EXP-011 (AGGREGATE NO-GO, PER_ENTITY req=1 GO)
  6. Equivalência bit-exact: perm_gap_strat ≡ h1.perm_strat, perm_gap ≡ h3.perm_pvalue
     (mesma seed/input, tolerância 1e-9; sem tocar nos runners H1/H3 lacrados)
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

# lab_harness vive na raiz do projeto (/home/pi/crypto_ai_bot)
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lab_harness import (  # noqa: E402
    JudgmentUnit,
    __version__,
    assemble_verdict,
    decile_gap,
    null_sanity,
    perm_gap,
    perm_gap_delta_strat,
    perm_gap_strat,
    spearman,
)


# ----------------------------------------------------------------------
# (1) spearman: monotônico e ruído
# ----------------------------------------------------------------------
def test_spearman_monotonico_vs_ruido():
    x = np.arange(100, dtype=float)
    y_mono = 3.0 * x + 5.0  # monotônica positiva perfeita
    assert spearman(x, y_mono) == pytest.approx(1.0, abs=1e-12)

    y_anti = -2.0 * x + 1.0  # monotônica negativa perfeita
    assert spearman(x, y_anti) == pytest.approx(-1.0, abs=1e-12)

    rng = np.random.default_rng(0)
    y_noise = rng.normal(size=100)
    rho_noise = spearman(x, y_noise)
    assert abs(rho_noise) < 0.25, f"spearman em ruído deveria ser ~0, deu {rho_noise:.3f}"


def test_spearman_n_menor_que_5_retorna_nan():
    assert np.isnan(spearman([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]))


# ----------------------------------------------------------------------
# (2) null_sanity: nulo centrado, sanity_null_ok
# ----------------------------------------------------------------------
def test_null_sanity_centrado_e_sanity_null_ok():
    rng = np.random.default_rng(42)
    n = 400
    feature = rng.normal(size=n)
    outcome = rng.normal(size=n)  # ruído puro, sem relação

    diag = null_sanity(feature, outcome, frac=0.10, n_perm=2000, rng=rng)

    # nulo deve centrar perto de zero (permutação global de ruído)
    assert diag["bias_within_3sigma"], (
        f"null_mean={diag['null_mean']:.4g} fora de ±{diag['bias_3sigma_tol']:.4g}"
    )
    # sob ruído puro, sanity-null (shuffle global) NÃO pode dar significância
    assert diag["sanity_null_ok"], f"sanity_null_pvalue={diag['sanity_null_pvalue']}"


def test_null_sanity_estratificado_tambem_centra():
    """Propriedade estatística (não pontual): sob ruído com K seeds independentes,
    bias_within_3sigma e sanity_null_ok devem disparar na MAIORIA das vezes.

    Um sanity-null individual segue distribuição quase-uniforme em [0,1] sob H0,
    então com threshold p>0.05 espera-se ~95% de pass-rate. Teste com seed única
    seria flaky por design — testamos a propriedade agregada.
    """
    K = 10
    bias_passes = 0
    sanity_passes = 0
    for seed in range(K):
        rng = np.random.default_rng(seed)
        n = 600
        feature = rng.normal(size=n)
        outcome = rng.normal(size=n)
        stratum = rng.choice(["A", "B", "C"], size=n)
        diag = null_sanity(feature, outcome, frac=0.10, n_perm=2000, rng=rng, stratum=stratum)
        if diag["bias_within_3sigma"]:
            bias_passes += 1
        if diag["sanity_null_ok"]:
            sanity_passes += 1
    # bias_within_3sigma é praticamente determinístico sob ruído (tolera 3σ_est)
    assert bias_passes >= K - 1, f"bias passou {bias_passes}/{K}, esperado >= {K-1}"
    # sanity_null_ok é estatístico: ~95% esperado, exigimos >=80% (conservador)
    assert sanity_passes >= int(0.80 * K), (
        f"sanity_null_ok passou {sanity_passes}/{K}, esperado >= {int(0.80*K)} "
        f"(80% conservador vs ~95% teórico)"
    )


# ----------------------------------------------------------------------
# (3) sinal plantado vs ruído (perm_gap global)
# ----------------------------------------------------------------------
def test_perm_gap_detecta_sinal_plantado():
    rng = np.random.default_rng(123)
    n = 500
    feature = rng.normal(size=n)
    # outcome carrega sinal: alto feature → outcome alto
    outcome = 0.4 * feature + rng.normal(scale=0.3, size=n)

    obs, p, null = perm_gap(feature, outcome, frac=0.10, n_perm=2000,
                            tail="greater", rng=rng)
    assert obs > 0, f"sinal plantado deveria dar obs>0, deu {obs:.4f}"
    assert p < 0.01, f"sinal forte deveria dar p<0.01, deu {p:.4f}"
    assert null is not None and len(null) == 2000


def test_perm_gap_nao_detecta_ruido():
    rng = np.random.default_rng(456)
    n = 500
    feature = rng.normal(size=n)
    outcome = rng.normal(size=n)  # sem relação

    obs, p, _ = perm_gap(feature, outcome, frac=0.10, n_perm=2000,
                         tail="two", rng=rng)
    assert p > 0.05, f"ruído puro não deveria dar p<0.05, deu {p:.4f}"


def test_perm_gap_n_insuficiente_retorna_nan():
    rng = np.random.default_rng(0)
    feature = np.arange(10, dtype=float)
    outcome = np.arange(10, dtype=float)
    obs, p, null = perm_gap(feature, outcome, frac=0.10, n_perm=100,
                            tail="two", rng=rng)
    assert np.isnan(obs) and np.isnan(p) and null is None


# ----------------------------------------------------------------------
# (4) perm_gap_strat direcional
# ----------------------------------------------------------------------
def test_perm_gap_strat_direcional_detecta_sinal_negativo():
    rng = np.random.default_rng(2026)
    n = 600
    stratum = rng.choice(["A", "B", "C"], size=n)
    # baseline DIFERENTE por estrato (composição que justifica estratificação)
    base = np.where(stratum == "A", +0.5, np.where(stratum == "B", 0.0, -0.5))
    feature = rng.normal(size=n)
    # sinal NEGATIVO: alto feature → outcome baixo
    outcome = base - 0.5 * feature + rng.normal(scale=0.3, size=n)

    obs, p, _ = perm_gap_strat(feature, outcome, stratum, frac=0.10,
                               n_perm=2000, tail="less", rng=rng)
    assert obs < 0, f"sinal negativo plantado deveria dar obs<0, deu {obs:.4f}"
    assert p < 0.01, f"detecção direcional deveria dar p<0.01, deu {p:.4f}"


def test_perm_gap_strat_ruido_nao_detecta_nem_estratificado():
    rng = np.random.default_rng(2027)
    n = 600
    stratum = rng.choice(["A", "B", "C"], size=n)
    base = np.where(stratum == "A", +0.5, np.where(stratum == "B", 0.0, -0.5))
    feature = rng.normal(size=n)
    outcome = base + rng.normal(scale=0.3, size=n)  # SEM relação com feature

    obs, p, _ = perm_gap_strat(feature, outcome, stratum, frac=0.10,
                               n_perm=2000, tail="two", rng=rng)
    assert p > 0.05, (
        f"ruído sob estratificação não deveria dar p<0.05, deu {p:.4f} (obs={obs:.4f})"
    )


def test_perm_gap_tail_invalida_erra():
    rng = np.random.default_rng(0)
    feature = np.arange(50, dtype=float)
    outcome = np.arange(50, dtype=float)
    with pytest.raises(ValueError, match="tail deve ser"):
        perm_gap(feature, outcome, frac=0.10, n_perm=10, tail="bilateral", rng=rng)


# ----------------------------------------------------------------------
# (5) assemble_verdict: cenário EXP-011
# ----------------------------------------------------------------------
def _exp011_scenario():
    """Replica os números reais do veredito EXP-011 (2026-05-29)."""
    per_entity = {
        "BTCUSDT": {"gap_bps": -70.2, "p": 0.0013},
        "ETHUSDT": {"gap_bps": -11.3, "p": 0.30},
    }
    aggregate = {"gap_bps": -46.1, "p": 0.0003}
    return per_entity, aggregate


def test_assemble_verdict_exp011_aggregate_nogo():
    per_entity, aggregate = _exp011_scenario()
    v = assemble_verdict(per_entity, aggregate, JudgmentUnit.AGGREGATE,
                         min_gap_bps=50.0, max_p=0.05)
    assert v["passou"] is False, "agregado |gap|=46.1 < 50 deveria falhar"
    assert v["unidade"] == "AGGREGATE"
    assert "gap" in v["motivo"].lower()


def test_assemble_verdict_exp011_per_entity_require1_go():
    per_entity, aggregate = _exp011_scenario()
    v = assemble_verdict(per_entity, aggregate, JudgmentUnit.PER_ENTITY,
                         min_gap_bps=50.0, max_p=0.05, require_entities=1)
    assert v["passou"] is True, "BTC sozinho satisfaz |gap|>=50 e p<0.05 → GO com req=1"
    assert v["unidade"] == "PER_ENTITY"
    assert v["n_pass"] == 1
    assert v["por_entidade"]["BTCUSDT"]["passou"] is True
    assert v["por_entidade"]["ETHUSDT"]["passou"] is False


def test_assemble_verdict_exp011_per_entity_require2_nogo():
    per_entity, aggregate = _exp011_scenario()
    v = assemble_verdict(per_entity, aggregate, JudgmentUnit.PER_ENTITY,
                         min_gap_bps=50.0, max_p=0.05, require_entities=2)
    assert v["passou"] is False, "ETH não passa → req=2 falha"
    assert v["n_pass"] == 1


def test_assemble_verdict_require_invalido_falha_estruturado():
    per_entity, _ = _exp011_scenario()
    v = assemble_verdict(per_entity, None, JudgmentUnit.PER_ENTITY,
                         min_gap_bps=50.0, max_p=0.05, require_entities=5)
    assert v["passou"] is False
    assert "require_entities" in v["motivo"]


# ----------------------------------------------------------------------
# (5b) direction pré-comprometida (lab_harness 1.1.0)
# ----------------------------------------------------------------------
def test_assemble_verdict_direction_pos_aceita_positivo_rejeita_negativo():
    """Pedido explícito da spec 1.1.0: direção 'pos' filtra por sinal E magnitude."""
    per_entity = {
        "A_pos": {"gap_bps": +60.0, "p": 0.01},  # passa com direction='pos'
        "B_neg": {"gap_bps": -60.0, "p": 0.01},  # NÃO passa com direction='pos' (sinal errado)
    }
    v = assemble_verdict(per_entity, None, JudgmentUnit.PER_ENTITY,
                         min_gap_bps=50.0, max_p=0.05, require_entities=1,
                         direction="pos")
    assert v["por_entidade"]["A_pos"]["passou"] is True
    assert v["por_entidade"]["B_neg"]["passou"] is False, (
        "magnitude |60|>=50 mas direção contrária → não pode passar"
    )
    assert v["n_pass"] == 1


def test_assemble_verdict_direction_neg_simetrico():
    per_entity = {
        "A_pos": {"gap_bps": +60.0, "p": 0.01},  # NÃO passa com direction='neg'
        "B_neg": {"gap_bps": -60.0, "p": 0.01},  # passa
    }
    v = assemble_verdict(per_entity, None, JudgmentUnit.PER_ENTITY,
                         min_gap_bps=50.0, max_p=0.05, require_entities=1,
                         direction="neg")
    assert v["por_entidade"]["A_pos"]["passou"] is False
    assert v["por_entidade"]["B_neg"]["passou"] is True


def test_assemble_verdict_direction_consistencia_automatica_require2():
    """Lição EXP-011: direction pré-comprometida + require>=2 garante consistência
    de sinal entre entidades automaticamente (sem cláusula adicional)."""
    per_entity = {
        "BTC": {"gap_bps": -70.0, "p": 0.001},   # negativo, significativo
        "ETH": {"gap_bps": +65.0, "p": 0.002},   # positivo, significativo → direção OPOSTA
    }
    # Ambos estatisticamente significativos, mas em direções opostas.
    # Com direction="neg" require=2, só BTC conta → NO-GO.
    v_neg = assemble_verdict(per_entity, None, JudgmentUnit.PER_ENTITY,
                             min_gap_bps=50.0, max_p=0.05,
                             require_entities=2, direction="neg")
    assert v_neg["passou"] is False
    assert v_neg["n_pass"] == 1, "só BTC está na direção 'neg'"

    # Comparação de regressão: SEM direction, ambos passam (|gap|>=50 e p<0.05)
    # → require=2 GO mesmo com sinais opostos. Demonstra o problema que direction resolve.
    v_none = assemble_verdict(per_entity, None, JudgmentUnit.PER_ENTITY,
                              min_gap_bps=50.0, max_p=0.05,
                              require_entities=2, direction=None)
    assert v_none["passou"] is True
    assert v_none["n_pass"] == 2, (
        "sem direction, BTC e ETH em direções opostas contariam juntos — "
        "demonstra por que pré-registros direcionais devem usar direction='pos'/'neg'"
    )


def test_assemble_verdict_direction_aggregate_tambem_funciona():
    aggregate_pos = {"gap_bps": +60.0, "p": 0.001}
    aggregate_neg = {"gap_bps": -60.0, "p": 0.001}
    v_pos_ok = assemble_verdict(None, aggregate_pos, JudgmentUnit.AGGREGATE,
                                min_gap_bps=50.0, max_p=0.05, direction="pos")
    v_pos_no = assemble_verdict(None, aggregate_neg, JudgmentUnit.AGGREGATE,
                                min_gap_bps=50.0, max_p=0.05, direction="pos")
    assert v_pos_ok["passou"] is True
    assert v_pos_no["passou"] is False
    assert "direção" in v_pos_no["motivo"]


def test_assemble_verdict_direction_invalida_erra():
    per_entity = {"X": {"gap_bps": +60.0, "p": 0.01}}
    with pytest.raises(ValueError, match="direction deve ser"):
        assemble_verdict(per_entity, None, JudgmentUnit.PER_ENTITY,
                         min_gap_bps=50.0, max_p=0.05, direction="up")


def test_assemble_verdict_exp011_regressao_intacta_com_direction_none():
    """Garante que o cenário EXP-011 cravado em 1.0.0 segue idêntico com direction=None
    (compatibilidade da default). Spec 1.1.0: 'mantém o teste de regressão intacto'."""
    per_entity, aggregate = _exp011_scenario()
    v_agg = assemble_verdict(per_entity, aggregate, JudgmentUnit.AGGREGATE,
                             min_gap_bps=50.0, max_p=0.05)  # direction=None implícito
    assert v_agg["passou"] is False  # |46.1|<50

    v_per = assemble_verdict(per_entity, aggregate, JudgmentUnit.PER_ENTITY,
                             min_gap_bps=50.0, max_p=0.05, require_entities=1)
    assert v_per["passou"] is True  # BTC |70|>=50
    assert v_per["n_pass"] == 1


# ----------------------------------------------------------------------
# (6) Equivalência bit-exact com h1.perm_strat e h3.perm_pvalue
# ----------------------------------------------------------------------
def _import_h1_h3_modules():
    """Carrega h1 e h3 dos pre-registros sem modificá-los."""
    pre_reg = os.path.abspath(os.path.join(_REPO_ROOT, "docs", "pre_registros"))
    if pre_reg not in sys.path:
        sys.path.insert(0, pre_reg)
    import h1_funding_conditioning as h1_mod  # noqa: WPS433
    import h3_lsr_vanilla as h3_mod  # noqa: WPS433
    return h1_mod, h3_mod


def test_equivalencia_perm_gap_strat_vs_h1_perm_strat():
    """perm_gap_strat(tail='less') deve reproduzir h1.perm_strat bit-exact."""
    h1, _ = _import_h1_h3_modules()

    seed = 20260528
    rng_local = np.random.default_rng(seed)
    n = 300
    feature = rng_local.normal(size=n)
    stratum = rng_local.choice(["TRENDING", "WEAK_TREND"], size=n)
    outcome = -0.4 * feature + rng_local.normal(scale=0.5, size=n)
    n_perm = 500

    # h1.perm_strat usa h1.RNG global — reset com seed conhecida
    h1.RNG = np.random.default_rng(seed)
    obs_h1, p_h1 = h1.perm_strat(feature, outcome, stratum,
                                 frac=0.10, n_perm=n_perm)

    # perm_gap_strat recebe rng explícito com mesma seed
    rng_eq = np.random.default_rng(seed)
    obs_lh, p_lh, _ = perm_gap_strat(feature, outcome, stratum,
                                     frac=0.10, n_perm=n_perm,
                                     tail="less", rng=rng_eq)

    assert obs_h1 == pytest.approx(obs_lh, abs=1e-9), (
        f"obs divergiu: h1={obs_h1} vs lab_harness={obs_lh}"
    )
    assert p_h1 == pytest.approx(p_lh, abs=1e-9), (
        f"p divergiu: h1={p_h1} vs lab_harness={p_lh}"
    )


def test_equivalencia_perm_gap_vs_h3_perm_pvalue():
    """perm_gap(tail='two') deve reproduzir h3.perm_pvalue bit-exact."""
    _, h3 = _import_h1_h3_modules()

    seed = 20260528
    rng_local = np.random.default_rng(seed)
    n = 300
    feature = rng_local.normal(size=n)
    outcome = 0.3 * feature + rng_local.normal(scale=0.5, size=n)
    n_perm = 500

    h3.RNG = np.random.default_rng(seed)
    obs_h3, p_h3 = h3.perm_pvalue(feature, outcome, frac=0.10, n_perm=n_perm)

    rng_eq = np.random.default_rng(seed)
    obs_lh, p_lh, _ = perm_gap(feature, outcome,
                               frac=0.10, n_perm=n_perm,
                               tail="two", rng=rng_eq)

    assert obs_h3 == pytest.approx(obs_lh, abs=1e-9), (
        f"obs divergiu: h3={obs_h3} vs lab_harness={obs_lh}"
    )
    assert p_h3 == pytest.approx(p_lh, abs=1e-9), (
        f"p divergiu: h3={p_h3} vs lab_harness={p_lh}"
    )


# ----------------------------------------------------------------------
# meta
# ----------------------------------------------------------------------
def test_versao_declarada():
    assert __version__ == "1.2.0"


# ----------------------------------------------------------------------
# (7) perm_gap_delta_strat — teste pareado de assimetria (lab_harness 1.2.0)
# ----------------------------------------------------------------------
def test_perm_gap_delta_strat_zero_se_labels_iguais():
    """Se label_a == label_b, delta observado é 0 e null centrado em 0."""
    rng = np.random.default_rng(11)
    n = 400
    feature = rng.normal(size=n)
    label_same = (rng.normal(size=n) > 0).astype(float)
    stratum = rng.choice(["A", "B"], size=n)

    obs, p, null = perm_gap_delta_strat(feature, label_same, label_same, stratum,
                                        frac=0.10, n_perm=1000, tail="two", rng=rng)
    assert obs == 0.0, f"delta com labels iguais deve ser exatamente 0, deu {obs}"
    assert (null == 0.0).all(), "null com labels iguais deve ser sempre 0"
    # p two-sided: 100% das amostras são >= 0 em magnitude, então p=1.0
    assert p == 1.0


def test_perm_gap_delta_strat_detecta_assimetria_plantada():
    """Plantamos: feature prediz label_a, mas NÃO label_b. Delta deve ser
    significativamente >0 com tail='greater'."""
    rng = np.random.default_rng(22)
    n = 600
    feature = rng.normal(size=n)
    # label_a: depende de feature (alto feature → alto a)
    label_a = (feature + 0.3 * rng.normal(size=n) > 0).astype(float)
    # label_b: independente de feature (puro ruído)
    label_b = (rng.normal(size=n) > 0).astype(float)
    stratum = rng.choice(["A", "B", "C"], size=n)

    obs, p, _ = perm_gap_delta_strat(feature, label_a, label_b, stratum,
                                     frac=0.10, n_perm=2000, tail="greater", rng=rng)
    assert obs > 0, f"assimetria plantada → obs>0, deu {obs:.4f}"
    assert p < 0.01, f"assimetria forte → p<0.01, deu {p:.4f}"


def test_perm_gap_delta_strat_nao_detecta_dois_correlacionados_iguais():
    """Plantamos: ambos labels correlacionam IGUALMENTE com feature. Delta ≈ 0,
    p>0.05. Simula o caso vol-confound: trap_score afeta rev E con igualmente."""
    rng = np.random.default_rng(33)
    n = 800
    feature = rng.normal(size=n)
    # AMBOS labels correlacionados com feature, mesma força
    noise_a = 0.4 * rng.normal(size=n)
    noise_b = 0.4 * rng.normal(size=n)
    label_a = (feature + noise_a > 0).astype(float)
    label_b = (feature + noise_b > 0).astype(float)
    stratum = rng.choice(["A", "B"], size=n)

    obs, p, _ = perm_gap_delta_strat(feature, label_a, label_b, stratum,
                                     frac=0.10, n_perm=2000, tail="two", rng=rng)
    # Tolerância: ambos respondem igualmente, mas há ruído diferente; delta deve
    # ser pequeno e não-significativo
    assert abs(obs) < 0.15, (
        f"labels igualmente correlacionados → delta pequeno, deu {obs:.4f}"
    )
    assert p > 0.05, (
        f"sob simetria vol-confound, delta não deveria ser significativo; p={p:.4f}"
    )


def test_perm_gap_delta_strat_nan_se_amostra_pequena():
    rng = np.random.default_rng(0)
    feature = np.arange(10, dtype=float)
    label_a = np.zeros(10)
    label_b = np.ones(10)
    stratum = np.zeros(10)
    obs, p, null = perm_gap_delta_strat(feature, label_a, label_b, stratum,
                                        frac=0.10, n_perm=100, tail="two", rng=rng)
    assert np.isnan(obs) and np.isnan(p) and null is None
