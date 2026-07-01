"""EXP-100 — carregamento e alinhamento do painel cross-section.

Lê o bot.db e devolve, por símbolo, um DataFrame hourly (indexado por bucket_ts)
com OHLCV + features estruturais alinhadas de forma CAUSAL:
  - LSR (long/short ratio) global e top, hourly;
  - OI e ΔOI hourly;
  - funding (cadência 8h) propagado por ffill — usa sempre o último funding
    com time <= bucket (nunca futuro).
Nada aqui decide trade; só monta o painel. Janela = dado farto (~68d).
Universos congelados na mini-moldura 2026-06-17.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DB_DEFAULT = Path(__file__).resolve().parents[2] / "runtime" / "baseline" / "bot.db"

# Universos (atualizado 2026-06-17 com a expansão 14→28 p/ o juiz forward).
# HYPE/SUI/LINK/AVAX/LTC/TRX/WLD/NEAR/ENA/AAVE/TIA/TON ficam só em "todos" (nem meme nem major).
MEMES = {"DOGEUSDT", "1000PEPEUSDT", "SPXUSDT", "TRUMPUSDT", "WIFUSDT",
         "FARTCOINUSDT", "PENGUUSDT", "1000SHIBUSDT", "1000BONKUSDT", "1000FLOKIUSDT"}
LARGE_CAP = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT"}


def _causal_ffill(src: pd.Series, target_index) -> pd.Series:
    """Alinha src (índice esparso, p.ex. funding 8h) ao target hourly usando
    sempre o último valor com índice <= alvo (ffill causal, sem futuro)."""
    if src.empty:
        return pd.Series(index=target_index, dtype=float)
    union = src.reindex(src.index.union(target_index)).sort_index().ffill()
    return union.reindex(target_index)


def load_panel(db_path=DB_DEFAULT, symbols=None):
    con = sqlite3.connect(str(db_path))
    try:
        prices = pd.read_sql_query(
            "SELECT symbol, bucket_ts, open_price, high_price, low_price, "
            "close_price, volume FROM k_prices ORDER BY symbol, bucket_ts", con)
        ratios = pd.read_sql_query(
            "SELECT symbol, bucket_ts, source, long_short_ratio FROM k_ratios", con)
        oi = pd.read_sql_query(
            "SELECT symbol, bucket_ts, sum_open_interest FROM k_open_interest", con)
        funding = pd.read_sql_query(
            "SELECT symbol, funding_time, funding_rate FROM k_funding_rates "
            "ORDER BY symbol, funding_time", con)
        # venda forçada = side='BUY' = LONG liquidado (validado na Etapa 0, 2026-07-01;
        # ver memoria liquidations-side-semantics). NAO usar side='SELL'.
        liq = pd.read_sql_query(
            "SELECT symbol, event_ts, notional FROM k_liquidations WHERE side='BUY'", con)
    finally:
        con.close()

    if symbols is not None:
        symbols = set(symbols)
        prices = prices[prices["symbol"].isin(symbols)]

    ratios_piv = pd.DataFrame()
    if not ratios.empty:
        ratios_piv = ratios.pivot_table(
            index=["symbol", "bucket_ts"], columns="source",
            values="long_short_ratio", aggfunc="last").reset_index()

    # liquidação forçada agregada por (símbolo, hora): soma o notional dos eventos
    # DENTRO da hora [t, t+1h) — causal por construção (nada de futuro).
    liq_agg = None
    if not liq.empty:
        liq = liq.copy()
        liq["bucket_ts"] = (liq["event_ts"] // 1000 // 3600) * 3600
        liq_agg = liq.groupby(["symbol", "bucket_ts"])["notional"].sum()

    panels = {}
    for sym, g in prices.groupby("symbol"):
        g = g.sort_values("bucket_ts").set_index("bucket_ts")
        df = g.rename(columns={"open_price": "open", "high_price": "high",
                               "low_price": "low", "close_price": "close"})[
            ["open", "high", "low", "close", "volume"]].copy()
        df["ret_1h"] = df["close"].pct_change()

        if not ratios_piv.empty:
            r = ratios_piv[ratios_piv["symbol"] == sym].set_index("bucket_ts")
            for col in ("global_account", "top_position", "top_account"):
                if col in r.columns:
                    df[f"lsr_{col}"] = r[col].reindex(df.index)

        if not oi.empty:
            o = oi[oi["symbol"] == sym].set_index("bucket_ts")["sum_open_interest"]
            df["oi"] = o.reindex(df.index)
            df["d_oi"] = df["oi"].pct_change()

        if not funding.empty:
            f = funding[funding["symbol"] == sym].sort_values("funding_time")
            if not f.empty:
                fser = pd.Series(f["funding_rate"].to_numpy(),
                                 index=f["funding_time"].to_numpy())
                df["funding"] = _causal_ffill(fser, df.index).to_numpy()

        # venda forçada (long liq) por hora; 0 = sem liquidação naquela hora.
        # símbolo sem coleta de liquidação fica com a coluna toda 0 (não dispara gatilho).
        if liq_agg is not None and sym in liq_agg.index.get_level_values(0):
            df["liq_sell_notional"] = liq_agg.loc[sym].reindex(df.index).fillna(0.0)
        else:
            df["liq_sell_notional"] = 0.0

        panels[sym] = df
    return panels


def universe(panels, name):
    """Filtra símbolos do painel por universo: 'todos' | 'memes' | 'large_cap'."""
    if name == "todos":
        return list(panels.keys())
    if name == "memes":
        return [s for s in panels if s in MEMES]
    if name == "large_cap":
        return [s for s in panels if s in LARGE_CAP]
    raise ValueError(f"universo desconhecido: {name}")


def time_boundary(panels, is_frac=2.0 / 3.0):
    """bucket_ts que separa IS (primeiros is_frac) de OOS, sobre a janela global."""
    lo = min(df.index.min() for df in panels.values() if len(df))
    hi = max(df.index.max() for df in panels.values() if len(df))
    return int(lo + (hi - lo) * is_frac)
