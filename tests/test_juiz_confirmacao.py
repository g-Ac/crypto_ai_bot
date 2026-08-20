"""Confirmação do Juiz (2º forward EXP-100) — freeze, julgamento e trigger.

Tudo sintético: painéis determinísticos, nunca toca o bot.db. O dado real forward
só é tocado no marco, pelo cron — aqui validamos a MECÂNICA (ver NO-GO sintético
não contamina; stealth fabricaria GO)."""
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if os.path.join(_REPO_ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(_REPO_ROOT, "scripts"))

import juiz_confirmacao_trigger as trig                    # noqa: E402
from research.juiz_forward import confirmacao              # noqa: E402

UTC = dt.timezone.utc
PANEL_START = int(dt.datetime(2026, 8, 4, tzinfo=UTC).timestamp())
CORTE_NO_INICIO = PANEL_START            # painel inteiro é forward
AGORA = dt.datetime(2026, 8, 3, 15, 0, tzinfo=UTC)


def _df(close, funding=None, start=PANEL_START):
    close = np.asarray(close, dtype=float)
    idx = [start + i * 3600 for i in range(len(close))]
    df = pd.DataFrame({"open": close, "high": close, "low": close,
                       "close": close, "volume": np.ones(len(close))}, index=idx)
    df["ret_1h"] = df["close"].pct_change()
    if funding is not None:
        df["funding"] = np.asarray(funding, dtype=float)
    return df


def _panel_momentum_vencedor(n_noise=30, n_ramp=60):
    """Ruído minúsculo e depois rampa forte de +5%/h: momentum_continuacao dispara
    long na rampa e ganha (líquido de fee) em H4."""
    noise = 100 + 0.05 * np.array([1 if i % 2 == 0 else -1 for i in range(n_noise)])
    ramp = 100.0 * 1.05 ** np.arange(1, n_ramp + 1)
    close = np.concatenate([noise, ramp])
    fund = np.concatenate([1e-5 * np.array([1 if i % 2 else -1 for i in range(n_noise)]),
                           np.full(n_ramp, 0.01)])
    return {"AAA": _df(close, funding=fund)}


def _panel_short_perdedor(n_blocos=3):
    """Blocos de flat + salto de +40% (z da banda >= 2 => short) com o preço
    CONTINUANDO a subir: todos os shorts perdem => expectancy < 0 => rejeitada_conf.
    Blocos repetidos porque o z decai rápido (a janela absorve o salto): cada
    episódio rende ~2 entries; 3 blocos => n=6."""
    partes, nivel = [], 100.0
    for _ in range(n_blocos):
        flat = nivel + 0.05 * np.array([1 if i % 2 == 0 else -1 for i in range(28)])
        salto = nivel * 1.4
        subida = salto + (nivel * 0.02) * np.arange(1, 9)
        partes += [flat, [salto], subida]
        nivel = subida[-1]
    close = np.concatenate([np.asarray(p, dtype=float) for p in partes])
    return {"AAA": _df(close)}


def _prereg(labels, corte_ts=CORTE_NO_INICIO, n_min=3, dias_min=1,
            marco="2026-10-03", hashes=None):
    return {
        "schema_version": 1, "created_at": "2026-08-03T00:00:00+00:00",
        "confirms": {"origem": "teste"}, "corte_ts": corte_ts, "marco": marco,
        "regua": {"metric": "expectancy_bps", "threshold": 0.0, "n_min": n_min,
                  "fdr_q": 0.10, "p_method": "bootstrap", "seed": 1,
                  "dias_min_valido": dias_min},
        "cells": [{"exp": "EXP-100", "label": lb,
                   "descoberta": {"n": 9, "expectancy_bps": 9.9, "p_value": 0.009}}
                  for lb in labels],
        "code_hashes": hashes if hashes is not None else confirmacao.code_hashes(),
    }


def _resultado_descoberta(candidatos):
    return {"gerado_em": "2026-08-01T11:05:38+00:00", "corte_forward_ts": 1,
            "dias_forward": 44.4, "veredito": "GO-INVESTIGAR",
            "candidatos": candidatos}


def _cand(label, exp="EXP-100", n=123):
    return {"exp": exp, "label": label, "n": n,
            "expectancy_bps": 81.8, "p_value": 0.0055}


# ───────────────────────── freeze ─────────────────────────

def test_freeze_congela_corte_futuro_e_marco_60d(tmp_path):
    res = tmp_path / "resultado.json"
    res.write_text(json.dumps(_resultado_descoberta([_cand("momentum_continuacao|funding_extremo|todos|H24")])))
    p = confirmacao.freeze(resultado_path=res, prereg_path=tmp_path / "prereg.json",
                           agora=AGORA)
    assert p["corte_ts"] == int(dt.datetime(2026, 8, 4, tzinfo=UTC).timestamp())
    assert p["marco"] == "2026-10-03"                       # corte + 60d
    assert p["corte_ts"] > int(AGORA.timestamp())           # estritamente futuro
    assert len(p["cells"]) == 1
    # dimensionamento pela taxa observada na descoberta (123 em 44.4d -> 60d)
    assert p["cells"][0]["n_esperado_conf"] == pytest.approx(123 / 44.4 * 60, abs=0.1)
    assert set(p["code_hashes"]) == set(confirmacao.HASH_FILES)


