"""
Agent Brain — Claude Haiku como tomador de decisao principal.
Recebe dados brutos de mercado de todos os ativos e decide quais acoes tomar.
Retorna um dict com 'reasoning' e 'actions'. Nunca lanca excecao.
"""
import os
import json
import anthropic
from config import AGENT_MODEL, AGENT_MAX_TOKENS, AGENT_TEMPERATURE

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


SYSTEM_PROMPT = """Voce e um trader quantitativo de criptomoedas especializado em analise tecnica.
Sua tarefa e analisar dados de mercado de varios ativos simultaneamente e decidir quais acoes tomar.

Regras obrigatorias:
1. Entre somente quando ha confluencia clara: RSI + tendencia 5m + HTF (1h) todos alinhados
2. LONG: RSI < 40 E SMA9 > SMA21 (5m) E HTF trend = alta
3. SHORT: RSI > 60 E SMA9 < SMA21 (5m) E HTF trend = baixa
4. SL baseado em ATR: sl_pct = max(atr_pct * 1.5, 2.0) — minimo 2%
5. TP obrigatorio: tp_pct >= sl_pct * 2.0 (R/R minimo 2.0)
6. Maximo de 3 posicoes abertas simultaneas
7. Nao abra posicao em ativo que ja tem posicao aberta
8. Confidence minimo de 60 para qualquer entrada
9. Considere os ultimos trades ao decidir (evite repetir erros recentes)
10. Em mercado lateral ou sem confluencia, prefira nao operar (acoes = [])

Responda SOMENTE com JSON valido (sem markdown, sem texto extra):
{
  "reasoning": "analise geral do mercado em 1-2 frases em portugues",
  "actions": [
    {
      "action": "OPEN_LONG",
      "symbol": "BTCUSDT",
      "confidence": 72,
      "sl_pct": 2.5,
      "tp_pct": 5.0,
      "reason": "motivo especifico em portugues"
    }
  ]
}

Tipos de action validos: OPEN_LONG, OPEN_SHORT, CLOSE
Para CLOSE inclua apenas action e symbol (sem sl_pct/tp_pct).
Omita ativos sem acao (nao inclua HOLD).
"""


def _format_prompt(market_data: dict, agent_state: dict, trade_history: list) -> str:
    lines = []

    capital = agent_state.get("capital", 0)
    positions = agent_state.get("positions", {})

    lines.append("=== PORTFOLIO ===")
    lines.append(f"Capital disponivel: ${capital:.2f}")
    lines.append(f"Posicoes abertas: {len(positions)}/3")

    if positions:
        lines.append("\nPosicoes abertas:")
        for sym, pos in positions.items():
            pnl_note = ""
            if sym in market_data:
                price = market_data[sym]["price"]
                entry = float(pos["entry_price"])
                if pos["type"] == "LONG":
                    pnl_pct = (price - entry) / entry * 100
                else:
                    pnl_pct = (entry - price) / entry * 100
                pnl_note = f" | PnL atual: {pnl_pct:+.2f}%"
            lines.append(
                f"  {sym}: {pos['type']} @ {pos['entry_price']:.4f}"
                f" SL:{pos['sl_price']:.4f} TP:{pos['tp_price']:.4f}{pnl_note}"
            )

    if trade_history:
        lines.append("\n=== ULTIMOS TRADES (referencia) ===")
        for t in trade_history[:5]:
            pnl = float(t.get("pnl_pct") or 0)
            lines.append(
                f"  {t.get('symbol', '')} {t.get('type', '')} | "
                f"PnL: {pnl:+.2f}% | saida: {t.get('exit_reason', '')}"
            )

    lines.append("\n=== DADOS DE MERCADO (5m) ===")
    for symbol, data in market_data.items():
        htf = data.get("htf", {})
        price = data["price"]
        atr_pct = data.get("atr_pct", 0)
        trend_5m = "alta" if data["sma9"] > data["sma21"] else "baixa"

        lines.append(f"\n{symbol}:")
        lines.append(f"  Preco: {price:.4f}")
        lines.append(f"  RSI(14): {data['rsi']:.1f}")
        lines.append(
            f"  Tendencia 5m: {trend_5m} "
            f"(SMA9={data['sma9']:.4f} SMA21={data['sma21']:.4f})"
        )
        lines.append(f"  ATR14: {data['atr14']:.4f} ({atr_pct:.2f}% do preco)")
        lines.append(f"  Volume acima media: {data['volume_above_avg']}")
        lines.append(f"  Body ratio candle: {data['body_ratio']:.2f}")
        lines.append(
            f"  Resistencia recente: {data['recent_high']:.4f} | "
            f"Suporte recente: {data['recent_low']:.4f}"
        )
        lines.append(
            f"  HTF (1h): trend={htf.get('trend', '?')} "
            f"RSI={htf.get('rsi', 0):.1f} "
            f"ATR={htf.get('atr14', 0):.4f}"
        )

    return "\n".join(lines)


def analyze_market(market_data: dict, agent_state: dict, trade_history: list) -> dict:
    """
    Chama Claude Haiku com todos os dados de mercado e retorna decisoes.
    Nunca lanca excecao — retorna acoes vazias em caso de falha.
    """
    empty = {"reasoning": "sem acao (erro ou sem dados)", "actions": []}

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[AGENT BRAIN] ANTHROPIC_API_KEY nao configurada no .env")
        return empty

    if not market_data:
        return empty

    try:
        user_message = _format_prompt(market_data, agent_state, trade_history)

        client = _get_client()
        response = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=AGENT_MAX_TOKENS,
            temperature=AGENT_TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text.strip()

        # Remove markdown code fences se presentes
        if "```" in raw:
            for part in raw.split("```"):
                stripped = part.lstrip("json").strip()
                if stripped.startswith("{"):
                    raw = stripped
                    break

        decisions = json.loads(raw)

        if "actions" not in decisions:
            decisions["actions"] = []

        reasoning = decisions.get("reasoning", "")
        print(f"  [AGENT BRAIN] {reasoning}")
        return decisions

    except json.JSONDecodeError as e:
        print(f"[AGENT BRAIN] JSON invalido na resposta do Claude: {e}")
        return empty
    except Exception as e:
        print(f"[AGENT BRAIN] Erro ao chamar Claude: {e}")
        return empty
