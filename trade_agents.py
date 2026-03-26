"""
Sistema Multi-Agent para Trade Automatico.

Fluxo:
  1. Analista (Claude)  -> valida oportunidade
  2. Risco (Python)     -> calcula posicao, SL, TP
  3. Executor (Python)  -> executa trade (paper ou real)
"""
import os
import json
import tempfile
import requests
import pandas as pd
import ta
from datetime import datetime, timedelta
import database as db
from dotenv import load_dotenv
from anthropic import Anthropic
from config import (
    STOP_LOSS_MAP, STOP_LOSS_PCT, AGENT_INITIAL_CAPITAL, COOLDOWN_MINUTES,
    ATR_SL_MULTIPLIER, ATR_SL_FLOOR_PCT,
)

load_dotenv()

# ============================================================
#  CONFIGURACAO DOS AGENTES
# ============================================================

AGENT_CAPITAL = AGENT_INITIAL_CAPITAL
AGENT_MAX_RISK_PER_TRADE = 2.0       # % do capital por trade
AGENT_MAX_POSITIONS = 3               # maximo de posicoes abertas
AGENT_REWARD_RATIO = 2.0              # TP = SL * reward_ratio
AGENT_STATE_FILE = "agent_state.json"

client = None
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if ANTHROPIC_API_KEY:
    client = Anthropic(api_key=ANTHROPIC_API_KEY)


# ============================================================
#  STATE MANAGEMENT
# ============================================================

def load_state():
    if not os.path.exists(AGENT_STATE_FILE):
        return {
            "capital": AGENT_CAPITAL,
            "positions": {},
            "cooldowns": {},
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "history": [],
        }
    with open(AGENT_STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    data = json.dumps(state, indent=4, default=str)
    dir_name = os.path.dirname(os.path.abspath(AGENT_STATE_FILE))
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as f:
        f.write(data)
        tmp_path = f.name
    os.replace(tmp_path, AGENT_STATE_FILE)


def log_trade(trade):
    db.insert_agent_trade(trade)


# ============================================================
#  AGENTE 1: ANALISTA (Claude)
# ============================================================

ANALYST_PROMPT = """Voce e um analista de trading de criptomoedas responsavel por validar oportunidades.

Voce recebe dados de uma analise tecnica automatizada. Sua funcao e decidir se o trade deve ser executado.

Considere:
- Alinhamento dos indicadores (quanto mais alinhados, melhor)
- RSI nao deve estar em extremos contra a direcao do trade
- Tendencia do 1h deve confirmar a direcao
- Volume acima da media e um bom sinal
- Body ratio forte na direcao do trade confirma momentum

Responda SOMENTE com um JSON valido, sem markdown, neste formato:
{"approved": true/false, "confidence": 0-100, "reasoning": "explicacao curta"}

Se os indicadores estao bem alinhados e o contexto confirma, aprove.
Se ha conflitos significativos, rejeite.
Seja objetivo e pratico."""


def agent_analyst(signal_data):
    """Agent 1: Validates opportunity using Claude."""
    if not client:
        # Fallback: approve if score >= SIGNAL_SCORE_MIN and htf_aligned
        approved = (
            signal_data["decision"] in ["BUY", "SELL"]
            and signal_data.get("htf_aligned", False)
        )
        return {
            "approved": approved,
            "confidence": signal_data.get("confidence_score", 50),
            "reasoning": "Analise automatica (Claude nao disponivel)",
        }

    data_text = (
        f"Ativo: {signal_data['symbol']}\n"
        f"Decisao do sistema: {signal_data['decision']}\n"
        f"Preco: {signal_data['price']:.4f}\n"
        f"Tendencia 5m: {signal_data['trend']}\n"
        f"Tendencia 1h: {signal_data['htf_trend']}\n"
        f"Alinhado HTF: {signal_data['htf_aligned']}\n"
        f"RSI: {signal_data['rsi']:.2f} ({signal_data['rsi_status']})\n"
        f"Posicao do preco: {signal_data['price_position']}\n"
        f"Direcao SMAs: {signal_data['sma_9_direction']} / {signal_data['sma_21_direction']}\n"
        f"Breakout: {signal_data['breakout_status']}\n"
        f"Volume acima media: {signal_data['volume_above_avg']}\n"
        f"Body ratio: {signal_data['body_ratio']}\n"
        f"Buy score: {signal_data['buy_score']} / Sell score: {signal_data['sell_score']}\n"
        f"Confidence score: {signal_data['confidence_score']}/100\n"
        f"Priority score: {signal_data['priority_score']}\n"
    )

    # Add recent trade history for context
    state = load_state()
    if state["history"]:
        recent = state["history"][-5:]
        data_text += f"\nUltimos {len(recent)} trades:\n"
        for h in recent:
            data_text += f"  {h['symbol']} {h['type']} -> {h['pnl_pct']:+.2f}%\n"

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=ANALYST_PROMPT,
            messages=[{"role": "user", "content": data_text}],
        )
        text = response.content[0].text.strip()
        # Remove markdown code blocks if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].strip()
        result = json.loads(text)
        return result
    except Exception as e:
        print(f"  Erro no Agente Analista: {e}")
        return {
            "approved": signal_data["decision"] in ["BUY", "SELL"],
            "confidence": signal_data.get("confidence_score", 50),
            "reasoning": f"Fallback automatico: {e}",
        }