def test_freeze_recusa_recongelar(tmp_path):
    res = tmp_path / "resultado.json"
    res.write_text(json.dumps(_resultado_descoberta([_cand("x|nenhum|todos|H4")])))
    confirmacao.freeze(resultado_path=res, prereg_path=tmp_path / "p.json", agora=AGORA)
    with pytest.raises(FileExistsError):
        confirmacao.freeze(resultado_path=res, prereg_path=tmp_path / "p.json",
                           agora=AGORA)


def test_freeze_recusa_sem_candidatos(tmp_path):
    res = tmp_path / "resultado.json"
    res.write_text(json.dumps(_resultado_descoberta([])))
    with pytest.raises(ValueError, match="sem candidatos"):
        confirmacao.freeze(resultado_path=res, prereg_path=tmp_path / "p.json",
                           agora=AGORA)


def test_freeze_recusa_exp_nao_suportado(tmp_path):
    res = tmp_path / "resultado.json"
    res.write_text(json.dumps(_resultado_descoberta(
        [_cand("scorer|H4|xsec", exp="EXP-101")])))
    with pytest.raises(ValueError, match="EXP-100"):
        confirmacao.freeze(resultado_path=res, prereg_path=tmp_path / "p.json",
                           agora=AGORA)


# ───────────────────────── confirmar ─────────────────────────

def test_confirmada_momentum_vencedor():
    p = confirmacao.confirmar(_prereg(["momentum_continuacao|nenhum|todos|H4"]),
                              panels=_panel_momentum_vencedor(), out_path=None)
    (c,) = p["cells"]
    assert c["estado"] == "confirmada" and c["n"] >= 3
    assert c["expectancy_bps"] > 0 and c["passes_fdr"]
    assert p["veredito"] == "CONFIRMADA" and p["n_confirmadas"] == 1
    assert p["code_drift"] == []


def test_filtro_funding_extremo_roda_na_cadeia():
    p = confirmacao.confirmar(
        _prereg(["momentum_continuacao|funding_extremo|todos|H4"]),
        panels=_panel_momentum_vencedor(), out_path=None)
    (c,) = p["cells"]
    assert c["estado"] == "confirmada"     # funding extremo na rampa mantém entries


def test_rejeitada_short_perdedor():
    p = confirmacao.confirmar(_prereg(["mean_reversion_banda|nenhum|todos|H4"]),
                              panels=_panel_short_perdedor(), out_path=None)
    (c,) = p["cells"]
    assert c["n"] >= 3 and c["expectancy_bps"] < 0
    assert c["estado"] == "rejeitada_conf"                  # terminal
    assert p["veredito"] == "NO-GO"


def test_corte_ignora_dado_pre_corte():
    """Rampa inteira ANTES do corte: nada dela pode contar no forward."""
    panels = _panel_momentum_vencedor()
    idx = list(panels["AAA"].index)
    corte_apos_rampa = idx[-1] + 3600
    panels["AAA2"] = panels["AAA"]          # símbolo extra pro painel não ficar vazio
    p = confirmacao.confirmar(
        _prereg(["momentum_continuacao|nenhum|todos|H4"], corte_ts=corte_apos_rampa),
        panels=panels, out_path=None)
    (c,) = p["cells"]
    assert c["n"] == 0
    assert c["estado"] == "dado_insuficiente"
    assert p["veredito"] == "DADO-INSUFICIENTE"


def test_janela_curta_vira_dado_insuficiente():
    """Painel de ~4 dias com dias_min=30: veredito DADO-INSUFICIENTE, não NO-GO
    (falha de dimensionamento, não tese morta — precedente NOTA B-20260701)."""
    p = confirmacao.confirmar(
        _prereg(["momentum_continuacao|nenhum|todos|H4"], dias_min=30),
        panels=_panel_momentum_vencedor(), out_path=None)
    assert p["cells"][0]["estado"] == "dado_insuficiente"
    assert p["veredito"] == "DADO-INSUFICIENTE"


def test_fdr_cohort_exclui_celula_sem_n():
    """Célula de universo memes (símbolo sintético fora de MEMES) tem n=0:
    fica fora do FDR e vira dado_insuficiente; a outra confirma sozinha."""
    p = confirmacao.confirmar(
        _prereg(["momentum_continuacao|nenhum|todos|H4",
                 "momentum_continuacao|nenhum|memes|H4"]),
        panels=_panel_momentum_vencedor(), out_path=None)
    por = {c["label"]: c for c in p["cells"]}
    assert por["momentum_continuacao|nenhum|todos|H4"]["estado"] == "confirmada"
    assert por["momentum_continuacao|nenhum|memes|H4"]["estado"] == "dado_insuficiente"
    assert p["veredito"] == "CONFIRMADA"


