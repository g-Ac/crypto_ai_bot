"""Copiloto Modulo B (Vigia de Saida): cerebro puro (avalia_saida) + estado + dedup do loop.
Fixtures em tmp db; price_fn injetavel (sem rede). Nao preve nada — so vigia regras objetivas."""
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import copiloto  # noqa: E402


# ───────────────────────── cerebro (avalia_saida) ─────────────────────────
def test_compra_subindo_sem_recuo_nao_alerta():
    r = copiloto.avalia_saida(entry=100, stop=97, direction="compra", price=103, peak_pct=0)
    assert r["pnl_pct"] == 3.0 and r["peak_pct"] == 3.0 and r["alerta"] is None


def test_trailing_dispara_quando_recua_30pct_do_pico():
    # pico +3%, preco cai pra +2% (recuo 33% > 30%) -> realiza
    r = copiloto.avalia_saida(entry=100, stop=97, direction="compra", price=102, peak_pct=3.0)
    assert r["alerta"] == "trailing" and "imagem" in r["motivo"]


def test_nao_chora_por_ruido_abaixo_do_min_profit():
    # pico +0.5% (< min_profit 1%): recuo nao dispara trailing
    r = copiloto.avalia_saida(entry=100, stop=97, direction="compra", price=100.2, peak_pct=0.5)
    assert r["alerta"] is None


def test_stop_ameacado_dispara():
    r = copiloto.avalia_saida(entry=100, stop=97, direction="compra", price=97.1, peak_pct=2.0)
    assert r["alerta"] == "stop"


def test_venda_short_trailing_e_stop():
    # short: favoravel = preco cai. pico +3% (preco ~97), sobe pra +2% -> trailing
    r = copiloto.avalia_saida(entry=100, stop=103, direction="venda", price=98, peak_pct=3.0)
    assert r["alerta"] == "trailing"
    # stop de short ameacado quando preco SOBE ate o stop
    r2 = copiloto.avalia_saida(entry=100, stop=103, direction="venda", price=103, peak_pct=2.0)
    assert r2["alerta"] == "stop"


# ───────────────────────── estado ─────────────────────────
def test_abrir_infere_direction_e_lista(tmp_path):
    db = str(tmp_path / "b.db")
    a = copiloto.abrir_trade("linkusdt", 7.50, 7.20, db_path=db)   # stop < entry -> compra
    b = copiloto.abrir_trade("ETHUSDT", 3000, 3100, db_path=db)    # stop > entry -> venda
    assert a["direction"] == "compra" and b["direction"] == "venda"
    assert a["symbol"] == "LINKUSDT"
    abertos = copiloto.listar_abertos(db)
    assert len(abertos) == 2
    assert len(copiloto.fechar_trade("LINKUSDT", db_path=db)) == 1   # retorna lista de fechados
    assert len(copiloto.listar_abertos(db)) == 1


# ───────────────────────── loop + dedup ─────────────────────────
def test_checar_dispara_uma_vez_e_rearma_em_novo_pico(tmp_path):
    db = str(tmp_path / "c.db")
    copiloto.abrir_trade("BTCUSDT", 100, 97, db_path=db)   # compra
    price = {"v": 103.0}
    fired = []
    def pf(_sym):
        return price["v"]
    def note(_t, m):
        fired.append(m)

    copiloto.checar_trades(pf, notifier=note, db_path=db)   # +3%, sem recuo -> nada
    assert fired == []
    price["v"] = 102.0
    copiloto.checar_trades(pf, notifier=note, db_path=db)   # recuo -> trailing dispara
    assert len(fired) == 1
    price["v"] = 101.5
    copiloto.checar_trades(pf, notifier=note, db_path=db)   # mesmo pico -> NAO re-dispara (dedup)
    assert len(fired) == 1
    price["v"] = 106.0
    copiloto.checar_trades(pf, notifier=note, db_path=db)   # novo pico +6% -> sem recuo, nada
    price["v"] = 103.0
    copiloto.checar_trades(pf, notifier=note, db_path=db)   # recuo do novo pico -> re-arma
    assert len(fired) == 2


def test_checar_preco_none_nao_quebra(tmp_path):
    db = str(tmp_path / "d.db")
    copiloto.abrir_trade("BTCUSDT", 100, 97, db_path=db)
    out = copiloto.checar_trades(lambda s: None, db_path=db)   # fetch falhou
    assert out == []                                          # pula sem crashar