# ============================================================
#  AGENTE 2: RISCO (Python)
# ============================================================

def get_atr(symbol, period=14):
    """Calculate ATR for dynamic SL/TP."""
    try:
        resp = requests.get(
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=1h&limit={period + 5}",
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore",
        ])
        for col in ["high", "low", "close"]:
            df[col] = df[col].astype(float)

        atr = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=period
        ).average_true_range()
        return atr.iloc[-1]
    except Exception:
        return None


def agent_risk(signal_data, analyst_result):
    """Agent 2: Calculates position size, SL, and TP."""
    state = load_state()
    symbol = signal_data["symbol"]
    price = signal_data["price"]
    direction = signal_data["decision"]  # BUY or SELL

    # Check max positions
    if len(state["positions"]) >= AGENT_MAX_POSITIONS:
        return {
            "approved": False,
            "reason": f"Maximo de {AGENT_MAX_POSITIONS} posicoes atingido",
        }

    # Check if already has position in this symbol
    if symbol in state["positions"]:
        return {
            "approved": False,
            "reason": f"Ja tem posicao aberta em {symbol}",
        }

    # Check cooldown after stop_loss
    cooldowns = state.get("cooldowns", {})
    if symbol in cooldowns:
        cooldown_end = datetime.fromisoformat(cooldowns[symbol]) + timedelta(minutes=COOLDOWN_MINUTES)
        if datetime.now() < cooldown_end:
            remaining = int((cooldown_end - datetime.now()).total_seconds() / 60)
            return {
                "approved": False,
                "reason": f"{symbol} em cooldown ({remaining}min restantes apos stop_loss)",
            }

    # Calculate SL based on ATR or config
    atr = get_atr(symbol)
    sl_pct = STOP_LOSS_MAP.get(symbol, STOP_LOSS_PCT)

    if atr:
        # ATR-based SL (1h): ATR_SL_MULTIPLIER x ATR, minimo de ATR_SL_FLOOR_PCT
        atr_sl_pct = (atr * ATR_SL_MULTIPLIER / price) * 100
        sl_pct = max(atr_sl_pct, ATR_SL_FLOOR_PCT)
    else:
        sl_pct = max(sl_pct, ATR_SL_FLOOR_PCT)

    # SL and TP prices
    if direction == "BUY":
        sl_price = price * (1 - sl_pct / 100)
        tp_price = price * (1 + (sl_pct * AGENT_REWARD_RATIO) / 100)
    else:
        sl_price = price * (1 + sl_pct / 100)
        tp_price = price * (1 - (sl_pct * AGENT_REWARD_RATIO) / 100)

    # Position sizing: risk-based
    risk_amount = state["capital"] * (AGENT_MAX_RISK_PER_TRADE / 100)
    position_size_usd = risk_amount / (sl_pct / 100)

    # Cap at 20% of capital
    max_size = state["capital"] * 0.20
    position_size_usd = min(position_size_usd, max_size)

    # Adjust confidence: reduce size if analyst confidence is low
    confidence = analyst_result.get("confidence", 50)
    if confidence < 70:
        position_size_usd *= 0.5
    elif confidence < 85:
        position_size_usd *= 0.75

    return {
        "approved": True,
        "position_size_usd": round(position_size_usd, 2),
        "sl_price": round(sl_price, 6),
        "tp_price": round(tp_price, 6),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(sl_pct * AGENT_REWARD_RATIO, 2),
        "risk_amount": round(risk_amount, 2),
        "atr": round(atr, 6) if atr else None,
    }


