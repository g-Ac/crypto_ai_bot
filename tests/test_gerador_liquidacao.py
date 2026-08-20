"""Primitiva de liquidação (sweep estrutural) — testes de causalidade.

Fixtures 100% sintéticas; nunca tocam o bot.db. Foco central: ZERO look-ahead —
truncar a série no ponto da entrada não pode mudar a decisão (test-ouro).
"""
import os
import sys

import pandas as pd

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from research.gerador_prereg import catalogo as cat  # noqa: E402

START4 = (1_700_000_000 // cat.FOUR_H) * cat.FOUR_H  # início alinhado a bloco de 4h


def _mk4h(candles, start=START4):
    """candles: lista de (open, high, low, close, liq). Cada um vira 4 horas — a 1ª
    carrega o range e a liquidação; as 3 seguintes ficam flat no close. Assim o candle
    4h reamostrado reproduz exatamente (open, high, low, close, liq) desejado."""
    rows, idx = [], []
    for i, (o, h, l, c, liq) in enumerate(candles):
        base = start + i * cat.FOUR_H
        rows.append((o, h, l, c, liq)); idx.append(base)
        for k in (1, 2, 3):
            rows.append((c, c, c, c, 0.0)); idx.append(base + k * cat.HOUR)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "liq_sell_notional"],
                        index=idx)


def _entry_ts(i):  # bucket horário do close do candle 4h i (onde a entry entra)
    return START4 + i * cat.FOUR_H + 3 * cat.HOUR


# cenário base: warm-up + pivô de fundo em i=2 (low 95, confirmado em i=4) +
# varredura/pico-de-liquidação/rejeição no candle i=6.
_BASE = [
    (100, 101, 99, 100, 100.0),   # 0
    (100, 101, 99, 100, 100.0),   # 1
    (100, 101, 95, 100, 100.0),   # 2  <- fundo (low 95)
    (100, 101, 99, 100, 100.0),   # 3
    (100, 101, 99, 100, 100.0),   # 4  <- pivô i=2 confirmado aqui (i+pivot_side)
    (100, 101, 98, 100, 100.0),   # 5
    (97, 100, 93, 98, 5000.0),    # 6  <- varre 95 (low 93) + pico de liq + rejeita (close 98)
    (98, 99, 97, 98, 100.0),      # 7  } cauda para permitir a barra de saída (exit 24h)
    (98, 99, 97, 98, 100.0),      # 8
    (98, 99, 97, 98, 100.0),      # 9
    (98, 99, 97, 98, 100.0),      # 10
    (98, 99, 97, 98, 100.0),      # 11
    (98, 99, 97, 98, 100.0),      # 12
]
_P = dict(pivot_side=2, lookback=10, p_pct=90, p_window=4, reject_within=2)


def test_cenario_completo_dispara_long():
    e = cat.sig_liquidacao_sweep_estrutural({"X": _mk4h(_BASE)}, ["X"], **_P)
    assert e == [("X", _entry_ts(6), 1)]        # exatamente 1 entry long, no close do candle 6


def test_gatilho_liquidacao_necessario():
    b = list(_BASE); b[6] = (97, 100, 93, 98, 0.0)   # varre e rejeita, mas SEM venda forçada
    assert cat.sig_liquidacao_sweep_estrutural({"X": _mk4h(b)}, ["X"], **_P) == []


def test_lookback_bloqueia_fundo_ancestral():
    p = dict(_P); p["lookback"] = 2                    # fundo i=2 fica velho demais (6-2=4 > 2)
    assert cat.sig_liquidacao_sweep_estrutural({"X": _mk4h(_BASE)}, ["X"], **p) == []


def test_rejeicao_fora_da_janela_nao_dispara():
    b = list(_BASE)
    b[6] = (97, 100, 93, 94, 5000.0)                  # varre + liq, mas close 94 < 95 (não rejeita)
    b[7] = (94, 94, 93, 94, 100.0)                     # segue sem rejeitar dentro de within=2
    b[8] = (94, 94, 93, 94, 100.0)
    assert cat.sig_liquidacao_sweep_estrutural({"X": _mk4h(b)}, ["X"], **_P) == []