def test_code_drift_flagrado_mas_nao_bloqueia():
    hashes = confirmacao.code_hashes()
    hashes["research/juiz_forward/judge.py"] = "0" * 64
    p = confirmacao.confirmar(
        _prereg(["momentum_continuacao|nenhum|todos|H4"], hashes=hashes),
        panels=_panel_momentum_vencedor(), out_path=None)
    assert p["code_drift"] == ["research/juiz_forward/judge.py"]
    assert p["veredito"] == "CONFIRMADA"    # flagra, não bloqueia


def test_label_fora_do_motor_quebra_alto():
    with pytest.raises(RuntimeError, match="ausentes no motor"):
        confirmacao.confirmar(_prereg(["nao_existe|nenhum|todos|H4"]),
                              panels=_panel_momentum_vencedor(), out_path=None)


def test_grava_resultado_json(tmp_path):
    out = tmp_path / "res.json"
    confirmacao.confirmar(_prereg(["momentum_continuacao|nenhum|todos|H4"]),
                          panels=_panel_momentum_vencedor(), out_path=out)
    assert json.loads(out.read_text())["veredito"] == "CONFIRMADA"


# ───────────────────────── trigger ─────────────────────────

def _write_prereg(tmp_path, **kw):
    p = tmp_path / "prereg.json"
    p.write_text(json.dumps(_prereg(["momentum_continuacao|nenhum|todos|H4"], **kw)))
    return p


def test_trigger_prereg_ausente_alerta(tmp_path):
    calls = []
    out = trig.run(prereg_path=tmp_path / "nao_existe.json",
                   flag_path=tmp_path / "flag", hoje=dt.date(2026, 10, 3),
                   notifier=lambda *a, **k: calls.append((a, k)))
    assert out == {"ran": False, "motivo": "prereg_ausente"}
    assert len(calls) == 1 and calls[0][1].get("critical") is True


def test_trigger_recusa_prereg_adulterado(tmp_path):
    prereg = _write_prereg(tmp_path)
    calls = []
    out = trig.run(prereg_path=prereg, flag_path=tmp_path / "flag",
                   hoje=dt.date(2026, 10, 3), expected_prereg_sha256="0" * 64,
                   notifier=lambda *a, **k: calls.append((a, k)))
    assert out == {"ran": False, "motivo": "prereg_adulterado"}
    assert not (tmp_path / "flag").exists()
    assert len(calls) == 1 and calls[0][1].get("critical") is True


def test_prereg_real_casa_com_hash_fixado():
    assert confirmacao._sha256(confirmacao.PREREG_DEFAULT) == trig.PINNED_PREREG_SHA256


def test_trigger_antes_do_marco_nao_roda(tmp_path):
    prereg = _write_prereg(tmp_path, marco="2026-10-03")
    calls = []
    out = trig.run(prereg_path=prereg, flag_path=tmp_path / "flag",
                   hoje=dt.date(2026, 10, 2),
                   notifier=lambda *a, **k: calls.append(a))
    assert out == {"ran": False, "motivo": "antes_do_marco"}
    assert calls == [] and not (tmp_path / "flag").exists()


def test_trigger_flag_e_idempotente(tmp_path):
    prereg = _write_prereg(tmp_path)
    (tmp_path / "flag").write_text("done")
    out = trig.run(prereg_path=prereg, flag_path=tmp_path / "flag",
                   hoje=dt.date(2026, 10, 3), notifier=lambda *a, **k: None)
    assert out == {"ran": False, "motivo": "flag"}


def test_trigger_roda_no_marco_grava_flag_e_notifica(tmp_path):
    prereg = _write_prereg(tmp_path)
    calls = []
    out = trig.run(prereg_path=prereg, flag_path=tmp_path / "flag",
                   panels=_panel_momentum_vencedor(), hoje=dt.date(2026, 10, 3),
                   out_path=str(tmp_path / "res.json"),
                   notifier=lambda *a, **k: calls.append((a, k)))
    assert out["ran"] is True and out["payload"]["veredito"] == "CONFIRMADA"
    assert "CONFIRMADA" in (tmp_path / "flag").read_text()
    assert len(calls) == 1 and calls[0][1].get("critical") is True
    assert json.loads((tmp_path / "res.json").read_text())["n_confirmadas"] == 1


def test_trigger_falha_alerta_e_nao_grava_flag(tmp_path):
    p = tmp_path / "prereg.json"
    p.write_text(json.dumps(_prereg(["nao_existe|nenhum|todos|H4"])))
    calls = []
    with pytest.raises(RuntimeError):
        trig.run(prereg_path=p, flag_path=tmp_path / "flag",
                 panels=_panel_momentum_vencedor(), hoje=dt.date(2026, 10, 3),
                 out_path=str(tmp_path / "res.json"),
                 notifier=lambda *a, **k: calls.append((a, k)))
    assert not (tmp_path / "flag").exists()
    assert len(calls) == 1 and calls[0][1].get("critical") is True
