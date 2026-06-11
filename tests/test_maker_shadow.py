"""Testes da simulacao maker-fill (PREREG_maker_fill_v11.md, regra §4).

Regras travadas no pre-registro:
- Limit post-only ao preco de entrada real; validade 2 candles 15m.
- Fill estrito: LONG exige low < limit (tocar exato NAO preenche); SHORT high > limit.
- Preco de fill = sempre o limit (sem melhora em gap).
- Candle de fill avalia SO o SL; TPs apenas a partir do candle seguinte.
- Candles seguintes: prioridade do runner (SL > TP2 > TP1 > timeout).
- Timeout ancorado no candle de confirmacao C (mesma contagem do executor:
  check no candle C+k usa duration=k-1; timeout quando duration >= 16).
- Fees: entrada maker 0.02; TP maker 0.02; SL/timeout taker 0.05.
- Non-fill: PnL da politica = 0.
"""
import pytest

from momentum.maker_shadow import simulate_maker_trade


def c(high, low, close):
    return {"high": high, "low": low, "close": close}


def _long(candles, **kw):
    params = dict(
        direction="LONG",
        entry_price=100.0,
        sl_price=99.0,
        tp1_price=101.0,
        tp2_price=101.5,
        candles=candles,
    )
    params.update(kw)
    return simulate_maker_trade(**params)


def _short(candles, **kw):
    params = dict(
        direction="SHORT",
        entry_price=100.0,
        sl_price=101.0,
        tp1_price=99.0,
        tp2_price=98.5,
        candles=candles,
    )
    params.update(kw)
    return simulate_maker_trade(**params)


def test_long_fill_estrito_c1_depois_tp1():
    # C+1 perfura a limit (low 99.9 < 100) sem tocar SL; C+2 atinge TP1.
    r = _long([c(100.5, 99.9, 100.2), c(101.2, 100.0, 101.1)])
    assert r["filled"] is True
    assert r["fill_candle"] == 1
    assert r["exit_reason"] == "tp1_hit"
    assert r["gross_pnl_pct"] == pytest.approx(1.0)
    assert r["entry_fee_rate"] == pytest.approx(0.02)
    assert r["exit_fee_rate"] == pytest.approx(0.02)  # TP sai como maker
    assert r["net_pnl_pct"] == pytest.approx(1.0 - 0.04)


def test_long_toque_exato_nao_preenche():
    # low == limit nos 2 candles da janela -> nao preenche (strict-through).
    r = _long([c(100.5, 100.0, 100.3), c(100.6, 100.0, 100.4)])
    assert r["filled"] is False
    assert r["fill_candle"] is None
    assert r["exit_reason"] == "no_fill"
    assert r["gross_pnl_pct"] == 0.0
    assert r["net_pnl_pct"] == 0.0


def test_long_fill_no_segundo_candle():
    r = _long([c(100.5, 100.2, 100.4), c(100.3, 99.95, 100.1), c(101.2, 100.0, 101.0)])
    assert r["filled"] is True
    assert r["fill_candle"] == 2
    assert r["exit_reason"] == "tp1_hit"


def test_fill_fora_da_janela_nao_conta():
    # Perfuracao so no 3o candle: fora da validade de 2 -> no_fill.
    r = _long([c(100.5, 100.2, 100.4), c(100.6, 100.1, 100.3), c(100.4, 99.5, 100.0)])
    assert r["filled"] is False
    assert r["exit_reason"] == "no_fill"


def test_candle_de_fill_nao_avalia_tp():
    # Candle de fill varre TP1 (high 101.4) mas TP nao conta no candle de fill;
    # SL nao foi tocado (low 99.8 > 99). Exit so no candle seguinte (SL).
    r = _long([c(101.4, 99.8, 101.2), c(100.0, 98.9, 99.2)])
    assert r["filled"] is True
    assert r["fill_candle"] == 1
    assert r["exit_reason"] == "sl_hit"
    assert r["gross_pnl_pct"] == pytest.approx(-1.0)
    assert r["exit_fee_rate"] == pytest.approx(0.05)  # SL sai como taker
    assert r["net_pnl_pct"] == pytest.approx(-1.0 - 0.07)


def test_sl_no_proprio_candle_de_fill():
    # Preco veio contra ate preencher e seguiu ate o SL no mesmo candle.
    r = _long([c(100.3, 98.9, 99.0)])
    assert r["filled"] is True
    assert r["exit_reason"] == "sl_hit"
    assert r["gross_pnl_pct"] == pytest.approx(-1.0)
    assert r["net_pnl_pct"] == pytest.approx(-1.07)


def test_prioridade_sl_sobre_tp_pos_fill():
    # Candle pos-fill varre SL e TP2: worst-case do runner -> sl_hit.
    r = _long([c(100.4, 99.9, 100.2), c(101.6, 98.9, 100.5)])
    assert r["exit_reason"] == "sl_hit"


def test_timeout_ancorado_no_candle_de_confirmacao():
    # Fill em C+1; nada toca niveis; timeout no candle C+17 (duration=16),
    # saindo no close como taker — mesma contagem do executor real.
    neutro = c(100.4, 99.5, 100.1)
    candles = [c(100.5, 99.9, 100.2)] + [neutro] * 15 + [c(100.4, 99.5, 100.3)]
    r = _long(candles)
    assert r["exit_reason"] == "timeout"
    assert r["duration_candles"] == 16
    assert r["gross_pnl_pct"] == pytest.approx(0.3)
    assert r["exit_fee_rate"] == pytest.approx(0.05)  # timeout sai a mercado
    assert r["net_pnl_pct"] == pytest.approx(0.3 - 0.07)