# ============================================================
#  AGENTE 3: EXECUTOR (Paper / Real)
# ============================================================

def agent_executor(signal_data, risk_params, analyst_result):
    """Agent 3: Executes the trade (paper mode)."""
    state = load_state()
    symbol = signal_data["symbol"]
    price = signal_data["price"]
    direction = "LONG" if signal_data["decision"] == "BUY" else "SHORT"

    # Record position
    state["positions"][symbol] = {
        "type": direction,
        "entry_price": price,
        "entry_time": datetime.now().isoformat(),
        "sl_price": risk_params["sl_price"],
        "tp_price": risk_params["tp_price"],
        "position_size_usd": risk_params["position_size_usd"],
        "analyst_confidence": analyst_result.get("confidence", 0),
    }
    save_state(state)

    # Log trade open
    trade = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "type": direction,
        "entry_price": price,
        "sl_price": risk_params["sl_price"],
        "tp_price": risk_params["tp_price"],
        "position_size_usd": risk_params["position_size_usd"],
        "analyst_confidence": analyst_result.get("confidence", 0),
        "capital_after": state["capital"],
    }
    log_trade(trade)

    return (
        f"[AGENT] {direction} executado: {symbol}\n"
        f"Entrada: {price:.4f}\n"
        f"SL: {risk_params['sl_price']:.4f} (-{risk_params['sl_pct']}%)\n"
        f"TP: {risk_params['tp_price']:.4f} (+{risk_params['tp_pct']}%)\n"
        f"Tamanho: ${risk_params['position_size_usd']:.2f}\n"
        f"Confianca analista: {analyst_result.get('confidence', 0)}/100\n"
        f"Razao: {analyst_result.get('reasoning', '')}"
    )


def check_agent_positions(results):
    """Check all open positions for SL/TP hits."""
    state = load_state()
    messages = []

    for result in results:
        symbol = result["symbol"]
        if symbol not in state["positions"]:
            continue

        pos = state["positions"][symbol]
        price = result["price"]
        entry = pos["entry_price"]

        hit = None

        if pos["type"] == "LONG":
            pnl_pct = ((price - entry) / entry) * 100
            if price <= pos["sl_price"]:
                hit = "stop_loss"
                pnl_pct = -abs(((entry - pos["sl_price"]) / entry) * 100)
            elif price >= pos["tp_price"]:
                hit = "take_profit"
                pnl_pct = abs(((pos["tp_price"] - entry) / entry) * 100)
        else:
            pnl_pct = ((entry - price) / entry) * 100
            if price >= pos["sl_price"]:
                hit = "stop_loss"
                pnl_pct = -abs(((pos["sl_price"] - entry) / entry) * 100)
            elif price <= pos["tp_price"]:
                hit = "take_profit"
                pnl_pct = abs(((entry - pos["tp_price"]) / entry) * 100)

        # Also exit on opposite signal
        if hit is None:
            if (pos["type"] == "LONG" and result["decision"] == "SELL") or \
               (pos["type"] == "SHORT" and result["decision"] == "BUY"):
                hit = "opposite_signal"

        if hit:
            pnl_usd = pos["position_size_usd"] * (pnl_pct / 100)
            state["capital"] += pnl_usd
            state["total_trades"] += 1

            if pnl_pct > 0:
                state["wins"] += 1
            else:
                state["losses"] += 1

            if hit == "stop_loss":
                state.setdefault("cooldowns", {})[symbol] = datetime.now().isoformat()

            state["history"].append({
                "symbol": symbol,
                "type": pos["type"],
                "pnl_pct": round(pnl_pct, 2),
            })
            # Keep only last 20
            state["history"] = state["history"][-20:]

            wr = (state["wins"] / state["total_trades"]) * 100

            trade = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "type": pos["type"],
                "entry_price": entry,
                "sl_price": pos["sl_price"],
                "tp_price": pos["tp_price"],
                "position_size_usd": pos["position_size_usd"],
                "exit_price": price,
                "pnl_pct": round(pnl_pct, 4),
                "pnl_usd": pnl_usd,
                "exit_reason": hit,
                "analyst_confidence": pos.get("analyst_confidence", 0),
                "capital_after": state["capital"],
            }
            log_trade(trade)

            msg = (
                f"[AGENT] {pos['type']} fechado: {symbol}\n"
                f"Entrada: {entry:.4f} | Saida: {price:.4f}\n"
                f"P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
                f"Motivo: {hit}\n"
                f"Capital: ${state['capital']:.2f} | "
                f"Trades: {state['total_trades']} | WR: {wr:.1f}%"
            )
            messages.append(msg)
            del state["positions"][symbol]

    save_state(state)
    return messages


