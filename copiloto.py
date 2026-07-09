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
    """/vigiando — lista os trades vigiados com o pnl e o pico atuais."""
    db = _db or DB_DEFAULT
    abertos = listar_abertos(db)
    if not abertos:
        return "Nada sendo vigiado. Use <code>/entrei SIMBOLO ENTRADA stop STOP</code>."
    linhas = ["<b>🛡️ Vigia de Saída:</b>"]
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
    """Uma passada da vigia com preco real + Telegram. Chamada pelo loop do bot."""
    from telegram_notifier import send_system_alert
    return checar_trades(preco_atual,
                         notifier=lambda titulo, msg: send_system_alert(titulo, msg, critical=False))
