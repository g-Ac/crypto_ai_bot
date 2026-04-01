import pandas as pd

from config import (
    SMA_SHORT, SMA_LONG, BREAKOUT_WINDOW,
    RSI_OVERSOLD, RSI_OVERBOUGHT, RSI_BUY_ZONE, RSI_SELL_ZONE,
    SIGNAL_SCORE_MIN, PRE_SIGNAL_SCORE_MIN, PRE_SIGNAL_DIFF_MIN, OBSERVATION_SCORE_MIN,
    BODY_RATIO_MIN,
)


def _score_row(row, htf_trend="lateral"):
    """Core scoring logic shared by generate_signal() and the backtester.

    Receives a single row (pd.Series or dict-like) with indicator columns
    already computed, plus the HTF trend string.

    Returns None if required indicators are NaN, otherwise returns a dict
    with: decision, price, buy_score, sell_score, htf_aligned.
    """
    s_col = f"sma_{SMA_SHORT}"
    l_col = f"sma_{SMA_LONG}"
    sp_col = f"sma_{SMA_SHORT}_prev"
    lp_col = f"sma_{SMA_LONG}_prev"
    rh_col = f"recent_high_{BREAKOUT_WINDOW}"
    rl_col = f"recent_low_{BREAKOUT_WINDOW}"

    price = row["close"]
    sma_short = row[s_col]
    sma_long = row[l_col]
    sma_short_prev = row[sp_col]
    sma_long_prev = row[lp_col]
    rsi = row["rsi"]
    recent_high = row[rh_col]
    recent_low = row[rl_col]
    volume = row["volume"]
    volume_avg = row["volume_avg"]
    body_ratio = row["body_ratio"]

    vals = [sma_short, sma_long, sma_short_prev, sma_long_prev,
            rsi, recent_high, recent_low, volume_avg]
    if any(pd.isna(v) for v in vals):
        return None

    volume_above_avg = volume > volume_avg

    if sma_short > sma_long:
        trend = "alta"
    elif sma_short < sma_long:
        trend = "baixa"
    else:
        trend = "lateral"

    if rsi < RSI_OVERSOLD:
        rsi_status = "sobrevendido"
    elif rsi > RSI_OVERBOUGHT:
        rsi_status = "sobrecomprado"
    else:
        rsi_status = "neutro"

    if sma_short > sma_short_prev:
        sma_short_direction = "subindo"
    elif sma_short < sma_short_prev:
        sma_short_direction = "caindo"
    else:
        sma_short_direction = "reta"

    if sma_long > sma_long_prev:
        sma_long_direction = "subindo"
    elif sma_long < sma_long_prev:
        sma_long_direction = "caindo"
    else:
        sma_long_direction = "reta"

    if price > recent_high:
        breakout_status = "rompeu maxima"
    elif price < recent_low:
        breakout_status = "rompeu minima"
    else:
        breakout_status = "dentro"

    buy_score = 0.0
    sell_score = 0.0

    # --- Grupo de tendencia (M3 FIX) ---
    # Os 3 criterios de tendencia (SMA cross, preco vs SMAs, direcao SMAs) sao
    # altamente correlacionados. Agrupamos como bloco unico que vale ate 1.5pts
    # em vez de 3x1pt, para evitar inflacao artificial do score.
    # 3/3 criterios = 1.5pts | 2/3 = 1.0pt | 1/3 = 0.5pt | 0/3 = 0pt
    buy_trend_hits = 0
    sell_trend_hits = 0

    # Criterio 1: tendencia (SMA curta > SMA longa)
    if trend == "alta":
        buy_trend_hits += 1
    elif trend == "baixa":
        sell_trend_hits += 1

    # Criterio 2: preco acima/abaixo das duas SMAs
    if price > sma_short and price > sma_long:
        buy_trend_hits += 1
    elif price < sma_short and price < sma_long:
        sell_trend_hits += 1

    # Criterio 3: direcao das SMAs (ambas subindo/caindo)
    if sma_short_direction == "subindo" and sma_long_direction == "subindo":
        buy_trend_hits += 1
    elif sma_short_direction == "caindo" and sma_long_direction == "caindo":
        sell_trend_hits += 1

    # Converte hits do grupo em pontuacao: {0: 0, 1: 0.5, 2: 1.0, 3: 1.5}
    _trend_points = {0: 0.0, 1: 0.5, 2: 1.0, 3: 1.5}
    buy_score += _trend_points[buy_trend_hits]
    sell_score += _trend_points[sell_trend_hits]

    if RSI_BUY_ZONE[0] <= rsi <= RSI_BUY_ZONE[1]:
        buy_score += 1
    elif RSI_SELL_ZONE[0] <= rsi <= RSI_SELL_ZONE[1]:
        sell_score += 1

    if breakout_status == "rompeu maxima":
        buy_score += 1
    elif breakout_status == "rompeu minima":
        sell_score += 1

    if volume_above_avg and breakout_status == "rompeu maxima":
        buy_score += 1
    elif volume_above_avg and breakout_status == "rompeu minima":
        sell_score += 1

    if body_ratio >= BODY_RATIO_MIN:
        buy_score += 1
    elif body_ratio <= -BODY_RATIO_MIN:
        sell_score += 1

    # --- Decision ---
    decision = "HOLD"

    if buy_score >= SIGNAL_SCORE_MIN and buy_score > sell_score:
        if rsi_status != "sobrecomprado":
            decision = "BUY"
    elif sell_score >= SIGNAL_SCORE_MIN and sell_score > buy_score:
        if rsi_status != "sobrevendido":
            decision = "SELL"

    if htf_trend == "alta" and decision == "SELL":
        decision = "HOLD"
    elif htf_trend == "baixa" and decision == "BUY":
        decision = "HOLD"

    htf_aligned = (
        (decision == "BUY" and htf_trend == "alta")
        or (decision == "SELL" and htf_trend == "baixa")
        or htf_trend == "lateral"
    )

    return {
        "decision": decision,
        "price": price,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "htf_aligned": htf_aligned,
        # Extra fields used by generate_signal() for rich output
        "trend": trend,
        "rsi": rsi,
        "rsi_status": rsi_status,
        "sma_short_direction": sma_short_direction,
        "sma_long_direction": sma_long_direction,
        "breakout_status": breakout_status,
        "volume_above_avg": volume_above_avg,
        "body_ratio": body_ratio,
    }


