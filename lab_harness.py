"""lab_harness — apparatus estatístico compartilhado entre runners de experimentos.

Versão: 1.0.0
Dependências: numpy, pandas. Sem scipy.
Determinismo: todas as funções com permutação aceitam `rng` (np.random.Generator) explícito;
não há estado global.

API pública:
- rankdata(a) -> ranks (média em empates)
- spearman(x, y) -> float (NaN se n<5)
- decile_gap(feature, outcome, frac=0.10) -> float (top frac − bottom frac; NaN se n<20)
- perm_gap(feature, outcome, frac, n_perm, tail, rng) -> (obs, p, null)
- perm_gap_strat(feature, outcome, stratum, frac, n_perm, tail, rng) -> (obs, p, null)
- null_sanity(feature, outcome, *, frac, n_perm, rng, stratum=None) -> dict de diagnóstico
- JudgmentUnit (Enum: AGGREGATE | PER_ENTITY)
- assemble_verdict(per_entity_stats, aggregate_stat, unit, *, min_gap_bps, max_p,
                   require_entities=None) -> dict {passou, unidade, motivo, ...}

Convenções:
- `tail` ∈ {"two", "less", "greater"}. "less" ↔ H1 testa obs<0; "greater" ↔ obs>0.
- Em `perm_gap_strat`, embaralhamento é DENTRO de cada estrato; a estatística é
  `decile_gap` no pool inteiro (decis ranqueados sobre todos os pontos).
- `assemble_verdict` NÃO escolhe a unidade de julgamento — recebe; o pré-registro
  do experimento é quem pré-compromete. Ver docstring de JudgmentUnit.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd  # noqa: F401 — exposto pra runners que queiram tipar inputs

__version__ = "1.2.0"

__all__ = [
    "__version__",
    "rankdata",
    "spearman",
    "decile_gap",
    "perm_gap",
    "perm_gap_strat",
    "perm_gap_delta_strat",
    "null_sanity",
    "JudgmentUnit",
    "assemble_verdict",
]


# ----------------------------------------------------------------------
# Estatística básica (numpy puro)
# ----------------------------------------------------------------------
def rankdata(a):
    """Ranks com média em empates (equivalente a scipy.stats.rankdata('average'))."""
    a = np.asarray(a, float)
    order = a.argsort()
    ranks = np.empty(len(a), float)
    ranks[order] = np.arange(1, len(a) + 1)
    _, inv, cnt = np.unique(a, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=ranks)
    return (sums / cnt)[inv]


def spearman(x, y):
    """Correlação de Spearman. NaN se n<5 ou variância zero."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if len(x) < 5 or len(x) != len(y):
        return np.nan
    rx = rankdata(x)
    ry = rankdata(y)
    rx -= rx.mean()
    ry -= ry.mean()
    den = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    return float((rx * ry).sum() / den) if den > 0 else np.nan


def decile_gap(feature, outcome, frac=0.10):
    """Diferença média(outcome | top frac de feature) − média(outcome | bottom frac).

    Top e bottom são `k = max(1, round(n*frac))` pontos cada (mesmo k nos dois lados).
    Retorna NaN se n<20 (poder amostral insuficiente).
    """
    feature = np.asarray(feature, float)
    outcome = np.asarray(outcome, float)
    n = len(feature)
    if n < 20 or len(outcome) != n:
        return np.nan
    k = max(1, int(round(n * frac)))
    order = np.argsort(feature)
    bot = outcome[order[:k]].mean()
    top = outcome[order[-k:]].mean()
    return float(top - bot)


# ----------------------------------------------------------------------
# Permutação
# ----------------------------------------------------------------------
def _pvalue_from_tail(obs, null, tail):
    if tail == "two":
        return float((np.abs(null) >= abs(obs)).mean())
    if tail == "less":
        return float((null <= obs).mean())
    if tail == "greater":
        return float((null >= obs).mean())
    raise ValueError(f"tail deve ser 'two' | 'less' | 'greater', recebido {tail!r}")


def perm_gap(feature, outcome, frac, n_perm, tail, rng):
    """Permutação global: embaralha `outcome` inteiro; estatística = decile_gap.

    Retorna (obs, p, null_array). Se obs é NaN (n<20), retorna (NaN, NaN, None).
    """
    feature = np.asarray(feature)
    outcome = np.asarray(outcome, float)
    obs = decile_gap(feature, outcome, frac)
    if np.isnan(obs):
        return obs, np.nan, None
    null = np.empty(n_perm)
    for i in range(n_perm):
        null[i] = decile_gap(feature, rng.permutation(outcome), frac)
    p = _pvalue_from_tail(obs, null, tail)
    return obs, p, null