def test_alinhamento_entry_no_indice_e_close():
    df = _mk4h(_BASE)
    (_, ts, d), = cat.sig_liquidacao_sweep_estrutural({"X": df}, ["X"], **_P)
    assert ts in df.index                             # é um bucket horário REAL do painel
    assert df.at[ts, "close"] == 98.0                 # close do bucket == close do candle 4h
    assert d == 1


def test_sem_look_ahead_truncando_a_serie():
    df = _mk4h(_BASE)
    full = cat.sig_liquidacao_sweep_estrutural({"X": df}, ["X"], **_P)
    ts = full[0][1]
    trunc = df[df.index <= ts]                         # remove TUDO após a entrada
    e2 = cat.sig_liquidacao_sweep_estrutural({"X": trunc}, ["X"], **_P)
    assert full[0] in e2                               # a decisão em ts não usou o futuro


def test_integracao_build_trades_nao_toca_disco():
    spec = {"signal": "liquidacao_sweep_estrutural", "signal_params": _P,
            "filter": "nenhum", "filter_params": {}, "side": "auto",
            "exit": {"type": "horizonte", "bars": 24}, "universe": "todos",
            "fee_bps_roundtrip": 10, "slippage_bps": 2}
    trades = cat.build_trades(spec, {"X": _mk4h(_BASE)})
    assert set(trades["symbol"]) <= {"X"}
    assert "ret_net_bps" in trades.columns
    assert len(trades) == 1                            # a entrada do cenário rende 1 trade fechado


# ───────── discriminante da qualidade da queda ─────────
_BASE_DISC = [
    (100, 100, 100, 100, 100.0),  # 0
    (100, 100, 100, 100, 100.0),  # 1
    (100, 100, 100, 100, 100.0),  # 2
    (100, 100, 100, 100, 100.0),  # 3
    (100, 100, 100, 100, 100.0),  # 4
    (100, 100, 90, 90, 5000.0),   # 5  queda -10% + venda forçada alta -> long
    (90, 91, 89, 90, 100.0),      # 6  } cauda p/ a barra de saída
    (90, 91, 89, 90, 100.0),      # 7
    (90, 91, 89, 90, 100.0),      # 8
]
_PD = dict(ret_pct=20, liq_pct=75, p_window=4)


def test_disc_queda_com_liq_dispara_long():
    e = cat.sig_liquidacao_discriminante({"X": _mk4h(_BASE_DISC)}, ["X"], **_PD)
    assert e == [("X", _entry_ts(5), 1)]              # queda + venda forçada alta -> 1 long


def test_disc_queda_sem_liq_nao_dispara():
    b = list(_BASE_DISC); b[5] = (100, 100, 90, 90, 0.0)   # mesma queda, SEM venda forçada
    assert cat.sig_liquidacao_discriminante({"X": _mk4h(b)}, ["X"], **_PD) == []


def test_disc_alta_com_liq_nao_dispara():
    b = list(_BASE_DISC); b[5] = (100, 110, 100, 110, 5000.0)  # sobe (não é queda) + liq alta
    assert cat.sig_liquidacao_discriminante({"X": _mk4h(b)}, ["X"], **_PD) == []


def test_disc_sem_look_ahead():
    df = _mk4h(_BASE_DISC)
    full = cat.sig_liquidacao_discriminante({"X": df}, ["X"], **_PD)
    ts = full[0][1]
    trunc = df[df.index <= ts]
    assert full[0] in cat.sig_liquidacao_discriminante({"X": trunc}, ["X"], **_PD)


