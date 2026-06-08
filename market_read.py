"""
Leitura de mercado sob demanda para apoio a decisao de spot manual (comando /mercado).

Funcoes PURAS de leitura (recebem conn, retornam dict/list) + formatacao (dict -> HTML Telegram).
NAO opera, NAO coleta, NAO sinaliza. Read-only sobre as tabelas k_*.

Convencao do side em k_liquidations (Bybit allLiquidation = "position side", confirmado 2026-06-08):
    BUY  = LONG  liquidado  -> cascata para baixo (pressao de baixa)
    SELL = SHORT liquidado  -> squeeze para cima  (pressao de alta)
Fonte: bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation
Coletor grava o 'S' cru (ver bybit_liquidation_feed.py); a interpretacao mora aqui.
Revalidar com dados forward (amostra inicial ~1 dia) -- esta constante e o ponto unico de correcao.
"""
from __future__ import annotations

import sqlite3

# Convencao do side -- ponto unico de verdade (corrigir SO aqui se o feed/fonte mudar)
LIQ_LONG_SIDE = "BUY"
LIQ_SHORT_SIDE = "SELL"

# Majors usados no termometro macro. Lista total e derivada do banco (all_symbols).
MAJORS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def all_symbols(conn: sqlite3.Connection) -> list[str]:
    """Simbolos efetivamente coletados (deriva do banco, nao hardcode)."""
    rows = conn.execute("SELECT DISTINCT symbol FROM k_prices ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


# ----------------------------------------------------------------------------
# Instrumento 2: mapa de pressao (liquidacoes)
# ----------------------------------------------------------------------------

def read_pressure(conn: sqlite3.Connection, hours: int = 24) -> list[dict]:
    """Liquidacoes por simbolo na janela (default 24h), ancoradas no evento mais recente.

    BUY=long liquidado, SELL=short liquidado (ver cabecalho). dominant_side e o lado
    MAIS liquidado: 'LONG' (cascata para baixo) ou 'SHORT' (squeeze para cima).
    """
    anchor = conn.execute("SELECT MAX(event_ts) FROM k_liquidations").fetchone()[0]
    if anchor is None:
        return []
    cutoff = anchor - hours * 3600 * 1000  # event_ts em ms
    rows = conn.execute(
        f"""
        SELECT symbol,
               SUM(CASE WHEN side='{LIQ_LONG_SIDE}'  THEN notional ELSE 0 END) AS longs_liq,
               SUM(CASE WHEN side='{LIQ_SHORT_SIDE}' THEN notional ELSE 0 END) AS shorts_liq,
               COUNT(*) AS events
        FROM k_liquidations
        WHERE event_ts > ?
        GROUP BY symbol
        HAVING SUM(notional) > 0
        ORDER BY SUM(notional) DESC
        """,
        (cutoff,),
    ).fetchall()
    out = []
    for r in rows:
        longs = r["longs_liq"] or 0.0
        shorts = r["shorts_liq"] or 0.0
        out.append({
            "symbol": r["symbol"],
            "longs_liq_usd": longs,
            "shorts_liq_usd": shorts,
            "total_usd": longs + shorts,
            "events": r["events"],
            "dominant_side": "LONG" if longs >= shorts else "SHORT",
        })
    return out


# ----------------------------------------------------------------------------
# Instrumento 1: termometro de regime -- tendencia
# ----------------------------------------------------------------------------

def _latest_close(conn: sqlite3.Connection, symbol: str):
    row = conn.execute(
        "SELECT bucket_ts, close_price FROM k_prices WHERE symbol=? ORDER BY bucket_ts DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    return (row["bucket_ts"], row["close_price"]) if row else (None, None)


def ret_pct(conn: sqlite3.Connection, symbol: str, hours: int) -> float | None:
    """Retorno % entre o close mais recente e o close em (mais_recente - hours).
    Robusto a gaps: usa o bucket com bucket_ts <= alvo (o mais recente que satisfaz)."""
    latest_ts, latest_close = _latest_close(conn, symbol)
    if latest_ts is None or not latest_close:
        return None
    target = latest_ts - hours * 3600
    row = conn.execute(
        "SELECT close_price FROM k_prices WHERE symbol=? AND bucket_ts<=? ORDER BY bucket_ts DESC LIMIT 1",
        (symbol, target),
    ).fetchone()
    if not row or not row["close_price"]:
        return None
    return 100.0 * (latest_close / row["close_price"] - 1)


def read_returns(conn: sqlite3.Connection, symbols, hours: int) -> dict:
    return {s: ret_pct(conn, s, hours) for s in symbols}


def read_breadth(conn: sqlite3.Connection, hours: int = 24) -> dict:
    """Amplitude: quantos dos simbolos coletados estao positivos na janela."""
    up = 0
    total = 0
    for s in all_symbols(conn):
        r = ret_pct(conn, s, hours)
        if r is not None:
            total += 1
            if r > 0:
                up += 1
    return {"up": up, "total": total, "pct_up": (100.0 * up / total if total else None)}


# ----------------------------------------------------------------------------
# Instrumento 1: termometro de regime -- volatilidade e fluxo
# ----------------------------------------------------------------------------

def _window_cutoff(conn: sqlite3.Connection, symbol: str, hours: int):
    latest_ts, _ = _latest_close(conn, symbol)
    return None if latest_ts is None else latest_ts - hours * 3600


def read_volatility(conn: sqlite3.Connection, symbol: str, hours: int = 24) -> float | None:
    """Volatilidade = media de (high-low)/open*100 nas velas da janela."""
    cutoff = _window_cutoff(conn, symbol, hours)
    if cutoff is None:
        return None
    rows = conn.execute(
        "SELECT open_price, high_price, low_price FROM k_prices WHERE symbol=? AND bucket_ts>?",
        (symbol, cutoff),
    ).fetchall()
    vals = [100.0 * (r["high_price"] - r["low_price"]) / r["open_price"]
            for r in rows if r["open_price"]]
    return sum(vals) / len(vals) if vals else None


def read_taker_ratio(conn: sqlite3.Connection, symbol: str, hours: int = 24) -> float | None:
    """% do volume que foi taker comprador (>50% = pressao compradora)."""
    cutoff = _window_cutoff(conn, symbol, hours)
    if cutoff is None:
        return None
    row = conn.execute(
        "SELECT SUM(taker_buy_base) tb, SUM(volume) v FROM k_prices WHERE symbol=? AND bucket_ts>?",
        (symbol, cutoff),
    ).fetchone()
    if not row or not row["v"]:
        return None
    return 100.0 * (row["tb"] or 0.0) / row["v"]


# ----------------------------------------------------------------------------
# Instrumento 1: termometro de regime -- crowding e alavancagem
# ----------------------------------------------------------------------------

def read_lsr(conn: sqlite3.Connection, symbol: str) -> dict:
    """Long/short ratio mais recente por source ('global_account' e 'top_position')."""
    out = {"global": None, "top": None}
    for source, key in (("global_account", "global"), ("top_position", "top")):
        row = conn.execute(
            "SELECT long_short_ratio FROM k_ratios WHERE symbol=? AND source=? "
            "ORDER BY bucket_ts DESC LIMIT 1",
            (symbol, source),
        ).fetchone()
        if row:
            out[key] = row["long_short_ratio"]
    return out


def read_funding(conn: sqlite3.Connection, symbol: str) -> dict:
    """Funding rate mais recente (funding_time em epoch s, granularidade 8h)."""
    row = conn.execute(
        "SELECT funding_time, funding_rate FROM k_funding_rates WHERE symbol=? "
        "ORDER BY funding_time DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if not row:
        return {"funding_rate": None, "funding_time": None}
    return {"funding_rate": row["funding_rate"], "funding_time": row["funding_time"]}


def read_basis(conn: sqlite3.Connection, symbol: str) -> dict:
    """Basis rate mais recente (futures vs index)."""
    row = conn.execute(
        "SELECT bucket_ts, basis_rate FROM k_basis WHERE symbol=? ORDER BY bucket_ts DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if not row:
        return {"basis_rate": None, "bucket_ts": None}
    return {"basis_rate": row["basis_rate"], "bucket_ts": row["bucket_ts"]}


def read_oi_change(conn: sqlite3.Connection, symbol: str, hours: int = 24) -> float | None:
    """% de variacao do sum_open_interest entre agora e (agora - hours). Robusto a gaps."""
    row = conn.execute(
        "SELECT bucket_ts, sum_open_interest FROM k_open_interest WHERE symbol=? "
        "ORDER BY bucket_ts DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if not row or not row["sum_open_interest"]:
        return None
    latest_ts, latest_oi = row["bucket_ts"], row["sum_open_interest"]
    prev = conn.execute(
        "SELECT sum_open_interest FROM k_open_interest WHERE symbol=? AND bucket_ts<=? "
        "ORDER BY bucket_ts DESC LIMIT 1",
        (symbol, latest_ts - hours * 3600),
    ).fetchone()
    if not prev or not prev["sum_open_interest"]:
        return None
    return 100.0 * (latest_oi / prev["sum_open_interest"] - 1)


# ----------------------------------------------------------------------------
# Instrumento 1: composicao do termometro macro
# ----------------------------------------------------------------------------

def read_regime(conn: sqlite3.Connection) -> dict:
    """Termometro macro: componentes lado a lado (SEM veredito). Micro pesada em BTC."""
    return {
        "returns_24h": read_returns(conn, MAJORS, 24),
        "returns_7d": read_returns(conn, MAJORS, 24 * 7),
        "breadth_24h": read_breadth(conn, 24),
        "volatility_btc": read_volatility(conn, "BTCUSDT", 24),
        "taker_btc": read_taker_ratio(conn, "BTCUSDT", 24),
        "lsr_btc": read_lsr(conn, "BTCUSDT"),
        "funding": {s: read_funding(conn, s) for s in MAJORS},
        "basis_btc": read_basis(conn, "BTCUSDT"),
        "oi_change_btc": read_oi_change(conn, "BTCUSDT", 24),
    }


def read_symbol(conn: sqlite3.Connection, symbol: str) -> dict:
    """Tudo de uma moeda num lugar (zoom do /mercado <SYM>)."""
    symbol = symbol.upper()
    pressure = next((p for p in read_pressure(conn, 24) if p["symbol"] == symbol), {})
    return {
        "symbol": symbol,
        "ret_24h": ret_pct(conn, symbol, 24),
        "ret_7d": ret_pct(conn, symbol, 24 * 7),
        "lsr": read_lsr(conn, symbol),
        "funding": read_funding(conn, symbol),
        "basis": read_basis(conn, symbol),
        "oi_change_24h": read_oi_change(conn, symbol, 24),
        "volatility_24h": read_volatility(conn, symbol, 24),
        "taker_24h": read_taker_ratio(conn, symbol, 24),
        "pressure": pressure,
    }


# ----------------------------------------------------------------------------
# Formatacao (dict/list -> HTML Telegram). Mostra componentes, NAO veredito.
# ----------------------------------------------------------------------------

def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "n/d"
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.2f}M"
    if a >= 1e3:
        return f"${v / 1e3:.0f}k"
    return f"${v:.0f}"


def _fmt_pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "n/d"
    return f"{v:+.2f}%" if signed else f"{v:.2f}%"


def _fmt_num(v: float | None, decimals: int = 2) -> str:
    return "n/d" if v is None else f"{v:.{decimals}f}"


def _sym_short(symbol: str) -> str:
    """BTCUSDT -> BTC para exibicao compacta."""
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _pressure_label(p: dict) -> str:
    """Lado dominante: LONG liquidado=cascata baixa (vermelho); SHORT=squeeze alta (verde)."""
    total = p.get("total_usd") or 0.0
    if p.get("dominant_side") == "LONG":
        share = 100.0 * p["longs_liq_usd"] / total if total else 0.0
        return f"\U0001f534 longs {share:.0f}% (cascata ↓)"
    share = 100.0 * p["shorts_liq_usd"] / total if total else 0.0
    return f"\U0001f7e2 shorts {share:.0f}% (squeeze ↑)"


def format_macro(regime: dict, pressure: list[dict], top_n: int = 8) -> str:
    """Termometro macro + mapa de pressao em HTML. Mostra componentes, NAO veredito."""
    lines = ["\U0001f4ca <b>Leitura de Mercado</b>", ""]

    # --- Tendencia (majors) ---
    lines.append("\U0001f4c8 <b>Tendencia</b> (24h / 7d)")
    for sym in MAJORS:
        r24 = regime["returns_24h"].get(sym)
        r7 = regime["returns_7d"].get(sym)
        lines.append(f"  {_sym_short(sym)}: <code>{_fmt_pct(r24)}</code> / <code>{_fmt_pct(r7)}</code>")
    b = regime["breadth_24h"]
    breadth = f"{b['up']}/{b['total']}" if b["total"] else "n/d"
    lines.append(f"  Amplitude: <code>{breadth}</code> positivos 24h")
    lines.append("")

    # --- Volatilidade / fluxo (BTC) ---
    lines.append("\U0001f300 <b>Vol &amp; Fluxo</b> (BTC, 24h)")
    lines.append(f"  Range medio: <code>{_fmt_pct(regime['volatility_btc'], signed=False)}</code>")
    lines.append(f"  Taker buy: <code>{_fmt_pct(regime['taker_btc'], signed=False)}</code>")
    lines.append("")

    # --- Crowding / alavancagem (BTC) ---
    lsr = regime["lsr_btc"]
    fr = regime["funding"].get("BTCUSDT", {}).get("funding_rate")
    fr_str = f"{fr * 100:+.4f}%" if fr is not None else "n/d"
    lines.append("\U0001f9ed <b>Posicionamento</b> (BTC)")
    lines.append(f"  LSR global/top: <code>{_fmt_num(lsr['global'])}</code> / <code>{_fmt_num(lsr['top'])}</code>")
    lines.append(f"  Funding: <code>{fr_str}</code>")
    lines.append(f"  Basis: <code>{_fmt_num(regime['basis_btc']['basis_rate'], 4)}</code>")
    lines.append(f"  OI 24h: <code>{_fmt_pct(regime['oi_change_btc'])}</code>")
    lines.append("")

    # --- Mapa de pressao (liquidacoes) ---
    lines.append("\U0001f525 <b>Pressao 24h</b> (liquidacoes)")
    if not pressure:
        lines.append("  <i>sem dados</i>")
    else:
        for p in pressure[:top_n]:
            lines.append(f"  {_sym_short(p['symbol'])}: {_fmt_usd(p['total_usd'])} — "
                         f"{_pressure_label(p)} · {p['events']}ev")
    return "\n".join(lines)


def format_symbol(data: dict) -> str:
    """Zoom de uma moeda em HTML (sem veredito)."""
    sym = _sym_short(data["symbol"])
    lsr = data["lsr"]
    fr = data["funding"].get("funding_rate")
    fr_str = f"{fr * 100:+.4f}%" if fr is not None else "n/d"
    lines = [
        f"\U0001f50e <b>{sym}</b>",
        "",
        f"Retorno: <code>{_fmt_pct(data['ret_24h'])}</code> 24h · "
        f"<code>{_fmt_pct(data['ret_7d'])}</code> 7d",
        f"Range medio 24h: <code>{_fmt_pct(data['volatility_24h'], signed=False)}</code>",
        f"Taker buy 24h: <code>{_fmt_pct(data['taker_24h'], signed=False)}</code>",
        "",
        f"LSR global/top: <code>{_fmt_num(lsr['global'])}</code> / <code>{_fmt_num(lsr['top'])}</code>",
        f"Funding: <code>{fr_str}</code>",
        f"Basis: <code>{_fmt_num(data['basis']['basis_rate'], 4)}</code>",
        f"OI 24h: <code>{_fmt_pct(data['oi_change_24h'])}</code>",
        "",
    ]
    p = data["pressure"]
    if p:
        lines.append(f"\U0001f525 Pressao 24h: {_fmt_usd(p['total_usd'])} — "
                     f"{_pressure_label(p)} · {p['events']}ev")
    else:
        lines.append("\U0001f525 Pressao 24h: <i>sem liquidacoes</i>")
    return "\n".join(lines)
