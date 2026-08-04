"""Julgador read-only da Fase F maker-fill — critérios selados em 2026-06-10."""
from __future__ import annotations

import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(_REPO, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(_REPO, "scripts"))

import judge_maker_fill_forward as judge  # noqa: E402


def _row(symbol, maker, taker, filled=True, fixture=False, gross=None, mfe=None):
    row = {
        "id": 1,
        "symbol": symbol,
        "direction": "LONG",
        "signal_ts": "2026-06-20 12:00:00",
        "candle_open_ts": 1776254400 if fixture else 1781956800,
        "limit_price": 85000.0 if fixture else 100.0,
        "sl_price": 84500.0 if fixture else 99.0,
        "tp1_price": 85800.0 if fixture else 101.0,
        "tp2_price": 86500.0 if fixture else 102.0,
        "status": "closed" if filled else "no_fill",
        "net_pnl_pct": maker if filled else 0.0,
        "taker_net_pnl_pct": taker,
        "created_at": "2026-06-20T12:00:00+00:00",
    }
    # Campos anexados pelo pareamento de load_and_validate (métricas §6)
    if gross is not None:
        row["taker_gross_pnl_pct"] = gross
    if mfe is not None:
        row["taker_mfe_pct"] = mfe
    return row


def test_remove_fixture_sintetica_conhecida_sem_filtrar_resultado():
    real = _row("BTCUSDT", 1.0, 0.8)
    fake = _row("BTCUSDT", 0.0, 0.8, filled=False, fixture=True)
    clean, removed = judge.clean_rows([fake, real])
    assert clean == [real]
    assert removed == 1


def test_go_exige_todos_os_cinco_criterios():
    rows = []
    # 60 trades, 48 fills; ganhos e perdas dão PF > 1.15 nos dois símbolos.
    for symbol in ("BTCUSDT", "ETHUSDT"):
        rows += [_row(symbol, 1.0, 0.5, True) for _ in range(18)]
        rows += [_row(symbol, -0.5, -0.6, True) for _ in range(6)]
        rows += [_row(symbol, 0.0, -0.2, False) for _ in range(6)]
    p = judge.evaluate(rows)
    assert p["veredito"] == "GO"
    assert all(c["pass"] for c in p["criterios"].values())


def test_pf_baixo_produz_no_go_mesmo_com_fill_suficiente():
    rows = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        rows += [_row(symbol, 0.5, -0.2, True) for _ in range(10)]
        rows += [_row(symbol, -1.0, -0.2, True) for _ in range(15)]
        rows += [_row(symbol, 0.0, 1.0, False) for _ in range(5)]
    p = judge.evaluate(rows)
    assert p["criterios"]["c1_fill_rate"]["pass"] is True
    assert p["criterios"]["c2_pf_agregado"]["pass"] is False
    assert p["veredito"] == "NO-GO"


def test_amostra_menor_50_e_inconclusiva():
    rows = [_row("BTCUSDT", 1.0, 0.5, True) for _ in range(20)]
    rows += [_row("ETHUSDT", -0.2, -0.3, True) for _ in range(20)]
    assert judge.evaluate(rows)["veredito"] == "INCONCLUSIVO"


def test_metricas_secao6_gross_e_mfe_dos_perdidos():
    """§6 exige sempre reportar: PnL bruto médio fill vs no-fill + MFE dos perdidos."""
    rows = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        rows += [_row(symbol, 1.0, 0.5, True, gross=0.6) for _ in range(25)]
        # perdidos: MFE 2.0 / 4.0 / 0.5 => média 13/6, mediana 2.0, max 4.0
        rows += [
            _row(symbol, 0.0, 1.0, False, gross=1.1, mfe=2.0),
            _row(symbol, 0.0, 3.0, False, gross=3.1, mfe=4.0),
            _row(symbol, 0.0, -0.4, False, gross=-0.3, mfe=0.5),
        ]
    sa = judge.evaluate(rows)["selecao_adversa"]
    assert sa["taker_gross_medio_quando_maker_preenche"] == 0.6
    assert abs(sa["taker_gross_medio_quando_maker_nao_preenche"] - 1.3) < 1e-9
    mfe = sa["mfe_dos_perdidos_pct"]
    assert mfe["n"] == 6
    assert abs(mfe["media"] - round(13 / 6, 6)) < 1e-9
    assert mfe["mediana"] == 2.0
    assert mfe["max"] == 4.0


def test_metricas_secao6_ausentes_viram_none_sem_quebrar():
    """Linhas sem os campos pareados (ex.: sintéticas) não fabricam métrica."""
    rows = [_row("BTCUSDT", 1.0, 0.5, True) for _ in range(30)]
    rows += [_row("ETHUSDT", -0.2, -0.3, True) for _ in range(30)]
    sa = judge.evaluate(rows)["selecao_adversa"]
    assert sa["taker_gross_medio_quando_maker_preenche"] is None
    assert sa["taker_gross_medio_quando_maker_nao_preenche"] is None
    assert sa["mfe_dos_perdidos_pct"] is None


def test_recusa_linha_nao_resolvida_ou_sem_pareamento():
    pending = _row("BTCUSDT", 0.0, 0.1)
    pending["status"] = "pending"
    try:
        judge.evaluate([pending] * 60)
    except ValueError as e:
        assert "não resolvidas" in str(e)
    else:
        raise AssertionError("deveria recusar pending")

    missing = _row("BTCUSDT", 0.0, None, False)
    try:
        judge.evaluate([missing] * 60)
    except ValueError as e:
        assert "sem pareamento" in str(e)
    else:
        raise AssertionError("deveria recusar taker ausente")
