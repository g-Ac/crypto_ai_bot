"""
Views da aba Mercado do Trade Desk (porta 5000).

Monta dicts prontos pra template Jinja consumindo o motor validado do
market_read.py SEM modifica-lo. Leitura, NAO sinal: sem score, sem veredito.

Validade de simbolo vem da lista canonica (copia de scripts/k_collector.SYMBOLS,
teste de paridade garante sync) — NUNCA de all_symbols(conn): em banco vazio a
lista do banco e vazia e quebraria o requisito "banco vazio renderiza n/d".

Helpers privados do market_read (_pressure_label, _fmt_*) sao importados de
proposito (spec 2026-06-10, ajuste 2): a decisao e nao tocar no motor, e o
teste anti-divergencia denuncia se o rotulo web divergir do Telegram.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

import market_read as mr

# Copia canonica de scripts/k_collector.SYMBOLS (teste de paridade garante sync).
# Ordem DEVE espelhar k_collector.SYMBOLS exatamente (o teste compara tuple==tuple).
SUPPORTED_MARKET_SYMBOLS = (
    # núcleo original (14)
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "HYPEUSDT", "LINKUSDT", "AVAXUSDT",
    "LTCUSDT", "TRXUSDT", "SUIUSDT", "1000PEPEUSDT",
    # expansão 2026-06-17 — memes (8):
    "SPXUSDT", "TRUMPUSDT", "WIFUSDT", "FARTCOINUSDT", "PENGUUSDT",
    "1000SHIBUSDT", "1000BONKUSDT", "1000FLOKIUSDT",
    # alts alto-beta (6):
    "WLDUSDT", "NEARUSDT", "ENAUSDT", "AAVEUSDT", "TIAUSDT", "TONUSDT",
)

# Espelho de SYMBOLS em static/js/mapa.js (o Mapa da Moeda so cobre BTC/ETH)
MAP_SYMBOLS = ("BTCUSDT", "ETHUSDT")


def normalize_symbol(raw) -> str | None:
    """'BTC' -> 'BTCUSDT', 'btcusdt' -> 'BTCUSDT'; None se nao esta na lista canonica.
    Borda conhecida: 'PEPE' -> 'PEPEUSDT' -> None (lista tem 1000PEPEUSDT)."""
    token = (raw or "").strip().upper()
    if not token:
        return None
    symbol = token if token.endswith("USDT") else f"{token}USDT"
    return symbol if symbol in SUPPORTED_MARKET_SYMBOLS else None


def _num(value, text: str) -> dict:
    """Par valor cru + texto formatado: o template colore pelo sinal de value."""
    return {"value": value, "text": text}


def _fmt_funding(rate) -> dict:
    return _num(rate, f"{rate * 100:+.4f}%" if rate is not None else "n/d")


def _pressure_row(p: dict) -> dict:
    """Linha do mapa de pressao pronta pra barra split CSS + rotulo do Telegram."""
    total = p.get("total_usd") or 0.0
    return {
        "symbol": p["symbol"],
        "name": mr._sym_short(p["symbol"]),
        "total": mr._fmt_usd(p["total_usd"]),
        "label": mr._pressure_label(p),          # EXATAMENTE o rotulo do Telegram
        "longs_pct": 100.0 * p["longs_liq_usd"] / total if total else 0.0,
        "shorts_pct": 100.0 * p["shorts_liq_usd"] / total if total else 0.0,
        "events": p["events"],
    }


def _freshness_view(fresh: dict) -> dict:
    """Chave 'sources' (nao 'items': .items em Jinja resolve pro metodo de dict)."""
    sources = [{"label": lbl, "age": mr._fmt_age(d["age_s"]), "stale": d["stale"]}
               for lbl, d in fresh.items()]
    return {"sources": sources,
            "stale_labels": [s["label"] for s in sources if s["stale"]]}


def _read_at(now_s: int) -> str:
    """Hora local do servidor, como o resto do dashboard."""
    return datetime.fromtimestamp(now_s).strftime("%H:%M")


def macro_view(conn: sqlite3.Connection, now_s: int) -> dict:
    """Leitura macro pronta pra mercado.html. Componentes, NAO veredito."""
    regime = mr.read_regime(conn)
    pressure = mr.read_pressure(conn, 24)
    majors = []
    for sym in mr.MAJORS:
        r24 = regime["returns_24h"].get(sym)
        r7 = regime["returns_7d"].get(sym)
        majors.append({
            "symbol": sym,
            "name": mr._sym_short(sym),
            "ret_24h": _num(r24, mr._fmt_pct(r24)),
            "ret_7d": _num(r7, mr._fmt_pct(r7)),
        })
    b = regime["breadth_24h"]
    funding = [{"name": mr._sym_short(sym),
                "rate": _fmt_funding(regime["funding"].get(sym, {}).get("funding_rate"))}
               for sym in mr.MAJORS]
    return {
        "majors": majors,
        "breadth": f"{b['up']}/{b['total']}" if b["total"] else "n/d",
        "vol_btc": mr._fmt_pct(regime["volatility_btc"], signed=False),
        "taker_btc": mr._fmt_pct(regime["taker_btc"], signed=False),
        "lsr": {"global": mr._fmt_num(regime["lsr_btc"]["global"]),
                "top": mr._fmt_num(regime["lsr_btc"]["top"])},
        "funding": funding,
        "basis_btc": _num(regime["basis_btc"]["basis_rate"],
                          mr._fmt_num(regime["basis_btc"]["basis_rate"], 4)),
        "oi_btc": _num(regime["oi_change_btc"], mr._fmt_pct(regime["oi_change_btc"])),
        "pressure": [_pressure_row(p) for p in pressure],
        "translation": mr.translate_macro(regime, pressure),
        "freshness": _freshness_view(mr.read_freshness(conn, now_s)),
        "read_at": _read_at(now_s),
    }


def symbol_view(conn: sqlite3.Connection, symbol: str, now_s: int) -> dict:
    """Zoom de uma moeda pronto pra mercado_symbol.html (sem veredito).
    `symbol` ja deve vir normalizado (normalize_symbol na rota)."""
    data = mr.read_symbol(conn, symbol)
    p = data["pressure"]
    return {
        "symbol": data["symbol"],
        "name": mr._sym_short(data["symbol"]),
        "ret_24h": _num(data["ret_24h"], mr._fmt_pct(data["ret_24h"])),
        "ret_7d": _num(data["ret_7d"], mr._fmt_pct(data["ret_7d"])),
        "vol": mr._fmt_pct(data["volatility_24h"], signed=False),
        "taker": mr._fmt_pct(data["taker_24h"], signed=False),
        "lsr": {"global": mr._fmt_num(data["lsr"]["global"]),
                "top": mr._fmt_num(data["lsr"]["top"])},
        "funding": _fmt_funding(data["funding"].get("funding_rate")),
        "basis": _num(data["basis"]["basis_rate"], mr._fmt_num(data["basis"]["basis_rate"], 4)),
        "oi": _num(data["oi_change_24h"], mr._fmt_pct(data["oi_change_24h"])),
        "pressure": _pressure_row(p) if p else None,
        "translation": mr.translate_symbol(data),
        "freshness": _freshness_view(mr.read_freshness(conn, now_s)),
        "read_at": _read_at(now_s),
        "tem_mapa": data["symbol"] in MAP_SYMBOLS,
    }
