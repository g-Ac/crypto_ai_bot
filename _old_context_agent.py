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


def interpret_signal(result: dict) -> str:
    if not client:
        return None

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
        return None
