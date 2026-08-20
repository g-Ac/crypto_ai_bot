"""Confirmador — congela o 2o forward (confirmacao) de cada candidata.

Descoberta -> Confirmacao (guarda anti-multiplicidade): passar o FDR no 1o forward torna a
hipotese CANDIDATA; ela so entra na carteira se CONFIRMAR num 2o forward independente. Este
modulo congela esse 2o pre-registro:
  - spec BYTE-IDENTICA a da descoberta (replicacao, nao nova busca) — mesma spec_signature;
  - corte estritamente futuro (schema.validate rejeita corte nao-futuro = mata vies temporal),
    logo a 2a janela [corte2, marco2) e DISJUNTA da 1a (independencia: dado never-seen);
  - batch CONF-YYYYMMDD (compartilhado no cohort -> o BH-FDR do colhedor paga multiplicidade
    entre confirmacoes simultaneas — mais rigor, nao menos).

Idempotente (1 confirmacao por candidata). BYPASSA de proposito o dedup spec_signature do
gerador — a confirmacao e a UNICA re-congelada sancionada do mesmo spec. NAO e re-rodar-ate-
passar: 1 tentativa por candidata, a maquina escolhe quando, falha e terminal (rejeitada_conf).
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from research.gerador_prereg import catalogo as cat
from research.gerador_prereg import gerador, schema

CONF_PREFIX = "CONF-"
MARCO_CONF_DIAS = 60   # janela de confirmacao generosa (warm-up do rolling come ~5-8d; licao NOTA)


def _is_conf(rec) -> bool:
    return str(rec.get("batch_id", "")).startswith(CONF_PREFIX)


def candidatas_sem_confirmacao(recs) -> list:
    """Descobertas judged+candidatas cuja signature ainda NAO tem CONF-record."""
    conf_sigs = {cat.spec_signature(r["spec"]) for r in recs if _is_conf(r)}
    out = []
    for r in recs:
        if _is_conf(r):
            continue
        v = r.get("verdict") or {}
        if r.get("status") == "judged" and v.get("is_candidato") \
                and cat.spec_signature(r["spec"]) not in conf_sigs:
            out.append(r)
    return out


def _marco_conf(corte_ts, dias=MARCO_CONF_DIAS) -> str:
    d = datetime.fromtimestamp(corte_ts, timezone.utc).date() + timedelta(days=dias)
    return d.isoformat()


def freeze_confirmations(journal_path, recs=None, agora=None, marco_conf=None) -> list:
    """Para cada candidata sem confirmacao, congela 1 CONF- pre-registro (spec identica,
    corte=amanha, batch CONF-YYYYMMDD, confirms=disc_id). Idempotente quando recs e relido
    do journal a cada execucao. Retorna os ids congelados nesta execucao."""
    if agora is None:
        agora = datetime.now(timezone.utc)
    if recs is None:
        recs = schema.read_journal(journal_path)

    batch_id = f"{CONF_PREFIX}{agora:%Y%m%d}"
    ja_no_batch = sum(1 for r in recs if r.get("batch_id") == batch_id)
    corte = gerador._corte_amanha(agora)      # meia-noite UTC de amanha = estritamente futuro

    novos = []
    for i, disc in enumerate(candidatas_sem_confirmacao(recs)):
        rec = copy.deepcopy(disc)             # spec BYTE-IDENTICA
        n_no = ja_no_batch + i + 1
        rec["id"] = f"PR-{agora:%Y%m%d}-C{n_no:03d}"
        rec["batch_id"] = batch_id
        rec["n_no_batch"] = n_no
        rec["status"] = "frozen"
        rec["created_at"] = agora.isoformat()
        rec["verdict"] = None
        rec["forward"] = dict(disc["forward"])
        rec["forward"]["corte_ts"] = corte
        rec["forward"]["marco"] = marco_conf or _marco_conf(corte)
        rec["confirms"] = disc["id"]          # proveniencia (a signature ja liga; isto e auditoria)
        schema.append(journal_path, rec)      # revalida: corte estritamente futuro, spec no catalogo
        novos.append(rec["id"])
    return novos
