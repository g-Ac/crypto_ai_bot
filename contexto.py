"""Copiloto — Contexto (o 🌡️ termometro do mercado).

Fatia do painel pre-trade: da ao Gabriel o CLIMA do mercado antes de decidir. LEITURA, NAO
PREVISAO — descreve o estado (BTC, funding, liquidacao, medo/ganancia) e sugere DISCIPLINA,
nunca direcao. Reusa o market_read.py (regime/funding/liquidacao ja validados); a unica peca
nova e o Fear & Greed (api.alternative.me, externo, cacheado).
"""
from __future__ import annotations

import sqlite3
import time

DB_PATH = "/home/pi/crypto_ai_bot/runtime/baseline/bot.db"

_FNG_CACHE = {"ts": 0.0, "data": None}
_FNG_TTL = 3600.0   # F&G atualiza ~1x/dia; cache de 1h evita martelar a API


def fear_greed(_fetch=None):
    """Fear & Greed Index (alternative.me). Cache 1h; stale-on-error. Retorna {value:int,
    label:str} ou None. _fetch injetavel p/ teste (sem rede)."""
    now = time.time()
    if _fetch is None and _FNG_CACHE["data"] is not None and now - _FNG_CACHE["ts"] < _FNG_TTL:
        return _FNG_CACHE["data"]
    try:
        if _fetch is None:
            import requests
            js = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8).json()
        else:
            js = _fetch()
        d = js["data"][0]
        out = {"value": int(d["value"]), "label": str(d["value_classification"])}
        _FNG_CACHE.update(ts=now, data=out)
        return out
    except Exception:
        return _FNG_CACHE["data"]   # cache velho se a rede falhar (ou None)


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def ler_contexto(conn=None, fng=None) -> dict:
    """Compoe o contexto reusando market_read. conn/fng injetaveis p/ teste."""
    import market_read as mr
    fechar = False
    if conn is None:
        conn = _conn()
        fechar = True
    try:
        pressure = mr.read_pressure(conn, 24)
        return {
            "btc_ret_24h": mr.ret_pct(conn, "BTCUSDT", 24),
            "funding_btc": mr.read_funding(conn, "BTCUSDT"),
            "liq_btc": next((p for p in pressure if p["symbol"] == "BTCUSDT"), {}),
            "breadth": mr.read_breadth(conn, 24),
            "fng": fng if fng is not None else fear_greed(),
        }
    finally:
        if fechar:
            conn.close()


def _clima_frase(ctx) -> str:
    """Sintese de 1 linha: DESCRITIVA + disciplina, NUNCA previsao de direcao."""
    btc = ctx.get("btc_ret_24h") or 0.0
    liq = (ctx.get("liq_btc") or {}).get("dominant_side")
    v = (ctx.get("fng") or {}).get("value")
    if btc < -2 and liq == "LONG":
        return ("Clima de queda com longs sendo liquidados — cuidado pra não comprar a faca. "
                "Se for entrar, espera a confirmação (a faca parar).")
    if btc > 2 and liq == "SHORT":
        return ("Clima de alta com shorts sendo esmagados — o squeeze pode esticar, mas não corre "
                "atrás. Se tá comprado, a vigia de saída é tua amiga.")
    if v is not None and v <= 25:
        return ("Medo extremo — onde a mão fraca costuma vender. Não é sinal de compra, é hora de "
                "disciplina e não de pânico.")
    if v is not None and v >= 75:
        return ("Ganância extrema — hora de proteger lucro, não de perseguir. Deixa a vigia de saída "
                "trabalhar.")
    return "Sem extremo claro no clima — segue tua régua, sem pressa."


def format_clima(ctx) -> str:
    """Termometro compacto (HTML Telegram). Mostra componentes + a frase de disciplina. Puro."""
    btc = ctx.get("btc_ret_24h")
    fund = (ctx.get("funding_btc") or {}).get("funding_rate")
    liq = ctx.get("liq_btc") or {}
    breadth = ctx.get("breadth") or {}
    fng = ctx.get("fng")

    linhas = ["<b>🌡️ Contexto do mercado</b> <i>(leitura, não previsão)</i>"]
    if btc is not None:
        seta = "🟢↑" if btc > 1 else ("🔴↓" if btc < -1 else "⚪→")
        regime = "subindo" if btc > 1 else ("caindo" if btc < -1 else "lateral")
        linhas.append(f"• BTC 24h: <b>{btc:+.1f}%</b> {seta} ({regime})")
    if breadth.get("pct_up") is not None:
        linhas.append(f"• Amplitude: {breadth['up']}/{breadth['total']} moedas no verde "
                      f"({breadth['pct_up']:.0f}%)")
    if fund is not None:
        quem = ("longs pagando (crowd comprado)" if fund > 0
                else "shorts pagando (crowd vendido)" if fund < 0 else "neutro")
        linhas.append(f"• Funding BTC: {fund*100:+.3f}% — {quem}")
    if liq.get("dominant_side"):
        desc = ("liquidando LONGS (cascata pra baixo)" if liq["dominant_side"] == "LONG"
                else "liquidando SHORTS (squeeze pra cima)")
        linhas.append(f"• Liquidação 24h: {desc} — ${(liq.get('total_usd', 0) or 0)/1e6:.1f}M")
    if fng:
        linhas.append(f"• Fear &amp; Greed: <b>{fng['value']}</b> ({fng['label']})")
    linhas.append("")
    linhas.append(f"<i>{_clima_frase(ctx)}</i>")
    return "\n".join(linhas)


def cmd_clima(arg="", _ctx=None):
    """/clima — termometro do mercado (BTC, funding, liquidacao, Fear&Greed). Leitura, nao sinal."""
    if _ctx is not None:
        return format_clima(_ctx)
    try:
        return format_clima(ler_contexto())
    except Exception as e:
        return f"Não consegui ler o contexto agora: {e}"
