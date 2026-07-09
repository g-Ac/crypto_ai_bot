"""Copiloto de Disciplina — Modulo B: Vigia de Saida (anti-sair-tarde).

NAO preve, NAO opera, SEM alavancagem. So vigia trades que o Gabriel abriu na mao e grita
na hora de realizar, antes do "lucro virar imagem". A decisao e SEMPRE dele.

Duas regras objetivas (por logica, nao otimizacao):
  (a) trailing  — o lucro recuou >= GIVEBACK do pico ja atingido (so vale se o pico foi
                  decente, >= min_profit_pct). "Ta virando imagem, realiza."
  (b) stop      — o preco ameacou/bateu o stop original.
A regra (b) de "forca morrendo" (RSI) e fatia seguinte.

Spec: docs/superpowers/specs/2026-06-16-copiloto-disciplina-design.md
Estado em SQLite (tabela copiloto_trades). Reusa market.get_candles p/ preco e o Telegram do bot.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

DB_DEFAULT = "/home/pi/crypto_ai_bot/runtime/baseline/bot.db"

# defaults LOGICOS (o Gabriel calibra no olho — NAO otimizar por resultado)
PARAMS = {
    "giveback": 0.30,        # recuo do pico que dispara o "realiza" (30%)
    "min_profit_pct": 1.0,   # so incomoda com trailing se o pico passou de +1% (nao chora por ruido)
    "rearm_pct": 0.5,        # re-arma o trailing se um novo pico superar o alertado por +0.5%
    "stop_near_pct": 0.3,    # avisa quando o preco chega a 0.3% do stop (ameaca), nao so no cruzamento
}


# ───────────────────────── cerebro (regra PURA, sem rede) ─────────────────────────
def avalia_saida(entry, stop, direction, price, peak_pct, params=PARAMS) -> dict:
    """Dado o estado de UM trade aberto e o preco atual, decide se alerta. Puro/deterministico.
    direction: 'compra' (long) | 'venda' (short). peak_pct: maior excursao favoravel ja vista (%).
    Retorna {pnl_pct, peak_pct (atualizado), alerta ('trailing'|'stop'|None), motivo}."""
    if direction == "compra":
        pnl = (price / entry - 1.0) * 100.0
        stop_ameacado = price <= stop * (1.0 + params["stop_near_pct"] / 100.0)
    else:  # venda (short)
        pnl = (entry / price - 1.0) * 100.0
        stop_ameacado = price >= stop * (1.0 - params["stop_near_pct"] / 100.0)

    novo_peak = max(peak_pct, pnl)
    alerta = motivo = None
    if stop_ameacado:
        alerta = "stop"
        motivo = f"stop ameacado: preco {price:g} vs stop {stop:g} (pnl {pnl:+.1f}%)."
    elif novo_peak >= params["min_profit_pct"] and pnl <= novo_peak * (1.0 - params["giveback"]):
        alerta = "trailing"
        motivo = (f"recuou {params['giveback']*100:.0f}% do pico (+{novo_peak:.1f}% -> {pnl:+.1f}%). "
                  f"Ta virando imagem — realiza.")
    return {"pnl_pct": round(pnl, 3), "peak_pct": round(novo_peak, 3),
            "alerta": alerta, "motivo": motivo}


# ───────────────────────── estado (SQLite) ─────────────────────────
def _conn(db_path=DB_DEFAULT):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c


def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS copiloto_trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol       TEXT NOT NULL,
            direction    TEXT NOT NULL,                 -- compra | venda
            entry_price  REAL NOT NULL,
            stop_price   REAL NOT NULL,
            peak_pct     REAL NOT NULL DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'aberto',-- aberto | fechado
            alert_state  TEXT NOT NULL DEFAULT '',      -- '' | trailing | stop
            alert_peak   REAL NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            closed_at    TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS copiloto_watchlist (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol       TEXT NOT NULL,
            direction    TEXT NOT NULL,                 -- compra | venda
            status       TEXT NOT NULL DEFAULT 'vigiando', -- vigiando | confirmado
            created_at   TEXT NOT NULL,
            confirmed_at TEXT
        )""")
    conn.commit()


def _direction_from_stop(entry, stop) -> str:
    """Infere compra/venda pela posicao do stop: stop abaixo do entry = long; acima = short."""
    return "venda" if stop > entry else "compra"


