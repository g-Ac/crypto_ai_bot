import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = None
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if ANTHROPIC_API_KEY:
    client = Anthropic(api_key=ANTHROPIC_API_KEY)


SYSTEM_PROMPT = """Voce e um analista tecnico de criptomoedas.
Voce recebe dados de uma analise tecnica automatizada e gera uma interpretacao
curta e direta em portugues brasileiro.

Regras:
- Maximo 4 linhas
- Nao use emojis
- Seja objetivo: diga o que os indicadores mostram e por que a decisao faz sentido (ou nao)
- Mencione os indicadores mais relevantes para essa decisao especifica
- Se for HOLD, explique o que esta impedindo um sinal claro
- Termine com o nivel de confianca
"""


def _rule_based_interpretation(result: dict) -> str:
    """Fallback interpretation when Claude is unavailable."""
    decision = result["decision"]
    symbol = result["symbol"]
    confidence = result["confidence_score"]
    rsi = result["rsi"]
    rsi_status = result["rsi_status"]
    htf_aligned = result["htf_aligned"]
    htf_trend = result["htf_trend"]
    volume = result["volume_above_avg"]
    buy_score = result["buy_score"]
    sell_score = result["sell_score"]

    lines = []

    score = buy_score if decision == "BUY" else sell_score
    if decision in ("BUY", "SELL"):
        lado = "compra" if decision == "BUY" else "venda"
        lines.append(f"{symbol}: sinal de {lado} com score {score} e confianca {confidence}/100.")
    else:
        lines.append(f"{symbol}: sem sinal claro (HOLD), confianca {confidence}/100.")

    indicators = []
    if htf_aligned:
        indicators.append("tendencia 1h confirma")
    else:
        indicators.append(f"tendencia 1h ({htf_trend}) NAO confirma")
    if volume:
        indicators.append("volume acima da media")
    if rsi_status != "neutro":
        indicators.append(f"RSI {rsi:.0f} ({rsi_status})")
    if indicators:
        lines.append("Indicadores: " + ", ".join(indicators) + ".")

    if confidence >= 80:
        lines.append(f"Confianca alta ({confidence}/100).")
    elif confidence >= 60:
        lines.append(f"Confianca moderada ({confidence}/100).")
    else:
        lines.append(f"Confianca baixa ({confidence}/100) - cautela.")

    return "\n".join(lines)


def interpret_signal(result: dict) -> str:
    if not client:
        return _rule_based_interpretation(result)

    data_text = (
        f"Ativo: {result['symbol']}\n"
        f"Preco: {result['price']:.2f}\n"
        f"SMA9: {result.get('sma_9', 0):.2f} / SMA21: {result.get('sma_21', 0):.2f}\n"
        f"Tendencia: {result['trend']}\n"
        f"RSI: {result['rsi']:.2f} ({result['rsi_status']})\n"
        f"Posicao: {result['price_position']}\n"
        f"Direcao SMAs: {result['sma_9_direction']} / {result['sma_21_direction']}\n"
        f"Breakout: {result['breakout_status']}\n"
        f"Volume acima da media: {result['volume_above_avg']}\n"
        f"Body ratio: {result['body_ratio']}\n"
        f"Tendencia 1h: {result['htf_trend']}\n"
        f"Alinhado com 1h: {result['htf_aligned']}\n"
        f"Buy score: {result['buy_score']} | Sell score: {result['sell_score']}\n"
        f"Decisao: {result['decision']}\n"
        f"Confianca: {result['confidence_score']}/100\n"
        f"Priority: {result['priority_score']}\n"
        f"Motivo: {result['reason']}\n"
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": data_text}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"Erro no Context Agent: {e}")
        return _rule_based_interpretation(result)
