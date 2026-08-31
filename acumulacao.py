"""Acumulacao — comprar ativo de qualidade com regra congelada, horizonte longo.

NAO preve, NAO opera, NAO recomenda ativo. Faz tres coisas:
  1. descreve o contexto de preco de um ativo (retrato, nunca palpite)
  2. avalia uma regra de compra que o Gabriel congelou ANTES
  3. compara essa regra contra o DCA simples no historico real

O item 3 e o que importa. Herda a licao mais cara do post-mortem: uma carteira que
qualquer pessoa monta em 5 minutos dominou 4,5 meses de engenharia. Regra nova que nao
bate o benchmark simples nao vira dinheiro real. Ponto.

Por que aqui o fee nao mata (e no momentum matava): frequencia domina taxa. O momentum
queimava 4,28 bps por hora exposta em 299 trades. Comprar 4x/ano paga fee 4x/ano.

Dado: klines diarios do endpoint publico da Binance (data-api.binance.vision, sem API
key, sem geo-bloqueio), persistidos em precos_diarios. Idempotente via INSERT OR IGNORE.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.request
from datetime import datetime, timezone

DB_DEFAULT = "/home/pi/crypto_ai_bot/runtime/baseline/bot.db"

# Endpoint publico de dado historico da Binance. Nao aceita ordem, nao pede chave.
KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
HTTP_TIMEOUT = 20.0

# Fee de compra a vista, um lado so (aqui so se compra). Fonte unica: se o config mudar,
# o modulo continua importavel.
try:
    from config import MOMENTUM_PAPER_ENTRY_FEE_RATE as _EF
    FEE_PCT = float(_EF)
except Exception:
    FEE_PCT = 0.05

# O que o Gabriel citou explicitamente. Adicionar ativo e decisao DELE — este modulo
# oferece fatos objetivos (fatos_do_ativo), nunca opiniao sobre fundamento.
UNIVERSO_DEFAULT = ["BTCUSDT", "ETHUSDT"]

JANELA_PADRAO = 365   # 1 ano de referencia p/ topo e percentil


# ───────────────────────── dados (I/O) ─────────────────────────
def _conn(db_path=DB_DEFAULT):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def ensure_schema(conn):
    """Tabela de preco diario. PK composta = idempotencia (re-rodar nao duplica)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS precos_diarios (
            symbol      TEXT NOT NULL,
            data        TEXT NOT NULL,          -- YYYY-MM-DD (UTC)
            close       REAL NOT NULL,
            high        REAL NOT NULL,
            low         REAL NOT NULL,
            volume_usd  REAL,
            PRIMARY KEY (symbol, data)
        )
    """)
    conn.commit()


def baixar_diarios(symbol, limit=1000, _fetch=None) -> list[dict]:
    """Baixa ate `limit` candles diarios (max 1000 = ~2,7 anos). _fetch injetavel p/ teste."""
    if _fetch is not None:
        raw = _fetch()
    else:
        url = f"{KLINES_URL}?symbol={symbol}&interval=1d&limit={int(limit)}"
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as r:
            raw = json.loads(r.read())
    out = []
    for k in raw:
        data = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append({
            "symbol": symbol, "data": data,
            "high": float(k[2]), "low": float(k[3]), "close": float(k[4]),
            "volume_usd": float(k[7]),
        })
    return out


def salvar_diarios(rows, db_path=DB_DEFAULT, conn=None) -> int:
    """Grava (idempotente). Retorna quantas linhas NOVAS entraram."""
    fechar = conn is None
    conn = conn or _conn(db_path)
    try:
        ensure_schema(conn)
        antes = conn.execute("SELECT COUNT(*) FROM precos_diarios").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO precos_diarios (symbol,data,close,high,low,volume_usd) "
            "VALUES (:symbol,:data,:close,:high,:low,:volume_usd)", rows)
        conn.commit()
        return conn.execute("SELECT COUNT(*) FROM precos_diarios").fetchone()[0] - antes
    finally:
        if fechar:
            conn.close()


def ler_serie(symbol, db_path=DB_DEFAULT, conn=None, com_volume=False):
    """Serie diaria ordenada do banco. (datas, closes) — ou (datas, closes, volumes)."""
    fechar = conn is None
    conn = conn or _conn(db_path)
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT data, close, volume_usd FROM precos_diarios WHERE symbol=? ORDER BY data",
            (symbol,)).fetchall()
        datas = [r["data"] for r in rows]
        closes = [r["close"] for r in rows]
        if com_volume:
            return datas, closes, [r["volume_usd"] for r in rows]
        return datas, closes
    finally:
        if fechar:
            conn.close()


# ───────────────────────── contexto (PURAS, descritivas) ─────────────────────────
def drawdown_do_topo(closes, janela=JANELA_PADRAO) -> float | None:
    """% abaixo do maior close da janela. 0 = no topo; 30 = 30% abaixo do topo."""
    if not closes:
        return None
    j = closes[-janela:] if janela else closes
    topo = max(j)
    if topo <= 0:
        return None
    return (topo - j[-1]) / topo * 100.0


def percentil_preco(closes, janela=JANELA_PADRAO) -> float | None:
    """0-100: quantos % dos closes da janela ficaram ABAIXO do preco atual.
    90 = mais caro que 90% da propria historia recente. Descritivo, nao preditivo."""
    if not closes:
        return None
    j = closes[-janela:] if janela else closes
    atual = j[-1]
    return sum(1 for c in j if c < atual) / len(j) * 100.0


def distancia_media(closes, n=200) -> float | None:
    """% de distancia do close atual pra media simples de n dias. None se falta dado."""
    if len(closes) < n or n <= 0:
        return None
    media = sum(closes[-n:]) / n
    if media <= 0:
        return None
    return (closes[-1] - media) / media * 100.0


def percentil_volume(volumes, janela=JANELA_PADRAO) -> float | None:
    """0-100: quantos % dos volumes da janela ficaram ABAIXO do atual.
    Volume e a medida mais direta de liquidez com historico longo (OI e LSR so guardam
    30 dias na API; liquidacao nao tem historico nenhum)."""
    if not volumes:
        return None
    j = [v for v in (volumes[-janela:] if janela else volumes) if v is not None]
    if not j:
        return None
    atual = j[-1]
    return sum(1 for v in j if v < atual) / len(j) * 100.0


def retorno_periodo(closes, dias=7) -> float | None:
    """% de variacao do close nos ultimos `dias`. Negativo = caiu."""
    if len(closes) <= dias or dias <= 0:
        return None
    antes = closes[-dias - 1]
    if antes <= 0:
        return None
    return (closes[-1] - antes) / antes * 100.0


def contexto_ativo(closes, janela=JANELA_PADRAO, volumes=None) -> dict:
    """Retrato do ativo em relacao a propria historia. NAO opina, NAO preve."""
    return {
        "preco": closes[-1] if closes else None,
        "dias": len(closes),
        "drawdown_topo_pct": drawdown_do_topo(closes, janela),
        "percentil": percentil_preco(closes, janela),
        "dist_media_200d_pct": distancia_media(closes, 200),
        "percentil_volume": percentil_volume(volumes, janela) if volumes else None,
        "retorno_7d_pct": retorno_periodo(closes, 7),
    }


def fatos_do_ativo(symbol, db_path=DB_DEFAULT, conn=None) -> dict:
    """Fatos OBJETIVOS p/ o Gabriel julgar fundamento — nunca um veredito nosso.
    Liquidez e idade sao fatos; 'tem fundamento' e juizo dele."""
    fechar = conn is None
    conn = conn or _conn(db_path)
    try:
        ensure_schema(conn)
        r = conn.execute(
            "SELECT COUNT(*) n, MIN(data) ini, AVG(volume_usd) vol FROM precos_diarios "
            "WHERE symbol=?", (symbol,)).fetchone()
        return {"symbol": symbol, "dias_de_historia": r["n"],
                "primeiro_dia": r["ini"], "volume_diario_medio_usd": r["vol"]}
    finally:
        if fechar:
            conn.close()


# ───────────────────────── regua congelada (PURA) ─────────────────────────
# Uma regra e um dict congelado ANTES de olhar o resultado. Tipos suportados:
#   {"tipo": "sempre"}                        -> DCA: compra todo aporte (o benchmark)
#   {"tipo": "drawdown", "limiar_pct": 30}    -> so compra se caiu >= 30% do topo
#   {"tipo": "percentil", "limiar": 30}       -> so compra se esta barato vs propria historia
#   {"tipo": "capitulacao", "vol_percentil_min": 90, "queda_min_pct": 5, "dias": 7}
#       -> volume no topo do ano E preco caindo. MECANISMO: venda forcada (liquidacao,
#          chamada de margem, panico) vende a qualquer preco e desloca o mercado. As unicas
#          hipoteses que chegaram longe no lab tinham historia causal ANTES do backtest.
TIPOS_REGRA = {"sempre", "drawdown", "percentil", "capitulacao"}


def valida_regra(regra) -> list[str]:
    """Lista de erros (vazia = valida). Regra invalida nunca deve rodar."""
    if not isinstance(regra, dict):
        return ["regra deve ser dict"]
    t = regra.get("tipo")
    if t not in TIPOS_REGRA:
        return [f"tipo invalido: {t!r} (use {sorted(TIPOS_REGRA)})"]
    if t == "drawdown":
        v = regra.get("limiar_pct")
        if not isinstance(v, (int, float)) or not (0 < v < 100):
            return ["drawdown exige limiar_pct entre 0 e 100"]
    if t == "percentil":
        v = regra.get("limiar")
        if not isinstance(v, (int, float)) or not (0 <= v <= 100):
            return ["percentil exige limiar entre 0 e 100"]
    if t == "capitulacao":
        v = regra.get("vol_percentil_min")
        if not isinstance(v, (int, float)) or not (0 <= v <= 100):
            return ["capitulacao exige vol_percentil_min entre 0 e 100"]
        q = regra.get("queda_min_pct")
        if not isinstance(q, (int, float)) or q < 0:
            return ["capitulacao exige queda_min_pct >= 0"]
    return []


def avalia_regra(ctx, regra) -> dict:
    """A regra bateu? Deterministico e puro. Informa — nao decide por voce."""
    erros = valida_regra(regra)
    if erros:
        return {"bateu": False, "motivo": "; ".join(erros)}
    t = regra["tipo"]
    if t == "sempre":
        return {"bateu": True, "motivo": "aporte periodico (DCA)"}
    if t == "drawdown":
        dd, lim = ctx.get("drawdown_topo_pct"), regra["limiar_pct"]
        if dd is None:
            return {"bateu": False, "motivo": "sem dado de drawdown"}
        return {"bateu": dd >= lim,
                "motivo": f"drawdown {dd:.1f}% vs limiar {lim:.1f}%"}
    if t == "capitulacao":
        pv, ret = ctx.get("percentil_volume"), ctx.get("retorno_7d_pct")
        if pv is None or ret is None:
            return {"bateu": False, "motivo": "sem dado de volume ou de retorno"}
        vol_ok = pv >= regra["vol_percentil_min"]
        queda_ok = ret <= -regra["queda_min_pct"]
        return {"bateu": vol_ok and queda_ok,
                "motivo": f"volume p{pv:.0f} (min {regra['vol_percentil_min']:.0f}), "
                          f"retorno 7d {ret:+.1f}% (max -{regra['queda_min_pct']:.1f}%)"}
    pc, lim = ctx.get("percentil"), regra["limiar"]
    if pc is None:
        return {"bateu": False, "motivo": "sem dado de percentil"}
    return {"bateu": pc <= lim, "motivo": f"percentil {pc:.0f} vs limiar {lim:.0f}"}


# ───────────────────────── benchmark (o juiz honesto) ─────────────────────────
def simula(datas, closes, regra, aporte=200.0, janela=JANELA_PADRAO,
           fee_pct=FEE_PCT, volumes=None) -> dict:
    """Simula aportes mensais sob uma regra, no historico real.

    Contrato anti-lookahead (a regra que o momentum aprendeu do jeito caro): o contexto
    do dia i usa SOMENTE closes[:i+1]. Nenhuma decisao enxerga o futuro.

    Dinheiro nao gasto vira caixa e espera. Valor final = unidades*preco + caixa, entao a
    comparacao entre regras e justa: mesmo dinheiro entrando, mesma janela.
    """
    erros = valida_regra(regra)
    if erros:
        raise ValueError("; ".join(erros))
    unidades = caixa = investido = 0.0
    compras = []
    mes_anterior = None
    for i, (d, preco) in enumerate(zip(datas, closes)):
        mes = d[:7]
        if mes != mes_anterior:          # aporte entra no 1o dia de cada mes com dado
            caixa += aporte
            investido += aporte
            mes_anterior = mes
        if caixa <= 0:
            continue
        ctx = contexto_ativo(closes[:i + 1], janela,
                             volumes[:i + 1] if volumes else None)   # <- so o passado
        if avalia_regra(ctx, regra)["bateu"]:
            liquido = caixa * (1 - fee_pct / 100.0)
            unidades += liquido / preco
            compras.append({"data": d, "preco": preco, "valor": caixa})
            caixa = 0.0
    preco_final = closes[-1] if closes else 0.0
    valor = unidades * preco_final + caixa
    return {
        "regra": regra, "investido": investido, "unidades": unidades, "caixa": caixa,
        "n_compras": len(compras), "compras": compras,
        "preco_medio": (sum(c["valor"] for c in compras) / unidades) if unidades else None,
        "valor_final": valor,
        "retorno_pct": ((valor / investido - 1) * 100.0) if investido else None,
    }


def compara_com_dca(datas, closes, regra, aporte=200.0, janela=JANELA_PADRAO,
                    fee_pct=FEE_PCT, volumes=None) -> dict:
    """A pergunta que decide tudo: a regra bate comprar todo mes sem pensar?

    Veredito mecanico. Se BATE-DCA nao aparecer, use DCA — e mais simples e ganhou.
    """
    r = simula(datas, closes, regra, aporte, janela, fee_pct, volumes)
    dca = simula(datas, closes, {"tipo": "sempre"}, aporte, janela, fee_pct)
    diff = r["valor_final"] - dca["valor_final"]
    return {
        "janela": (datas[0], datas[-1]) if datas else (None, None),
        "regra": r, "dca": dca,
        "diferenca": diff,
        "diferenca_pct": (diff / dca["valor_final"] * 100.0) if dca["valor_final"] else None,
        "veredito": "BATE-DCA" if diff > 0 else "PERDE-PRO-DCA",
    }


def robustez_por_janela(datas, closes, regra, anos=3, aporte=200.0,
                        janela=JANELA_PADRAO, fee_pct=FEE_PCT, volumes=None) -> dict:
    """Walk-forward: a regra bate o DCA em VARIAS janelas, ou so numa sortuda?

    Lei nº 6 do lab ("walk-forward obrigatorio para qualquer filtro"): um unico
    compara_com_dca e cherry-pick esperando pra acontecer. Uma regra que ganha em 1 de 6
    janelas nao tem edge, tem beta de regime — o erro nº 1 do post-mortem.

    Veredito ROBUSTA exige ganhar na MAIORIA das janelas E media positiva. Qualquer coisa
    abaixo disso e NAO-ROBUSTA: use DCA.
    """
    if not datas:
        return {"janelas": [], "n": 0, "veredito": "SEM-DADO"}
    passo = 365 * anos
    saidas = []
    ini = 0
    while ini + passo <= len(datas):
        ds, cs = datas[ini:ini + passo], closes[ini:ini + passo]
        vs = volumes[ini:ini + passo] if volumes else None
        o = compara_com_dca(ds, cs, regra, aporte, janela, fee_pct, vs)
        saidas.append({"de": ds[0], "ate": ds[-1], "diferenca_pct": o["diferenca_pct"],
                       "veredito": o["veredito"]})
        ini += 365   # janelas deslizantes de 1 ano
    if not saidas:
        return {"janelas": [], "n": 0, "veredito": "SEM-DADO"}
    difs = [s["diferenca_pct"] for s in saidas if s["diferenca_pct"] is not None]
    ganhou = sum(1 for d in difs if d > 0)
    media = sum(difs) / len(difs) if difs else 0.0
    robusta = difs and ganhou > len(difs) / 2 and media > 0
    return {
        "janelas": saidas, "n": len(saidas),
        "ganhou_em": ganhou, "taxa_vitoria": ganhou / len(difs) if difs else 0.0,
        "diferenca_media_pct": media,
        "pior_pct": min(difs) if difs else None, "melhor_pct": max(difs) if difs else None,
        "veredito": "ROBUSTA" if robusta else "NAO-ROBUSTA",
    }
