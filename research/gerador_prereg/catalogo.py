"""Catálogo fechado de primitivas auto-executáveis (espaço NOVO além do Juiz).

Cada primitiva é determinística, CAUSAL (só passado: shift / janelas fechadas <= t)
e carrega um rationale a priori (tese mecanicista — nada de caixa-preta). O gerador
COMPÕE primitivas daqui; nunca escreve código novo por ciclo. O colhedor re-instancia
a partir da spec do journal e mede no forward com a engine validada do EXP-100.

Interface (idêntica ao EXP-100, p/ reuso da engine de medição):
  signal(panels, symbols, **params) -> list[(symbol, ts, direction)]
  filter(entries, panels, **params) -> list[(symbol, ts, direction)]

As 4 famílias e 5 filtros do EXP-100 ficam FORA daqui de propósito — o Juiz já os
varre (146 células). Aqui só entra o que é genuinamente espaço novo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.exp100_screening import backtest as _bt
from research.exp100_screening import data as _data

HOUR = 3600
FOUR_H = 4 * HOUR


# ───────────────────────── helpers causais ─────────────────────────
def _collect(symbol, index, mask, direction):
    """Empacota (symbol, ts, dir) onde mask é True e dir ∈ {+1,-1}."""
    sel = np.asarray(mask, dtype=bool)
    ts = np.asarray(index)[sel]
    dd = np.asarray(direction)[sel]
    out = []
    for t, d in zip(ts, dd):
        if d == 0 or np.isnan(d):
            continue
        out.append((symbol, int(t), int(d)))
    return out


def _causal_z(series: pd.Series) -> pd.Series:
    """z-score expanding CAUSAL (média/desvio só do passado, shift(1))."""
    mu = series.expanding(min_periods=24).mean().shift(1)
    sd = series.expanding(min_periods=24).std().shift(1)
    return (series - mu) / sd


# ───────────────────────── SINAIS (espaço novo) ─────────────────────────
def sig_sequencia_candles(panels, symbols, n=3, modo="reversao"):
    """N candles consecutivos da mesma cor (close>open / close<open).
    Tese: streaks longas marcam exaustão (modo=reversao, aposta contra) ou ímpeto
    (modo=continuacao, a favor). Causal: a streak fecha no close de t (a entrada)."""
    out = []
    for s in symbols:
        df = panels[s]
        up = (df["close"] > df["open"]).astype(int)
        dn = (df["close"] < df["open"]).astype(int)
        run_up = up.rolling(n).sum().to_numpy()   # ==n => n verdes consecutivos
        run_dn = dn.rolling(n).sum().to_numpy()
        streak_up = run_up == n
        streak_dn = run_dn == n
        if modo == "reversao":
            direction = np.where(streak_up, -1.0, np.where(streak_dn, 1.0, 0.0))
        else:  # continuacao
            direction = np.where(streak_up, 1.0, np.where(streak_dn, -1.0, 0.0))
        out += _collect(s, df.index, streak_up | streak_dn, direction)
    return out


def sig_reacao_nivel(panels, symbols, win=24):
    """Preço TESTA a máx/mín de `win` barras anteriores e REJEITA (fecha de volta
    pra dentro do range) -> reversão local. Distinto de breakout (que aposta no
    rompimento). prev_hi/prev_lo via shift(1) = causal."""
    out = []
    for s in symbols:
        df = panels[s]
        prev_hi = df["high"].rolling(win).max().shift(1)
        prev_lo = df["low"].rolling(win).min().shift(1)
        c, h, l = df["close"], df["high"], df["low"]
        testou_hi = ((h >= prev_hi) & (c < prev_hi)).to_numpy()   # tocou topo, rejeitou -> short
        testou_lo = ((l <= prev_lo) & (c > prev_lo)).to_numpy()   # tocou fundo, rejeitou -> long
        direction = np.where(testou_hi, -1.0, np.where(testou_lo, 1.0, 0.0))
        out += _collect(s, df.index, testou_hi | testou_lo, direction)
    return out


def sig_funding_flip(panels, symbols):
    """Funding cruza zero. Tese: virada do regime de posicionamento prossegue na nova
    direção — neg->pos (shorts cederam) = long; pos->neg (longs cederam) = short.
    Requer coluna `funding` (ffill causal já no panel). Sem params (eps=0 fixo)."""
    out = []
    for s in symbols:
        df = panels[s]
        if "funding" not in df.columns:
            continue
        f = df["funding"]
        fp = f.shift(1)
        cross_up = ((fp <= 0) & (f > 0)).to_numpy()   # neg->pos => long
        cross_dn = ((fp >= 0) & (f < 0)).to_numpy()   # pos->neg => short
        direction = np.where(cross_up, 1.0, np.where(cross_dn, -1.0, 0.0))
        out += _collect(s, df.index, cross_up | cross_dn, direction)
    return out


def sig_oi_preco_div(panels, symbols, win=4, z=1.0):
    """Divergência OI×preço na janela `win`, ambos z-extremos causais:
    OI sobe + preço cai = shorts novos acumulando -> short (continuação da pressão);
    OI cai + preço sobe = cobertura de short -> long. Requer coluna `oi`."""
    out = []
    for s in symbols:
        df = panels[s]
        if "oi" not in df.columns:
            continue
        z_oi = _causal_z(df["oi"].pct_change(win))
        z_ret = _causal_z(df["close"].pct_change(win))
        strong = (z_oi.abs() >= z) & (z_ret.abs() >= z)
        oi_up_px_dn = (strong & (z_oi > 0) & (z_ret < 0)).to_numpy()   # -> short
        oi_dn_px_up = (strong & (z_oi < 0) & (z_ret > 0)).to_numpy()   # -> long
        direction = np.where(oi_up_px_dn, -1.0, np.where(oi_dn_px_up, 1.0, 0.0))
        out += _collect(s, df.index, oi_up_px_dn | oi_dn_px_up, direction)
    return out


def _resample_4h(df):
    """Reamostra painel horário -> candles de 4h (alinhados a 00/04/08/12/16/20 UTC).
    Causal: cada candle agrega SÓ as horas do bloco [T, T+4h). `last_hour` = bucket
    horário do close (onde a entry entra: seu close == close do candle 4h)."""
    idx = np.asarray(df.index, dtype=np.int64)
    blk = (idx // FOUR_H) * FOUR_H
    g = df.groupby(blk)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
        "liq": g["liq_sell_notional"].sum(),
    })
    out["last_hour"] = pd.Series(idx, index=df.index).groupby(blk).max()
    return out


def sig_liquidacao_sweep_estrutural(panels, symbols, pivot_side=3, lookback=18,
                                    p_pct=90, p_window=30, reject_within=2):
    """Varredura de fundo estrutural + pico de venda forçada (long liq = side=BUY).
    Tese: num fundo 4h VÁLIDO, o pico de liquidação forçada esgota os vendedores ->
    vácuo -> se o close volta pra dentro (rejeição), reverte (long).
    Causal: pivô só usado após confirmação (i+pivot_side); P90 rolling shift(1);
    varredura/rejeição no close do candle de entrada. Requer coluna `liq_sell_notional`."""
    q = p_pct / 100.0
    out = []
    for s in symbols:
        df = panels.get(s)
        if df is None or "liq_sell_notional" not in df.columns:
            continue
        d4 = _resample_4h(df)
        n = len(d4)
        if n < pivot_side * 2 + 2:
            continue
        low = d4["low"].to_numpy(float)
        close = d4["close"].to_numpy(float)
        liq = d4["liq"].to_numpy(float)
        last_hour = d4["last_hour"].to_numpy(np.int64)
        # P90 rolling CAUSAL: percentil dos p_window candles ANTERIORES (shift 1) —
        # compara liq[t] com o passado, nunca consigo mesmo.
        p90 = d4["liq"].rolling(p_window).quantile(q).shift(1).to_numpy(float)
        # pivôs de fundo (janela centrada); só USADOS a partir de i+pivot_side (confirmação).
        is_piv = np.zeros(n, bool)
        for i in range(pivot_side, n - pivot_side):
            if low[i] == low[i - pivot_side:i + pivot_side + 1].min():
                is_piv[i] = True
        piv_idx = np.flatnonzero(is_piv)
        for t in range(n):
            if not (p90[t] > 0) or not (liq[t] >= p90[t]):     # gatilho de liquidação
                continue
            fundo = None                                        # fundo válido = pivô
            for i in piv_idx:                                   # confirmado, dentro do lookback
                if i > t - pivot_side:
                    break
                if i >= t - lookback:
                    fundo = low[i]
            if fundo is None or not (low[t] < fundo):           # exige varredura do fundo
                continue
            for tr in range(t, min(t + reject_within + 1, n)):  # rejeição em <= within candles
                if close[tr] > fundo:
                    out.append((s, int(last_hour[tr]), 1))
                    break
    return out


def sig_liquidacao_discriminante(panels, symbols, ret_pct=20, liq_pct=75, p_window=30):
    """Discriminante da qualidade da queda (long liq = side=BUY). Tese: queda COM venda
    forçada alta = venda inelástica/temporária -> overshoot -> reverte (long); queda SEM
    liquidação = repricing informado -> continua. Caso-base: LONG quando o candle 4h cai
    (ret < 0 e no quantil inferior causal) E a liquidação é alta (>= P{liq_pct} causal
    rolling). Causal: percentis rolling shift(1). Requer coluna `liq_sell_notional`."""
    out = []
    for s in symbols:
        df = panels.get(s)
        if df is None or "liq_sell_notional" not in df.columns:
            continue
        d4 = _resample_4h(df)
        if len(d4) < p_window + 1:
            continue
        ret = d4["close"].pct_change()
        ret_thr = ret.rolling(p_window).quantile(ret_pct / 100.0).shift(1).to_numpy(float)
        liq_thr = d4["liq"].rolling(p_window).quantile(liq_pct / 100.0).shift(1).to_numpy(float)
        r = ret.to_numpy(float)
        lq = d4["liq"].to_numpy(float)
        last_hour = d4["last_hour"].to_numpy(np.int64)
        for t in range(len(d4)):
            if np.isnan(ret_thr[t]) or not (liq_thr[t] > 0):
                continue
            if r[t] < 0 and r[t] <= ret_thr[t] and lq[t] >= liq_thr[t]:
                out.append((s, int(last_hour[t]), 1))   # queda + venda forçada alta -> long
    return out


# ───────────────────────── FILTROS (espaço novo) ─────────────────────────
_SESSOES = {            # janelas UTC (sobrepõem de propósito; escolha exclui as outras)
    "asia": set(range(0, 8)),
    "europa": set(range(7, 16)),
    "us": set(range(13, 22)),
}


def flt_nenhum(entries, panels):
    return list(entries)


def flt_hora_sessao(entries, panels, sessao="us"):
    """Mantém só entries cuja hora UTC do bucket cai na sessão. Tese: liquidez e
    comportamento variam por sessão (ásia/europa/us)."""
    horas = _SESSOES[sessao]
    return [(s, ts, d) for (s, ts, d) in entries if (int(ts) // HOUR) % 24 in horas]


def flt_vol_regime(entries, panels, regime="alta", win=24, z=0.5):
    """Mantém entries em regime de vol realizada alta/baixa (rolling std de ret_1h),
    classificado por z causal (vol via shift(1), estritamente pré-barra)."""
    flags = {}
    for s, df in panels.items():
        vol = df["ret_1h"].rolling(win).std().shift(1)
        zz = _causal_z(vol)
        flags[s] = (zz >= z) if regime == "alta" else (zz <= -z)
    out = []
    for s, ts, d in entries:
        f = flags.get(s)
        if f is not None and ts in f.index and bool(f.loc[ts]):
            out.append((s, ts, d))
    return out


# ───────────────────────── registries ─────────────────────────
# param_space: valores PERMITIDOS por param (o gerador amostra daqui; o schema valida).
SIGNALS = {
    "sequencia_candles": {
        "fn": sig_sequencia_candles,
        "rationale": "streak de N candles mesma cor = exaustão (reversão) ou ímpeto (continuação)",
        "param_space": {"n": [3, 4, 5], "modo": ["reversao", "continuacao"]},
    },
    "reacao_nivel": {
        "fn": sig_reacao_nivel,
        "rationale": "teste e rejeição de máx/mín de janela = suporte/resistência -> reversão local",
        "param_space": {"win": [12, 24, 48]},
    },
    "funding_flip": {
        "fn": sig_funding_flip,
        "rationale": "funding cruza zero = virada de crowding prossegue na nova direção",
        "param_space": {},
    },
    "oi_preco_div": {
        "fn": sig_oi_preco_div,
        "rationale": "divergência OI×preço revela acumulação de shorts (->short) ou cobertura (->long)",
        "param_space": {"win": [4, 8], "z": [1.0, 1.5]},
    },
    "liquidacao_sweep_estrutural": {
        "fn": sig_liquidacao_sweep_estrutural,
        "rationale": "pico de venda forçada (long liq, side=BUY) varrendo fundo 4h válido "
                     "-> exaustão dos forçados -> reversão (long)",
        "param_space": {"pivot_side": [3], "lookback": [12, 18, 24],
                        "p_pct": [90, 95], "p_window": [30], "reject_within": [2]},
    },
    "liquidacao_discriminante": {
        "fn": sig_liquidacao_discriminante,
        "rationale": "queda com venda forçada (long liq) alta = overshoot inelástico -> reverte "
                     "(long); queda sem liquidação = repricing informado (continua)",
        "param_space": {"ret_pct": [10, 20], "liq_pct": [75, 90], "p_window": [30]},
    },
}

FILTERS = {
    "nenhum": {"fn": flt_nenhum, "rationale": "sem filtro", "param_space": {}},
    "hora_sessao": {
        "fn": flt_hora_sessao,
        "rationale": "liquidez/comportamento variam por sessão UTC",
        "param_space": {"sessao": ["asia", "europa", "us"]},
    },
    "vol_regime": {
        "fn": flt_vol_regime,
        "rationale": "edges de momentum/reversão dependem do regime de vol realizada",
        "param_space": {"regime": ["alta", "baixa"], "win": [24], "z": [0.5]},
    },
}

EXITS = {
    "horizonte": {
        "rationale": "saída no close de entry + H barras (engine validada EXP-100)",
        "param_space": {"bars": [4, 8, 24]},
    },
}

UNIVERSES = ["todos", "memes", "large_cap"]


# ───────────────────────── execução de uma spec ─────────────────────────
def build_trades(spec, panels):
    """Re-instancia uma spec do journal e devolve o DataFrame de trades (ret_net_bps).
    Usado pelo colhedor — Python puro, determinístico, sem Claude. Não toca disco:
    recebe `panels` já carregado (real no marco, ou sintético nos testes)."""
    sig = SIGNALS[spec["signal"]]
    syms = _data.universe(panels, spec["universe"])
    entries = sig["fn"](panels, syms, **spec.get("signal_params", {}))

    flt = FILTERS[spec["filter"]]
    entries = flt["fn"](entries, panels, **spec.get("filter_params", {}))

    bars = spec["exit"]["bars"]
    entries = _bt.dedupe_overlap(entries, bars)
    cost = float(spec["fee_bps_roundtrip"]) + float(spec["slippage_bps"])
    return _bt.trade_returns(entries, panels, bars, fee_bps=cost)


def spec_signature(spec):
    """Assinatura canônica de uma spec — usada p/ deduplicação (não repetir hipótese)."""
    parts = [
        spec["signal"], _kv(spec.get("signal_params", {})),
        spec["filter"], _kv(spec.get("filter_params", {})),
        spec["universe"], f"H{spec['exit']['bars']}",
    ]
    return "|".join(parts)


def _kv(d):
    return ",".join(f"{k}={d[k]}" for k in sorted(d))
