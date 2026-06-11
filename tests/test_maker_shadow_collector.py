"""Testes do coletor maker-shadow Fase F (spec 2026-06-10-maker-shadow-collector-design).

Invariantes do desenho (inegociaveis):
1. signal_ts real = instante do nascimento da sombra (now), nao reconstruido.
2. Nenhum dado anterior ao nascimento conta para fill: o candle onde a ordem
   nasceu NUNCA usa wick (so ticks observados); candles abertos pos-sinal podem.
3. Snapshot de book no nascimento como diagnostico (would_post etc.);
   falha de fetch nunca bloqueia.
"""
from datetime import datetime, timezone

import pytest

from momentum.maker_shadow_collector import MakerShadowCollector

NOON = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)


def t(minutes):
    """datetime aware: NOON + minutes."""
    from datetime import timedelta
    return NOON + timedelta(minutes=minutes)


def iso(minutes):
    return t(minutes).strftime("%Y-%m-%d %H:%M:%S")


def make(tmp_path, now_min=3, book="default"):
    """Coletor com db temporario, relogio e book injetados."""
    if book == "default":
        book = {"bid": 99.5, "ask": 100.5}
    state = {"now": t(now_min)}
    coll = MakerShadowCollector(
        db_path=str(tmp_path / "shadow.db"),
        book_fn=lambda symbol: book,
        now_fn=lambda: state["now"],
    )
    return coll, state


def open_long(coll, **kw):
    params = dict(symbol="BTCUSDT", direction="LONG", entry_price=100.0,
                  sl_price=99.0, tp1_price=101.0, tp2_price=101.5,
                  candle_open_ts=iso(0))  # candle N abre no NOON
    params.update(kw)
    return coll.on_trade_opened(**params)


def candle(minutes, high, low, close):
    return {"time": iso(minutes), "high": high, "low": low, "close": close}


# --- Nascimento (invariantes 1 e 3) ---

def test_opened_cria_pending_com_expiry_e_book(tmp_path):
    coll, _ = make(tmp_path)
    sid = open_long(coll)
    row = coll.get(sid)
    assert row["status"] == "pending"
    assert row["limit_price"] == 100.0
    assert row["signal_ts"] == iso(3)  # now real, nao open do candle
    assert row["expiry_ts"] == int(t(30).timestamp())  # fim de N+1
    assert row["best_bid_at_signal"] == 99.5
    assert row["best_ask_at_signal"] == 100.5
    assert row["would_post"] == 1  # LONG: limit 100 < ask 100.5
    assert row["post_only_reject_hypothetical"] == 0
    assert row["spread_bps"] == pytest.approx(100.0, abs=0.5)


def test_opened_sem_book_nao_quebra(tmp_path):
    coll, _ = make(tmp_path, book=None)
    sid = open_long(coll)
    row = coll.get(sid)
    assert row["status"] == "pending"
    assert row["best_bid_at_signal"] is None
    assert row["would_post"] is None


def test_would_post_reject_quando_marketable(tmp_path):
    # LONG com limit >= ask executaria imediatamente como taker (reject hipotetico).
    coll, _ = make(tmp_path, book={"bid": 99.0, "ask": 100.0})
    sid = open_long(coll)
    row = coll.get(sid)
    assert row["would_post"] == 0
    assert row["post_only_reject_hypothetical"] == 1


# --- Fill por tick (invariante 2: tick e sempre pos-nascimento) ---

def test_tick_fill_estrito(tmp_path):
    coll, state = make(tmp_path)
    sid = open_long(coll)
    state["now"] = t(8)
    coll.on_cycle(symbol="BTCUSDT", tick_price=100.0, now_candle_open_ts=iso(0))
    assert coll.get(sid)["status"] == "pending"  # tocar exato nao preenche
    coll.on_cycle(symbol="BTCUSDT", tick_price=99.99, now_candle_open_ts=iso(0))
    row = coll.get(sid)
    assert row["status"] == "filled"
    assert row["fill_source"] == "cycle_tick"
    assert row["fill_candle_open_ts"] == int(t(0).timestamp())


def test_tick_fill_short(tmp_path):
    coll, state = make(tmp_path)
    sid = open_long(coll, direction="SHORT", sl_price=101.0,
                    tp1_price=99.0, tp2_price=98.5)
    state["now"] = t(8)
    coll.on_cycle(symbol="BTCUSDT", tick_price=100.01, now_candle_open_ts=iso(0))
    assert coll.get(sid)["status"] == "filled"


# --- Invariante 2: wick do candle do nascimento NAO preenche ---

def test_wick_do_candle_do_nascimento_nao_preenche(tmp_path):
    coll, state = make(tmp_path)
    sid = open_long(coll)  # nasce 12:03, dentro do candle N (open 12:00)
    state["now"] = t(15, )
    # candle N fechou com low 99.0 < limit — mas abriu ANTES do signal_ts.
    coll.on_cycle(symbol="BTCUSDT", tick_price=100.4,
                  now_candle_open_ts=iso(15),
                  closed_candle=candle(0, 100.8, 99.0, 100.4))
    assert coll.get(sid)["status"] == "pending"


