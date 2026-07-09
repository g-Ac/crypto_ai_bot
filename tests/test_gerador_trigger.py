"""Trigger idempotente do colhedor — decide rodar + notifica. Tudo sintético/mock."""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if os.path.join(_REPO_ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(_REPO_ROOT, "scripts"))

import gerador_prereg_trigger as trig                # noqa: E402
from research.gerador_prereg import schema           # noqa: E402

CREATED = "2026-06-18T00:00:00+00:00"
CORTE = schema.epoch_of("2026-06-19T00:00:00+00:00")
PANEL_START = schema.epoch_of("2026-06-20T00:00:00+00:00")


def _panel(n=60):
    close = np.arange(10, 10 + n, dtype=float)
    open_ = close - 0.5
    idx = [PANEL_START + i * 3600 for i in range(n)]
    df = pd.DataFrame({"open": open_, "high": np.maximum(open_, close),
                       "low": np.minimum(open_, close), "close": close,
                       "volume": np.ones(n)}, index=idx)
    df["ret_1h"] = df["close"].pct_change()
    return {"AAA": df}


def _rec(marco):
    r = schema.new_frozen(rec_id="PR-1", created_at=CREATED, batch_id="B-T", n_no_batch=1,
                          hypothesis="h", motivation="m", signal="sequencia_candles",
                          signal_params={"n": 3, "modo": "continuacao"}, filter_name="nenhum",
                          filter_params={}, side="auto", bars=4, universe="todos",
                          corte_ts=CORTE, marco=marco)
    r["forward"]["n_min"] = 5
    return r


def test_nada_vencido_nao_roda(tmp_path):
    p = tmp_path / "journal.jsonl"
    schema.append(str(p), _rec("2030-01-01"))       # marco no futuro
    calls = []
    out = trig.run(journal_path=str(p), panels=_panel(), hoje=dt.date(2026, 8, 1),
                   out_path=str(tmp_path / "res.json"), notifier=lambda *a: calls.append(a))
    assert out["ran"] is False
    assert calls == []
    assert schema.read_journal(str(p))[0]["status"] == "frozen"   # intacto


def test_vencido_roda_e_notifica(tmp_path):
    p = tmp_path / "journal.jsonl"
    schema.append(str(p), _rec("2026-08-01"))
    calls = []
    out = trig.run(journal_path=str(p), panels=_panel(), hoje=dt.date(2026, 8, 1),
                   out_path=str(tmp_path / "res.json"), notifier=lambda *a: calls.append(a))
    assert out["ran"] is True
    assert out["payload"]["n_julgados"] == 1
    assert len(calls) == 1                            # notificou uma vez
    assert schema.read_journal(str(p))[0]["status"] == "judged"
