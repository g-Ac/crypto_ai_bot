from config import (
    SMA_SHORT, SMA_LONG, BREAKOUT_WINDOW,
    RSI_OVERSOLD, RSI_OVERBOUGHT, RSI_BUY_ZONE, RSI_SELL_ZONE,
    SIGNAL_SCORE_MIN, PRE_SIGNAL_SCORE_MIN, PRE_SIGNAL_DIFF_MIN, OBSERVATION_SCORE_MIN,
    BODY_RATIO_MIN,
)


def generate_signal(df, htf_trend="lateral"):
    last = df.iloc[-2]
    candle_time = last["time"]

    price = last["close"]
    sma_short = last[f"sma_{SMA_SHORT}"]
    sma_long = last[f"sma_{SMA_LONG}"]
    sma_short_prev = last[f"sma_{SMA_SHORT}_prev"]
    sma_long_prev = last[f"sma_{SMA_LONG}_prev"]
    rsi = last["rsi"]
    recent_high = last[f"recent_high_{BREAKOUT_WINDOW}"]
    recent_low = last[f"recent_low_{BREAKOUT_WINDOW}"]
    volume = last["volume"]
    volume_avg = last["volume_avg"]
    volume_above_avg = volume > volume_avg
    body_ratio = last["body_ratio"]

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

    if price > sma_short and price > sma_long:
        price_position = "acima das duas médias"
    elif price > sma_short and price < sma_long:
        price_position = f"acima da sma {SMA_SHORT} e abaixo da sma {SMA_LONG}"
    elif price < sma_short and price > sma_long:
        price_position = f"abaixo da sma {SMA_SHORT} e acima da sma {SMA_LONG}"
    else:
        price_position = "abaixo das duas médias"

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
        breakout_status = "rompeu máxima recente"
    elif price < recent_low:
        breakout_status = "rompeu mínima recente"
    else:
        breakout_status = "dentro da faixa recente"

    buy_score = 0
    sell_score = 0

    if trend == "alta":
        buy_score += 1
    elif trend == "baixa":
        sell_score += 1

    if price > sma_short and price > sma_long:
        buy_score += 1
    elif price < sma_short and price < sma_long:
        sell_score += 1

    if sma_short_direction == "subindo" and sma_long_direction == "subindo":
        buy_score += 1
    elif sma_short_direction == "caindo" and sma_long_direction == "caindo":
        sell_score += 1

    if RSI_BUY_ZONE[0] <= rsi <= RSI_BUY_ZONE[1]:
        buy_score += 1
    elif RSI_SELL_ZONE[0] <= rsi <= RSI_SELL_ZONE[1]:
        sell_score += 1

    if breakout_status == "rompeu máxima recente":
        buy_score += 1
    elif breakout_status == "rompeu mínima recente":
        sell_score += 1

    if volume_above_avg and breakout_status == "rompeu máxima recente":
        buy_score += 1
    elif volume_above_avg and breakout_status == "rompeu mínima recente":
        sell_score += 1

    if body_ratio >= BODY_RATIO_MIN:
        buy_score += 1
    elif body_ratio <= -BODY_RATIO_MIN:
        sell_score += 1

    if buy_score > sell_score:
        dominant_side = "BUY"
    elif sell_score > buy_score:
        dominant_side = "SELL"
    else:
        dominant_side = "NEUTRAL"

    decision = "HOLD"
    reason = "Condições insuficientes para compra ou venda."

    if buy_score >= SIGNAL_SCORE_MIN and buy_score > sell_score:
        if rsi_status == "sobrecomprado":
            decision = "HOLD"
            reason = "RSI sobrecomprado, evitando compra em topo."
        else:
            decision = "BUY"
            reason = "Condições de compra bem alinhadas."

    elif sell_score >= SIGNAL_SCORE_MIN and sell_score > buy_score:
        if rsi_status == "sobrevendido":
            decision = "HOLD"
            reason = "RSI sobrevendido, evitando venda em fundo."
        else:
            decision = "SELL"
            reason = "Condições de venda bem alinhadas."

    else:
        if dominant_side == "BUY" and rsi_status == "sobrecomprado":
            reason = "Contexto comprador, mas RSI sobrecomprado exige cautela."
        elif dominant_side == "SELL" and rsi_status == "sobrevendido":
            reason = "Contexto vendedor, mas RSI sobrevendido exige cautela."
        elif dominant_side == "BUY":
            reason = "Contexto comprador moderado, mas sem confirmação final."
        elif dominant_side == "SELL":
            reason = "Contexto vendedor moderado, mas sem confirmação final."
        else:
            reason = "Mercado sem dominância clara."

    if htf_trend == "alta" and decision == "SELL":
        decision = "HOLD"
        reason = "Sinal contra tendência do 1h (alta)."
    elif htf_trend == "baixa" and decision == "BUY":
        decision = "HOLD"
        reason = "Sinal contra tendência do 1h (baixa)."

    htf_aligned = (
        (decision == "BUY" and htf_trend == "alta")
        or (decision == "SELL" and htf_trend == "baixa")
        or htf_trend == "lateral"
    )

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

    priority_score = confidence_score + (score_difference * 5)

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
        "rsi": rsi,
        "rsi_status": rsi_status,
        "price_position": price_position,
        "sma_9_direction": sma_short_direction,
        "sma_21_direction": sma_long_direction,
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
