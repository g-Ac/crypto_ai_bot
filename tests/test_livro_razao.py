"""Livro-Razão — reducer de estado (build_book) + alocação cauda-aware (allocate).

Fixtures 100% sintéticas (verdicts hand-crafted no formato do colhedor). Nunca toca
bot.db nem journal real. Prova: estados corretos por assinatura e a fórmula de alocação
zerando exatamente o caso-veneno do VRP (mediana+ com média−).
"""
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from research.gerador_prereg import livro_razao as lr  # noqa: E402


def _spec(signal, bars=24):
    return {"signal": signal, "signal_params": {}, "filter": "nenhum",
            "filter_params": {}, "side": "long", "exit": {"type": "horizonte", "bars": bars},
            "universe": "todos", "fee_bps_roundtrip": 10, "slippage_bps": 2}


def _rec(signal, batch, status="frozen", verdict=None, n_min=30, corte_ts=1000, bars=24):
    return {"id": f"{batch}-{signal}", "batch_id": batch, "status": status,
            "spec": _spec(signal, bars),
            "forward": {"corte_ts": corte_ts, "marco": "2026-08-01", "n_min": n_min},
            "verdict": verdict}


def _v(n, exp, is_cand, passes=True, p=0.03):
    return {"n": n, "expectancy_net_bps": exp, "is_candidato": is_cand,
            "passes_fdr": passes, "p_value": p, "pf": 1.5, "win_rate": 0.5}


# ───────────────────────── build_book: estados ─────────────────────────
def test_frozen_e_em_forward():
    recs = [_rec("s1", "B-1", status="frozen", corte_ts=1000)]
    book = lr.build_book(recs)                       # sem hoje -> frozen
    (e,) = book.values()
    assert e["estado"] == "frozen"
    book2 = lr.build_book(recs, hoje_ts=2000)        # hoje > corte -> em_forward
    assert list(book2.values())[0]["estado"] == "em_forward"


def test_candidata_rejeitada_dado_insuficiente():
    recs = [
        _rec("cand", "B-1", "judged", _v(50, 30.0, True)),
        _rec("rej", "B-1", "judged", _v(50, -5.0, False)),      # n>=n_min, não candidata
        _rec("poucos", "B-1", "judged", _v(12, 40.0, False)),   # n<n_min
    ]
    book = lr.build_book(recs)
    est = {e["disc_id"].split("-", 2)[-1]: e["estado"] for e in book.values()}
    assert est["cand"] == "candidata"
    assert est["rej"] == "rejeitada"
    assert est["poucos"] == "dado_insuficiente"


def test_confirmacao_em_andamento_e_na_carteira():
    # descoberta candidata + confirmação frozen -> em_confirmacao
    recs = [_rec("t", "B-1", "judged", _v(40, 25.0, True)),
            _rec("t", "CONF-20260801", "frozen")]
    assert list(lr.build_book(recs).values())[0]["estado"] == "em_confirmacao"
    # confirmação julgada, candidata, sinal consistente -> na_carteira
    recs2 = [_rec("t", "B-1", "judged", _v(40, 25.0, True)),
             _rec("t", "CONF-20260801", "judged", _v(35, 20.0, True))]
    e = list(lr.build_book(recs2).values())[0]
    assert e["estado"] == "na_carteira"
    assert len(e["forwards"]) == 2                   # descoberta + confirmação


def test_rejeitada_conf_e_dado_insuf_conf():
    # confirmação não-candidata -> rejeitada_conf (terminal)
    recs = [_rec("t", "B-1", "judged", _v(40, 25.0, True)),
            _rec("t", "CONF-20260801", "judged", _v(40, -3.0, False))]
    assert list(lr.build_book(recs).values())[0]["estado"] == "rejeitada_conf"
    # confirmação com n<n_min -> dado_insuf_conf
    recs2 = [_rec("t", "B-1", "judged", _v(40, 25.0, True)),
             _rec("t", "CONF-20260801", "judged", _v(11, 25.0, False))]
    assert list(lr.build_book(recs2).values())[0]["estado"] == "dado_insuf_conf"