def perm_gap_strat(feature, outcome, stratum, frac, n_perm, tail, rng):
    """Permutação estratificada: embaralha `outcome` DENTRO de cada nível de `stratum`.

    A estatística observada e nula é `decile_gap` sobre o pool inteiro (decis
    construídos sobre todos os pontos, não dentro de estrato).

    Retorna (obs, p, null_array). Se obs é NaN (n<20), retorna (NaN, NaN, None).
    """
    feature = np.asarray(feature)
    outcome = np.asarray(outcome, float)
    stratum = np.asarray(stratum)
    obs = decile_gap(feature, outcome, frac)
    if np.isnan(obs):
        return obs, np.nan, None
    idx_by = [np.where(stratum == s)[0] for s in np.unique(stratum)]
    null = np.empty(n_perm)
    for i in range(n_perm):
        op = outcome.copy()
        for idx in idx_by:
            op[idx] = outcome[rng.permutation(idx)]
        null[i] = decile_gap(feature, op, frac)
    p = _pvalue_from_tail(obs, null, tail)
    return obs, p, null


def perm_gap_delta_strat(feature, label_a, label_b, stratum,
                         frac, n_perm, tail, rng):
    """Teste pareado da DIFERENÇA entre dois gaps no mesmo feature, mesmo pool.

    Estatística observada: `delta = decile_gap(feature, label_a) − decile_gap(feature, label_b)`.

    Permutação pareada estratificada: dentro de cada nível de `stratum`, embaralha
    os DOIS labels com a MESMA permutação π (mantém feature fixo). Isso preserva
    a correlação intrínseca entre label_a e label_b (e.g., quando ambos são
    funções determinísticas do mesmo input — vide H4 onde rev/con vêm do mesmo
    price/k/σ) — o teste isola a ASSIMETRIA entre eles, não a correlação base.

    Uso típico: discriminar "feature realmente prediz A mais que B" de "feature
    proxia algo que afeta os dois igualmente" (vol-confound). Se delta não-
    significativo, A e B são indistinguíveis sob feature → classifica como
    confound, não sinal genuíno.

    tail ∈ {"two", "less", "greater"}. Para H4: "greater" (delta>0: feature
    discrimina A — reversal — mais que B — continuation).

    Retorna (obs_delta, p, null_array). Se algum gap é NaN, retorna (NaN, NaN, None).
    """
    feature = np.asarray(feature)
    label_a = np.asarray(label_a, float)
    label_b = np.asarray(label_b, float)
    stratum = np.asarray(stratum)
    obs_a = decile_gap(feature, label_a, frac)
    obs_b = decile_gap(feature, label_b, frac)
    if np.isnan(obs_a) or np.isnan(obs_b):
        return np.nan, np.nan, None
    obs_delta = obs_a - obs_b
    idx_by = [np.where(stratum == s)[0] for s in np.unique(stratum)]
    null = np.empty(n_perm)
    for i in range(n_perm):
        ap = label_a.copy()
        bp = label_b.copy()
        for idx in idx_by:
            perm = rng.permutation(idx)
            ap[idx] = label_a[perm]
            bp[idx] = label_b[perm]   # MESMA π → pareado (preserva corr. a×b)
        null[i] = decile_gap(feature, ap, frac) - decile_gap(feature, bp, frac)
    p = _pvalue_from_tail(obs_delta, null, tail)
    return obs_delta, p, null