def generate_signal(df, htf_trend="lateral"):
    last = df.iloc[-2]
    candle_time = last["time"]

    scored = _score_row(last, htf_trend)
    if scored is None:
        return None

    price = scored["price"]
    sma_short = last[f"sma_{SMA_SHORT}"]
    sma_long = last[f"sma_{SMA_LONG}"]
    buy_score = scored["buy_score"]
    sell_score = scored["sell_score"]
    decision = scored["decision"]
    rsi_status = scored["rsi_status"]
    trend = scored["trend"]
    breakout_status = scored["breakout_status"]
    volume_above_avg = scored["volume_above_avg"]
    body_ratio = scored["body_ratio"]
    htf_aligned = scored["htf_aligned"]

    if price > sma_short and price > sma_long:
        price_position = "acima das duas medias"
    elif price > sma_short and price < sma_long:
        price_position = f"acima da sma {SMA_SHORT} e abaixo da sma {SMA_LONG}"
    elif price < sma_short and price > sma_long:
        price_position = f"abaixo da sma {SMA_SHORT} e acima da sma {SMA_LONG}"
    else:
        price_position = "abaixo das duas medias"

    if buy_score > sell_score:
        dominant_side = "BUY"
    elif sell_score > buy_score:
        dominant_side = "SELL"
    else:
        dominant_side = "NEUTRAL"

    reason = "Condicoes insuficientes para compra ou venda."

    if buy_score >= SIGNAL_SCORE_MIN and buy_score > sell_score:
        if rsi_status == "sobrecomprado":
            reason = "RSI sobrecomprado, evitando compra em topo."
        else:
            reason = "Condicoes de compra bem alinhadas."
    elif sell_score >= SIGNAL_SCORE_MIN and sell_score > buy_score:
        if rsi_status == "sobrevendido":
            reason = "RSI sobrevendido, evitando venda em fundo."
        else:
            reason = "Condicoes de venda bem alinhadas."
    else:
        if dominant_side == "BUY" and rsi_status == "sobrecomprado":
            reason = "Contexto comprador, mas RSI sobrecomprado exige cautela."
        elif dominant_side == "SELL" and rsi_status == "sobrevendido":
            reason = "Contexto vendedor, mas RSI sobrevendido exige cautela."
        elif dominant_side == "BUY":
            reason = "Contexto comprador moderado, mas sem confirmacao final."
        elif dominant_side == "SELL":
            reason = "Contexto vendedor moderado, mas sem confirmacao final."
        else:
            reason = "Mercado sem dominancia clara."

    if htf_trend == "alta" and decision == "HOLD" and sell_score >= SIGNAL_SCORE_MIN:
        reason = "Sinal contra tendencia do 1h (alta)."
    elif htf_trend == "baixa" and decision == "HOLD" and buy_score >= SIGNAL_SCORE_MIN:
        reason = "Sinal contra tendencia do 1h (baixa)."

    best_score = max(buy_score, sell_score)

    if best_score >= SIGNAL_SCORE_MIN:
        signal_strength = "forte"
    elif best_score >= OBSERVATION_SCORE_MIN:
        signal_strength = "moderado"
    else:
        signal_strength = "fraco"

    score_difference = abs(buy_score - sell_score)

    if decision in ["BUY", "SELL"]:
        opportunity_type = "sinal"
    elif (buy_score >= PRE_SIGNAL_SCORE_MIN or sell_score >= PRE_SIGNAL_SCORE_MIN) and score_difference >= PRE_SIGNAL_DIFF_MIN:
        opportunity_type = "pre_sinal"
    elif buy_score >= OBSERVATION_SCORE_MIN or sell_score >= OBSERVATION_SCORE_MIN:
        opportunity_type = "observacao"
    else:
        opportunity_type = "nenhuma"

    confidence_score = 50
    confidence_score += best_score * 10
    confidence_score += score_difference * 5

    if signal_strength == "fraco":
        confidence_score -= 10
    elif signal_strength == "forte":
        confidence_score += 10

    if rsi_status == "sobrecomprado" and dominant_side == "BUY":
        confidence_score -= 15

    if rsi_status == "sobrevendido" and dominant_side == "SELL":
        confidence_score -= 15

    if decision == "HOLD":
        confidence_score -= 20

    confidence_score = max(0, min(100, confidence_score))

    priority_score = confidence_score

    if opportunity_type == "sinal":
        priority_score += 20
    elif opportunity_type == "pre_sinal":
        priority_score += 10

    if decision == "HOLD":
        priority_score -= 15

    priority_score = max(0, min(100, priority_score))

    return {
        "candle_time": candle_time,
        "price": price,
        "sma_9": sma_short,
        "sma_21": sma_long,
        "trend": trend,
        "rsi": scored["rsi"],
        "rsi_status": rsi_status,
        "price_position": price_position,
        "sma_9_direction": scored["sma_short_direction"],
        "sma_21_direction": scored["sma_long_direction"],
        "breakout_status": breakout_status,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "signal_strength": signal_strength,
        "decision": decision,
        "reason": reason,
        "score_difference": score_difference,
        "opportunity_type": opportunity_type,
        "dominant_side": dominant_side,
        "confidence_score": confidence_score,
        "priority_score": priority_score,
        "volume_above_avg": volume_above_avg,
        "body_ratio": round(body_ratio, 4),
        "htf_trend": htf_trend,
        "htf_aligned": htf_aligned,
    }
