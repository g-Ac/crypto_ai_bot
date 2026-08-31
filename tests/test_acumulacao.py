"""Testes do modulo de Acumulacao (comprar qualidade com regra congelada, horizonte longo).

Foco nas invariantes que impedem autoengano:
  - contexto e DESCRITIVO (drawdown/percentil/media), nunca palpite de direcao
  - a simulacao NAO enxerga o futuro (anti-lookahead) — a falha mais cara do projeto
  - a comparacao contra DCA e justa: mesmo dinheiro, mesma janela, caixa contabilizado
"""
import sqlite3

import pytest

import acumulacao as ac


# ─────────────────────── contexto (puro, descritivo) ───────────────────────

def test_drawdown_zero_quando_no_topo():
    assert ac.drawdown_do_topo([10, 20, 30]) == pytest.approx(0.0)


def test_drawdown_mede_queda_do_topo():
    # topo 100, atual 70 -> 30% abaixo
    assert ac.drawdown_do_topo([50, 100, 70]) == pytest.approx(30.0)


def test_drawdown_respeita_janela():
    # janela=2 enxerga so [100, 70]; o 200 antigo fica fora
    assert ac.drawdown_do_topo([200, 100, 70], janela=2) == pytest.approx(30.0)


def test_drawdown_sem_dado_retorna_none():
    assert ac.drawdown_do_topo([]) is None


def test_percentil_no_topo_e_100():
    assert ac.percentil_preco([1, 2, 3, 4, 10]) == pytest.approx(80.0)


def test_percentil_no_fundo_e_zero():
    assert ac.percentil_preco([10, 9, 8, 1]) == pytest.approx(0.0)


def test_distancia_media_none_se_falta_dado():
    assert ac.distancia_media([1, 2, 3], n=200) is None


def test_distancia_media_positiva_acima_da_media():
    # media de [10,10,10,10] = 10; atual 10 -> 0%. Com 20 no fim, media sobe
    assert ac.distancia_media([10, 10, 10, 20], n=4) == pytest.approx(60.0)


def test_contexto_ativo_devolve_retrato_sem_opiniao():
    ctx = ac.contexto_ativo([100, 80])
    assert ctx["preco"] == 80 and ctx["dias"] == 2
    assert ctx["drawdown_topo_pct"] == pytest.approx(20.0)
    # nada de "compre"/"venda"/"vai subir" no retrato
    assert set(ctx) == {"preco", "dias", "drawdown_topo_pct", "percentil",
                        "dist_media_200d_pct"}


# ─────────────────────── regua congelada ───────────────────────

def test_valida_regra_rejeita_tipo_desconhecido():
    assert ac.valida_regra({"tipo": "adivinhar"})


def test_valida_regra_rejeita_limiar_fora_de_faixa():
    assert ac.valida_regra({"tipo": "drawdown", "limiar_pct": 150})


def test_regra_invalida_nunca_dispara_compra():
    out = ac.avalia_regra({"drawdown_topo_pct": 90.0}, {"tipo": "drawdown"})
    assert out["bateu"] is False


def test_regra_drawdown_dispara_no_limiar():
    ctx = {"drawdown_topo_pct": 30.0}
    assert ac.avalia_regra(ctx, {"tipo": "drawdown", "limiar_pct": 30})["bateu"] is True


def test_regra_drawdown_nao_dispara_acima_do_limiar():
    ctx = {"drawdown_topo_pct": 12.0}
    assert ac.avalia_regra(ctx, {"tipo": "drawdown", "limiar_pct": 30})["bateu"] is False


def test_regra_sempre_e_o_dca():
    assert ac.avalia_regra({}, {"tipo": "sempre"})["bateu"] is True


# ─────────────────────── simulacao ───────────────────────

def _serie(precos, ano=2024):
    """Uma serie mensal simples: 1 ponto por mes (o aporte entra em cada um)."""
    datas = [f"{ano + i // 12:04d}-{i % 12 + 1:02d}-01" for i in range(len(precos))]
    return datas, list(precos)


def test_dca_compra_todo_mes():
    datas, closes = _serie([100] * 6)
    r = ac.simula(datas, closes, {"tipo": "sempre"}, aporte=100, fee_pct=0)
    assert r["n_compras"] == 6
    assert r["investido"] == pytest.approx(600.0)
    assert r["unidades"] == pytest.approx(6.0)


def test_preco_constante_devolve_o_investido():
    datas, closes = _serie([100] * 6)
    r = ac.simula(datas, closes, {"tipo": "sempre"}, aporte=100, fee_pct=0)
    assert r["valor_final"] == pytest.approx(600.0)
    assert r["retorno_pct"] == pytest.approx(0.0)