# ----------------------------------------------------------------------
# Diagnóstico do harness (NÃO julga GO)
# ----------------------------------------------------------------------
def null_sanity(feature, outcome, *, frac, n_perm, rng, stratum=None):
    """Diagnóstico do apparatus, NÃO veredito do experimento.

    Reporta:
      - obs_gap                 estatística observada
      - p_two_sided             p two-sided da permutação (mesmo procedimento que o teste oficial)
      - null_mean / null_std    distribuição nula
      - null_min / null_max     extremos
      - z_obs_vs_null           obs / null_std (proxy de p via normal)
      - bias_within_3sigma      |null_mean| < 3*null_std/sqrt(n_perm)
      - bias_3sigma_tol         valor numérico dessa tolerância (pra inspeção)
      - sanity_null_pvalue      p two-sided rodando o pipeline com `outcome` embaralhado globalmente
      - sanity_null_ok          sanity_null_pvalue > 0.05 (esperado: ruído não dá significância)

    Nuance benigna (NÃO consertar): em permutação estratificada com estratos de
    tamanhos/baselines diferentes, um viés PEQUENO em null_mean é benigno — está
    embutido tanto em obs quanto em null e cancela no p-value. Reportar como
    benigno, não tratar como bug.
    """
    feature = np.asarray(feature)
    outcome = np.asarray(outcome, float)
    if stratum is None:
        obs, _, null = perm_gap(feature, outcome, frac, n_perm, "two", rng)
    else:
        obs, _, null = perm_gap_strat(feature, outcome, np.asarray(stratum), frac, n_perm, "two", rng)

    if null is None:
        return {
            "obs_gap": None if np.isnan(obs) else float(obs),
            "error": "decile_gap NaN (n<20) — sem distribuição nula",
        }

    null_mean = float(null.mean())
    null_std = float(null.std(ddof=0))
    p_two_sided = float((np.abs(null) >= abs(obs)).mean())
    z = float(obs / null_std) if null_std > 0 else np.nan
    sigma_estimator = float(3.0 * null_std / np.sqrt(n_perm)) if n_perm > 0 else np.inf
    bias_ok = abs(null_mean) <= sigma_estimator

    # Sanity-null: outcome embaralhado GLOBALMENTE (rompe qualquer estrutura interna,
    # incluindo dentro de estratos) — pipeline NÃO pode dar significância.
    outcome_shuffled = rng.permutation(outcome)
    if stratum is None:
        _, sanity_p, _ = perm_gap(feature, outcome_shuffled, frac, n_perm, "two", rng)
    else:
        _, sanity_p, _ = perm_gap_strat(feature, outcome_shuffled, np.asarray(stratum),
                                        frac, n_perm, "two", rng)
    sanity_p_val = None if sanity_p is None or np.isnan(sanity_p) else float(sanity_p)
    sanity_ok = sanity_p_val is not None and sanity_p_val > 0.05

    return {
        "obs_gap": float(obs),
        "p_two_sided": p_two_sided,
        "null_mean": null_mean,
        "null_std": null_std,
        "null_min": float(null.min()),
        "null_max": float(null.max()),
        "z_obs_vs_null": z,
        "bias_within_3sigma": bool(bias_ok),
        "bias_3sigma_tol": sigma_estimator,
        "sanity_null_pvalue": sanity_p_val,
        "sanity_null_ok": bool(sanity_ok),
    }


# ----------------------------------------------------------------------
# Unidade de julgamento (lição cravada no EXP-011)
# ----------------------------------------------------------------------
class JudgmentUnit(Enum):
    """Unidade pré-comprometida de julgamento de um experimento.

    AGGREGATE — um único veredito no pool inteiro. **Esta é a unidade MAIS confundida
        por composição de regime/entidade:** decis vêm em proporções diferentes dos
        estratos, e estratos têm baselines distintos, então o gap agregado embute
        composição. Aceitável quando as entidades são intercambiáveis a priori; arriscado
        quando há heterogeneidade (vide EXP-011: agregado NO-GO por 4 bps, mas BTC
        intra-regime mostrou edge robusto que ETH não confirma).

    PER_ENTITY — cada entidade testada independentemente; GO requer
        `require_entities` entidades passando cumpre_direção(gap) E p<max_p
        (default: todas). Captura sinal entidade-específico que o agregado dilui;
        custo: mais conservador, exige amostragem por entidade. Combinado com
        `direction` pré-comprometida, a consistência de sinal entre entidades
        fica automática: duas entidades em direções opostas nunca contam juntas.

    A escolha é do PRÉ-REGISTRO. assemble_verdict NÃO escolhe — recebe.
    """
    AGGREGATE = "aggregate"
    PER_ENTITY = "per_entity"


def _direction_ok(gap: float, min_gap_bps: float, direction: Optional[str]) -> bool:
    """Avalia se gap cumpre direção+magnitude pré-comprometidas."""
    if direction is None:
        return abs(gap) >= min_gap_bps
    if direction == "pos":
        return gap >= min_gap_bps
    if direction == "neg":
        return gap <= -min_gap_bps
    raise ValueError(
        f"direction deve ser None | 'pos' | 'neg', recebido {direction!r}"
    )


def _motivo_falha_gap(gap: float, min_gap_bps: float, direction: Optional[str]) -> str:
    if direction is None:
        return f"|gap|={abs(gap):.2f}bps < {min_gap_bps:.2f}"
    if direction == "pos":
        return f"gap={gap:+.2f}bps não satisfaz >= +{min_gap_bps:.2f} (direção 'pos')"
    return f"gap={gap:+.2f}bps não satisfaz <= -{min_gap_bps:.2f} (direção 'neg')"