def test_na_carteira_exige_sinal_consistente():
    # confirmação candidata MAS descoberta com expectancy<=0 -> NÃO entra (sinal inconsistente)
    recs = [_rec("t", "B-1", "judged", _v(40, -1.0, True)),   # is_candidato mas exp<0 (borda)
            _rec("t", "CONF-20260801", "judged", _v(35, 20.0, True))]
    assert list(lr.build_book(recs).values())[0]["estado"] == "rejeitada_conf"


# ───────────────────────── allocate: fórmula ─────────────────────────
def test_veneno_vrp_mediana_pos_media_neg_zera():
    # muitos +pequenos e uma cauda −enorme: mediana > 0, média < 0 -> w=0
    rets = [10.0] * 40 + [-500.0]
    out = lr.allocate({"veneno": rets})
    a = out["hipoteses"]["veneno"]
    assert a["mu_bps"] < 0 and a["w"] == 0.0
    assert "veto" in a["motivo"]


def test_cauda_gorda_reduz_peso():
    apertada = [30.0] * 50 + [-20.0] * 10       # perdas pequenas -> tail_factor alto
    gorda = [30.0] * 50 + [-200.0] * 10         # cauda gorda -> tail_factor baixo
    a = lr.allocate({"x": apertada})["hipoteses"]["x"]
    b = lr.allocate({"x": gorda})["hipoteses"]["x"]
    assert a["w"] > b["w"] and a["tail_factor"] > b["tail_factor"]


def test_shrink_move_o_peso_de_verdade():
    # mesma FORMA (mesmo tail_factor), n diferente -> shrink move o PESO estritamente,
    # e no regime sub-teto (o mu/dd² antigo saturava e tornava esta asserção vácua).
    dist = [40.0] * 20 + [-10.0] * 5            # n=25
    dist_grande = [40.0] * 200 + [-10.0] * 50   # mesma forma, n=250
    ap = lr._alloc_one(dist)
    gr = lr._alloc_one(dist_grande)
    assert gr["w"] > ap["w"]                    # mais evidência -> aposta ESTRITAMENTE maior
    assert ap["w"] < lr.W_CAP and gr["w"] < lr.W_CAP   # sub-teto: o shrink de fato pesa
    assert ap["shrink"] < gr["shrink"]
    assert abs(ap["tail_factor"] - gr["tail_factor"]) < 1e-9   # mesma forma -> mesmo tail


def test_teto_w_cap():
    forte = [100.0] * 100 + [-1.0] * 5          # edge enorme, cauda mínima
    a = lr.allocate({"x": forte})["hipoteses"]["x"]
    assert a["w"] <= lr.W_CAP + 1e-9


def test_ruin_guard():
    # média positiva, mas a maior perda sozinha > mu*n (apaga o pnl acumulado)
    rets = [5.0] * 30 + [-200.0]                # mu*n = soma ~ -50 ... na verdade mu<0 aqui
    rets = [20.0] * 30 + [-500.0]              # soma=100, mu=100/31; |min|=500 > mu*n=100
    a = lr.allocate({"x": rets})["hipoteses"]["x"]
    assert a["w"] == 0.0 and "ruin" in a["motivo"]


def test_normalizacao_e_caixa():
    forte1 = [100.0] * 100 + [-1.0] * 5
    forte2 = [100.0] * 100 + [-1.0] * 5
    out = lr.allocate({"a": forte1, "b": forte2})   # 2x W_CAP=0.5 -> soma<=1, sem escala
    assert abs(out["sleeve_total"] + out["caixa"] - 1.0) < 1e-9
    assert out["sleeve_total"] <= 1.0 + 1e-9
    assert abs(sum(h["alloc_pct"] for h in out["hipoteses"].values()) - 1.0) < 1e-9


def test_carteira_vazia_valida():
    out = lr.allocate({})
    assert out == {"hipoteses": {}, "sleeve_total": 0.0, "caixa": 1.0}
    # todos zerados também é válido (soma_pct = 0, caixa = 1)
    out2 = lr.allocate({"z": [-1.0] * 40})
    assert out2["sleeve_total"] == 0.0 and out2["caixa"] == 1.0


