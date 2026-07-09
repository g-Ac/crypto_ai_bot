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
    assert copiloto.fechar_trade("LINKUSDT", db_path=db) == 1
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
    assert "Encerrei" in copiloto.cmd_fechei("solusdt", _db=db)
    assert "Não achei" in copiloto.cmd_fechei("XRPUSDT", _db=db)
    assert "Nada sendo vigiado" in copiloto.cmd_vigiando(_db=db)