# ============================================================
#  ORQUESTRADOR
# ============================================================

def orchestrate(results):
    """Main orchestrator: runs the 3-agent pipeline for each signal."""
    messages = []

    # Step 0: check existing positions for SL/TP
    exit_msgs = check_agent_positions(results)
    messages.extend(exit_msgs)

    # Step 1-3: process new signals
    for result in results:
        if result["decision"] not in ["BUY", "SELL"]:
            continue

        symbol = result["symbol"]
        print(f"\n  [ORQUESTRADOR] Processando sinal {result['decision']} em {symbol}...")

        # AGENT 1: Analyst
        print(f"  [AGENTE 1] Analisando {symbol}...")
        analyst = agent_analyst(result)
        print(f"  [AGENTE 1] Aprovado: {analyst['approved']} | Confianca: {analyst.get('confidence', 0)}")
        print(f"  [AGENTE 1] Razao: {analyst.get('reasoning', '')}")

        if not analyst["approved"]:
            messages.append(
                f"[AGENT] Sinal {result['decision']} em {symbol} REJEITADO pelo Analista\n"
                f"Razao: {analyst.get('reasoning', 'N/A')}"
            )
            continue

        # AGENT 2: Risk
        print(f"  [AGENTE 2] Calculando risco para {symbol}...")
        risk = agent_risk(result, analyst)
        print(f"  [AGENTE 2] Aprovado: {risk['approved']}")

        if not risk["approved"]:
            messages.append(
                f"[AGENT] Sinal {result['decision']} em {symbol} BLOQUEADO pelo Risco\n"
                f"Razao: {risk.get('reason', 'N/A')}"
            )
            continue

        print(f"  [AGENTE 2] Size: ${risk['position_size_usd']} | SL: {risk['sl_pct']}% | TP: {risk['tp_pct']}%")

        # AGENT 3: Executor
        print(f"  [AGENTE 3] Executando trade...")
        exec_msg = agent_executor(result, risk, analyst)
        messages.append(exec_msg)
        print(f"  [AGENTE 3] Trade executado com sucesso")

    return messages


def get_agent_status():
    """Return current agent trading status."""
    state = load_state()
    wr = (state["wins"] / state["total_trades"]) * 100 if state["total_trades"] > 0 else 0
    ret = ((state["capital"] - AGENT_CAPITAL) / AGENT_CAPITAL) * 100

    lines = [
        f"[AGENTS] Capital: ${state['capital']:.2f} ({ret:+.2f}%)",
        f"[AGENTS] Trades: {state['total_trades']} | W:{state['wins']} L:{state['losses']} | WR: {wr:.1f}%",
        f"[AGENTS] Posicoes: {len(state['positions'])}/{AGENT_MAX_POSITIONS}",
    ]

    for sym, pos in state["positions"].items():
        lines.append(
            f"  {sym}: {pos['type']} @ {pos['entry_price']:.4f} | "
            f"SL: {pos['sl_price']:.4f} | TP: {pos['tp_price']:.4f}"
        )

    return "\n".join(lines)