def test_wick_de_n1_preenche(tmp_path):
    coll, state = make(tmp_path)
    sid = open_long(coll)
    state["now"] = t(30)
    # N+1 (open 12:15 >= signal 12:03) fechou perfurando a limit, sem tocar SL.
    coll.on_cycle(symbol="BTCUSDT", tick_price=100.2,
                  now_candle_open_ts=iso(30),
                  closed_candle=candle(15, 100.6, 99.5, 100.2))
    row = coll.get(sid)
    assert row["status"] == "filled"
    assert row["fill_source"] == "next_candle_wick"


def test_wick_fill_com_sl_no_mesmo_candle_fecha_em_sl(tmp_path):
    # Candle do fill avalia SO o SL: perfura limit e segue ate o SL.
    coll, state = make(tmp_path)
    sid = open_long(coll)
    state["now"] = t(30)
    coll.on_cycle(symbol="BTCUSDT", tick_price=99.2,
                  now_candle_open_ts=iso(30),
                  closed_candle=candle(15, 100.4, 98.9, 99.2))
    row = coll.get(sid)
    assert row["status"] == "closed"
    assert row["exit_reason"] == "sl_hit"
    assert row["gross_pnl_pct"] == pytest.approx(-1.0)
    assert row["net_pnl_pct"] == pytest.approx(-1.07)  # entrada maker + SL taker


# --- Expiry ---

def test_expiry_vira_no_fill(tmp_path):
    coll, state = make(tmp_path)
    sid = open_long(coll)
    state["now"] = t(31)  # > 12:30 (fim de N+1)
    coll.on_cycle(symbol="BTCUSDT", tick_price=100.6, now_candle_open_ts=iso(30))
    row = coll.get(sid)
    assert row["status"] == "no_fill"
    assert row["net_pnl_pct"] == 0.0


def test_tick_apos_expiry_nao_preenche(tmp_path):
    coll, state = make(tmp_path)
    sid = open_long(coll)
    state["now"] = t(31)
    coll.on_cycle(symbol="BTCUSDT", tick_price=99.9, now_candle_open_ts=iso(30))
    assert coll.get(sid)["status"] == "no_fill"


# --- Desfecho pos-fill ---

def test_tp1_no_candle_seguinte_ao_fill(tmp_path):
    coll, state = make(tmp_path)
    sid = open_long(coll)
    state["now"] = t(8)
    coll.on_cycle(symbol="BTCUSDT", tick_price=99.99, now_candle_open_ts=iso(0))
    # N fecha: candle do fill -> so SL (low 99.5 > 99, segue aberto).
    state["now"] = t(16)
    coll.on_cycle(symbol="BTCUSDT", tick_price=100.3, now_candle_open_ts=iso(15),
                  closed_candle=candle(0, 100.6, 99.5, 100.3))
    assert coll.get(sid)["status"] == "filled"
    # N+1 fecha atingindo TP1 -> closed com fee maker na saida.
    state["now"] = t(31)
    coll.on_cycle(symbol="BTCUSDT", tick_price=101.2, now_candle_open_ts=iso(30),
                  closed_candle=candle(15, 101.2, 100.1, 101.1))
    row = coll.get(sid)
    assert row["status"] == "closed"
    assert row["exit_reason"] == "tp1_hit"
    assert row["gross_pnl_pct"] == pytest.approx(1.0)
    assert row["net_pnl_pct"] == pytest.approx(0.96)


def test_tp_nao_conta_no_candle_do_fill(tmp_path):
    coll, state = make(tmp_path)
    sid = open_long(coll)
    state["now"] = t(8)
    coll.on_cycle(symbol="BTCUSDT", tick_price=99.99, now_candle_open_ts=iso(0))
    # N fecha varrendo TP1 — mas e o candle do fill: TP nao conta.
    state["now"] = t(16)
    coll.on_cycle(symbol="BTCUSDT", tick_price=101.2, now_candle_open_ts=iso(15),
                  closed_candle=candle(0, 101.4, 99.5, 101.2))
    assert coll.get(sid)["status"] == "filled"


def test_timeout_ancorado_no_candle_do_sinal(tmp_path):
    coll, state = make(tmp_path)
    sid = open_long(coll)
    state["now"] = t(8)
    coll.on_cycle(symbol="BTCUSDT", tick_price=99.99, now_candle_open_ts=iso(0))
    state["now"] = t(16)
    coll.on_cycle(symbol="BTCUSDT", tick_price=100.2, now_candle_open_ts=iso(15),
                  closed_candle=candle(0, 100.4, 99.5, 100.2))  # seed
    # Salta para o candle N+17 (k=17 -> duration 16): timeout no close, taker.
    state["now"] = t(17 * 15 + 1)
    coll.on_cycle(symbol="BTCUSDT", tick_price=100.3,
                  now_candle_open_ts=iso(18 * 15),
                  closed_candle=candle(17 * 15, 100.5, 99.6, 100.3))
    row = coll.get(sid)
    assert row["status"] == "closed"
    assert row["exit_reason"] == "timeout"
    assert row["gross_pnl_pct"] == pytest.approx(0.3)
    assert row["net_pnl_pct"] == pytest.approx(0.3 - 0.07)


# --- Pareamento com o trade taker real ---

def test_on_trade_closed_grava_taker_net(tmp_path):
    coll, _ = make(tmp_path)
    sid = open_long(coll)
    coll.on_trade_closed(sid, taker_net_pnl_pct=-0.55)
    assert coll.get(sid)["taker_net_pnl_pct"] == pytest.approx(-0.55)
