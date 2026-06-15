"""Fundos/topos/suportes automaticos — geometria pura sobre candles.

Marca o que o olho marcaria com uma caneta: pivos de minima (fundos) e maxima
(topos), e niveis tocados mais de uma vez (suporte/resistencia). Sem indicador,
sem opiniao — so a forma do grafico. Alimenta a tela de rotulagem cega e, depois,
o desk operacional.

Candle: dict {"time", "open", "high", "low", "close"} (formato lightweight-charts).
"""
from __future__ import annotations


def swing_points(candles: list[dict], k: int = 2) -> dict:
    """Pivos: um fundo no indice i tem low menor que os k candles de cada lado
    (analogo pra topo com high). Retorna {"lows": [...], "highs": [...]} com
    {"time", "price"} cada."""
    lows: list[dict] = []
    highs: list[dict] = []
    n = len(candles)
    for i in range(k, n - k):
        c = candles[i]
        window = candles[i - k:i] + candles[i + 1:i + k + 1]
        if all(c["low"] < w["low"] for w in window):
            lows.append({"time": c["time"], "price": c["low"]})
        if all(c["high"] > w["high"] for w in window):
            highs.append({"time": c["time"], "price": c["high"]})
    return {"lows": lows, "highs": highs}


def support_levels(candles: list[dict], k: int = 2, tol: float = 0.003) -> list[dict]:
    """Agrupa pivot lows proximos (dentro de tol relativo) num nivel de suporte.
    Um nivel tocado 2+ vezes e o que o olho chamaria de suporte de verdade.
    Retorna [{"price", "touches"}]."""
    lows = swing_points(candles, k)["lows"]
    levels: list[dict] = []
    for p in sorted(lows, key=lambda x: x["price"]):
        for lv in levels:
            if abs(p["price"] - lv["price"]) / lv["price"] <= tol:
                lv["_acc"].append(p["price"])
                lv["price"] = sum(lv["_acc"]) / len(lv["_acc"])
                lv["touches"] += 1
                break
        else:
            levels.append({"price": p["price"], "touches": 1, "_acc": [p["price"]]})
    for lv in levels:
        lv.pop("_acc")
    return levels