def test_fee_reduz_unidades_compradas():
    datas, closes = _serie([100] * 3)
    com = ac.simula(datas, closes, {"tipo": "sempre"}, aporte=100, fee_pct=1.0)
    sem = ac.simula(datas, closes, {"tipo": "sempre"}, aporte=100, fee_pct=0.0)
    assert com["unidades"] < sem["unidades"]


def test_regra_que_nunca_dispara_fica_tudo_em_caixa():
    # preco so sobe -> drawdown sempre 0 -> limiar de 50% nunca bate
    datas, closes = _serie([10, 20, 30, 40])
    r = ac.simula(datas, closes, {"tipo": "drawdown", "limiar_pct": 50}, aporte=100, fee_pct=0)
    assert r["n_compras"] == 0
    assert r["unidades"] == 0
    assert r["caixa"] == pytest.approx(400.0)
    assert r["valor_final"] == pytest.approx(400.0)   # caixa conta no valor final


def test_caixa_acumula_e_entra_de_uma_vez_quando_a_regra_bate():
    # sobe 3 meses (nao compra), despenca no 4o (compra tudo)
    datas, closes = _serie([100, 200, 300, 120])
    r = ac.simula(datas, closes, {"tipo": "drawdown", "limiar_pct": 50}, aporte=100, fee_pct=0)
    assert r["n_compras"] == 1
    assert r["compras"][0]["valor"] == pytest.approx(400.0)   # os 4 aportes juntos
    assert r["caixa"] == pytest.approx(0.0)


def test_simulacao_nao_enxerga_o_futuro():
    """Anti-lookahead: a decisao do dia i nao pode mudar por causa de dado depois de i.

    Prefixo comum -> as compras feitas no prefixo tem que ser IDENTICAS, mesmo que a
    serie longa termine num crash gigante que mudaria o topo se houvesse vazamento.
    """
    curta = _serie([100, 200, 300, 120])
    longa = _serie([100, 200, 300, 120, 1000, 50])
    regra = {"tipo": "drawdown", "limiar_pct": 50}
    r_curta = ac.simula(*curta, regra, aporte=100, fee_pct=0)
    r_longa = ac.simula(*longa, regra, aporte=100, fee_pct=0)
    assert r_longa["compras"][:len(r_curta["compras"])] == r_curta["compras"]


def test_simula_rejeita_regra_invalida():
    datas, closes = _serie([100, 100])
    with pytest.raises(ValueError):
        ac.simula(datas, closes, {"tipo": "chute"}, aporte=100)


# ─────────────────────── benchmark vs DCA ───────────────────────

def test_dca_comparado_consigo_mesmo_empata():
    datas, closes = _serie([100, 90, 110, 95])
    out = ac.compara_com_dca(datas, closes, {"tipo": "sempre"}, aporte=100, fee_pct=0)
    assert out["diferenca"] == pytest.approx(0.0)
    assert out["veredito"] == "PERDE-PRO-DCA"   # empate nao e vitoria: > 0 exigido


def test_veredito_perde_pro_dca_quando_a_regra_fica_de_fora_da_alta():
    # so sobe: a regra de drawdown nunca compra e fica no caixa enquanto o DCA capitaliza
    datas, closes = _serie([10, 20, 30, 40, 50, 60])
    out = ac.compara_com_dca(datas, closes, {"tipo": "drawdown", "limiar_pct": 40},
                             aporte=100, fee_pct=0)
    assert out["veredito"] == "PERDE-PRO-DCA"
    assert out["regra"]["n_compras"] == 0


def test_veredito_bate_dca_quando_a_regra_compra_o_fundo():
    # sobe forte e desaba: comprar so no fundo acumula mais unidades que o DCA
    datas, closes = _serie([100, 300, 500, 100, 120, 140])
    out = ac.compara_com_dca(datas, closes, {"tipo": "drawdown", "limiar_pct": 60},
                             aporte=100, fee_pct=0)
    assert out["veredito"] == "BATE-DCA"
    assert out["regra"]["unidades"] > out["dca"]["unidades"]


def test_comparacao_usa_a_mesma_janela_e_o_mesmo_dinheiro():
    datas, closes = _serie([100, 150, 80, 90])
    out = ac.compara_com_dca(datas, closes, {"tipo": "drawdown", "limiar_pct": 30},
                             aporte=100, fee_pct=0)
    assert out["regra"]["investido"] == out["dca"]["investido"]
    assert out["janela"] == (datas[0], datas[-1])