# ───────────────────────── comandos (parsing) ─────────────────────────
def test_cmd_entrei_com_e_sem_palavra_stop(tmp_path):
    db = str(tmp_path / "e.db")
    r1 = copiloto.cmd_entrei("LINKUSDT 7.50 stop 7.20", _db=db)
    assert "LINKUSDT" in r1 and "compra" in r1
    r2 = copiloto.cmd_entrei("ETHUSDT 3000 3100", _db=db)      # sem 'stop', virou venda
    assert "ETHUSDT" in r2 and "venda" in r2
    assert len(copiloto.listar_abertos(db)) == 2


def test_cmd_entrei_virgula_decimal_e_erro(tmp_path):
    db = str(tmp_path / "f.db")
    assert "compra" in copiloto.cmd_entrei("BTCUSDT 100,5 stop 99,0", _db=db)  # virgula
    assert "Uso:" in copiloto.cmd_entrei("BTCUSDT", _db=db)                    # falta stop
    assert "Uso:" in copiloto.cmd_entrei("", _db=db)                          # vazio


def test_cmd_fechei_e_vigiando_vazio(tmp_path):
    db = str(tmp_path / "g.db")
    copiloto.cmd_entrei("SOLUSDT 150 stop 145", _db=db)
    assert "Encerrei" in copiloto.cmd_fechei("solusdt 152", _db=db)   # preco explicito, sem rede
    assert "Não achei" in copiloto.cmd_fechei("XRPUSDT 1", _db=db)
    assert "Nada sendo vigiado" in copiloto.cmd_vigiando(_db=db)


# ═════════════════════ MODULO A — Guarda de Entrada ═════════════════════
import numpy as np      # noqa: E402
import pandas as pd     # noqa: E402

_PA = dict(copiloto.PARAMS_A, lookback=5)   # janela curta p/ testes compactos


def test_entrada_compra_confirma_quando_faca_parou_e_rsi_sobe():
    lows = [100, 101, 100, 102, 100]        # fundo = 100
    closes = [100, 101, 100, 102, 103]      # +3% do fundo (dentro de 2-6%)
    highs = [105, 106, 104, 108, 110]       # resistencia = 110
    rsis = [30, 35, 32, 40, 45]             # RSI virando pra cima (45 > 40)
    r = copiloto.avalia_entrada(highs, lows, closes, rsis, "compra", _PA)
    assert r["confirmado"] and r["stop"] == 100 and r["alvo"] == 110 and r["rr"] > 2


def test_entrada_nao_confirma_faca_ainda_caindo():
    r = copiloto.avalia_entrada([105]*5, [100]*5, [100, 100, 100, 100, 100.5],
                                [30, 35, 32, 40, 45], "compra", _PA)
    assert not r["confirmado"]              # so +0.5% do fundo -> ainda e a faca


def test_entrada_nao_confirma_se_ja_correu():
    r = copiloto.avalia_entrada([120]*5, [100]*5, [100, 100, 100, 100, 110],
                                [30, 35, 32, 40, 45], "compra", _PA)
    assert not r["confirmado"]              # +10% -> a entrada ja passou (> bounce_max)


def test_entrada_nao_confirma_rsi_caindo():
    r = copiloto.avalia_entrada([110]*5, [100]*5, [100, 100, 100, 102, 103],
                                [45, 40, 38, 36, 34], "compra", _PA)
    assert not r["confirmado"]              # bounce ok, mas RSI ainda caindo


def test_entrada_venda_confirma():
    highs = [100, 99, 100, 98, 97]          # topo = 100
    closes = [100, 99, 100, 98, 97]         # -3% do topo
    lows = [95, 94, 96, 92, 90]             # alvo = 90
    rsis = [70, 65, 68, 60, 55]             # RSI virando pra baixo (55 < 60)
    r = copiloto.avalia_entrada(highs, lows, closes, rsis, "venda", _PA)
    assert r["confirmado"] and r["stop"] == 100 and r["alvo"] == 90


def test_watchlist_crud_e_dedup(tmp_path):
    db = str(tmp_path / "wl.db")
    assert copiloto.adicionar_vigia("LINKUSDT", "compra", db_path=db)["novo"] is True
    assert copiloto.adicionar_vigia("LINKUSDT", "compra", db_path=db)["novo"] is False  # dedup
    assert len(copiloto.listar_vigias(db)) == 1
    assert copiloto.remover_vigia("linkusdt", db_path=db) == 1
    assert copiloto.listar_vigias(db) == []


