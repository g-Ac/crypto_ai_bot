"""Gerador/amostrador — congela 1 hipótese nova por execução, forward-only."""
import datetime as dt
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from research.gerador_prereg import catalogo as cat  # noqa: E402
from research.gerador_prereg import gerador, schema   # noqa: E402

AGORA = dt.datetime(2026, 6, 18, 12, 0, tzinfo=dt.timezone.utc)


def test_gera_um_frozen_valido(tmp_path):
    p = tmp_path / "journal.jsonl"
    status, rid = gerador.gerar(journal_path=str(p), agora=AGORA)
    assert status == "REGISTERED"
    assert rid == "PR-20260618-001"
    recs = schema.read_journal(str(p))
    assert len(recs) == 1 and schema.is_valid(recs[0])
    assert recs[0]["status"] == "frozen" and recs[0]["verdict"] is None
    assert recs[0]["forward"]["corte_ts"] > schema.epoch_of(AGORA.isoformat())  # futuro


def test_cinco_diversos_depois_batch_full(tmp_path):
    p = tmp_path / "journal.jsonl"
    ids = []
    for _ in range(5):
        s, rid = gerador.gerar(journal_path=str(p), agora=AGORA)
        assert s == "REGISTERED"
        ids.append(rid)
    s6, _ = gerador.gerar(journal_path=str(p), agora=AGORA)
    assert s6 == "BATCH_FULL"
    recs = schema.read_journal(str(p))
    assert len(recs) == 5
    assert len({cat.spec_signature(r["spec"]) for r in recs}) == 5    # todas diversas
    assert ids == [f"PR-20260618-{i:03d}" for i in range(1, 6)]


def test_nao_duplica_hipotese(tmp_path):
    p = tmp_path / "journal.jsonl"
    gerador.gerar(journal_path=str(p), agora=AGORA)
    gerador.gerar(journal_path=str(p), agora=AGORA)
    recs = schema.read_journal(str(p))
    assert cat.spec_signature(recs[0]["spec"]) != cat.spec_signature(recs[1]["spec"])


def test_skipped_quando_fila_esgota(tmp_path):
    p = tmp_path / "journal.jsonl"
    for _ in range(len(gerador.CANDIDATOS)):       # cap alto p/ esgotar a fila, não o batch
        s, _ = gerador.gerar(journal_path=str(p), agora=AGORA, cap_n=20)
        assert s == "REGISTERED"
    s, _ = gerador.gerar(journal_path=str(p), agora=AGORA, cap_n=20)
    assert s == "SKIPPED"


def test_determinismo(tmp_path):
    p1, p2 = tmp_path / "j1.jsonl", tmp_path / "j2.jsonl"
    gerador.gerar(journal_path=str(p1), agora=AGORA)
    gerador.gerar(journal_path=str(p2), agora=AGORA)
    a = schema.read_journal(str(p1))[0]["spec"]
    b = schema.read_journal(str(p2))[0]["spec"]
    assert cat.spec_signature(a) == cat.spec_signature(b)
