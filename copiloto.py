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

import math
import os
import sqlite3
from datetime import datetime, timezone

DB_DEFAULT = "/home/pi/crypto_ai_bot/runtime/baseline/bot.db"

# Fee round-trip como FONTE UNICA do config (0.05%/leg taker = 0.10% ida-e-volta). NUNCA o
# SINGLE_SIDE_FEE_PCT antigo (0.04) — o proprio config manda nao usar. try/except mantem o
# copiloto importavel se o config mudar. A saga do Momentum provou: fee = 2x o edge, ignorar mata.
try:
    from config import MOMENTUM_PAPER_ENTRY_FEE_RATE as _EF, MOMENTUM_PAPER_EXIT_FEE_RATE as _XF
    _FEE_RT_PCT = float(_EF) + float(_XF)
except Exception:
    _FEE_RT_PCT = 0.10

# defaults LOGICOS (o Gabriel calibra no olho — NAO otimizar por resultado)
PARAMS = {
    "giveback": 0.30,        # recuo do pico que dispara o "realiza" (30%)
    "min_profit_pct": 1.0,   # so incomoda se o pico passou de +1% (nao chora por ruido)
    "rearm_pct": 0.5,        # re-arma o "realiza" se um novo pico superar o alertado por +0.5%
    "stop_near_pct": 0.3,    # avisa quando o preco chega a 0.3% do stop (ameaca), nao so no cruzamento
    # forca-morrendo por RSI (aviso ANTECIPADO ao trailing)
    "rsi_window": 14,
    "rsi_alto": 60.0,        # RSI que conta como "esticado" p/ cima (compra sobrecomprada)
    "rsi_baixo": 40.0,       # esticado p/ baixo (venda sobrevendida)
    "forca_lookback": 6,     # janela p/ ver se o RSI esticou recentemente
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


def avalia_forca(rsis, pnl_pct, peak_pct, direction, params=PARAMS) -> dict:
    """Forca morrendo (aviso ANTECIPADO ao trailing): estando em lucro, o RSI ESTICOU (chegou a
    sobrecomprado/sobrevendido) e agora VIROU contra o trade — o momentum morreu antes do recuo de
    30%. Puro. rsis: janela de RSI. Retorna {forca: bool, motivo}. So vale se em lucro decente."""
    if peak_pct < params["min_profit_pct"] or pnl_pct <= 0 or len(rsis) < 3:
        return {"forca": False, "motivo": None}
    lb = params["forca_lookback"]
    recent = rsis[-lb:] if len(rsis) >= lb else rsis
    r_now, r_prev = rsis[-1], rsis[-2]
    if direction == "compra":
        esticou = max(recent) >= params["rsi_alto"]       # chegou a sobrecomprado
        virou = r_now < r_prev                             # e o RSI agora cai
    else:  # venda
        esticou = min(recent) <= params["rsi_baixo"]       # chegou a sobrevendido
        virou = r_now > r_prev                             # e o RSI agora sobe
    forca = bool(esticou and virou)
    motivo = (f"a força tá morrendo (RSI {r_now:.0f} virou após esticar), lucro em {pnl_pct:+.1f}%. "
              f"Tá começando a virar imagem — realiza.") if forca else None
    return {"forca": forca, "motivo": motivo}


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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS copiloto_settings (
            key          TEXT PRIMARY KEY,              -- banca | risco_pct
            value        TEXT NOT NULL,
            updated_at   TEXT NOT NULL
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
def checar_trades(price_fn, notifier=None, db_path=DB_DEFAULT, params=PARAMS, candles_fn=None):
    """Para cada trade aberto: busca preco (price_fn(symbol)->float|None), avalia trailing/stop e —
    se candles_fn fornecido — tambem a FORCA (RSI morrendo, aviso antecipado). Atualiza o pico e
    dispara com DEDUP: trailing e forca compartilham o slot 'realiza' (nao duplica); stop e separado.
    Retorna a lista de alertas disparados. price_fn/candles_fn injetaveis (rede fora dos testes)."""
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
            forca = {"forca": False, "motivo": None}
            if candles_fn is not None:
                df = candles_fn(t["symbol"])
                if df is not None and len(df) >= params["rsi_window"] + 3:
                    rsis = _rsi([float(x) for x in df["close"]], params["rsi_window"])
                    forca = avalia_forca(rsis, r["pnl_pct"], r["peak_pct"], t["direction"], params)
            alert_state, alert_peak = t["alert_state"], t["alert_peak"]
            fire, motivo = False, None
            if r["alerta"] == "stop" and alert_state != "stop":
                fire, alert_state, motivo = True, "stop", r["motivo"]
            else:
                realiza = (r["alerta"] == "trailing") or forca["forca"]
                if realiza and (alert_state != "realiza"
                                or r["peak_pct"] > alert_peak + params["rearm_pct"]):
                    fire, alert_state, alert_peak = True, "realiza", r["peak_pct"]
                    motivo = forca["motivo"] if forca["forca"] else r["motivo"]
            _persist_check(conn, t["id"], r["peak_pct"], alert_state, alert_peak)
            if fire:
                msg = f"{t['symbol']} ({t['direction']}) @ {price:g} — {motivo}"
                disparados.append({"symbol": t["symbol"], "alerta": alert_state, "msg": msg})
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
        return math.isfinite(float(s))   # rejeita nan/inf: nao podem entrar como preco/banca
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
    msg = (f"✅ Vigiando <b>{tr['symbol']}</b> ({tr['direction']}) @ {entry:g}, stop {stop:g}.\n"
           f"Te aviso quando o lucro começar a virar imagem ou o stop for ameaçado. "
           f"A decisão é sempre sua.")
    # rede de seguranca: se a banca ja esta setada, lembra o tamanho pro perfil (reusa avalia_risco).
    # Sem banca setada, a mensagem fica IDENTICA a de antes (backward-compatible).
    banca, risk_pct = _resolve_banca_risco(None, db)
    if banca:
        r = avalia_risco(entry, stop, banca=banca, risk_pct=risk_pct)
        if not r.get("erro") and r.get("notional"):
            base = tr["symbol"].replace("USDT", "") or tr["symbol"]
            if r.get("notional_capped"):     # honra o veto de alavancagem: admite o risco real menor
                msg += (f"\n<i>stop curto: sem alavancagem, ~{r['notional']:g} USDT (banca inteira) = "
                        f"risco real ~{r['risk_real_pct']:g}% (menor que {risk_pct:g}%).</i>")
            else:
                msg += (f"\n<i>Tamanho p/ {risk_pct:g}% da banca: ~{r['notional']:g} USDT "
                        f"({r['qty']:g} {base}).</i>")
    return msg


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
    saidas = checar_trades(preco_atual, notifier=notif, candles_fn=_candles_para)
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


# ═════════════════════════ FATIA RISCO — Quanto arriscar (fee-aware) ═════════════════════════
# A 4a fatia do painel pre-trade. Dado onde o Gabriel quer entrar e onde poe o stop, diz QUANTO
# arriscar (tamanho da posicao) e se o trade VALE A PENA (R:R LIQUIDO de fee). NAO preve direcao —
# entrega a barra (o trade paga o pedagio?), a leitura e dele. Cerebro 100% PURO (sem rede/DB).
# A licao do Momentum embutida na conta: o fee morde os DOIS lados, o R:R bruto mente, o liquido nao.

PARAMS_RISCO = {
    "risk_pct": 0.5,             # piso do perfil congelado (0.5-0.75, NUNCA 1%)
    "fee_rt_pct": _FEE_RT_PCT,   # round-trip do config (0.10), fallback 0.10
    "rr_bom": 2.0,               # R:R liquido >= 2 => vale (breakeven-WR so 33%)
    "rr_min": 1.0,               # < 1 => reprova (exigiria acertar > 50%; sem edge direcional, desonesto)
    "fee_bite_max": 0.25,        # aviso "stop curto" se o fee for >= 25% do risco
    "risk_pct_perfil": 0.75,     # TETO do perfil conservador: acima disso, AVISA (nao e clamp)
    "risk_pct_min": 0.1, "risk_pct_max": 2.0,  # clamp DURO (sanidade), separado do teto do perfil
}


def avalia_risco(entry, stop, alvo=None, banca=None, risk_pct=None, fee_rt_pct=None,
                 direction=None, params=PARAMS_RISCO) -> dict:
    """Cerebro PURO da fatia Risco. ZERO rede/DB, deterministico (espelha avalia_saida/avalia_entrada).
    Dois blocos independentes: VEREDITO (R:R liquido — nao precisa de banca) e TAMANHO (sizing — nao
    precisa de alvo). O fee entra em 3 lugares: encolhe o premio, engorda o risco, e define o breakeven.
    direction inferido do stop (stop>entry=venda). Retorna dict com 'erro' setado quando invalido."""
    if (entry is None or stop is None or not math.isfinite(entry) or not math.isfinite(stop)
            or entry <= 0 or stop <= 0):
        return {"erro": "preços têm que ser positivos"}
    if entry == stop:
        return {"erro": "stop igual à entrada — sem risco definido, não dá pra dimensionar"}
    risk_pct = params["risk_pct"] if risk_pct is None else risk_pct
    fee_rt_pct = params["fee_rt_pct"] if fee_rt_pct is None else fee_rt_pct
    avisos = []
    lo, hi = params["risk_pct_min"], params["risk_pct_max"]
    if risk_pct < lo or risk_pct > hi:
        risk_pct = min(max(risk_pct, lo), hi)
        avisos.append(f"risco/trade fora de {lo}-{hi}%, ajustei pra {risk_pct:g}%")
    if risk_pct > params["risk_pct_perfil"]:   # dentro do clamp duro, mas acima do perfil: AVISA
        avisos.append(f"risco {risk_pct:g}%/trade está acima do teu perfil conservador "
                      f"(0.5-0.75%) — só se os dados justificarem")
    direction = direction or _direction_from_stop(entry, stop)
    fee_rt = fee_rt_pct / 100.0

    # --- risco (sempre) ---
    risk_frac = (entry - stop) / entry if direction == "compra" else (stop - entry) / entry
    if risk_frac <= 0:
        return {"erro": "stop do lado errado pra essa direção"}
    net_risk = risk_frac + fee_rt                         # perda real ao stopar JA paga os 2 legs
    fee_bite = fee_rt / risk_frac
    if fee_bite >= params["fee_bite_max"]:
        avisos.append(f"stop curto: o fee {fee_rt_pct:g}% é {fee_bite*100:.0f}% do teu risco — "
                      f"pedágio pesado (foi assim que o Momentum sangrou)")
    breakeven_price = entry * (1 + fee_rt) if direction == "compra" else entry * (1 - fee_rt)

    def _alvo_para(k):                                    # preco-alvo p/ R:R LIQUIDO k
        g = k * net_risk + fee_rt                         # ganho bruto que, menos o fee, da k*net_risk
        return entry * (1 + g) if direction == "compra" else entry * (1 - g)

    out = {"erro": None, "direction": direction, "risk_frac_pct": round(risk_frac * 100, 3),
           "fee_rt_pct": fee_rt_pct, "net_risk_pct": round(net_risk * 100, 3),
           "breakeven_price": round(breakeven_price, 6),
           "alvo_1a1": round(_alvo_para(1.0), 6), "alvo_2a1": round(_alvo_para(2.0), 6),
           "gross_reward_pct": None, "net_reward_pct": None, "rr_gross": None, "rr_net": None,
           "breakeven_wr": None, "veredito": None, "risk_amount": None, "notional": None,
           "qty": None, "notional_capped": False, "risk_real_pct": None, "avisos": avisos}

    # --- veredito (se tem alvo; NAO precisa de banca) ---
    if alvo is not None and alvo > 0:
        gross_reward = (alvo - entry) / entry if direction == "compra" else (entry - alvo) / entry
        out["gross_reward_pct"] = round(gross_reward * 100, 3)
        if gross_reward <= 0:
            out["veredito"] = "reprova"
            avisos.append("alvo do lado errado (contrário ao trade) — R:R negativo")
        else:
            net_reward = gross_reward - fee_rt            # o alvo tem que pagar o pedagio ANTES de lucrar
            rr_gross = gross_reward / risk_frac
            rr_net = round(net_reward / net_risk, 2)      # arredonda ANTES de classificar: o veredito bate
            out["net_reward_pct"] = round(net_reward * 100, 3)  # com o numero que o Gabriel ve (sem epsilon)
            out["rr_gross"] = round(rr_gross, 2)
            out["rr_net"] = rr_net
            out["breakeven_wr"] = round(1.0 / (1.0 + rr_net), 3) if rr_net > -1 else None
            out["veredito"] = ("reprova" if (net_reward <= 0 or rr_net < params["rr_min"])
                               else "magro" if rr_net < params["rr_bom"] else "bom")

    # --- tamanho (se tem banca; NAO precisa de alvo) ---
    if banca is not None and banca > 0:
        risk_amount = banca * risk_pct / 100.0
        notional = risk_amount / net_risk                 # divide pelo risco LIQUIDO: worst-case == risk_amount
        if notional > banca:                              # passaria da banca => precisaria alavancar (VETADO)
            notional = banca
            out["notional_capped"] = True
            out["risk_real_pct"] = round(net_risk * 100, 3)
            avisos.append(f"sem alavancagem (vetada): nem a banca inteira arrisca {risk_pct:g}% com esse "
                          f"stop; risco real {net_risk*100:.2f}%. Afasta o stop ou aceita posição menor")
        out["risk_amount"] = round(risk_amount, 2)
        out["notional"] = round(notional, 2)
        out["qty"] = round(notional / entry, 6)
    return out


# ── settings (I/O fino; banca real + risco/trade persistidos) ──
def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM copiloto_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value, agora=None):
    ts = agora or datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO copiloto_settings (key, value, updated_at) VALUES (?,?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                 (key, str(value), ts))
    conn.commit()


def _resolve_banca_risco(inline_banca=None, db_path=DB_DEFAULT):
    """Resolve (banca, risco_pct) numa unica conexao. Cascata da banca: inline > setting > env > None.
    risco_pct vem do setting (default 0.5, o piso conservador do perfil)."""
    conn = _conn(db_path)
    try:
        ensure_schema(conn)
        risk_pct = float(get_setting(conn, "risco_pct", str(PARAMS_RISCO["risk_pct"])))
        setting_banca = get_setting(conn, "banca")
    finally:
        conn.close()
    if inline_banca is not None:
        return inline_banca, risk_pct
    if setting_banca is not None:
        return float(setting_banca), risk_pct
    env = os.environ.get("COPILOTO_BANCA")
    try:                                     # env malformado nao pode quebrar /risco nem /entrei
        return (float(env) if env else None), risk_pct
    except (TypeError, ValueError):
        return None, risk_pct


# ── formatador (HTML Telegram fino; mantem cmd_risco enxuto) ──
def _fmt_risco(sym, entry, stop, alvo, banca, res) -> str:
    base = sym.replace("USDT", "") or sym
    d = res["direction"]
    ver = res.get("veredito")
    emoji = {"bom": "✅", "magro": "⚠️", "reprova": "❌"}.get(ver, "")
    ge = "≥" if d == "compra" else "≤"

    if ver == "reprova":
        head = f"📐 <b>{sym}</b> ({d}) @ {entry:g} — assim NÃO vale {emoji}"
    elif ver in ("bom", "magro"):
        head = f"📐 <b>{sym}</b> ({d}) @ {entry:g} — quanto arriscar {emoji}"
    else:
        head = f"📐 <b>{sym}</b> ({d}) @ {entry:g} — risco &amp; tamanho"
    linhas = [head, ""]

    # bloco TAMANHO
    if res.get("notional") is not None:
        linhas.append(f"<b>Tamanho:</b> arrisca <b>{res['risk_amount']:g}</b> USDT → "
                      f"posição ~<b>{res['notional']:g}</b> ({res['qty']:g} {base})")
        if not res.get("notional_capped"):
            linhas.append(f"Se o stop bater, perde ~{res['risk_amount']:g} — já com o pedágio do fee.")
        linhas.append("")

    # bloco VEREDITO
    if ver in ("bom", "magro"):
        linhas.append(f"<b>Vale a pena?</b> R/R líquido <b>{res['rr_net']:g}</b> {emoji} "
                      f"(bruto {res['rr_gross']:g})")
        linhas.append(f"Risco {res['net_risk_pct']:g}% · prêmio {res['net_reward_pct']:g}% "
                      f"(descontei o fee {res['fee_rt_pct']:g}% dos dois lados)")
        if res.get("breakeven_wr") is not None:
            linhas.append(f"Basta acertar <b>{round(res['breakeven_wr']*100)}%</b> das vezes pra empatar.")
    elif ver == "reprova":
        if res.get("rr_net") is not None:
            linhas.append(f"R/R líquido <b>{res['rr_net']:g}</b> — o fee derrubou do bruto "
                          f"{res['rr_gross']:g}.")
            linhas.append(f"Risco real {res['net_risk_pct']:g}% · prêmio real {res['net_reward_pct']:g}%")
        linhas.append(f"Pra virar 2:1 líquido, teu alvo tinha que estar {ge} <b>{res['alvo_2a1']:g}</b>.")

    # avisos do cerebro (stop curto, alavancagem, clamp, alvo lado errado)
    for a in res.get("avisos", []):
        linhas.append(f"⚠️ {a}.")

    # sem alvo: sugere os alvos-alvo
    if ver is None:
        linhas.append("Pra valer a pena, mira em pelo menos:")
        linhas.append(f"• 1:1 líquido → {res['alvo_1a1']:g}")
        linhas.append(f"• 2:1 líquido → {res['alvo_2a1']:g} (o que eu buscaria)")
        linhas.append(f"Manda o alvo: <code>/risco {sym} {entry:g} stop {stop:g} alvo {res['alvo_2a1']:g}</code>")

    # sem banca: dica pra setar
    if res.get("notional") is None:
        linhas.append("<i>Seta a banca pra eu dizer o tamanho: <code>/banca 2000</code>.</i>")

    # proximo passo (so quando o trade tem alvo aprovavel) + a decisao e dele
    if ver in ("bom", "magro"):
        linhas.append("")
        linhas.append(f"Se entrar: <code>/entrei {sym} {entry:g} stop {stop:g}</code>")
    linhas.append("<i>A decisão é sua.</i>")
    return "\n".join(linhas)


# ── comandos Telegram (Fatia Risco) ──
def cmd_banca(arg, _db=None):
    """/banca [VALOR] [risco_pct] — grava/mostra a banca REAL e o risco/trade pro sizing."""
    db = _db or DB_DEFAULT
    toks = (arg or "").replace(",", ".").split()
    nums = [float(t) for t in toks if _is_float(t)]
    conn = _conn(db)
    try:
        ensure_schema(conn)
        if not nums:
            b = get_setting(conn, "banca")
            r = float(get_setting(conn, "risco_pct", str(PARAMS_RISCO["risk_pct"])))
            if not b:
                return ("Banca não setada. Manda <code>/banca 2000</code> (teu capital REAL pro sizing, "
                        "não o paper). Opcional: <code>/banca 2000 0.75</code> pra ajustar o risco/trade.")
            flag = "" if r <= PARAMS_RISCO["risk_pct_perfil"] else " ⚠️ (acima do perfil 0.5-0.75%)"
            return (f"Banca: <b>{float(b):g}</b> USDT · risco/trade <b>{r:g}%</b>{flag} = "
                    f"{float(b)*r/100:g} USDT por trade.\n"
                    f"Muda com <code>/banca 3000</code> ou <code>/banca 3000 0.75</code>.")
        if nums[0] <= 0:
            return "Banca tem que ser positiva."
        set_setting(conn, "banca", nums[0])
        if len(nums) > 1:
            set_setting(conn, "risco_pct", min(max(nums[1], PARAMS_RISCO["risk_pct_min"]),
                                                PARAMS_RISCO["risk_pct_max"]))
        r = float(get_setting(conn, "risco_pct", str(PARAMS_RISCO["risk_pct"])))
        # a frase de "conservador" e CONDICIONAL: acima do teto do perfil (0.75), avisa em vez de endossar
        nota = ("<i>Conservador de propósito — teu perfil.</i>"
                if r <= PARAMS_RISCO["risk_pct_perfil"]
                else f"⚠️ <i>{r:g}% está acima do teu perfil conservador (0.5-0.75%) — "
                     f"só se os dados justificarem.</i>")
        return (f"Banca setada: <b>{nums[0]:g}</b> USDT. Vou dimensionar arriscando <b>{r:g}%</b> "
                f"({nums[0]*r/100:g} USDT) por trade. {nota}")
    finally:
        conn.close()


def cmd_risco(arg, _db=None):
    """/risco SIMBOLO ENTRADA STOP [ALVO] [banca CAP] — quanto arriscar + se vale a pena (R:R
    liquido de fee). Advisory puro: NAO registra nada, NAO usa rede. A decisao e sempre do Gabriel."""
    db = _db or DB_DEFAULT
    toks = (arg or "").replace(",", ".").split()
    sym, nums, banca_inline = None, [], None
    i = 0
    while i < len(toks):
        t = toks[i]
        tl = t.lower()
        if tl in ("banca", "cap", "capital") and i + 1 < len(toks) and _is_float(toks[i + 1]):
            banca_inline = float(toks[i + 1])
            i += 2
            continue
        if _is_float(t):
            nums.append(float(t))
        elif tl not in ("stop", "alvo") and sym is None:
            sym = t.upper()
        i += 1
    if not sym or len(nums) < 2:
        return ("Uso: <code>/risco SIMBOLO ENTRADA STOP [ALVO]</code>\n"
                "ex: <code>/risco LINKUSDT 7.50 stop 7.20 alvo 8.40</code>")
    entry, stop = nums[0], nums[1]
    alvo = nums[2] if len(nums) >= 3 else None
    banca, risk_pct = _resolve_banca_risco(banca_inline, db)
    res = avalia_risco(entry, stop, alvo=alvo, banca=banca, risk_pct=risk_pct)
    if res.get("erro"):
        return f"⚠️ {res['erro']}."
    # guarda de 1-POSICAO (AVISO, nunca bloqueia — a decisao e dele). Reusa estado que ja existe.
    prefixo = ""
    abertos = listar_abertos(db)
    if abertos:
        outros = ", ".join(a["symbol"] for a in abertos)
        prefixo = (f"⚠️ Você já tem posição aberta ({outros}). Teu perfil é 1 por vez — "
                   f"considere fechar antes.\n\n")
    return prefixo + _fmt_risco(sym, entry, stop, alvo, banca, res)