def _df_bounce_compra(n=40):
    """Cai de 130 a ~100 e faz bounce pra 103 (faca parou); RSI sobe no fim."""
    closes = list(np.linspace(130, 100, n - 4)) + [100.5, 101.5, 102.5, 103.0]
    c = np.array(closes, float)
    return pd.DataFrame({"high": c * 1.003, "low": c * 0.997, "close": c})


def test_checar_entradas_confirma_uma_vez_e_dedup(tmp_path):
    db = str(tmp_path / "ce.db")
    copiloto.adicionar_vigia("BTCUSDT", "compra", db_path=db)
    fired = []
    d1 = copiloto.checar_entradas(lambda s: _df_bounce_compra(),
                                  notifier=lambda t, m: fired.append(m), db_path=db)
    assert len(d1) == 1 and "CONFIRMOU" in d1[0]["msg"]
    # status virou 'confirmado' -> proxima passada nao re-dispara (dedup)
    d2 = copiloto.checar_entradas(lambda s: _df_bounce_compra(), db_path=db)
    assert d2 == []


def test_cmd_vigiar_e_cancelar(tmp_path):
    db = str(tmp_path / "cv.db")
    assert "Vigiando" in copiloto.cmd_vigiar("LINKUSDT compra", _db=db)
    assert "Já tô vigiando" in copiloto.cmd_vigiar("LINKUSDT", _db=db)   # default compra, dedup
    assert "compra" in copiloto.cmd_vigiando(_db=db).lower()             # aparece na lista
    assert "Parei de vigiar" in copiloto.cmd_cancelar("LINKUSDT", _db=db)


# ═════════════════════ Módulo B — força-morrendo por RSI ═════════════════════
def test_forca_compra_dispara_quando_rsi_estica_e_vira():
    rsis = [50, 55, 62, 65, 63]     # esticou (65 >= 60) e agora cai (63 < 65)
    f = copiloto.avalia_forca(rsis, pnl_pct=3.0, peak_pct=4.0, direction="compra")
    assert f["forca"] and "morrendo" in f["motivo"]


def test_forca_nao_dispara_fora_do_lucro():
    f = copiloto.avalia_forca([50, 55, 62, 65, 63], pnl_pct=0.5, peak_pct=0.5, direction="compra")
    assert not f["forca"]           # pico +0.5% < min_profit


def test_forca_nao_dispara_sem_esticar_nem_sem_virar():
    assert not copiloto.avalia_forca([45, 48, 50, 52, 51], 3, 4, "compra")["forca"]  # nao esticou
    assert not copiloto.avalia_forca([50, 55, 62, 64, 66], 3, 4, "compra")["forca"]  # esticou mas sobe


def test_forca_venda_espelho():
    rsis = [50, 45, 38, 35, 37]     # esticou p/ baixo (35 <= 40) e agora sobe (37 > 35)
    assert copiloto.avalia_forca(rsis, 3, 4, "venda")["forca"]


def _df_forca_compra():
    closes = list(np.linspace(90, 106, 29)) + [105.4]   # sobe forte, da uma virada no fim
    c = np.array(closes, float)
    return pd.DataFrame({"high": c * 1.001, "low": c * 0.999, "close": c})


def test_checar_trades_forca_dispara_realiza_antes_do_trailing(tmp_path):
    db = str(tmp_path / "fr.db")
    copiloto.abrir_trade("BTCUSDT", 100, 97, db_path=db)   # compra, stop 97
    fired = []
    # preco 104 = +4% (peak 4; trailing NAO dispara: 4 > 2.8). Candles: RSI esticou+virou -> forca
    d = copiloto.checar_trades(lambda s: 104.0, notifier=lambda t, m: fired.append(m),
                               db_path=db, candles_fn=lambda s: _df_forca_compra())
    assert len(d) == 1 and "força" in d[0]["msg"] and d[0]["alerta"] == "realiza"
    # dedup no mesmo pico -> nao re-dispara
    d2 = copiloto.checar_trades(lambda s: 104.0, db_path=db, candles_fn=lambda s: _df_forca_compra())
    assert d2 == []