def assemble_verdict(per_entity_stats: Optional[dict],
                     aggregate_stat: Optional[dict],
                     unit: JudgmentUnit,
                     *,
                     min_gap_bps: float,
                     max_p: float,
                     require_entities: Optional[int] = None,
                     direction: Optional[str] = None) -> dict:
    """Monta veredito GO/NO-GO segundo a unidade pré-comprometida.

    Args:
      per_entity_stats: dict {nome_entidade: {"gap_bps": float, "p": float, ...}}.
          Ignorado se unit=AGGREGATE.
      aggregate_stat: dict {"gap_bps": float, "p": float, ...}. Ignorado se unit=PER_ENTITY.
      unit: JudgmentUnit.AGGREGATE | JudgmentUnit.PER_ENTITY.
      min_gap_bps: piso de magnitude (em bps).
      max_p: teto de p-value.
      require_entities: só usado em PER_ENTITY. Default: todas as entidades.
      direction: pré-comprometimento de direção do gap.
        - None  → |gap| >= min_gap_bps (bidirecional; comportamento default).
        - "pos" → gap >= +min_gap_bps (sinal positivo E magnitude).
        - "neg" → gap <= -min_gap_bps (sinal negativo E magnitude).
        Consequência em PER_ENTITY: como cada entidade que "passa" já está na direção
        committed, a consistência de direção entre entidades (require_entities>=2) fica
        automática — duas entidades em direções opostas nunca contam juntas.

    Returns:
      dict com {passou, unidade, motivo, ...} — keys adicionais variam por unit.
    """
    if unit == JudgmentUnit.AGGREGATE:
        if not aggregate_stat:
            return {"passou": False, "unidade": "AGGREGATE",
                    "motivo": "aggregate_stat ausente"}
        gap = aggregate_stat.get("gap_bps")
        p = aggregate_stat.get("p")
        if gap is None or p is None:
            return {"passou": False, "unidade": "AGGREGATE",
                    "motivo": "aggregate_stat sem gap_bps ou p"}
        mag_ok = _direction_ok(float(gap), min_gap_bps, direction)
        p_ok = p < max_p
        passou = bool(mag_ok and p_ok)
        motivos = []
        if not mag_ok:
            motivos.append(_motivo_falha_gap(float(gap), min_gap_bps, direction))
        if not p_ok:
            motivos.append(f"p={p:.4g} >= {max_p}")
        return {
            "passou": passou,
            "unidade": "AGGREGATE",
            "gap_bps": float(gap),
            "p": float(p),
            "min_gap_bps": float(min_gap_bps),
            "max_p": float(max_p),
            "direction": direction,
            "motivo": "GO" if passou else "; ".join(motivos),
        }

    if unit == JudgmentUnit.PER_ENTITY:
        if not per_entity_stats:
            return {"passou": False, "unidade": "PER_ENTITY",
                    "motivo": "per_entity_stats vazio"}
        n_total = len(per_entity_stats)
        req = n_total if require_entities is None else int(require_entities)
        if req < 1 or req > n_total:
            return {"passou": False, "unidade": "PER_ENTITY",
                    "motivo": f"require_entities={req} fora de [1, {n_total}]"}
        # valida direction cedo (antes de iterar entidades)
        _direction_ok(0.0, min_gap_bps, direction)
        por_entidade = {}
        n_pass = 0
        for entity, stat in per_entity_stats.items():
            gap = stat.get("gap_bps") if stat else None
            p = stat.get("p") if stat else None
            if gap is None or p is None:
                por_entidade[entity] = {"passou": False, "motivo": "dados ausentes",
                                        "gap_bps": gap, "p": p}
                continue
            mag_ok = _direction_ok(float(gap), min_gap_bps, direction)
            p_ok = p < max_p
            ok = bool(mag_ok and p_ok)
            por_entidade[entity] = {
                "passou": ok,
                "gap_bps": float(gap),
                "p": float(p),
                "mag_ok": bool(mag_ok),
                "p_ok": bool(p_ok),
            }
            if ok:
                n_pass += 1
        passou = n_pass >= req
        return {
            "passou": bool(passou),
            "unidade": "PER_ENTITY",
            "n_pass": int(n_pass),
            "n_total": int(n_total),
            "require_entities": int(req),
            "min_gap_bps": float(min_gap_bps),
            "max_p": float(max_p),
            "direction": direction,
            "por_entidade": por_entidade,
            "motivo": ("GO" if passou
                       else f"{n_pass}/{n_total} entidades passam (require={req})"),
        }

    raise ValueError(
        f"unit deve ser JudgmentUnit.AGGREGATE ou JudgmentUnit.PER_ENTITY, recebido {unit!r}"
    )