# ───────── endurecimento pós-revisão (2026-07-02) ─────────
def _entries_em_blocos_completos(entries, trunc_end_ts):
    """Entradas cujo bloco de 4h já FECHOU na série truncada (o contrato causal:
    decisões de blocos completos nunca mudam; o bloco parcial da borda é instável
    por construção do resample e é descartado da comparação)."""
    last_block = (int(trunc_end_ts) // cat.FOUR_H) * cat.FOUR_H
    return sorted(e for e in entries if (e[1] // cat.FOUR_H) * cat.FOUR_H < last_block)


def test_ouro_multiponto_igualdade_sweep_e_disc():
    """Teste-ouro forte: em TODOS os pontos de truncamento horário, as decisões de
    blocos 4h completos são IDÊNTICAS (igualdade de conjunto, não pertencimento)."""
    for sig, base, params in (
        (cat.sig_liquidacao_sweep_estrutural, _BASE, _P),
        (cat.sig_liquidacao_discriminante, _BASE_DISC, _PD),
    ):
        df = _mk4h(base)
        full = sig({"X": df}, ["X"], **params)
        for cut in df.index:
            trunc = df[df.index <= cut]
            got = sig({"X": trunc}, ["X"], **params)
            assert _entries_em_blocos_completos(got, cut) == \
                _entries_em_blocos_completos([e for e in full if e[1] <= cut], cut), \
                f"{sig.__name__}: decisão de bloco completo mudou ao truncar em {cut}"


def test_sweep_params_de_producao():
    """Exercita os params CONGELADOS no journal (pivot_side=3, p_window=30, lookback=18):
    warm-up do rolling(30) + confirmação de pivô, invisíveis nas fixtures pequenas.
    Lows estritamente decrescentes entre o pivô e a varredura: sem empates, região flat
    criaria pseudo-pivôs (lows iguais empatam o min da janela) e mudaria o fundo."""
    candles = [(100, 101, 99, 100, 100.0)] * 20            # 0..19 warm-up
    candles.append((100, 101, 95, 100, 100.0))             # 20: pivô real (low 95)
    for k in range(15):                                     # 21..35: lows 98.9 -> 96.1
        low = 98.9 - 0.2 * k
        candles.append((100, 101, low, 100, 100.0))
    candles.append((97, 100, 93, 98, 5000.0))              # 36: varre 95 + liq + rejeita
    candles += [(98, 99, 97, 98, 100.0)] * 6               # 37..42: cauda p/ exit 24h
    prod = dict(pivot_side=3, lookback=18, p_pct=90, p_window=30, reject_within=2)
    e = cat.sig_liquidacao_sweep_estrutural({"X": _mk4h(candles)}, ["X"], **prod)
    assert e == [("X", _entry_ts(36), 1)]
    # e ANTES do warm-up do rolling(30) nada dispara, mesmo com o mesmo desenho:
    cedo = list(candles[:34])
    cedo[10] = (100, 101, 95, 100, 100.0)      # pivô cedo
    cedo[26] = (97, 100, 93, 98, 5000.0)       # varredura em t=26 < p_window+1
    e2 = cat.sig_liquidacao_sweep_estrutural({"X": _mk4h(cedo)}, ["X"], **prod)
    assert e2 == []                            # p90 ainda NaN => sem gatilho (warm-up real)


def test_pivo_mais_recente_vence():
    """Pina o comportamento CONGELADO apontado na revisão: com 2 pivôs no lookback, o
    fundo é o MAIS RECENTE (mesmo mais raso). A varredura de 96 perfura o pivô novo (97)
    mas não o velho (95) — se o código usasse o mais fundo, não haveria entrada."""
    lows = [99, 99, 95, 98.5, 98.4, 98.3, 98.2, 98.1, 97, 98.2, 98.3, 98.4]
    candles = [(100, 101, l, 100, 100.0) for l in lows]
    candles.append((98, 99, 96, 98, 5000.0))   # 12: low 96 < 97 (novo), > 95 (velho)
    candles += [(98, 99, 97.5, 98, 100.0)] * 3
    e = cat.sig_liquidacao_sweep_estrutural({"X": _mk4h(candles)}, ["X"], **_P)
    assert e == [("X", _entry_ts(12), 1)]      # fundo usado = 97 (pivô mais recente)


def test_simbolo_com_liq_toda_zero_nunca_dispara():
    """Caminho vivo de produção: 14 dos 28 símbolos não têm coleta de liquidação
    (coluna toda 0). Nenhuma das duas primitivas pode disparar (guarda thr>0)."""
    base = [(100, 101, 99, 100, 0.0)] * 12
    base[2] = (100, 101, 95, 100, 0.0)
    base[6] = (97, 100, 93, 98, 0.0)           # varre e rejeita, mas liq inexistente
    df = _mk4h(base)
    assert cat.sig_liquidacao_sweep_estrutural({"X": df}, ["X"], **_P) == []
    down = [(100, 100, 100, 100, 0.0)] * 6 + [(100, 100, 90, 90, 0.0)] + \
           [(90, 91, 89, 90, 0.0)] * 3
    assert cat.sig_liquidacao_discriminante({"X": _mk4h(down)}, ["X"], **_PD) == []
