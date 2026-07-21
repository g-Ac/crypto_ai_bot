"""Testes do upgrade path do cooldown (fechar_trade com PnL + avalia_cooldown + integracao).

Disciplina do perfil congelado: cooldown apos 2 perdas SEGUIDAS. NAO bloqueia — avisa. O cerebro
avalia_cooldown e puro (lista de fechados + agora injetavel), entao asserts deterministicos.
"""
from datetime import datetime, timedelta, timezone

import pytest

import copiloto

AGORA = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _trade(pnl, horas_atras):
    return {"pnl_pct": pnl, "closed_at": (AGORA - timedelta(hours=horas_atras)).isoformat()}


# ─────────────────────── fechar_trade calcula PnL líquido ───────────────────────

def test_fechar_compra_calcula_pnl_net(tmp_path):
    db = str(tmp_path / "b.db")
    copiloto.abrir_trade("BTCUSDT", 100.0, 97.0, db_path=db)          # compra
    fechados = copiloto.fechar_trade("BTCUSDT", exit_price=102.0, db_path=db, fee_rt_pct=0.10)
    assert len(fechados) == 1
    # gross +2% menos fee 0.10% => +1.90% net
    assert fechados[0]["pnl_pct"] == pytest.approx(1.9, abs=0.001)


def test_fechar_venda_calcula_pnl_net(tmp_path):
    db = str(tmp_path / "b.db")
    copiloto.abrir_trade("ETHUSDT", 100.0, 103.0, db_path=db)         # venda (stop acima)
    fechados = copiloto.fechar_trade("ETHUSDT", exit_price=98.0, db_path=db, fee_rt_pct=0.10)
    # short: 100/98-1 = +2.041% gross, -fee 0.10% => +1.941% net
    assert fechados[0]["pnl_pct"] == pytest.approx(1.941, abs=0.001)


def test_fechar_sem_preco_nao_calcula(tmp_path):
    db = str(tmp_path / "b.db")
    copiloto.abrir_trade("BTCUSDT", 100.0, 97.0, db_path=db)
    fechados = copiloto.fechar_trade("BTCUSDT", db_path=db)           # sem exit_price
    assert fechados[0]["pnl_pct"] is None
    assert len(copiloto.listar_abertos(db)) == 0                      # mas fechou mesmo assim


# ─────────────────────── avalia_cooldown (cérebro puro) ───────────────────────

def test_duas_perdas_seguidas_dentro_da_janela_dispara():
    trades = [_trade(-1.2, 1), _trade(-0.8, 3)]
    r = copiloto.avalia_cooldown(trades, AGORA)
    assert r["consecutive_losses"] == 2 and r["em_cooldown"]


def test_uma_vitoria_zera_a_sequencia():
    trades = [_trade(+2.0, 1), _trade(-0.8, 3), _trade(-1.0, 5)]      # a mais recente e ganho
    r = copiloto.avalia_cooldown(trades, AGORA)
    assert r["consecutive_losses"] == 0 and not r["em_cooldown"]


def test_perda_ganho_perda_conta_so_a_ultima():
    trades = [_trade(-0.5, 1), _trade(+1.0, 3), _trade(-1.0, 5)]      # recente=perda, antes=ganho
    r = copiloto.avalia_cooldown(trades, AGORA)
    assert r["consecutive_losses"] == 1 and not r["em_cooldown"]


def test_cooldown_esfria_depois_da_janela():
    trades = [_trade(-1.2, 30), _trade(-0.8, 33)]                     # 2 perdas mas ha 30h
    r = copiloto.avalia_cooldown(trades, AGORA)
    assert r["consecutive_losses"] == 2 and not r["em_cooldown"]      # esfriou


def test_tres_perdas_seguidas():
    trades = [_trade(-1, 1), _trade(-1, 2), _trade(-1, 3)]
    r = copiloto.avalia_cooldown(trades, AGORA)
    assert r["consecutive_losses"] == 3 and r["em_cooldown"]


def test_trades_sem_pnl_sao_ignorados():
    trades = [{"pnl_pct": None, "closed_at": AGORA.isoformat()}, _trade(-1, 1), _trade(-1, 2)]
    r = copiloto.avalia_cooldown(trades, AGORA)
    assert r["consecutive_losses"] == 2 and r["em_cooldown"]          # o None nao quebra a sequencia