def test_incompleto_quando_candles_acabam():
    # Fill aconteceu mas a serie termina sem exit nem timeout -> incomplete
    # (Fase F em andamento / trade recente na Fase R).
    r = _long([c(100.5, 99.9, 100.2), c(100.4, 99.6, 100.1)])
    assert r["filled"] is True
    assert r["exit_reason"] == "incomplete"


def test_short_fill_estrito_e_tp1():
    # SHORT: fill exige high > limit (estrito); TP1 abaixo.
    r = _short([c(100.1, 99.6, 99.8), c(99.4, 98.9, 99.0)])
    assert r["filled"] is True
    assert r["exit_reason"] == "tp1_hit"
    assert r["gross_pnl_pct"] == pytest.approx(1.0)
    assert r["net_pnl_pct"] == pytest.approx(0.96)


def test_short_toque_exato_nao_preenche():
    r = _short([c(100.0, 99.6, 99.8), c(100.0, 99.5, 99.7)])
    assert r["filled"] is False
    assert r["exit_reason"] == "no_fill"


def test_short_sl_no_candle_de_fill():
    # high 101.2 perfura limit (fill) e passa do SL 101 no mesmo candle.
    r = _short([c(101.2, 99.9, 101.0)])
    assert r["filled"] is True
    assert r["exit_reason"] == "sl_hit"
    assert r["gross_pnl_pct"] == pytest.approx(-1.0)


# --- Ancora do candle do sinal N (replay Fase R) ---
# Semantica real do executor (descoberta na Fase R, adendo do pre-registro):
# o sinal dispara no 1o ciclo de 5min de um candle 15m NOVO, com entry_price
# = preco parcial desse candle N. Logo entry esta CONTIDO no range final de N,
# e open(N) = floor15(t_close) - duration*15m (offset 0 ou -1; gaps de ciclo
# empurram mais para tras).

from momentum.maker_shadow import locate_signal_candle

_M15 = 15 * 60 * 1000


def _klines(closes, start_ms=1_000_000_000_000):
    # Klines 15m reais sao sempre alinhados a fronteiras de 15min (premissa
    # do locate); o helper alinha o start para refletir isso.
    start_ms = (start_ms // _M15) * _M15
    ks = [
        {"open_time": start_ms + i * _M15, "high": cl + 1, "low": cl - 1, "close": cl}
        for i, cl in enumerate(closes)
    ]
    idx = {k["open_time"]: i for i, k in enumerate(ks)}
    return ks, idx


def test_locate_acha_candle_do_sinal_por_contencao():
    # dur=3, fechamento dentro do candle indice 6 -> est N = indice 3;
    # entry 101.0 esta no range [100, 102] do candle 3.
    ks, idx = _klines([90.0, 95.0, 100.0, 101.0, 102.0, 103.0, 104.0])
    close_ts = ks[6]["open_time"] + 7 * 60 * 1000  # fechado no meio do candle 6
    ni, off = locate_signal_candle(ks, idx, close_ts, 3, entry_price=101.0)
    assert ni == 3
    assert off == 0


def test_locate_recua_quando_estimativa_nao_contem():
    # Gap de ciclo: candle estimado (idx 3, range [100,102]) nao contem o
    # entry 95.0; recua ate o primeiro que contem (idx 1, range [94,96]).
    ks, idx = _klines([90.0, 95.0, 100.0, 101.0, 102.0, 103.0, 104.0])
    close_ts = ks[6]["open_time"] + 7 * 60 * 1000
    ni, off = locate_signal_candle(ks, idx, close_ts, 3, entry_price=95.0)
    assert ni == 1
    assert off == -2


def test_locate_sem_contencao_retorna_none():
    ks, idx = _klines([90.0, 95.0, 100.0, 101.0])
    close_ts = ks[3]["open_time"] + 7 * 60 * 1000
    ni, off = locate_signal_candle(ks, idx, close_ts, 1, entry_price=50.0)
    assert ni is None
    assert off is None


# --- Agregacao da politica (semantica da emenda 4 do pre-registro) ---

from momentum.maker_shadow import summarize_policy


def _row(filled, net, reason):
    return {"filled": filled, "net_pnl_pct": net, "exit_reason": reason}


def test_summarize_pf_ignora_zeros_de_no_fill():
    # PF e dos PnLs executados: no_fill (0) e neutro para PF por definicao,
    # mas conta 0 no PnL total e entra no denominador do fill_rate.
    rows = [
        _row(True, 1.0, "tp1_hit"),
        _row(True, -0.5, "sl_hit"),
        _row(False, 0.0, "no_fill"),
    ]
    s = summarize_policy(rows)
    assert s["pf_executados"] == pytest.approx(2.0)
    assert s["total_net_pct"] == pytest.approx(0.5)
    assert s["fill_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert s["n_trades"] == 3
    assert s["n_filled"] == 2


def test_summarize_exclui_incomplete_de_tudo():
    rows = [
        _row(True, 1.0, "tp1_hit"),
        _row(True, 0.0, "incomplete"),
    ]
    s = summarize_policy(rows)
    assert s["n_trades"] == 1
    assert s["n_incomplete"] == 1
    assert s["total_net_pct"] == pytest.approx(1.0)


def test_summarize_pf_indefinido_sem_perdas():
    # PF indefinido (sem perdas) nao vira infinito magico: retorna None
    # (pre-registro: PF indefinido nao aprova).
    rows = [_row(True, 1.0, "tp1_hit"), _row(False, 0.0, "no_fill")]
    s = summarize_policy(rows)
    assert s["pf_executados"] is None
