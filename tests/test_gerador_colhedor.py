"""Colhedor mecânico — julgamento forward-only, BH-FDR por batch, idempotência.

Tudo sintético: panel em escada (determinístico), nunca toca o bot.db. O dado real
forward só é tocado no marco, pelo cron — aqui validamos a MECÂNICA (o teu princípio
do verificador: ver NO-GO sintético não contamina; stealth fabricaria GO)."""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from research.gerador_prereg import colhedor, schema  # noqa: E402

CREATED = "2026-06-18T00:00:00+00:00"
CORTE = schema.epoch_of("2026-06-19T00:00:00+00:00")
PANEL_START = schema.epoch_of("2026-06-20T00:00:00+00:00")   # > CORTE => forward pega tudo
HOJE_VENCIDO = dt.date(2026, 8, 1)


def _panel_escada(n=60, start=PANEL_START, subindo=True):
    close = np.arange(10, 10 + n, dtype=float)
    if not subindo:
        close = close[::-1].copy()
    open_ = close - 0.5 if subindo else close + 0.5   # verde se sobe, vermelho se desce
    idx = [start + i * 3600 for i in range(n)]
    df = pd.DataFrame({"open": open_, "high": np.maximum(open_, close),
                       "low": np.minimum(open_, close), "close": close,
                       "volume": np.ones(n)}, index=idx)
    df["ret_1h"] = df["close"].pct_change()
    return {"AAA": df}


def _rec(rec_id, n_no_batch, modo, n_min=5, marco="2026-08-01", batch="B-T"):
    r = schema.new_frozen(rec_id=rec_id, created_at=CREATED, batch_id=batch,
                          n_no_batch=n_no_batch, hypothesis="h", motivation="m",
                          signal="sequencia_candles", signal_params={"n": 3, "modo": modo},
                          filter_name="nenhum", filter_params={}, side="auto", bars=4,
                          universe="todos", corte_ts=CORTE, marco=marco)
    r["forward"]["n_min"] = n_min
    return r


def test_forward_panels_corta_pre_corte():
    df = _panel_escada(n=80)["AAA"]
    idx = list(df.index)
    fp = colhedor._forward_panels({"X": df}, corte_ts=idx[40])
    assert fp["X"].index.min() == idx[40]
    assert len(fp["X"]) == 40   # só o dado >= corte


def test_go_e_nogo_no_mesmo_batch(tmp_path):
    p = tmp_path / "journal.jsonl"
    schema.append(str(p), _rec("PR-1", 1, "continuacao"))  # long em alta => ganha
    schema.append(str(p), _rec("PR-2", 2, "reversao"))     # short em alta => perde
    out = colhedor.colher(journal_path=str(p), panels=_panel_escada(), hoje=HOJE_VENCIDO,
                          out_path=str(tmp_path / "res.json"), load=False)
    assert out["batches"]["B-T"]["veredito"] == "GO-INVESTIGAR"
    back = {r["id"]: r for r in schema.read_journal(str(p))}
    assert back["PR-1"]["status"] == "judged"
    assert back["PR-1"]["verdict"]["is_candidato"] is True
    assert back["PR-1"]["verdict"]["expectancy_net_bps"] > 0
    assert back["PR-2"]["verdict"]["is_candidato"] is False
    assert back["PR-2"]["verdict"]["expectancy_net_bps"] < 0


def test_dado_insuficiente_quando_n_abaixo_do_minimo(tmp_path):
    p = tmp_path / "journal.jsonl"
    schema.append(str(p), _rec("PR-1", 1, "continuacao", n_min=1000))  # nunca atinge
    out = colhedor.colher(journal_path=str(p), panels=_panel_escada(), hoje=HOJE_VENCIDO,
                          out_path=str(tmp_path / "res.json"), load=False)
    assert out["batches"]["B-T"]["veredito"] == "DADO-INSUFICIENTE"
    assert out["candidatos"] == []


def test_marco_futuro_nao_julga(tmp_path):
    p = tmp_path / "journal.jsonl"
    schema.append(str(p), _rec("PR-1", 1, "continuacao", marco="2030-01-01"))
    out = colhedor.colher(journal_path=str(p), panels=_panel_escada(), hoje=HOJE_VENCIDO,
                          out_path=str(tmp_path / "res.json"), load=False)
    assert out["n_julgados"] == 0
    assert schema.read_journal(str(p))[0]["status"] == "frozen"   # intacto


def test_idempotencia(tmp_path):
    p = tmp_path / "journal.jsonl"
    schema.append(str(p), _rec("PR-1", 1, "continuacao"))
    r1 = colhedor.colher(journal_path=str(p), panels=_panel_escada(), hoje=HOJE_VENCIDO,
                         out_path=str(tmp_path / "res.json"), load=False)
    snap = schema.read_journal(str(p))
    r2 = colhedor.colher(journal_path=str(p), panels=_panel_escada(), hoje=HOJE_VENCIDO,
                         out_path=str(tmp_path / "res.json"), load=False)
    assert r1["n_julgados"] == 1
    assert r2["n_julgados"] == 0                       # nada re-julgado
    assert schema.read_journal(str(p)) == snap         # journal inalterado na 2ª
