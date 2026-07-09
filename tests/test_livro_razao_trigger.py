"""Trigger do livro-razao (end-to-end sintetico) + gate da mesa. Zero bot.db."""
import datetime as dt
import json
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from research.gerador_prereg import mesa, schema           # noqa: E402
import scripts.livro_razao_trigger as trig                 # noqa: E402

AGORA = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.timezone.utc)


def _disc(path, signal, is_cand, n=40, exp=25.0, batch="B-1"):
    rec = schema.new_frozen(
        rec_id=f"{batch}-{signal}", created_at="2026-06-18T00:00:00+00:00",
        batch_id=batch, n_no_batch=1, hypothesis="h", motivation="m",
        signal=signal, signal_params={}, filter_name="nenhum", filter_params={},
        side="long", bars=24, universe="todos",
        corte_ts=schema.epoch_of("2026-06-19T00:00:00+00:00"))
    rec["status"] = "judged"
    rec["verdict"] = {"n": n, "expectancy_net_bps": exp, "is_candidato": is_cand,
                      "passes_fdr": is_cand, "p_value": 0.03, "veredito_batch": "x",
                      "pf": 1.5, "win_rate": 0.5, "dias_forward": 30.0, "label": "x"}
    schema.append(path, rec)
    return rec


# ───────────────────────── trigger end-to-end ─────────────────────────
def test_trigger_congela_confirmacao_e_grava_carteira(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    out = str(tmp_path / "carteira.json")
    _disc(p, "funding_flip", is_cand=True)              # 1 candidata
    _disc(p, "oi_preco_div", is_cand=False)             # 1 rejeitada
    got = []
    res = trig.run(journal_path=p, agora=AGORA, panels={}, out_path=out,
                   notifier=lambda t, m, c: got.append((t, m, c)))
    assert len(res["confirmacoes"]) == 1                # só a candidata confirma
    assert res["n_carteira"] == 0                       # conf ainda não julgada -> carteira vazia
    snap = json.loads(open(out).read())
    assert snap["derived"] is True and snap["caixa"] == 1.0
    assert got and got[0][2] is False                  # notificou (não-crítico)


def test_trigger_idempotente(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    out = str(tmp_path / "carteira.json")
    _disc(p, "funding_flip", is_cand=True)
    r1 = trig.run(journal_path=p, agora=AGORA, panels={}, out_path=out)
    r2 = trig.run(journal_path=p, agora=AGORA, panels={}, out_path=out)  # relê -> no-op
    assert len(r1["confirmacoes"]) == 1 and r2["confirmacoes"] == []


# ───────────────────────── gate da mesa ─────────────────────────
def _spec(signal, bars=24):
    return {"signal": signal, "signal_params": {}, "filter": "nenhum", "filter_params": {},
            "side": "long", "exit": {"type": "horizonte", "bars": bars}, "universe": "todos",
            "fee_bps_roundtrip": 10, "slippage_bps": 2}


def test_mesa_recusa_cemiterio_dedup_e_catalogo(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    _disc(p, "funding_flip", is_cand=False)             # rejeitada -> cemitério
    _disc(p, "reacao_nivel", is_cand=True)              # candidata -> no journal, viva
    recs = schema.read_journal(p)

    ok, motivo = mesa.pode_congelar(_spec("funding_flip"), recs)
    assert not ok and "cemiterio" in motivo             # morta

    ok, motivo = mesa.pode_congelar(_spec("reacao_nivel"), recs)
    assert not ok and "dedup" in motivo                 # já registrada (viva, mas duplicada)

    ok, motivo = mesa.pode_congelar(_spec("oi_preco_div"), recs)
    assert ok                                           # nova, viva, no catálogo

    ok, motivo = mesa.pode_congelar(_spec("sinal_inexistente"), recs)
    assert not ok and "catalogo" in motivo              # fora do catálogo


def test_cemiterio_so_pega_mortas(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    _disc(p, "funding_flip", is_cand=False)             # rejeitada
    _disc(p, "reacao_nivel", is_cand=True)              # candidata (viva)
    _disc(p, "oi_preco_div", is_cand=False, n=12)       # dado_insuficiente (NÃO é cemitério)
    cem = mesa.cemiterio(schema.read_journal(p))
    from research.gerador_prereg import catalogo as cat
    assert cat.spec_signature(_spec("funding_flip")) in cem
    assert cat.spec_signature(_spec("reacao_nivel")) not in cem
    assert cat.spec_signature(_spec("oi_preco_div")) not in cem   # dado_insuf re-dimensionável
