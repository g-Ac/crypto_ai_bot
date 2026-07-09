"""Catálogo do gerador de pré-registros — primitivas auto-executáveis.

Fixtures 100% sintéticas e determinísticas (nunca toca o bot.db). Valida direção
e causalidade de cada primitiva, a integração build_trades e a deduplicação.
"""
import os
import sys

import numpy as np
import pandas as pd

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from research.gerador_prereg import catalogo as cat  # noqa: E402

START = 1_700_000_000  # epoch alinhado a hora cheia? não importa p/ a maioria; hora_sessao usa ts próprios


def _mk(close, open=None, high=None, low=None, funding=None, oi=None, start=START):
    n = len(close)
    idx = [start + i * cat.HOUR for i in range(n)]
    close = np.asarray(close, float)
    open = np.asarray(open, float) if open is not None else np.r_[close[0], close[:-1]]
    high = np.asarray(high, float) if high is not None else np.maximum(open, close)
    low = np.asarray(low, float) if low is not None else np.minimum(open, close)
    df = pd.DataFrame({"open": open, "high": high, "low": low, "close": close,
                       "volume": np.ones(n)}, index=idx)
    df["ret_1h"] = df["close"].pct_change()
    if funding is not None:
        df["funding"] = np.asarray(funding, float)
    if oi is not None:
        df["oi"] = np.asarray(oi, float)
        df["d_oi"] = df["oi"].pct_change()
    return df, idx


# ───────────────────────── sinais ─────────────────────────
def test_sequencia_candles_reversao_e_continuacao():
    df, idx = _mk(close=[11, 12, 13, 14], open=[10, 11, 12, 13])  # 4 verdes
    rev = cat.sig_sequencia_candles({"X": df}, ["X"], n=3, modo="reversao")
    assert len(rev) == 2 and all(d == -1 for _, _, d in rev)        # streak verde -> short
    assert {t for _, t, _ in rev} == {idx[2], idx[3]}               # causal: só onde a streak fecha
    cont = cat.sig_sequencia_candles({"X": df}, ["X"], n=3, modo="continuacao")
    assert all(d == 1 for _, _, d in cont)


def test_reacao_nivel_topo_rejeitado_vira_short():
    df, idx = _mk(close=[9, 9, 9, 9, 9.4],
                  open=[9, 9, 9, 9, 9.2],
                  high=[10, 10, 10, 10, 9],
                  low=[8, 8, 8, 8, 9])
    e = cat.sig_reacao_nivel({"X": df}, ["X"], win=3)
    assert e == [("X", idx[3], -1)]   # testou o topo 10 e rejeitou (close 9 < 10)


def test_reacao_nivel_fundo_rejeitado_vira_long():
    # highs decrescentes (não testam topo); só idx4 toca o fundo histórico (9) e rejeita
    df, idx = _mk(close=[15, 15, 15, 15, 9.5],
                  open=[15, 15, 15, 15, 12],
                  high=[20, 19, 18, 17, 16],
                  low=[8, 9, 10, 11, 8])
    e = cat.sig_reacao_nivel({"X": df}, ["X"], win=3)
    assert e == [("X", idx[4], 1)]    # tocou o fundo 9 e fechou acima (9.5) => long


def test_funding_flip_direcao():
    df, idx = _mk(close=[1, 1, 1, 1], funding=[-0.01, -0.01, 0.01, 0.01])
    e = cat.sig_funding_flip({"X": df}, ["X"])
    assert e == [("X", idx[2], 1)]    # neg->pos => long
    df2, idx2 = _mk(close=[1, 1, 1, 1], funding=[0.01, 0.01, -0.01, -0.01])
    e2 = cat.sig_funding_flip({"X": df2}, ["X"])
    assert e2 == [("X", idx2[2], -1)]  # pos->neg => short


def test_funding_flip_ignora_sem_coluna():
    df, _ = _mk(close=[1, 2, 3])
    assert cat.sig_funding_flip({"X": df}, ["X"]) == []


def test_oi_preco_div_oi_sobe_preco_cai_vira_short():
    n = 60
    rng = np.arange(n)
    close = 100 + 0.05 * np.sin(rng)        # baixa vol de base
    oi = 1000 + 0.5 * np.cos(rng)
    close[40:] = np.linspace(100, 80, n - 40)   # preço despenca
    oi[40:] = np.linspace(1000, 1300, n - 40)   # OI dispara
    df, _ = _mk(close=close, oi=oi)
    e = cat.sig_oi_preco_div({"X": df}, ["X"], win=4, z=1.0)
    assert len(e) >= 1
    assert all(d == -1 for _, _, d in e)        # OI up + preço down => short


# ───────────────────────── filtros ─────────────────────────
def test_hora_sessao_filtra_por_hora_utc():
    entries = [("X", h * cat.HOUR, 1) for h in (5, 14, 20, 23)]  # horas UTC 5,14,20,23
    us = cat.flt_hora_sessao(entries, {}, sessao="us")           # us = 13..21
    assert [t // cat.HOUR for _, t, _ in us] == [14, 20]


def test_vol_regime_mantem_so_alta_vol():
    # baixa vol = close flat (ret=0 => z=nan, nunca mantido); alta vol = oscilação ±3
    hi = 100 + np.cumsum(np.full(20, 3.0) * np.where(np.arange(20) % 2 == 0, 1.0, -1.0))
    close = np.r_[np.full(40, 100.0), hi]
    df, idx = _mk(close=close)
    entries = [("X", t, 1) for t in idx]
    kept = cat.flt_vol_regime(entries, {"X": df}, regime="alta", win=3, z=0.5)
    assert kept, "deveria manter entries na região de alta vol"
    assert all(t >= idx[40] for _, t, _ in kept)   # nada da região flat de baixa vol


# ───────────────────────── integração ─────────────────────────
def _spec(**over):
    s = {"signal": "sequencia_candles", "signal_params": {"n": 3, "modo": "continuacao"},
         "filter": "nenhum", "filter_params": {}, "side": "auto",
         "exit": {"type": "horizonte", "bars": 2}, "universe": "todos",
         "fee_bps_roundtrip": 10, "slippage_bps": 2}
    s.update(over)
    return s


def test_build_trades_aplica_custo_e_dedupe():
    df, _ = _mk(close=list(range(11, 25)), open=list(range(10, 24)))  # 14 verdes subindo
    trades = cat.build_trades(_spec(), {"X": df})
    assert len(trades) >= 1
    assert "ret_net_bps" in trades.columns
    assert np.isfinite(trades["ret_net_bps"]).all()
    # custo de 12 bps embutido: gross - 12 = net (verificado via engine do EXP-100)


def test_build_trades_universo_nao_toca_disco():
    df, _ = _mk(close=[11, 12, 13, 14, 15], open=[10, 11, 12, 13, 14])
    # universe 'todos' = chaves do panel sintético; nunca abre o bot.db
    trades = cat.build_trades(_spec(exit={"type": "horizonte", "bars": 1}), {"AAA": df})
    assert set(trades["symbol"]) <= {"AAA"}


def test_spec_signature_dedup():
    a = cat.spec_signature(_spec())
    b = cat.spec_signature(_spec(filter="hora_sessao", filter_params={"sessao": "us"}))
    assert a != b
    assert cat.spec_signature(_spec()) == cat.spec_signature(_spec())  # determinística