# ───────────────────────── render (snapshot) ─────────────────────────
import numpy as np      # noqa: E402
import pandas as pd     # noqa: E402


def _mk_panel(closes, start=1_700_000_000):
    idx = [start + i * 3600 for i in range(len(closes))]
    close = np.array(closes, float)
    op = np.r_[close[0], close[:-1]]
    df = pd.DataFrame({"open": op, "high": np.maximum(op, close),
                       "low": np.minimum(op, close), "close": close,
                       "volume": np.ones(len(close))}, index=idx)
    df["ret_1h"] = df["close"].pct_change()
    return df


def _rec_full(signal, params, batch, verdict, bars, corte_ts):
    return {"id": f"{batch}-{signal}", "batch_id": batch, "status": "judged",
            "spec": {"signal": signal, "signal_params": params, "filter": "nenhum",
                     "filter_params": {}, "side": "long",
                     "exit": {"type": "horizonte", "bars": bars}, "universe": "todos",
                     "fee_bps_roundtrip": 10, "slippage_bps": 2},
            "forward": {"corte_ts": corte_ts, "marco": "2026-08-01", "n_min": 30},
            "verdict": verdict}


def test_render_carteira_vazia():
    recs = [_rec("s1", "B-1", "judged", _v(50, -5.0, False))]   # rejeitada -> sem carteira
    snap = lr.render(recs, {})
    assert snap["derived"] is True
    assert snap["sleeve_total"] == 0.0 and snap["caixa"] == 1.0
    assert all("alloc" not in h for h in snap["hipoteses"])


def test_render_membro_na_carteira():
    start = 1_700_000_000
    corte = start - 1
    params = {"n": 3, "modo": "continuacao"}
    disc = _rec_full("sequencia_candles", params, "B-1", _v(40, 25.0, True), 4, corte)
    conf = _rec_full("sequencia_candles", params, "CONF-20260801", _v(35, 20.0, True), 4, corte)
    panels = {"X": _mk_panel([100 * 1.01 ** i for i in range(20)], start)}
    snap = lr.render([disc, conf], panels, hoje_ts=start + 100 * 3600)
    membros = [h for h in snap["hipoteses"] if h["estado"] == "na_carteira"]
    assert len(membros) == 1
    m = membros[0]
    assert "alloc" in m and m["alloc"]["n"] >= 1        # re-mediu trades reais no forward
    assert m["alloc"]["mu_bps"] > 0                     # pooled positivo -> permanece na_carteira
    assert 0.0 <= snap["sleeve_total"] <= 1.0
    assert abs(snap["sleeve_total"] + snap["caixa"] - 1.0) < 1e-9


def test_render_rebaixa_na_carteira_com_pooled_negativo():
    # verdicts dizem candidata (build_book -> na_carteira provisório), MAS o pooled real é
    # negativo: reversao short num painel que só sobe -> o short perde -> mu<0.
    # render finaliza o gate pooled>0 (§4 regra 2) -> rebaixa para rejeitada_conf (cemitério).
    start = 1_700_000_000
    corte = start - 1
    params = {"n": 3, "modo": "reversao"}              # short em up-streak
    disc = _rec_full("sequencia_candles", params, "B-1", _v(40, 25.0, True), 4, corte)
    conf = _rec_full("sequencia_candles", params, "CONF-20260801", _v(35, 20.0, True), 4, corte)
    panels = {"X": _mk_panel([100 * 1.01 ** i for i in range(20)], start)}  # só sobe -> short perde
    snap = lr.render([disc, conf], panels, hoje_ts=start + 100 * 3600)
    (h,) = snap["hipoteses"]
    assert h["alloc"]["mu_bps"] < 0                    # pooled negativo
    assert h["estado"] == "rejeitada_conf"            # rebaixado, NÃO na_carteira
    assert not [x for x in snap["hipoteses"] if x["estado"] == "na_carteira"]
