"""Confirmador — congela o 2o forward das candidatas (descoberta -> confirmacao).

Journal em tmp_path; specs com signals reais do catalogo (o append revalida). Prova:
1 confirmacao por candidata, corte estritamente futuro, mesma signature, bypass do dedup,
idempotencia, e que nao-candidata nao gera confirmacao.
"""
import datetime as dt
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from research.gerador_prereg import catalogo as cat        # noqa: E402
from research.gerador_prereg import confirmador, schema     # noqa: E402

AGORA = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.timezone.utc)


def _disc(path, signal, is_cand=True, n=40, exp=25.0, bars=24, batch="B-1"):
    """Escreve uma descoberta JUDGED valida no journal (signal real do catalogo)."""
    rec = schema.new_frozen(
        rec_id=f"{batch}-{signal}-{bars}", created_at="2026-06-18T00:00:00+00:00",
        batch_id=batch, n_no_batch=1, hypothesis="h", motivation="m",
        signal=signal, signal_params={}, filter_name="nenhum", filter_params={},
        side="long", bars=bars, universe="todos",
        corte_ts=schema.epoch_of("2026-06-19T00:00:00+00:00"))
    rec["status"] = "judged"
    rec["verdict"] = {"n": n, "expectancy_net_bps": exp, "is_candidato": is_cand,
                      "passes_fdr": is_cand, "p_value": 0.03, "veredito_batch": "GO-INVESTIGAR",
                      "pf": 1.5, "win_rate": 0.5, "dias_forward": 30.0, "label": "x"}
    schema.append(path, rec)
    return rec


def test_congela_uma_confirmacao_valida(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    disc = _disc(p, "funding_flip", is_cand=True)
    novos = confirmador.freeze_confirmations(p, agora=AGORA)
    assert len(novos) == 1
    recs = schema.read_journal(p)
    conf = [r for r in recs if r["id"] in novos][0]
    assert schema.is_valid(conf)
    assert conf["batch_id"] == "CONF-20260801"
    assert conf["status"] == "frozen" and conf["verdict"] is None
    assert conf["confirms"] == disc["id"]
    # spec byte-identica -> mesma signature
    assert cat.spec_signature(conf["spec"]) == cat.spec_signature(disc["spec"])
    # corte estritamente futuro vs created_at (mata vies)
    assert conf["forward"]["corte_ts"] > schema.epoch_of(conf["created_at"])
    # janela de confirmacao disjunta (corte depois do created_at de hoje)
    assert conf["forward"]["marco"] > conf["created_at"][:10]


def test_idempotente(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    _disc(p, "funding_flip", is_cand=True)
    n1 = confirmador.freeze_confirmations(p, agora=AGORA)
    n2 = confirmador.freeze_confirmations(p, agora=AGORA)   # relê o journal -> ve a CONF -> no-op
    assert len(n1) == 1 and n2 == []
    assert sum(1 for r in schema.read_journal(p)
               if str(r["batch_id"]).startswith("CONF-")) == 1


def test_nao_candidata_nao_confirma(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    _disc(p, "funding_flip", is_cand=False)          # rejeitada
    assert confirmador.freeze_confirmations(p, agora=AGORA) == []


def test_multiplas_candidatas_no_mesmo_batch(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    _disc(p, "funding_flip", is_cand=True)
    _disc(p, "reacao_nivel", is_cand=True)            # signature distinta
    _disc(p, "oi_preco_div", is_cand=False)           # rejeitada -> não confirma
    novos = confirmador.freeze_confirmations(p, agora=AGORA)
    assert len(novos) == 2                            # só as 2 candidatas
    recs = schema.read_journal(p)
    confs = [r for r in recs if str(r["batch_id"]).startswith("CONF-")]
    assert {r["n_no_batch"] for r in confs} == {1, 2}   # numeração no batch
    assert all(r["batch_id"] == "CONF-20260801" for r in confs)   # cohort compartilhado (FDR paga)


def test_bypass_do_dedup_do_gerador(tmp_path):
    # a signature da descoberta JA existe no journal; o confirmador congela mesmo assim
    p = str(tmp_path / "journal.jsonl")
    disc = _disc(p, "funding_flip", is_cand=True)
    sig = cat.spec_signature(disc["spec"])
    assert any(cat.spec_signature(r["spec"]) == sig for r in schema.read_journal(p))
    novos = confirmador.freeze_confirmations(p, agora=AGORA)
    assert len(novos) == 1                            # congelou apesar da signature já existir
