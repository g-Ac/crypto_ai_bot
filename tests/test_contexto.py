"""Testes do Contexto (termometro do mercado). Foco: sintetizador PURO + parser F&G injetavel.

Regra de ouro validada aqui: o clima e DESCRITIVO + disciplina, NUNCA previsao de direcao.
"""
import contexto


# ─────────────────────── Fear & Greed (parser, sem rede) ───────────────────────

def _fake_fng(value, label):
    return lambda: {"data": [{"value": str(value), "value_classification": label}]}


def test_fear_greed_parseia_value_e_label():
    out = contexto.fear_greed(_fetch=_fake_fng(72, "Greed"))
    assert out == {"value": 72, "label": "Greed"}


def test_fear_greed_value_vira_int():
    out = contexto.fear_greed(_fetch=_fake_fng("15", "Extreme Fear"))
    assert out["value"] == 15 and isinstance(out["value"], int)


def test_fear_greed_json_quebrado_nao_estoura():
    # payload sem 'data' -> nao levanta, cai no cache (None aqui)
    contexto._FNG_CACHE.update(ts=0.0, data=None)
    assert contexto.fear_greed(_fetch=lambda: {"erro": "x"}) is None


def test_fear_greed_usa_cache_velho_se_falhar():
    contexto._FNG_CACHE.update(ts=0.0, data={"value": 50, "label": "Neutral"})
    # fetch estoura -> devolve o cache antigo em vez de None
    def _boom():
        raise RuntimeError("rede caiu")
    assert contexto.fear_greed(_fetch=_boom) == {"value": 50, "label": "Neutral"}
    contexto._FNG_CACHE.update(ts=0.0, data=None)  # limpa p/ nao vazar entre testes


# ─────────────────────── _clima_frase (disciplina, nao previsao) ───────────────────────

def test_frase_faca_caindo_com_longs_liquidando():
    ctx = {"btc_ret_24h": -4.0, "liq_btc": {"dominant_side": "LONG"}, "fng": {"value": 20}}
    frase = contexto._clima_frase(ctx)
    assert "faca" in frase.lower()
    # nunca preve direcao
    assert "vai subir" not in frase.lower() and "vai cair" not in frase.lower()


def test_frase_squeeze_de_alta_com_shorts_liquidando():
    ctx = {"btc_ret_24h": 3.5, "liq_btc": {"dominant_side": "SHORT"}, "fng": {"value": 65}}
    frase = contexto._clima_frase(ctx)
    assert "squeeze" in frase.lower() and "não corre atrás" in frase


def test_frase_medo_extremo_nao_e_sinal_de_compra():
    ctx = {"btc_ret_24h": 0.2, "liq_btc": {}, "fng": {"value": 12}}
    frase = contexto._clima_frase(ctx)
    assert "não é sinal de compra" in frase.lower() or "nao e sinal de compra" in frase.lower()


def test_frase_ganancia_extrema_protege_lucro():
    ctx = {"btc_ret_24h": 0.5, "liq_btc": {}, "fng": {"value": 82}}
    frase = contexto._clima_frase(ctx)
    assert "proteger lucro" in frase.lower()


def test_frase_sem_extremo_segue_a_regua():
    ctx = {"btc_ret_24h": 0.3, "liq_btc": {}, "fng": {"value": 50}}
    frase = contexto._clima_frase(ctx)
    assert "régua" in frase.lower() or "regua" in frase.lower()


def test_frase_nunca_promete_direcao_em_nenhum_ramo():
    proibidas = ["vai subir", "vai cair", "compra agora", "vende agora", "garantido"]
    cenarios = [
        {"btc_ret_24h": -5, "liq_btc": {"dominant_side": "LONG"}, "fng": {"value": 10}},
        {"btc_ret_24h": 5, "liq_btc": {"dominant_side": "SHORT"}, "fng": {"value": 90}},
        {"btc_ret_24h": 0, "liq_btc": {}, "fng": {"value": 50}},
    ]
    for ctx in cenarios:
        frase = contexto._clima_frase(ctx).lower()
        assert not any(p in frase for p in proibidas)


# ─────────────────────── format_clima (render, puro) ───────────────────────

def _ctx_completo():
    return {
        "btc_ret_24h": -3.2,
        "funding_btc": {"funding_rate": 0.00012},
        "liq_btc": {"symbol": "BTCUSDT", "dominant_side": "LONG", "total_usd": 42_000_000},
        "breadth": {"up": 3, "total": 10, "pct_up": 30.0},
        "fng": {"value": 22, "label": "Extreme Fear"},
    }


def test_format_mostra_todos_componentes():
    txt = contexto.format_clima(_ctx_completo())
    assert "BTC 24h" in txt and "-3.2%" in txt
    assert "Amplitude" in txt and "3/10" in txt
    assert "Funding" in txt and "+0.012%" in txt      # 0.00012 * 100
    assert "liquidando LONGS" in txt and "$42.0M" in txt
    assert "Fear &amp; Greed" in txt and "22" in txt


def test_format_marca_leitura_nao_previsao():
    txt = contexto.format_clima(_ctx_completo())
    assert "leitura, não previsão" in txt


def test_format_tolera_dados_faltando():
    # so BTC disponivel; resto ausente nao deve estourar
    txt = contexto.format_clima({"btc_ret_24h": 1.5})
    assert "BTC 24h" in txt
    assert "Funding" not in txt and "Liquidação" not in txt


def test_format_funding_negativo_marca_shorts_pagando():
    ctx = _ctx_completo()
    ctx["funding_btc"] = {"funding_rate": -0.0003}
    txt = contexto.format_clima(ctx)
    assert "shorts pagando" in txt


def test_format_liquidacao_short_marca_squeeze():
    ctx = _ctx_completo()
    ctx["liq_btc"] = {"symbol": "BTCUSDT", "dominant_side": "SHORT", "total_usd": 5_000_000}
    txt = contexto.format_clima(ctx)
    assert "liquidando SHORTS" in txt and "squeeze" in txt


# ─────────────────────── cmd_clima (fio do comando) ───────────────────────

def test_cmd_clima_usa_ctx_injetado():
    txt = contexto.cmd_clima(_ctx=_ctx_completo())
    assert "Contexto do mercado" in txt and "BTC 24h" in txt
