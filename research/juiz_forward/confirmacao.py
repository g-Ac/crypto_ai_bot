"""Confirmação — 2º forward pré-registrado dos candidatos do Juiz (EXP-100).

Descoberta -> Confirmação: o GO-INVESTIGAR de 2026-08-01 tornou células CANDIDATAS;
elas só viram edge de carteira se CONFIRMAREM num 2º forward independente (corte
estritamente futuro => janela DISJUNTA da descoberta). Este módulo congela esse 2º
pré-registro e o julga no marco — espelho do confirmador do gerador_prereg, mas no
pipeline do Juiz: as células vivem em exp100_screening, fora do catálogo do gerador
(disjunto por design); reimplementá-las lá quebraria a spec byte-idêntica.

Spec byte-idêntica por construção: o julgamento reusa judge._cells_exp100 (o MESMO
código e seed da descoberta) e seleciona as células candidatas pelo label. O BH-FDR
paga a multiplicidade DO COHORT de confirmação (as candidatas juntas, não as 146).
Hashes sha256 do motor ficam congelados no pré-registro: signals/filters/judge não
estão no git, então drift de código até o marco é FLAGRADO no veredito (não bloqueia
— um marco queimado é pior que um veredito flagrado).

Régua (congelada no freeze, mesma da descoberta): confirmada = n>=n_min E passa
BH-FDR(q) E expectancy>threshold. Janela<dias_min ou n<n_min = dado_insuficiente
(falha de DIMENSIONAMENTO — precedente NOTA_INTERPRETACAO_B-20260701: recongelar
janela maior, não é tese morta). O resto é rejeitada_conf, TERMINAL — 1 tentativa
por candidata, sem re-rodar-até-passar.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from research.exp100_screening import data as datamod
from research.exp100_screening import stats
from research.juiz_forward import judge

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PREREG_DEFAULT = HERE / "confirmacao_prereg.json"
OUT_DEFAULT = HERE / "confirmacao_resultado.json"
RESULTADO_DESCOBERTA = HERE / "resultado.json"

# régua espelha a descoberta (judge.py) e o confirmador do gerador (marco 60d)
MARCO_CONF_DIAS = 60
N_MIN = judge.N_MIN_DIR
FDR_Q = judge.FDR_Q
DIAS_MIN_VALIDO = judge.DIAS_MIN_VALIDO
SEED = 1                     # seed fixa das células EXP-100 em judge._cells_exp100

# cadeia measurement-critical da célula EXP-100 (drift aqui = spec diferente).
# Inclui este módulo: ele decide estado/veredito/cohort, então drift aqui muda o
# julgamento tanto quanto drift no motor.
HASH_FILES = (
    "research/exp100_screening/signals.py",
    "research/exp100_screening/filters.py",
    "research/exp100_screening/backtest.py",
    "research/exp100_screening/data.py",
    "research/exp100_screening/stats.py",
    "research/juiz_forward/judge.py",
    "research/juiz_forward/confirmacao.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_hashes(root: Path = ROOT) -> dict:
    return {rel: _sha256(Path(root) / rel) for rel in HASH_FILES}


def _corte_amanha(agora: datetime) -> int:
    """Meia-noite UTC de amanhã — estritamente futuro (convenção do gerador)."""
    d = agora.date() + timedelta(days=1)
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _dias(panels) -> float:
    if not panels:
        return 0.0
    lo = min(df.index.min() for df in panels.values())
    hi = max(df.index.max() for df in panels.values())
    return (hi - lo) / 86400.0


def freeze(resultado_path=RESULTADO_DESCOBERTA, prereg_path=PREREG_DEFAULT,
           agora=None, marco_dias=MARCO_CONF_DIAS, root=ROOT, motivo_refreeze=None):
    """Congela o pré-registro de confirmação a partir dos candidatos da descoberta.

    Recusa recongelar por padrão. Recongelar EXIGE `motivo_refreeze` E que a janela
    ainda NÃO tenha aberto (corte do pré-registro vigente no futuro) — antes do corte
    nenhum dado forward foi observado, então re-congelar não pode ser garimpo; depois
    do corte seria re-rodar-até-passar e é BARRADO. O pré-registro anterior fica
    registrado no campo `refreeze` (auditoria: nada some silenciosamente).

    Só EXP-100 é suportado — o motor da confirmação é judge._cells_exp100; um
    candidato de outro EXP exige extensão consciente, não um freeze silencioso que
    o marco não saberá julgar.
    """
    prereg_path = Path(prereg_path)
    if agora is None:
        agora = datetime.now(timezone.utc)

    anterior = None
    if prereg_path.exists():
        if not motivo_refreeze:
            raise FileExistsError(f"pré-registro já congelado: {prereg_path} "
                                  f"(recongelar exige motivo_refreeze)")
        velho = json.loads(prereg_path.read_text())
        if velho["corte_ts"] <= int(agora.timestamp()):
            raise ValueError(
                "janela de confirmação já abriu (corte_ts no passado): recongelar "
                "agora seria re-rodar contra dado já observado. BARRADO.")
        anterior = {"created_at": velho.get("created_at"),
                    "corte_ts": velho["corte_ts"], "marco": velho.get("marco"),
                    "sha256": hashlib.sha256(prereg_path.read_bytes()).hexdigest()}

    res = json.loads(Path(resultado_path).read_text())
    cands = res.get("candidatos") or []
    if not cands:
        raise ValueError("descoberta sem candidatos; nada a confirmar")
    nao_suportados = [c["label"] for c in cands if c.get("exp") != "EXP-100"]
    if nao_suportados:
        raise ValueError(f"só EXP-100 é suportado na confirmação: {nao_suportados}")

    corte = _corte_amanha(agora)
    marco = (datetime.fromtimestamp(corte, timezone.utc).date()
             + timedelta(days=marco_dias)).isoformat()

    dias_desc = float(res.get("dias_forward") or 0.0)
    cells = []
    for c in cands:
        # dimensionamento pelo pipeline COMPLETO (lição da NOTA): a taxa observada
        # na descoberta já desconta warm-up de rolling e dedupe
        n_esp = round(c["n"] / dias_desc * marco_dias, 1) if dias_desc > 0 else None
        cells.append({
            "exp": c["exp"], "label": c["label"],
            "descoberta": {"n": c["n"], "expectancy_bps": c["expectancy_bps"],
                           "p_value": c["p_value"]},
            "n_esperado_conf": n_esp,
        })

    prereg = {
        "schema_version": 1,
        "created_at": agora.isoformat(),
        "confirms": {"origem": "research/juiz_forward/resultado.json",
                     "gerado_em": res.get("gerado_em"),
                     "veredito_descoberta": res.get("veredito"),
                     "corte_descoberta_ts": res.get("corte_forward_ts")},
        "corte_ts": corte,
        "marco": marco,
        "regua": {"metric": "expectancy_bps", "threshold": 0.0, "n_min": N_MIN,
                  "fdr_q": FDR_Q, "p_method": "bootstrap", "seed": SEED,
                  "dias_min_valido": DIAS_MIN_VALIDO},
        "cells": cells,
        "code_hashes": code_hashes(root),
        "integracao_carteira": "pendente — decidir quando (se) algo confirmar no marco",
    }
    if anterior is not None:
        prereg["refreeze"] = {"motivo": motivo_refreeze, "anterior": anterior}
    prereg_path.write_text(json.dumps(prereg, indent=2, ensure_ascii=False))
    return prereg


def _valida_corte(prereg):
    """Guarda anti-viés no PONTO DE USO (espelha schema.validate do gerador).

    O pré-registro é JSON mutável num SD card e fica 60 dias parado até o marco;
    validar só no freeze deixaria um corte adulterado (ou corrompido) re-medir a
    janela que a descoberta já minerou — confirmação falsa e silenciosa. Barra:
    corte não-futuro vs created_at, e corte que não é estritamente posterior ao
    corte da descoberta (janelas precisam ser DISJUNTAS).
    """
    corte = prereg.get("corte_ts")
    if not isinstance(corte, int):
        raise ValueError(f"corte_ts inválido: {corte!r}")
    created = prereg.get("created_at")
    if created:
        try:
            criado_ts = int(datetime.fromisoformat(created).timestamp())
        except ValueError as e:
            raise ValueError(f"created_at não é ISO-8601: {created!r}") from e
        if corte <= criado_ts:
            raise ValueError("corte_ts não é estritamente futuro vs created_at "
                             "(viés!): pré-registro adulterado ou corrompido")
    corte_desc = (prereg.get("confirms") or {}).get("corte_descoberta_ts")
    if corte_desc is not None and corte <= corte_desc:
        raise ValueError(
            f"corte_ts ({corte}) <= corte da descoberta ({corte_desc}): a janela "
            f"de confirmação NÃO é disjunta — re-mediria dado já minerado. BARRADO.")


def confirmar(prereg_path=PREREG_DEFAULT, panels=None, out_path=OUT_DEFAULT,
              root=ROOT):
    """Julga a confirmação no dado forward (>= corte_ts do pré-registro).

    Reusa judge._cells_exp100 no painel cortado (warm-up dentro da janela, idêntico
    à descoberta) e seleciona as células do pré-registro. FDR sobre o cohort.
    """
    prereg = (prereg_path if isinstance(prereg_path, dict)
              else json.loads(Path(prereg_path).read_text()))
    _valida_corte(prereg)
    regua = prereg["regua"]

    atuais = code_hashes(root)
    drift = sorted(p for p, h in prereg["code_hashes"].items() if atuais.get(p) != h)

    if panels is None:
        panels = datamod.load_panel()
    corte = prereg["corte_ts"]
    fp = {}
    for s, df in panels.items():
        f = df[df.index >= corte]
        if len(f) > 0:
            fp[s] = f
    dias = _dias(fp)

    por_label = {c["label"]: c for c in judge._cells_exp100(fp)}
    faltando = [c["label"] for c in prereg["cells"] if c["label"] not in por_label]
    if faltando:
        raise RuntimeError(f"células do pré-registro ausentes no motor: {faltando}")

    sel = []
    for c in prereg["cells"]:
        m = por_label[c["label"]]
        sel.append({"exp": c["exp"], "label": c["label"], "descoberta": c["descoberta"],
                    "n": int(m["n"]), "expectancy_bps": m["expectancy_bps"],
                    "p_value": m["p_value"]})

    janela_ok = dias >= regua["dias_min_valido"]
    elig_idx = [i for i, c in enumerate(sel)
                if c["n"] >= regua["n_min"] and np.isfinite(c["p_value"])]
    pvals = [sel[i]["p_value"] for i in elig_idx]
    rej = stats.benjamini_hochberg(pvals, q=regua["fdr_q"]) if pvals else np.zeros(0, bool)
    passes = [False] * len(sel)
    for i, ok in zip(elig_idx, rej):
        passes[i] = bool(ok)

    n_conf = 0
    for i, c in enumerate(sel):
        c["passes_fdr"] = passes[i]
        if not janela_ok or c["n"] < regua["n_min"]:
            c["estado"] = "dado_insuficiente"
        elif passes[i] and np.isfinite(c["expectancy_bps"]) \
                and c["expectancy_bps"] > regua["threshold"]:
            c["estado"] = "confirmada"
            n_conf += 1
        else:
            c["estado"] = "rejeitada_conf"

    if not janela_ok or not elig_idx:
        veredito = "DADO-INSUFICIENTE"
    elif n_conf > 0:
        veredito = "CONFIRMADA"
    else:
        veredito = "NO-GO"

    payload = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "corte_ts": corte, "marco": prereg["marco"],
        "dias_forward": round(dias, 1), "n_simbolos": len(fp),
        "veredito": veredito, "n_confirmadas": n_conf,
        "code_drift": drift,
        "cells": sel,
    }
    if out_path is not None:
        Path(out_path).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


if __name__ == "__main__":
    p = confirmar()
    print(f"CONFIRMAÇÃO: {p['veredito']} | {p['dias_forward']}d forward, "
          f"{p['n_confirmadas']} confirmada(s)"
          + (f" | DRIFT DE CÓDIGO: {p['code_drift']}" if p["code_drift"] else ""))
    for c in p["cells"]:
        print(f"  -> {c['label']}: {c['estado']} exp={c['expectancy_bps']:.1f}bps "
              f"n={c['n']} p={c['p_value']:.3f}")