def abrir_trade(symbol, entry, stop, direction=None, db_path=DB_DEFAULT, agora=None):
    agora = agora or datetime.now(timezone.utc)
    direction = direction or _direction_from_stop(entry, stop)
    conn = _conn(db_path)
    try:
        ensure_schema(conn)
        cur = conn.execute(
            "INSERT INTO copiloto_trades (symbol, direction, entry_price, stop_price, created_at) "
            "VALUES (?,?,?,?,?)",
            (symbol.upper(), direction, float(entry), float(stop), agora.isoformat()))
        conn.commit()
        return {"id": cur.lastrowid, "symbol": symbol.upper(), "direction": direction,
                "entry": float(entry), "stop": float(stop)}
    finally:
        conn.close()


def listar_abertos(db_path=DB_DEFAULT):
    conn = _conn(db_path)
    try:
        ensure_schema(conn)
        return [dict(r) for r in conn.execute(
            "SELECT * FROM copiloto_trades WHERE status='aberto' ORDER BY id").fetchall()]
    finally:
        conn.close()


def fechar_trade(symbol, db_path=DB_DEFAULT, agora=None):
    """Fecha o(s) trade(s) aberto(s) do simbolo. Retorna quantos fechou."""
    agora = agora or datetime.now(timezone.utc)
    conn = _conn(db_path)
    try:
        ensure_schema(conn)
        cur = conn.execute(
            "UPDATE copiloto_trades SET status='fechado', closed_at=? "
            "WHERE status='aberto' AND symbol=?", (agora.isoformat(), symbol.upper()))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def _persist_check(conn, tid, peak_pct, alert_state, alert_peak):
    conn.execute("UPDATE copiloto_trades SET peak_pct=?, alert_state=?, alert_peak=? WHERE id=?",
                 (peak_pct, alert_state, alert_peak, tid))


# ───────────────────────── vigia (loop de checagem, com dedup) ─────────────────────────
def checar_trades(price_fn, notifier=None, db_path=DB_DEFAULT, params=PARAMS):
    """Para cada trade aberto: busca preco (price_fn(symbol)->float|None), avalia, atualiza o
    pico e dispara alerta com DEDUP. Retorna a lista de alertas disparados nesta passada.
    price_fn injetavel (rede fora dos testes); notifier(titulo, msg) opcional."""
    conn = _conn(db_path)
    disparados = []
    try:
        ensure_schema(conn)
        abertos = [dict(r) for r in conn.execute(
            "SELECT * FROM copiloto_trades WHERE status='aberto' ORDER BY id").fetchall()]
        for t in abertos:
            price = price_fn(t["symbol"])
            if price is None or price <= 0:
                continue                                   # falha de preco: pula, nao quebra
            r = avalia_saida(t["entry_price"], t["stop_price"], t["direction"],
                             float(price), t["peak_pct"], params)
            alert_state, alert_peak = t["alert_state"], t["alert_peak"]
            fire = False
            if r["alerta"] == "stop" and alert_state != "stop":
                fire, alert_state = True, "stop"
            elif r["alerta"] == "trailing" and (
                    alert_state != "trailing"
                    or r["peak_pct"] > alert_peak + params["rearm_pct"]):
                fire, alert_state, alert_peak = True, "trailing", r["peak_pct"]
            _persist_check(conn, t["id"], r["peak_pct"], alert_state, alert_peak)
            if fire:
                msg = f"{t['symbol']} ({t['direction']}) @ {price:g} — {r['motivo']}"
                disparados.append({"symbol": t["symbol"], "alerta": r["alerta"], "msg": msg})
                if notifier:
                    try:
                        notifier("Copiloto — Vigia de Saida", msg)
                    except Exception as e:
                        print(f"[copiloto] notificacao falhou: {e}")
        conn.commit()
        return disparados
    finally:
        conn.close()


# ───────────────────────── preco fresco (rede) ─────────────────────────
def preco_atual(symbol):
    """Ultimo close 1m via Binance (market.get_candles). None se falhar (nao quebra o loop)."""
    try:
        from market import get_candles
        df = get_candles(symbol.upper(), "1m", 2)
        if df is not None and len(df):
            return float(df["close"].iloc[-1])
    except Exception:
        pass
    return None


