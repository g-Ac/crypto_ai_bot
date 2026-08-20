"""Schema + validação + IO do journal.jsonl (1 linha = 1 pré-registro congelado).

A validação é a GUARDA de integridade: barra primitiva fora do catálogo, param
inválido, corte forward não-futuro (viés!) e inconsistência status×verdict. Sem isso
o colhedor poderia julgar lixo, ou pior, um pré-registro que "olhou o passado".
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from research.gerador_prereg import catalogo as cat

# defaults congelados na MINI_MOLDURA (2026-06-18)
FEE_BPS_ROUNDTRIP = 10.0
SLIPPAGE_BPS = 2.0
N_MIN = 30
THRESHOLD_BPS = 0.0
METRIC = "expectancy_net_bps"
P_METHOD = "bootstrap"
MARCO_DEFAULT = "2026-08-01"

REQUIRED_TOP = ["id", "created_at", "batch_id", "n_no_batch", "status",
                "hypothesis", "motivation", "spec", "forward", "verdict"]
REQUIRED_SPEC = ["signal", "signal_params", "filter", "filter_params", "side",
                 "exit", "universe", "fee_bps_roundtrip", "slippage_bps"]
REQUIRED_FWD = ["corte_ts", "marco", "metric", "threshold", "n_min", "p_method"]
VALID_STATUS = {"frozen", "judged", "skipped"}
VALID_SIDE = {"long", "short", "auto"}


def epoch_of(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _check_params(label, params, space):
    if not isinstance(params, dict):
        return [f"{label} deve ser dict"]
    errs = []
    for k, v in params.items():
        if k not in space:
            errs.append(f"{label}: param desconhecido '{k}'")
        elif v not in space[k]:
            errs.append(f"{label}: valor inválido {k}={v}")
    return errs


def validate(rec) -> list[str]:
    """Lista de erros (vazia = válido)."""
    errs = [f"falta campo '{k}'" for k in REQUIRED_TOP if k not in rec]
    if errs:
        return errs
    if rec["status"] not in VALID_STATUS:
        errs.append(f"status inválido: {rec['status']}")
    if not isinstance(rec.get("n_no_batch"), int) or rec["n_no_batch"] < 1:
        errs.append("n_no_batch deve ser int >= 1")

    spec, fwd = rec["spec"], rec["forward"]
    errs += [f"falta spec.{k}" for k in REQUIRED_SPEC if k not in spec]
    errs += [f"falta forward.{k}" for k in REQUIRED_FWD if k not in fwd]
    if errs:
        return errs

    # primitivas ∈ catálogo (a trava)
    if spec["signal"] not in cat.SIGNALS:
        errs.append(f"signal fora do catálogo: {spec['signal']}")
    else:
        errs += _check_params("signal_params", spec["signal_params"],
                              cat.SIGNALS[spec["signal"]]["param_space"])
    if spec["filter"] not in cat.FILTERS:
        errs.append(f"filter fora do catálogo: {spec['filter']}")
    else:
        errs += _check_params("filter_params", spec["filter_params"],
                              cat.FILTERS[spec["filter"]]["param_space"])
    if spec["side"] not in VALID_SIDE:
        errs.append(f"side inválido: {spec['side']}")
    ex = spec["exit"]
    if not isinstance(ex, dict) or ex.get("type") != "horizonte":
        errs.append("exit.type deve ser 'horizonte'")
    elif ex.get("bars") not in cat.EXITS["horizonte"]["param_space"]["bars"]:
        errs.append(f"exit.bars fora do catálogo: {ex.get('bars')}")
    if spec["universe"] not in cat.UNIVERSES:
        errs.append(f"universe inválido: {spec['universe']}")
    for k in ("fee_bps_roundtrip", "slippage_bps"):
        v = spec[k]
        if not isinstance(v, (int, float)) or v < 0:
            errs.append(f"spec.{k} deve ser número >= 0")

    # forward: corte ESTRITAMENTE futuro vs created_at (mata o viés temporal)
    created = None
    try:
        created = epoch_of(rec["created_at"])
    except Exception:
        errs.append("created_at não é ISO-8601")
    if not isinstance(fwd["corte_ts"], int):
        errs.append("forward.corte_ts deve ser int (epoch UTC)")
    elif created is not None and fwd["corte_ts"] <= created:
        errs.append("forward.corte_ts não é estritamente futuro vs created_at (viés!)")
    if fwd["metric"] != METRIC:
        errs.append(f"métrica inesperada: {fwd['metric']}")
    if fwd["p_method"] != P_METHOD:
        errs.append(f"p_method inesperado: {fwd['p_method']}")
    if not isinstance(fwd["n_min"], int) or fwd["n_min"] < 1:
        errs.append("forward.n_min inválido")

    # status × verdict
    if rec["status"] == "frozen" and rec["verdict"] is not None:
        errs.append("status frozen exige verdict=null")
    if rec["status"] == "judged" and not isinstance(rec["verdict"], dict):
        errs.append("status judged exige verdict objeto")
    return errs


def is_valid(rec) -> bool:
    return not validate(rec)


def new_frozen(rec_id, created_at, batch_id, n_no_batch, hypothesis, motivation,
               signal, signal_params, filter_name, filter_params, side, bars,
               universe, corte_ts, marco=MARCO_DEFAULT):
    """Monta um pré-registro congelado válido (defaults de custo/régua embutidos)."""
    rec = {
        "id": rec_id, "created_at": created_at, "batch_id": batch_id,
        "n_no_batch": n_no_batch, "status": "frozen",
        "hypothesis": hypothesis, "motivation": motivation,
        "spec": {
            "signal": signal, "signal_params": signal_params,
            "filter": filter_name, "filter_params": filter_params,
            "side": side, "exit": {"type": "horizonte", "bars": bars},
            "universe": universe,
            "fee_bps_roundtrip": FEE_BPS_ROUNDTRIP, "slippage_bps": SLIPPAGE_BPS,
        },
        "forward": {
            "corte_ts": corte_ts, "marco": marco, "metric": METRIC,
            "threshold": THRESHOLD_BPS, "n_min": N_MIN, "p_method": P_METHOD,
        },
        "verdict": None,
    }
    return rec


# ───────────────────────── IO ─────────────────────────
def read_journal(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def append(path, rec):
    errs = validate(rec)
    if errs:
        raise ValueError(f"pré-registro inválido, recusado: {errs}")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def rewrite(path, recs):
    """Reescreve o journal inteiro (colhedor grava verdicts). Revalida cada linha."""
    lines = []
    for r in recs:
        errs = validate(r)
        if errs:
            raise ValueError(f"registro inválido no rewrite: {errs}")
        lines.append(json.dumps(r, ensure_ascii=False))
    Path(path).write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