def test_lista_vazia_nao_quebra():
    r = copiloto.avalia_cooldown([], AGORA)
    assert r["consecutive_losses"] == 0 and not r["em_cooldown"]


# ─────────────────────── integração: status + comandos ───────────────────────

def _perder_duas(db):
    # abre e fecha 2 trades perdedores (compra que caiu)
    copiloto.abrir_trade("BTCUSDT", 100.0, 97.0, db_path=db)
    copiloto.fechar_trade("BTCUSDT", exit_price=98.0, db_path=db)     # -2% -0.1 = perda
    copiloto.abrir_trade("ETHUSDT", 100.0, 97.0, db_path=db)
    copiloto.fechar_trade("ETHUSDT", exit_price=99.0, db_path=db)     # -1% -0.1 = perda


def test_status_cooldown_apos_duas_perdas(tmp_path):
    db = str(tmp_path / "b.db")
    _perder_duas(db)
    st = copiloto.status_cooldown(db)
    assert st["consecutive_losses"] == 2 and st["em_cooldown"]


def test_risco_mostra_aviso_de_cooldown(tmp_path):
    db = str(tmp_path / "b.db")
    _perder_duas(db)
    out = copiloto.cmd_risco("LINKUSDT 7.50 7.20 8.40", _db=db)
    assert "🧊" in out and "pausa" in out


def test_fechei_reporta_pnl_e_arma_cooldown(tmp_path):
    db = str(tmp_path / "b.db")
    copiloto.abrir_trade("BTCUSDT", 100.0, 97.0, db_path=db)
    copiloto.fechar_trade("BTCUSDT", exit_price=98.0, db_path=db)     # 1a perda
    copiloto.cmd_entrei("ETHUSDT 100 stop 97", _db=db)
    out = copiloto.cmd_fechei("ETHUSDT 99", _db=db)                   # 2a perda seguida
    assert "🔴" in out and "%" in out
    assert "🧊" in out and "pausa" in out


def test_fechei_ganho_mostra_verde_sem_cooldown(tmp_path):
    db = str(tmp_path / "b.db")
    copiloto.cmd_entrei("BTCUSDT 100 stop 97", _db=db)
    out = copiloto.cmd_fechei("BTCUSDT 105", _db=db)                  # +5% -0.1 = ganho
    assert "🟢" in out and "🧊" not in out


def test_fechei_sem_preco_usa_price_fn_injetado(tmp_path):
    db = str(tmp_path / "b.db")
    copiloto.cmd_entrei("BTCUSDT 100 stop 97", _db=db)
    out = copiloto.cmd_fechei("BTCUSDT", _db=db, _price_fn=lambda s: 103.0)
    assert "Encerrei" in out and "🟢" in out                          # 103 -> +3% -0.1 = ganho


# ─────────────────────── migração sob concorrência (achado 3/3 da revisão) ───────────────────────

def test_migracao_concorrente_nao_quebra(tmp_path):
    """Reproduz a corrida TOCTOU: ciclo de 5min e polling do Telegram migram o mesmo bot.db ao mesmo
    tempo. Sem o try/except no ALTER, a thread perdedora estoura 'duplicate column name'."""
    import sqlite3
    import threading

    db = str(tmp_path / "race.db")
    c = sqlite3.connect(db)                        # schema ANTIGO: forca a migracao a rodar
    c.execute("""CREATE TABLE copiloto_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, direction TEXT NOT NULL,
        entry_price REAL NOT NULL, stop_price REAL NOT NULL, peak_pct REAL DEFAULT 0,
        status TEXT DEFAULT 'aberto', alert_state TEXT DEFAULT '', alert_peak REAL DEFAULT 0,
        created_at TEXT NOT NULL, closed_at TEXT)""")
    c.commit()
    c.close()

    erros = []
    n = 8
    barreira = threading.Barrier(n)

    def worker():
        try:
            barreira.wait()                        # todas batem no ensure_schema juntas
            conn = copiloto._conn(db)
            try:
                copiloto.ensure_schema(conn)
            finally:
                conn.close()
        except Exception as e:
            erros.append(repr(e))

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert erros == [], f"migração concorrente quebrou: {erros}"
    conn = copiloto._conn(db)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(copiloto_trades)").fetchall()]
    conn.close()
    assert "exit_price" in cols and "pnl_pct" in cols   # e a migração de fato aconteceu