# ───────────────────────── comandos Telegram (Modulo B) ─────────────────────────
def _is_float(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def cmd_entrei(arg, _db=None):
    """/entrei SIMBOLO ENTRADA [stop] STOP — registra um trade aberto pra vigiar a saida."""
    db = _db or DB_DEFAULT
    toks = (arg or "").replace(",", ".").split()
    sym, nums = None, []
    for t in toks:
        if _is_float(t):
            nums.append(float(t))
        elif t.lower() != "stop" and sym is None:
            sym = t
    if not sym or len(nums) < 2:
        return ("Uso: <code>/entrei SIMBOLO ENTRADA stop STOP</code>\n"
                "ex: <code>/entrei LINKUSDT 7.50 stop 7.20</code>")
    entry, stop = nums[0], nums[1]
    if entry <= 0 or stop <= 0:
        return "Preços têm que ser positivos."
    tr = abrir_trade(sym, entry, stop, db_path=db)
    return (f"✅ Vigiando <b>{tr['symbol']}</b> ({tr['direction']}) @ {entry:g}, stop {stop:g}.\n"
            f"Te aviso quando o lucro começar a virar imagem ou o stop for ameaçado. "
            f"A decisão é sempre sua.")


def cmd_vigiando(arg="", _db=None):
    """/vigiando — mostra a Guarda de Entrada (watchlist) + a Vigia de Saida (trades abertos)."""
    db = _db or DB_DEFAULT
    vigias = listar_vigias(db)
    abertos = listar_abertos(db)
    if not vigias and not abertos:
        return ("Nada sendo vigiado.\n"
                "• <code>/vigiar SIMBOLO compra</code> — guarda de entrada (anti-entrar-cedo)\n"
                "• <code>/entrei SIMBOLO ENTRADA stop STOP</code> — vigia de saída (anti-sair-tarde)")
    linhas = []
    if vigias:
        linhas.append("<b>👁️ Guarda de Entrada:</b>")
        for v in vigias:
            marca = "✅ confirmou" if v["status"] == "confirmado" else "aguardando a faca parar"
            linhas.append(f"• <b>{v['symbol']}</b> ({v['direction']}) — {marca}")
    if abertos:
        linhas.append("<b>🛡️ Vigia de Saída:</b>")
        for t in abertos:
            price = preco_atual(t["symbol"])
            if price:
                r = avalia_saida(t["entry_price"], t["stop_price"], t["direction"], price, t["peak_pct"])
                pico = max(t["peak_pct"], r["pnl_pct"])
                linhas.append(f"• <b>{t['symbol']}</b> ({t['direction']}) entrada {t['entry_price']:g} | "
                              f"agora {price:g} | pnl {r['pnl_pct']:+.1f}% (pico +{pico:.1f}%)")
            else:
                linhas.append(f"• <b>{t['symbol']}</b> ({t['direction']}) entrada {t['entry_price']:g} | "
                              f"preço indisponível")
    return "\n".join(linhas)


def cmd_fechei(arg, _db=None):
    """/fechei SIMBOLO — encerra a vigia daquele símbolo."""
    db = _db or DB_DEFAULT
    toks = (arg or "").split()
    if not toks:
        return "Uso: <code>/fechei SIMBOLO</code>"
    sym = toks[0].upper()
    n = fechar_trade(sym, db_path=db)
    return f"Encerrei a vigia de <b>{sym}</b> ({n} trade(s))." if n else \
        f"Não achei vigia aberta pra {sym}."


def run_vigia_cycle():
    """Uma passada do copiloto — Modulo B (vigia de saida) + Modulo A (guarda de entrada) — com
    dado real + Telegram. Chamada pelo loop do bot. Retorna a lista de alertas disparados."""
    from telegram_notifier import send_system_alert
    notif = lambda titulo, msg: send_system_alert(titulo, msg, critical=False)  # noqa: E731
    saidas = checar_trades(preco_atual, notifier=notif)
    entradas = checar_entradas(_candles_para, notifier=notif)
    return saidas + entradas


# ═════════════════════════ MODULO A — Guarda de Entrada (anti-entrar-cedo) ═════════════════════════
# Espelho do B: em vez de vigiar a saida de um trade aberto, vigia a ENTRADA de uma moeda na
# watchlist e so da o "verde" quando a faca para de cair (recuperou X% do fundo) E o momentum vira.
# Nao preve direcao — so segura a mao pra nao comprar a faca no meio da queda. Decisao e do Gabriel.

PARAMS_A = {
    "lookback": 20,       # candles p/ o fundo/topo local (a "faca")
    "bounce_min": 2.0,    # recuperou pelo menos 2% do fundo (a faca parou de cair)
    "bounce_max": 6.0,    # mas nao mais que 6% (senao a entrada ja passou)
    "timeframe": "15m",   # granularidade da vigia de entrada
    "candle_limit": 120,
    "rsi_window": 14,
}


def avalia_entrada(highs, lows, closes, rsis, direction, params=PARAMS_A) -> dict:
    """Cerebro PURO do Modulo A. Recebe janelas de high/low/close + RSI ja computado. Decide se a
    entrada CONFIRMOU (a faca parou E o momentum virou) — nao preve, so espera a confirmacao.
    Retorna {confirmado, price, stop, alvo, rr, contexto}."""
    lb = params["lookback"]
    price = float(closes[-1])
    if direction == "compra":
        ref = min(lows[-lb:])                                  # fundo recente (a faca)
        subiu = (price / ref - 1.0) * 100.0 if ref > 0 else 0.0
        faca_parou = params["bounce_min"] <= subiu <= params["bounce_max"]
        momentum = rsis[-1] > rsis[-2]                         # RSI virando pra CIMA
        stop, alvo = ref, max(highs[-lb:])                     # stop = fundo; alvo = resistencia
        rr = (alvo - price) / (price - stop) if price > stop else 0.0
        contexto = f"subiu {subiu:.1f}% do fundo {ref:g}, RSI {'subindo' if momentum else 'caindo'} ({rsis[-1]:.0f})"
    else:  # venda
        ref = max(highs[-lb:])                                 # topo recente
        caiu = (1.0 - price / ref) * 100.0 if ref > 0 else 0.0
        topo_parou = params["bounce_min"] <= caiu <= params["bounce_max"]
        momentum = rsis[-1] < rsis[-2]                         # RSI virando pra BAIXO
        stop, alvo = ref, min(lows[-lb:])
        rr = (price - alvo) / (stop - price) if stop > price else 0.0
        contexto = f"caiu {caiu:.1f}% do topo {ref:g}, RSI {'caindo' if momentum else 'subindo'} ({rsis[-1]:.0f})"
    return {"confirmado": bool(faca_parou and momentum) if direction == "compra"
            else bool(topo_parou and momentum),
            "price": round(price, 6), "stop": round(stop, 6), "alvo": round(alvo, 6),
            "rr": round(rr, 2), "contexto": contexto}


# ── watchlist (estado) ──
def adicionar_vigia(symbol, direction="compra", db_path=DB_DEFAULT, agora=None):
    agora = agora or datetime.now(timezone.utc)
    conn = _conn(db_path)
    try:
        ensure_schema(conn)
        # nao duplica: se ja vigia o mesmo symbol+direction, no-op
        ja = conn.execute("SELECT id FROM copiloto_watchlist WHERE symbol=? AND direction=? "
                          "AND status='vigiando'", (symbol.upper(), direction)).fetchone()
        if ja:
            return {"id": ja["id"], "symbol": symbol.upper(), "direction": direction, "novo": False}
        cur = conn.execute("INSERT INTO copiloto_watchlist (symbol, direction, created_at) "
                           "VALUES (?,?,?)", (symbol.upper(), direction, agora.isoformat()))
        conn.commit()
        return {"id": cur.lastrowid, "symbol": symbol.upper(), "direction": direction, "novo": True}
    finally:
        conn.close()


def listar_vigias(db_path=DB_DEFAULT):
    conn = _conn(db_path)
    try:
        ensure_schema(conn)
        return [dict(r) for r in conn.execute(
            "SELECT * FROM copiloto_watchlist WHERE status IN ('vigiando','confirmado') "
            "ORDER BY id").fetchall()]
    finally:
        conn.close()


def remover_vigia(symbol, db_path=DB_DEFAULT):
    conn = _conn(db_path)
    try:
        ensure_schema(conn)
        cur = conn.execute("DELETE FROM copiloto_watchlist WHERE symbol=? AND "
                           "status IN ('vigiando','confirmado')", (symbol.upper(),))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ── indicadores + candles ──
def _rsi(closes, window=14):
    import pandas as pd
    from ta.momentum import RSIIndicator
    s = pd.Series(closes, dtype=float)
    return RSIIndicator(close=s, window=window).rsi().fillna(50.0).tolist()


def _candles_para(symbol, params=PARAMS_A):
    """DataFrame de candles do timeframe da vigia (rede). None se falhar."""
    try:
        from market import get_candles
        return get_candles(symbol.upper(), params["timeframe"], params["candle_limit"])
    except Exception:
        return None


# ── loop de checagem (Modulo A), com dedup via status ──
def checar_entradas(candles_fn, notifier=None, db_path=DB_DEFAULT, params=PARAMS_A):
    """Para cada moeda na watchlist: busca candles, computa RSI, avalia. Ao confirmar, alerta UMA
    vez (status -> confirmado). candles_fn(symbol)->DataFrame|None. Retorna alertas disparados."""
    conn = _conn(db_path)
    disparados = []
    try:
        ensure_schema(conn)
        vigias = [dict(r) for r in conn.execute(
            "SELECT * FROM copiloto_watchlist WHERE status='vigiando' ORDER BY id").fetchall()]
        minimo = params["lookback"] + params["rsi_window"] + 2
        for v in vigias:
            df = candles_fn(v["symbol"])
            if df is None or len(df) < minimo:
                continue                                        # dado insuficiente: pula
            highs = [float(x) for x in df["high"]]
            lows = [float(x) for x in df["low"]]
            closes = [float(x) for x in df["close"]]
            rsis = _rsi(closes, params["rsi_window"])
            r = avalia_entrada(highs, lows, closes, rsis, v["direction"], params)
            if r["confirmado"]:
                conn.execute("UPDATE copiloto_watchlist SET status='confirmado', confirmed_at=? "
                             "WHERE id=?", (datetime.now(timezone.utc).isoformat(), v["id"]))
                msg = (f"{v['symbol']} ({v['direction']}) CONFIRMOU @ {r['price']:g}. "
                       f"A faca parou — {r['contexto']}. Se for entrar, stop sugerido {r['stop']:g}, "
                       f"alvo {r['alvo']:g}, R/R {r['rr']:.1f}. A decisao e sua.")
                disparados.append({"symbol": v["symbol"], "alerta": "entrada", "msg": msg})
                if notifier:
                    try:
                        notifier("Copiloto — Guarda de Entrada", msg)
                    except Exception as e:
                        print(f"[copiloto] notificacao A falhou: {e}")
        conn.commit()
        return disparados
    finally:
        conn.close()


# ── comandos Telegram (Modulo A) ──
def cmd_vigiar(arg, _db=None):
    """/vigiar SIMBOLO [compra|venda] — poe uma moeda na watchlist ate a entrada confirmar."""
    db = _db or DB_DEFAULT
    toks = (arg or "").split()
    if not toks:
        return ("Uso: <code>/vigiar SIMBOLO [compra|venda]</code>\n"
                "ex: <code>/vigiar LINKUSDT compra</code> — te aviso quando a faca parar de cair.")
    sym = toks[0].upper()
    direction = "compra"
    for t in toks[1:]:
        if t.lower() in ("compra", "venda"):
            direction = t.lower()
    v = adicionar_vigia(sym, direction, db_path=db)
    if not v["novo"]:
        return f"Já tô vigiando <b>{sym}</b> ({direction})."
    return (f"👁️ Vigiando a entrada de <b>{sym}</b> ({direction}). "
            f"Fico calado até a faca parar de cair e o momentum virar — aí te dou o verde. "
            f"<i>Não é sinal de compra, é permissão pra você não entrar cedo demais.</i>")


def cmd_cancelar(arg, _db=None):
    """/cancelar SIMBOLO — tira a moeda da watchlist de entrada."""
    db = _db or DB_DEFAULT
    toks = (arg or "").split()
    if not toks:
        return "Uso: <code>/cancelar SIMBOLO</code>"
    sym = toks[0].upper()
    n = remover_vigia(sym, db_path=db)
    return f"Parei de vigiar a entrada de <b>{sym}</b>." if n else f"Não tava vigiando {sym}."
