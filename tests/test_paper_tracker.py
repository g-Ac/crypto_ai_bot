"""Testes do paper_tracker. Candles sinteticos via DataFrame pandas;
NOW_S e multiplo de 900 (boundary limpo) — derivado do test_market_read."""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from k_collector import SCHEMA as K_SCHEMA
from liquidation_store import SCHEMA as LIQ_SCHEMA
from tests.test_market_read import HOUR, NOW_S, add_funding, add_price
from tests.test_paper_data import FORM_OK, fake_candles_fn

import paper_data
import paper_tracker

T0 = (NOW_S // 900) * 900          # boundary 15m <= NOW_S


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(K_SCHEMA)
    c.executescript(LIQ_SCHEMA)
    paper_data.ensure_schema(c)
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        add_price(c, sym, bucket_ts=NOW_S - 24 * HOUR, close=100.0)
        add_price(c, sym, bucket_ts=NOW_S, close=104.0, volume=1000, taker_buy_base=600)
        add_funding(c, sym, NOW_S, rate=0.0001)
    c.commit()
    return c


def mk_open_trade(conn, created_at, direction="long", entry=2500.0, stop=2450.0,
                  target=2600.0):
    form = dict(FORM_OK, direction=direction, entry_price=str(entry),
                stop_price=str(stop), target_price=str(target))
    res = paper_data.create_trade(conn, fake_candles_fn(close=entry), created_at, form)
    assert res["ok"], res
    return res["trade_id"]


def candles_df(specs):
    """specs: lista de (open_time_s, open, high, low, close)."""
    return pd.DataFrame([
        {"time": pd.Timestamp(t, unit="s"), "open": o, "high": h, "low": l,
         "close": c, "volume": 1.0} for t, o, h, l, c in specs])


def df_fn(df):
    return lambda symbol, interval, limit: df


def get(conn, tid):
    return conn.execute("SELECT * FROM paper_manual_trades WHERE id=?", (tid,)).fetchone()


def test_toca_alvo_fecha_no_alvo(conn):
    tid = mk_open_trade(conn, T0 - 100)            # boundary do trade = T0
    df = candles_df([(T0, 2500, 2550, 2480, 2540),
                     (T0 + 900, 2540, 2610, 2530, 2590)])
    out = paper_tracker.process_open_trades(conn, df_fn(df), T0 + 1800)
    row = get(conn, tid)
    assert row["status"] == "closed" and row["exit_reason"] == "target"
    assert row["exit_price"] == 2600.0 and row["exit_ts"] == T0 + 900
    assert out["closed"] == 1


def test_toca_stop_fecha_no_stop(conn):
    tid = mk_open_trade(conn, T0 - 100)
    df = candles_df([(T0, 2500, 2520, 2440, 2460)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["exit_reason"] == "stop" and row["exit_price"] == 2450.0


def test_candle_ambiguo_assume_stop(conn):
    tid = mk_open_trade(conn, T0 - 100)
    df = candles_df([(T0, 2500, 2650, 2400, 2550)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    assert get(conn, tid)["exit_reason"] == "stop"


def test_gap_fecha_no_open(conn):
    tid = mk_open_trade(conn, T0 - 100)
    df = candles_df([(T0, 2380, 2400, 2350, 2390)])   # abre abaixo do stop 2450
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["exit_reason"] == "stop" and row["exit_price"] == 2380.0


def test_short_toca_alvo(conn):
    tid = mk_open_trade(conn, T0 - 100, direction="short", entry=2500.0,
                        stop=2550.0, target=2400.0)
    df = candles_df([(T0, 2500, 2520, 2390, 2410)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["exit_reason"] == "target" and row["exit_price"] == 2400.0


def test_ignora_candle_pre_registro_e_parcial(conn):
    tid = mk_open_trade(conn, T0 + 60)               # registro DEPOIS de T0 abrir
    df = candles_df([(T0, 2500, 2700, 2300, 2510),   # toque "antes" do registro: ignora
                     (T0 + 900, 2510, 2530, 2495, 2520)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 1500)  # T0+900 ainda aberto
    row = get(conn, tid)
    assert row["status"] == "open" and row["last_checked_ts"] is None


def test_atualiza_mfe_mae_sem_fechar(conn):
    tid = mk_open_trade(conn, T0 - 100)
    df = candles_df([(T0, 2500, 2580, 2460, 2570)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["status"] == "open"
    assert row["mfe_price"] == 2580.0 and row["mae_price"] == 2460.0
    assert row["last_checked_ts"] == T0


def test_idempotente_rodar_duas_vezes(conn):
    mk_open_trade(conn, T0 - 100)
    df = candles_df([(T0, 2500, 2580, 2460, 2570)])
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    out2 = paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    assert out2 == {"checked": 1, "closed": 0}        # nada novo a varrer, nada muda


def test_sem_dados_mantem_aberto(conn):
    tid = mk_open_trade(conn, T0 - 100)
    out = paper_tracker.process_open_trades(conn, lambda *a: None, T0 + 900)
    assert get(conn, tid)["status"] == "open"
    assert out["checked"] == 1 and out["closed"] == 0


def test_nao_sobrescreve_trade_ja_fechado(conn):
    """Guarda TOCTOU: trade fechado via close_manual nao e reprocessado pelo tracker."""
    tid = mk_open_trade(conn, T0 - 100)
    # Fechar manualmente antes de rodar o tracker
    res = paper_data.close_manual(conn, fake_candles_fn(close=2500.0), T0, tid)
    assert res["ok"] is True
    assert get(conn, tid)["exit_reason"] == "manual"

    # Candle que tocaria stop — mas o trade ja esta fechado
    df = candles_df([(T0, 2500, 2520, 2440, 2460)])
    out = paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)

    # SELECT filtra por status='open', entao o trade fechado nao e nem checado
    assert out["checked"] == 0
    # exit_reason deve permanecer 'manual'
    assert get(conn, tid)["exit_reason"] == "manual"


# ---------------------------------------------------------------------------
# Novos testes (fixes 1-3 + edge cases)
# ---------------------------------------------------------------------------

from tests.test_market_read import NOW_S as _NOW_S  # noqa: E402


def test_guard_update_nao_sobrescreve_com_row_stale(conn):
    """UPDATE WHERE status='open' salva quando trade foi fechado apos SELECT stale."""
    tid = mk_open_trade(conn, T0 - 100)
    stale_row = get(conn, tid)           # captura row antes do fechamento
    # Fechar via close_manual (simula Flask fechando enquanto tracker segura stale)
    res = paper_data.close_manual(conn, fake_candles_fn(close=2520.0), _NOW_S + 100, tid)
    assert res["ok"] is True
    assert get(conn, tid)["exit_reason"] == "manual"
    # Chama _process_trade diretamente com row stale — candle toca stop
    df = candles_df([(T0, 2500, 2700, 2300, 2510)])
    result = paper_tracker._process_trade(conn, df_fn(df), T0 + 900, stale_row)
    assert result is False
    assert get(conn, tid)["exit_reason"] == "manual"


def test_janela_nao_alcanca_start_mantem_aberto(conn):
    """Fail-safe: fetch nao alcanca start => trade mantido aberto, last_checked_ts None."""
    # boundary = T0 (created_at = T0-100)
    tid = mk_open_trade(conn, T0 - 100)
    # df tem so candles a partir de T0+1800 — START e T0, gap de 2 candles
    # stop=2450; low=2400 tocaria stop se processado — mas nao deve processar
    df = candles_df([
        (T0 + 1800, 2500, 2520, 2400, 2510),
        (T0 + 2700, 2510, 2530, 2490, 2520),
    ])
    out = paper_tracker.process_open_trades(conn, df_fn(df), T0 + 3600)
    row = get(conn, tid)
    assert row["status"] == "open"
    assert row["last_checked_ts"] is None
    assert out["closed"] == 0
    assert out["checked"] == 1


def test_dois_trades_mesmo_simbolo(conn):
    """Dois trades ETHUSDT abertos; candle fecha apenas o que tem alvo menor."""
    # Trade 1: stop=2450, target=2600 — candle nao atinge (high=2520 < 2600)
    t1 = mk_open_trade(conn, T0 - 100, entry=2500.0, stop=2450.0, target=2600.0)
    # Trade 2: stop=2450, target=2510 — candle atinge target (high=2520 >= 2510)
    # low=2460 > stop=2450 entao nao ha ambiguidade — so target e atingido
    t2 = mk_open_trade(conn, T0 - 100, entry=2500.0, stop=2450.0, target=2510.0)
    df = candles_df([(T0, 2500, 2520, 2460, 2510)])
    out = paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    r1 = get(conn, t1)
    r2 = get(conn, t2)
    assert r1["status"] == "open"
    assert r1["mfe_price"] == 2520.0 and r1["mae_price"] == 2460.0
    assert r2["status"] == "closed" and r2["exit_reason"] == "target"
    assert out == {"checked": 2, "closed": 1}


def test_candle_exatamente_no_boundary(conn):
    """created_at == T0 (multiplo de 900): boundary e T0, candle nesse open_time conta."""
    # Usa T0 como created_at e NOW_S para _last_closed_price encontrar preco valido
    # fake_candles_fn retorna 3 candles; o penultimo (open NOW_S-1800) esta fechado em T0
    tid = mk_open_trade(conn, T0, entry=2500.0, stop=2450.0, target=2600.0)
    df = candles_df([(T0, 2500, 2650, 2490, 2600)])   # high=2650 >= target=2600
    out = paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["status"] == "closed" and row["exit_reason"] == "target"
    assert out["closed"] == 1


def test_short_toca_stop(conn):
    """Short: high >= stop => saida no stop."""
    tid = mk_open_trade(conn, T0 - 100, direction="short",
                        entry=2500.0, stop=2550.0, target=2400.0)
    df = candles_df([(T0, 2500, 2560, 2490, 2510)])   # high=2560 >= stop=2550
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["status"] == "closed"
    assert row["exit_reason"] == "stop" and row["exit_price"] == 2550.0


def test_short_candle_ambiguo(conn):
    """Short ambiguo (high >= stop E low <= target): stop prevalece (pessimista)."""
    tid = mk_open_trade(conn, T0 - 100, direction="short",
                        entry=2500.0, stop=2550.0, target=2400.0)
    df = candles_df([(T0, 2500, 2560, 2390, 2450)])   # high=2560 e low=2390
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["exit_reason"] == "stop"


def test_short_gap_abre_alem_do_stop(conn):
    """Short com gap: open > stop => fill no open."""
    tid = mk_open_trade(conn, T0 - 100, direction="short",
                        entry=2500.0, stop=2550.0, target=2400.0)
    df = candles_df([(T0, 2580, 2600, 2490, 2510)])   # open=2580 > stop=2550
    paper_tracker.process_open_trades(conn, df_fn(df), T0 + 900)
    row = get(conn, tid)
    assert row["exit_reason"] == "stop" and row["exit_price"] == 2580.0


def test_excecao_no_get_candles_isolada(conn):
    """get_candles levanta RuntimeError => trade fica aberto, sem excecao propagada."""
    tid = mk_open_trade(conn, T0 - 100)

    def boom(*a):
        raise RuntimeError("conexao recusada")

    out = paper_tracker.process_open_trades(conn, boom, T0 + 900)
    assert out == {"checked": 1, "closed": 0}
    assert get(conn, tid)["status"] == "open"
