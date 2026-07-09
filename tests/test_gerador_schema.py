"""Schema/validação/IO do journal de pré-registros."""
import copy
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from research.gerador_prereg import schema  # noqa: E402

CREATED = "2026-06-18T12:00:00+00:00"
CORTE = schema.epoch_of("2026-06-19T00:00:00+00:00")   # estritamente futuro


def _valid():
    return schema.new_frozen(
        rec_id="PR-20260618-001", created_at=CREATED, batch_id="B-20260618",
        n_no_batch=1, hypothesis="streak de 3 candles reverte",
        motivation="exaustão pós-streak", signal="sequencia_candles",
        signal_params={"n": 3, "modo": "reversao"}, filter_name="nenhum",
        filter_params={}, side="auto", bars=4, universe="todos", corte_ts=CORTE)


def test_record_valido():
    assert schema.is_valid(_valid()), schema.validate(_valid())


def test_signal_fora_do_catalogo():
    r = _valid()
    r["spec"]["signal"] = "nao_existe"
    assert any("signal fora do catálogo" in e for e in schema.validate(r))


def test_param_invalido():
    r = _valid()
    r["spec"]["signal_params"] = {"n": 99}    # 99 não está no param_space
    assert any("valor inválido n=99" in e for e in schema.validate(r))


def test_corte_nao_futuro_e_vies():
    r = _valid()
    r["forward"]["corte_ts"] = schema.epoch_of("2026-06-17T00:00:00+00:00")  # passado
    assert any("estritamente futuro" in e for e in schema.validate(r))


def test_corte_igual_ao_created_tambem_invalido():
    r = _valid()
    r["forward"]["corte_ts"] = schema.epoch_of(CREATED)   # == created, não estritamente futuro
    assert any("estritamente futuro" in e for e in schema.validate(r))


def test_frozen_exige_verdict_null():
    r = _valid()
    r["verdict"] = {"veredito": "GO"}
    assert any("verdict=null" in e for e in schema.validate(r))


def test_universe_e_exit_invalidos():
    r = _valid()
    r["spec"]["universe"] = "xpto"
    r["spec"]["exit"] = {"type": "horizonte", "bars": 7}   # 7 fora do param_space
    errs = schema.validate(r)
    assert any("universe inválido" in e for e in errs)
    assert any("exit.bars fora" in e for e in errs)


def test_fee_negativo():
    r = _valid()
    r["spec"]["slippage_bps"] = -1
    assert any("slippage_bps deve ser número >= 0" in e for e in schema.validate(r))


def test_io_round_trip(tmp_path):
    p = tmp_path / "journal.jsonl"
    a, b = _valid(), _valid()
    b["id"] = "PR-20260618-002"
    b["n_no_batch"] = 2
    schema.append(str(p), a)
    schema.append(str(p), b)
    got = schema.read_journal(str(p))
    assert [r["id"] for r in got] == ["PR-20260618-001", "PR-20260618-002"]


def test_append_recusa_invalido(tmp_path):
    p = tmp_path / "journal.jsonl"
    bad = _valid()
    bad["spec"]["signal"] = "nope"
    try:
        schema.append(str(p), bad)
        assert False, "deveria ter recusado"
    except ValueError:
        pass
    assert schema.read_journal(str(p)) == []   # nada gravado


def test_rewrite_grava_verdict(tmp_path):
    p = tmp_path / "journal.jsonl"
    r = _valid()
    schema.append(str(p), r)
    recs = schema.read_journal(str(p))
    recs[0]["status"] = "judged"
    recs[0]["verdict"] = {"veredito": "NO-GO", "expectancy_net_bps": -3.1, "n": 41}
    schema.rewrite(str(p), recs)
    back = schema.read_journal(str(p))
    assert back[0]["status"] == "judged"
    assert back[0]["verdict"]["veredito"] == "NO-GO"