# ─────────────────────── persistencia ───────────────────────

def test_salvar_diarios_e_idempotente(tmp_path):
    db = str(tmp_path / "t.db")
    rows = [{"symbol": "BTCUSDT", "data": "2026-01-01", "close": 100.0,
             "high": 110.0, "low": 90.0, "volume_usd": 1e6}]
    assert ac.salvar_diarios(rows, db_path=db) == 1
    assert ac.salvar_diarios(rows, db_path=db) == 0      # re-rodar nao duplica
    datas, closes = ac.ler_serie("BTCUSDT", db_path=db)
    assert datas == ["2026-01-01"] and closes == [100.0]


def test_ler_serie_ordena_por_data(tmp_path):
    db = str(tmp_path / "t.db")
    rows = [{"symbol": "ETHUSDT", "data": d, "close": c, "high": c, "low": c,
             "volume_usd": 1.0}
            for d, c in [("2026-01-03", 3.0), ("2026-01-01", 1.0), ("2026-01-02", 2.0)]]
    ac.salvar_diarios(rows, db_path=db)
    datas, closes = ac.ler_serie("ETHUSDT", db_path=db)
    assert closes == [1.0, 2.0, 3.0]


def test_baixar_diarios_parseia_klines_sem_rede():
    # formato real da Binance: [open_time, o, h, l, c, vol, close_time, quote_vol, ...]
    fake = [[1735689600000, "1", "120", "80", "100", "5", 0, "1000000", 0, "0", "0", "0"]]
    rows = ac.baixar_diarios("BTCUSDT", _fetch=lambda: fake)
    assert rows == [{"symbol": "BTCUSDT", "data": "2025-01-01", "close": 100.0,
                     "high": 120.0, "low": 80.0, "volume_usd": 1000000.0}]


def test_fatos_do_ativo_da_fatos_nao_veredito(tmp_path):
    db = str(tmp_path / "t.db")
    rows = [{"symbol": "BTCUSDT", "data": f"2026-01-0{i}", "close": 100.0, "high": 100.0,
             "low": 100.0, "volume_usd": 2e6} for i in range(1, 4)]
    ac.salvar_diarios(rows, db_path=db)
    f = ac.fatos_do_ativo("BTCUSDT", db_path=db)
    assert f["dias_de_historia"] == 3
    assert f["primeiro_dia"] == "2026-01-01"
    assert f["volume_diario_medio_usd"] == pytest.approx(2e6)


# ─────────────────────── walk-forward (a trava anti-cherry-pick) ───────────────────────

def _serie_diaria(precos):
    """Serie diaria a partir de 2018-01-01 (o walk-forward corta por dia, nao por mes)."""
    from datetime import date, timedelta
    d0 = date(2018, 1, 1)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(len(precos))], list(precos)


def test_robustez_sem_dado_suficiente_nao_inventa_veredito():
    datas, closes = _serie_diaria([100] * 50)
    out = ac.robustez_por_janela(datas, closes, {"tipo": "drawdown", "limiar_pct": 30})
    assert out["veredito"] == "SEM-DADO" and out["n"] == 0


def test_robustez_gera_varias_janelas_deslizantes():
    datas, closes = _serie_diaria([100 + (i % 200) for i in range(365 * 6)])
    out = ac.robustez_por_janela(datas, closes, {"tipo": "drawdown", "limiar_pct": 30}, anos=3)
    assert out["n"] >= 3
    assert all(j["de"] < j["ate"] for j in out["janelas"])


def test_regra_que_perde_na_maioria_e_nao_robusta():
    # preco so sobe: a regra de drawdown nunca compra e perde o bull inteiro
    datas, closes = _serie_diaria([100 + i for i in range(365 * 6)])
    out = ac.robustez_por_janela(datas, closes, {"tipo": "drawdown", "limiar_pct": 50}, anos=3)
    assert out["veredito"] == "NAO-ROBUSTA"
    assert out["taxa_vitoria"] < 0.5


def test_dca_contra_ele_mesmo_nunca_e_robusta():
    """Empate nao vira GO — a regra tem que GANHAR, nao empatar."""
    datas, closes = _serie_diaria([100 + (i % 300) for i in range(365 * 6)])
    out = ac.robustez_por_janela(datas, closes, {"tipo": "sempre"}, anos=3)
    assert out["veredito"] == "NAO-ROBUSTA"
    assert out["diferenca_media_pct"] == pytest.approx(0.0)
