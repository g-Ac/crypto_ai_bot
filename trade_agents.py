"""
Sistema Multi-Agent para Trade Automatico.

Fluxo:
  1. Analista (Claude)  -> valida oportunidade
  2. Risco (Python)     -> calcula posicao, SL, TP
  3. Executor (Python)  -> executa trade (paper ou real)
"""
import os
import json
import time
import tempfile
import uuid
import requests
import pandas as pd
import ta
from datetime import datetime, timedelta
import database as db
from dotenv import load_dotenv
from anthropic import Anthropic
from config import (
    AGENT_INITIAL_CAPITAL, COOLDOWN_MINUTES,
    ATR_SL_MULTIPLIER, ATR_SL_FLOOR_PCT,
    AGENT_REAL_EXECUTION_ENABLED,
    AGENT_REAL_MIN_CONFIDENCE,
    AGENT_REAL_MIN_SETUP_QUALITY,
    AGENT_REAL_BLOCKED_ENTRY_QUALITY,
    AGENT_REAL_BLOCKED_INVALIDATION_QUALITY,
    ROUND_TRIP_FEE_PCT,
)
from runtime_config import AGENT_STATE_FILE

load_dotenv()

# ============================================================
#  CONFIGURACAO DOS AGENTES
# ============================================================

AGENT_CAPITAL = AGENT_INITIAL_CAPITAL
AGENT_MAX_RISK_PER_TRADE = 2.0       # % do capital por trade
AGENT_MAX_POSITIONS = 3               # maximo de posicoes abertas
AGENT_REWARD_RATIO = 2.0              # TP = SL * reward_ratio

client = None
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if ANTHROPIC_API_KEY:
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

ANALYST_PROMPT_VERSION = "analyst_v3_regime"


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

def _build_analyst_prompt(state):
    """Build dynamic analyst prompt with current performance context."""
    base = """Voce e o ULTIMO FILTRO antes da execucao de um trade real.
Seu trabalho principal e IMPEDIR trades ruins. Uma boa taxa de rejeicao e 60-80%.

## Seu papel

Voce recebe dados tecnicos de um ativo e deve decidir independentemente:
1. Se existe uma oportunidade (LONG, SHORT, ou NENHUMA)
2. Qual a qualidade do setup
3. Se deve aprovar ou rejeitar

Voce NAO recebe a decisao do sistema. Voce DECIDE a direcao.

## Regra de ouro

Na DUVIDA, rejeite. O custo de perder uma oportunidade e ZERO.
O custo de aprovar um trade ruim e real (dinheiro perdido).

## Filtro de regime (OBRIGATORIO)

O campo "Regime de mercado" nos dados indica a forca da tendencia:
- ADX < 20 = mercado SEM TENDENCIA -> rejeite sinais de tendencia/momentum. So aprove reversao se extremamente claro.
- ADX 20-25 = tendencia FRACA -> exija confluencia excepcional (confidence minima 85)
- ADX > 25 = tendencia PRESENTE -> analise normal, mas ainda seja critico
- Se BB Width < 2% = mercado comprimido -> apenas breakouts excepcionais podem ser validos

## Escala de confidence CALIBRADA

- 90-100: Setup perfeito, TODOS os indicadores alinhados, tendencia forte confirmada, regime adequado. RARO (< 5% dos sinais)
- 75-89: Setup bom com pequenas ressalvas. Aprovavel se ADX > 25 e tendencia alinhada
- 50-74: Setup mediocre. REJEITE — nao ha margem suficiente
- 0-49: Setup fraco ou conflitante. REJEITE sempre

## Benchmarks de calibracao

- Se voce esta aprovando mais de 40% dos sinais, esta sendo permissivo demais
- Se sua confidence media e > 80, esta sendo overconfident
- Um analista conservador real rejeitaria 7 de cada 10 sinais
- Confidence 100 deveria ser praticamente impossivel em scalping/5min

## Criterios de avaliacao

- RSI em extremo CONTRA a direcao proposta = red flag forte
- Tendencia 1h desalinhada com direcao = red flag forte
- ADX < 20 com sinal de momentum/tendencia = REJEITAR
- Volume abaixo da media = red flag moderada
- Body ratio fraco (< 0.5) = entrada duvidosa
- Breakout sem volume = falso sinal provavel (REJEITAR)
- Score de confianca do sistema < 60 = cautela extra

## Escala de qualidade

- setup_quality: "A" (excelente - raro), "B" (aceitavel), "C" (fraco), "D" (pessimo)
- entry_quality: "ideal", "acceptable", "late", "poor"
- invalidation_quality: "clear", "acceptable", "unclear", "missing"
"""

    total = state.get("total_trades", 0)
    wins = state.get("wins", 0)
    losses = state.get("losses", 0)
    win_rate = (wins / total * 100) if total > 0 else 0

    consecutive_losses = 0
    for h in reversed(state.get("history", [])):
        if h.get("pnl_pct", 0) < 0:
            consecutive_losses += 1
        else:
            break

    if total > 0:
        base += f"\n## Contexto de performance atual\n"
        base += f"- Win rate: {win_rate:.0f}% ({wins}W/{losses}L de {total} trades)\n"
        base += f"- Perdas consecutivas recentes: {consecutive_losses}\n"

        if consecutive_losses >= 3:
            base += f"\nATENCAO: {consecutive_losses} perdas consecutivas.\n"
            base += "Seja MUITO CONSERVADOR. So aprove sinais com confluencia excepcional.\n"
            base += "Exija confidence minima de 75 para aprovar.\n"
        elif consecutive_losses >= 2:
            base += "\nUltimos 2 trades foram perdas. Seja moderadamente cauteloso.\n"
        elif win_rate > 60 and total >= 5:
            base += "\nBoa performance recente. Mantenha o padrao de qualidade.\n"

    base += """
## Formato de resposta

Responda SOMENTE com um JSON valido, sem markdown, sem texto antes ou depois:

{"approved": false, "confidence": 35, "direction": "none", "setup_quality": "C", "entry_quality": "poor", "invalidation_quality": "unclear", "route": "reject", "thesis": ["fato 1"], "red_flags": ["problema 1", "problema 2"], "reasoning": "explicacao curta e objetiva"}

Regras do JSON:
- "approved": booleano obrigatorio (default: false)
- "confidence": inteiro 0-100 obrigatorio (default: 30 — suba somente com evidencia)
- "direction": "long", "short" ou "none" (VOCE decide a direcao baseado nos dados)
- "setup_quality": "A", "B", "C" ou "D"
- "entry_quality": "ideal", "acceptable", "late" ou "poor"
- "invalidation_quality": "clear", "acceptable", "unclear" ou "missing"
- "route": "scalping", "swing" ou "reject"
- "thesis": lista de strings curtas (maximo 3 itens — fatos que suportam)
- "red_flags": lista de strings curtas (maximo 3 itens — problemas encontrados)
- "reasoning": string curta e objetiva (maximo 200 caracteres)

IMPORTANTE: Comece com "approved": false e "confidence": 30.
So mude para true se encontrar evidencia FORTE e confluente.
Se ha QUALQUER conflito, dado insuficiente, ou regime desfavoravel, rejeite.
Na duvida, SEMPRE rejeite."""

    return base


# Valid values for analyst enum fields
_VALID_SETUP_QUALITY = {"A", "B", "C", "D"}
_VALID_ENTRY_QUALITY = {"ideal", "acceptable", "late", "poor"}
_VALID_INVALIDATION_QUALITY = {"clear", "acceptable", "unclear", "missing"}
_VALID_ROUTES = {"scalping", "swing", "reject"}


def _normalize_analyst_response(raw: dict) -> dict:
    """
    Normalize and validate the analyst Claude response.

    Returns a normalized dict on success.
    Raises ValueError if the response cannot be safely normalized.
    """
    # --- approved (required, bool) ---
    approved = raw.get("approved")
    if approved is None:
        raise ValueError("Campo 'approved' ausente")
    if isinstance(approved, str):
        approved = approved.lower().strip() in ("true", "yes", "sim", "1")
    approved = bool(approved)

    # --- confidence (required, int 0-100) ---
    confidence = raw.get("confidence")
    if confidence is None:
        raise ValueError("Campo 'confidence' ausente")
    try:
        confidence = int(float(confidence))
    except (TypeError, ValueError):
        raise ValueError(f"Campo 'confidence' invalido: {confidence}")
    confidence = max(0, min(100, confidence))

    # --- setup_quality (enum, default "C") ---
    setup_quality = str(raw.get("setup_quality", "C")).strip().upper()
    if setup_quality not in _VALID_SETUP_QUALITY:
        setup_quality = "C"

    # --- entry_quality (enum, default "poor") ---
    entry_quality = str(raw.get("entry_quality", "poor")).strip().lower()
    if entry_quality not in _VALID_ENTRY_QUALITY:
        entry_quality = "poor"

    # --- invalidation_quality (enum, default "unclear") ---
    invalidation_quality = str(raw.get("invalidation_quality", "unclear")).strip().lower()
    if invalidation_quality not in _VALID_INVALIDATION_QUALITY:
        invalidation_quality = "unclear"

    # --- route (enum, default based on approved) ---
    route = str(raw.get("route", "")).strip().lower()
    if route not in _VALID_ROUTES:
        route = "reject" if not approved else "scalping"

    # --- thesis (list of strings, max 3) ---
    thesis = raw.get("thesis", [])
    if isinstance(thesis, str):
        thesis = [thesis]
    if not isinstance(thesis, list):
        thesis = []
    thesis = [str(t).strip()[:150] for t in thesis[:3] if t]

    # --- red_flags (list of strings, max 3) ---
    red_flags = raw.get("red_flags", [])
    if isinstance(red_flags, str):
        red_flags = [red_flags]
    if not isinstance(red_flags, list):
        red_flags = []
    red_flags = [str(r).strip()[:150] for r in red_flags[:3] if r]

    # --- direction (new: Haiku decides direction) ---
    _VALID_DIRECTIONS = {"long", "short", "none"}
    direction = str(raw.get("direction", "none")).strip().lower()
    if direction not in _VALID_DIRECTIONS:
        direction = "none"

    # --- reasoning (string, truncate) ---
    reasoning = str(raw.get("reasoning", "")).strip()[:500]
    if not reasoning:
        reasoning = "Sem justificativa fornecida"

    # --- Cross-validation: reject incoherent responses ---
    if approved and route == "reject":
        approved = False
        reasoning = f"Auto-corrigido: approved=true com route=reject. {reasoning}"

    if approved and direction == "none":
        approved = False
        reasoning = f"Auto-corrigido: approved=true sem direcao definida. {reasoning}"

    if not approved and route in ("scalping", "swing"):
        route = "reject"

    if not approved:
        direction = "none"

    return {
        "approved": approved,
        "confidence": confidence,
        "direction": direction,
        "setup_quality": setup_quality,
        "entry_quality": entry_quality,
        "invalidation_quality": invalidation_quality,
        "route": route,
        "thesis": thesis,
        "red_flags": red_flags,
        "reasoning": reasoning,
    }


def _fallback_analyst_response(reason: str) -> dict:
    """Return a conservative fallback response when Claude fails."""
    return {
        "approved": False,
        "confidence": 0,
        "direction": "none",
        "reasoning": f"Fallback conservador ({reason})",
        "setup_quality": "D",
        "entry_quality": "poor",
        "invalidation_quality": "missing",
        "route": "reject",
        "thesis": [],
        "red_flags": [reason[:150]],
    }


def agent_analyst(signal_data):
    """Agent 1: Validates opportunity using Claude."""
    if not client:
        # Fallback without Claude: reject everything (fail-safe)
        return {
            "approved": False,
            "confidence": 0,
            "direction": "none",
            "reasoning": "Claude indisponivel — rejeicao por seguranca",
            "setup_quality": "D",
            "entry_quality": "poor",
            "invalidation_quality": "missing",
            "route": "reject",
            "thesis": [],
            "red_flags": ["Claude indisponivel"],
        }

    # --- ADX regime classification ---
    adx_value = signal_data.get("adx_1h", 0)
    atr_1h_pct = signal_data.get("atr_1h_pct", 0)
    bb_width_1h = signal_data.get("bb_width_1h", 0)
    if adx_value >= 25:
        regime_label = "TRENDING"
    elif adx_value >= 20:
        regime_label = "WEAK_TREND"
    else:
        regime_label = "RANGING"

    data_text = (
        f"Ativo: {signal_data['symbol']}\n"
        f"Preco: {signal_data['price']:.4f}\n"
        f"\n--- Regime de mercado (1h) ---\n"
        f"ADX(14): {adx_value:.1f} ({regime_label})\n"
        f"ATR(14) 1h: {atr_1h_pct:.2f}%\n"
        f"BB Width 1h: {bb_width_1h:.2f}%\n"
        f"\n--- Indicadores 5m ---\n"
        f"Tendencia 5m: {signal_data['trend']}\n"
        f"RSI: {signal_data['rsi']:.2f} ({signal_data['rsi_status']})\n"
        f"Posicao do preco: {signal_data['price_position']}\n"
        f"Direcao SMAs: {signal_data['sma_9_direction']} / {signal_data['sma_21_direction']}\n"
        f"Breakout: {signal_data['breakout_status']}\n"
        f"Volume acima media: {signal_data['volume_above_avg']}\n"
        f"Body ratio: {signal_data['body_ratio']}\n"
        f"\n--- Contexto 1h ---\n"
        f"Tendencia 1h: {signal_data['htf_trend']}\n"
        f"Alinhado HTF: {signal_data['htf_aligned']}\n"
        f"\n--- Scores do sistema (referencia, NAO instrucao) ---\n"
        f"Buy score: {signal_data['buy_score']} / Sell score: {signal_data['sell_score']}\n"
        f"Confidence score: {signal_data['confidence_score']}/100\n"
    )

    # Add recent trade history for context
    state = load_state()
    if state["history"]:
        recent = state["history"][-5:]
        data_text += f"\nUltimos {len(recent)} trades:\n"
        for h in recent:
            data_text += f"  {h['symbol']} {h['type']} -> {h['pnl_pct']:+.2f}%\n"

    import time as _time
    _t0 = _time.time()
    _fallback_used = False
    _parse_success = True
    _model = "claude-haiku-4-5-20251001"

    try:
        response = client.messages.create(
            model=_model,
            max_tokens=300,
            system=_build_analyst_prompt(state),
            messages=[{"role": "user", "content": data_text}],
        )
        text = response.content[0].text.strip()
        # Remove markdown code blocks if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].strip()
        raw = json.loads(text)
        result = _normalize_analyst_response(raw)
    except json.JSONDecodeError as e:
        print(f"  Erro parse JSON do Analista: {e}")
        _fallback_used = True
        _parse_success = False
        result = _fallback_analyst_response(f"JSON invalido: {e}")
    except ValueError as e:
        print(f"  Erro normalizacao do Analista: {e}")
        _fallback_used = True
        _parse_success = False
        result = _fallback_analyst_response(f"Normalizacao falhou: {e}")
    except Exception as e:
        print(f"  Erro no Agente Analista: {e}")
        _fallback_used = True
        _parse_success = False
        result = _fallback_analyst_response(f"API erro: {e}")

    _latency = (_time.time() - _t0) * 1000
    try:
        db.insert_ai_decision({
            "symbol": signal_data.get("symbol", ""),
            "system": "agent",
            "model": _model,
            "prompt_version": ANALYST_PROMPT_VERSION,
            "latency_ms": round(_latency, 1),
            "fallback_used": _fallback_used,
            "parse_success": _parse_success,
            "approved": result.get("approved", False),
            "confidence": result.get("confidence", 0),
            "reasoning": result.get("reasoning", "")[:500],
        })
    except Exception:
        pass

    return result


# ============================================================
#  AGENTE 2: RISCO (Python)
# ============================================================

def get_atr(symbol, period=14):
    """Calculate ATR for dynamic SL/TP with retry logic."""
    for attempt in range(3):
        try:
            resp = requests.get(
                f"https://api.binance.com/api/v3/klines"
                f"?symbol={symbol}&interval=1h&limit={period + 5}",
                timeout=10,
            )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5))
                time.sleep(retry_after)
                continue
            if resp.status_code != 200:
                time.sleep(2 ** attempt)
                continue

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
        except Exception as e:
            print(f"  [ATR] Tentativa {attempt + 1}/3 falhou para {symbol}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None


def agent_risk(signal_data, analyst_result):
    """Agent 2: Calculates position size, SL, and TP."""
    state = load_state()
    symbol = signal_data["symbol"]
    price = signal_data["price"]
    direction = signal_data["decision"]  # BUY or SELL

    # Check capital
    if state["capital"] <= 0:
        return {
            "approved": False,
            "reason": f"Capital esgotado (${state['capital']:.2f})",
        }

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
    if atr:
        # ATR-based SL (1h): ATR_SL_MULTIPLIER x ATR, minimo de ATR_SL_FLOOR_PCT
        atr_sl_pct = (atr * ATR_SL_MULTIPLIER / price) * 100
        sl_pct = max(atr_sl_pct, ATR_SL_FLOOR_PCT)
    else:
        # Sem ATR disponivel: fallback universal
        sl_pct = ATR_SL_FLOOR_PCT

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
#  EXECUTION POLICY
# ============================================================

def agent_execution_policy(analyst_result, risk_params, state):
    """Evaluate execution eligibility for the agent desk.

    Returns dict with:
        recommended_mode: what the quality gates suggest ("paper" or "real")
        real_eligible: True if both quality gates AND env gate pass
        allowed: whether the trade is allowed at all
        reason: short explanation

    Note: this function evaluates eligibility only. The executor always
    runs in paper mode until a real order-placement path is implemented.
    """
    confidence = analyst_result.get("confidence", 0)
    setup = analyst_result.get("setup_quality", "D")
    entry = analyst_result.get("entry_quality", "poor")
    invalidation = analyst_result.get("invalidation_quality", "missing")

    # Always allowed — policy decides eligibility, not approval
    # (approval was already decided by analyst + risk)

    # Check quality gates for real recommendation
    quality_ok = (
        confidence >= AGENT_REAL_MIN_CONFIDENCE
        and setup in AGENT_REAL_MIN_SETUP_QUALITY
        and entry not in AGENT_REAL_BLOCKED_ENTRY_QUALITY
        and invalidation not in AGENT_REAL_BLOCKED_INVALIDATION_QUALITY
    )

    if quality_ok:
        recommended_mode = "real"
    else:
        recommended_mode = "paper"

    # real_eligible: True only if env gate is explicitly enabled AND quality passes
    if AGENT_REAL_EXECUTION_ENABLED and quality_ok:
        real_eligible = True
        reason = "Gate real habilitado e quality gates passaram"
    elif quality_ok:
        real_eligible = False
        reason = (
            f"Quality gates OK (conf={confidence}, setup={setup}, "
            f"entry={entry}, inv={invalidation}) mas AGENT_REAL_EXECUTION_ENABLED=false"
        )
    else:
        real_eligible = False
        blocks = []
        if confidence < AGENT_REAL_MIN_CONFIDENCE:
            blocks.append(f"conf={confidence}<{AGENT_REAL_MIN_CONFIDENCE}")
        if setup not in AGENT_REAL_MIN_SETUP_QUALITY:
            blocks.append(f"setup={setup}")
        if entry in AGENT_REAL_BLOCKED_ENTRY_QUALITY:
            blocks.append(f"entry={entry}")
        if invalidation in AGENT_REAL_BLOCKED_INVALIDATION_QUALITY:
            blocks.append(f"inv={invalidation}")
        reason = f"Quality gates bloquearam: {', '.join(blocks)}"

    return {
        "recommended_mode": recommended_mode,
        "real_eligible": real_eligible,
        "allowed": True,
        "reason": reason,
    }


# ============================================================
#  AGENTE 3: EXECUTOR (Paper / Real)
# ============================================================

def agent_executor(signal_data, risk_params, analyst_result, policy_result):
    """Agent 3: Executes the trade (paper mode).

    execution_mode always reflects what actually happened (paper).
    recommended_mode captures the policy recommendation for traceability.
    """
    state = load_state()
    symbol = signal_data["symbol"]
    price = signal_data["price"]
    direction = "LONG" if signal_data["decision"] == "BUY" else "SHORT"

    lifecycle_id = str(uuid.uuid4())
    # execution_mode = what actually happened (always paper until real path exists)
    execution_mode = "paper"
    # recommended_mode = what the policy would have allowed
    recommended_mode = policy_result["recommended_mode"]

    # Record position (with lifecycle metadata)
    state["positions"][symbol] = {
        "type": direction,
        "entry_price": price,
        "entry_time": datetime.now().isoformat(),
        "sl_price": risk_params["sl_price"],
        "tp_price": risk_params["tp_price"],
        "position_size_usd": risk_params["position_size_usd"],
        "analyst_confidence": analyst_result.get("confidence", 0),
        "execution_mode": execution_mode,
        "recommended_mode": recommended_mode,
        "lifecycle_id": lifecycle_id,
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
        "execution_mode": execution_mode,
        "recommended_mode": recommended_mode,
        "lifecycle_id": lifecycle_id,
    }
    try:
        log_trade(trade)
    except Exception as db_err:
        print(f"  [ERRO] Falha ao salvar trade no banco: {db_err}")

    lc_short = lifecycle_id[:8]
    return (
        f"[AGENT] {direction} executado [PAPER]: {symbol}\n"
        f"Entrada: {price:.4f}\n"
        f"SL: {risk_params['sl_price']:.4f} (-{risk_params['sl_pct']}%)\n"
        f"TP: {risk_params['tp_price']:.4f} (+{risk_params['tp_pct']}%)\n"
        f"Tamanho: ${risk_params['position_size_usd']:.2f}\n"
        f"Confianca analista: {analyst_result.get('confidence', 0)}/100\n"
        f"Policy: rec={recommended_mode} | exec={execution_mode} | "
        f"LC: {lc_short}\n"
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

        exit_price = price  # default: preco de mercado

        if pos["type"] == "LONG":
            pnl_pct = ((price - entry) / entry) * 100
            if price <= pos["sl_price"]:
                hit = "stop_loss"
                exit_price = pos["sl_price"]
                pnl_pct = -abs(((entry - pos["sl_price"]) / entry) * 100)
            elif price >= pos["tp_price"]:
                hit = "take_profit"
                exit_price = pos["tp_price"]
                pnl_pct = abs(((pos["tp_price"] - entry) / entry) * 100)
        else:
            pnl_pct = ((entry - price) / entry) * 100
            if price >= pos["sl_price"]:
                hit = "stop_loss"
                exit_price = pos["sl_price"]
                pnl_pct = -abs(((pos["sl_price"] - entry) / entry) * 100)
            elif price <= pos["tp_price"]:
                hit = "take_profit"
                exit_price = pos["tp_price"]
                pnl_pct = abs(((entry - pos["tp_price"]) / entry) * 100)

        # Exit on strong opposite signal only (confidence > 70 or score diff >= 3)
        if hit is None:
            is_opposite = (
                (pos["type"] == "LONG" and result["decision"] == "SELL") or
                (pos["type"] == "SHORT" and result["decision"] == "BUY")
            )
            if is_opposite:
                confidence = result.get("confidence_score", 0)
                score_diff = result.get("score_difference", 0)
                if confidence > 70 or score_diff >= 3:
                    hit = "opposite_signal"

        if hit:
            pnl_pct -= ROUND_TRIP_FEE_PCT  # Descontar fees
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

            pos_exec_mode = pos.get("execution_mode", "paper")
            pos_rec_mode = pos.get("recommended_mode", "paper")
            pos_lifecycle_id = pos.get("lifecycle_id")

            trade = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "type": pos["type"],
                "entry_price": entry,
                "sl_price": pos["sl_price"],
                "tp_price": pos["tp_price"],
                "position_size_usd": pos["position_size_usd"],
                "exit_price": exit_price,
                "pnl_pct": round(pnl_pct, 4),
                "pnl_usd": pnl_usd,
                "exit_reason": hit,
                "analyst_confidence": pos.get("analyst_confidence", 0),
                "capital_after": state["capital"],
                "execution_mode": pos_exec_mode,
                "recommended_mode": pos_rec_mode,
                "lifecycle_id": pos_lifecycle_id,
            }
            try:
                log_trade(trade)
            except Exception as db_err:
                print(f"  [ERRO] Falha ao salvar trade no banco: {db_err}")

            lc_short = pos_lifecycle_id[:8] if pos_lifecycle_id else "?"
            msg = (
                f"[AGENT] {pos['type']} fechado [PAPER]: {symbol}\n"
                f"Entrada: {entry:.4f} | Saida: {exit_price:.4f}\n"
                f"P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
                f"Motivo: {hit} | rec={pos_rec_mode} | LC: {lc_short}\n"
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

def orchestrate(results, open_new=True):
    """Main orchestrator: runs the 3-agent pipeline for each signal."""
    messages = []

    # Step 0: check existing positions for SL/TP (always runs)
    exit_msgs = check_agent_positions(results)
    messages.extend(exit_msgs)

    if not open_new:
        return messages

    # Rejection rate tracking
    _signals_evaluated = 0
    _signals_rejected_analyst = 0
    _signals_rejected_risk = 0
    _signals_executed = 0

    # Step 1-3: process new signals
    for result in results:
        if result["decision"] not in ["BUY", "SELL"]:
            continue

        _signals_evaluated += 1
        symbol = result["symbol"]
        print(f"\n  [ORQUESTRADOR] Processando sinal {result['decision']} em {symbol}...")

        # AGENT 1: Analyst
        print(f"  [AGENTE 1] Analisando {symbol}...")
        analyst = agent_analyst(result)

        # --- Regime-aware confidence threshold ---
        analyst_confidence = analyst.get("confidence", 50)
        adx = result.get("adx_1h", 0)
        if adx < 20:
            min_confidence = 85  # RANGING: only exceptional setups
        elif adx < 25:
            min_confidence = 80  # WEAK_TREND: high bar
        else:
            min_confidence = 75  # TRENDING: standard threshold (was 60)

        if analyst["approved"] and analyst_confidence < min_confidence:
            analyst["approved"] = False
            analyst["direction"] = "none"
            analyst["reasoning"] = (
                f"Auto-rejeitado: confianca {analyst_confidence} < {min_confidence} "
                f"(regime ADX={adx:.0f}). Original: {analyst.get('reasoning', '')}"
            )
            print(f"  [THRESHOLD] Rejeitado: conf {analyst_confidence} < {min_confidence} (ADX={adx:.0f})")

        # --- Direction consistency: Haiku's direction must match system signal ---
        haiku_dir = analyst.get("direction", "none")
        system_decision = result.get("decision", "HOLD")
        if analyst["approved"] and haiku_dir != "none":
            expected_dir = "long" if system_decision == "BUY" else "short" if system_decision == "SELL" else "none"
            if haiku_dir != expected_dir and expected_dir != "none":
                analyst["approved"] = False
                analyst["direction"] = "none"
                analyst["reasoning"] = (
                    f"Auto-rejeitado: Haiku sugere {haiku_dir.upper()} mas sistema propoe {system_decision}. "
                    f"Divergencia = sinal fraco. Original: {analyst.get('reasoning', '')}"
                )
                print(f"  [DIVERGENCIA] Rejeitado: Haiku={haiku_dir} vs sistema={system_decision}")

        print(f"  [AGENTE 1] Aprovado: {analyst['approved']} | Dir: {analyst.get('direction', '?')} | Conf: {analyst.get('confidence', 0)} | Regime: {result.get('regime_label', '?')} (ADX={adx:.0f})")
        print(f"  [AGENTE 1] Razao: {analyst.get('reasoning', '')}")

        if not analyst["approved"]:
            _signals_rejected_analyst += 1
            messages.append(
                f"[AGENT] Sinal {result['decision']} em {symbol} REJEITADO pelo Analista "
                f"(conf={analyst.get('confidence', 0)}, dir={analyst.get('direction', '?')})\n"
                f"Razao: {analyst.get('reasoning', 'N/A')}"
            )
            continue

        # AGENT 2: Risk
        print(f"  [AGENTE 2] Calculando risco para {symbol}...")
        risk = agent_risk(result, analyst)
        print(f"  [AGENTE 2] Aprovado: {risk['approved']}")

        if not risk["approved"]:
            _signals_rejected_risk += 1
            messages.append(
                f"[AGENT] Sinal {result['decision']} em {symbol} BLOQUEADO pelo Risco\n"
                f"Razao: {risk.get('reason', 'N/A')}"
            )
            continue

        print(f"  [AGENTE 2] Size: ${risk['position_size_usd']} | SL: {risk['sl_pct']}% | TP: {risk['tp_pct']}%")

        # EXECUTION POLICY
        state = load_state()
        policy = agent_execution_policy(analyst, risk, state)
        print(
            f"  [POLICY] rec={policy['recommended_mode']} | "
            f"eligible={policy['real_eligible']} | {policy['reason']}"
        )

        # AGENT 3: Executor (always paper until real path exists)
        print(f"  [AGENTE 3] Executando trade em paper...")
        exec_msg = agent_executor(result, risk, analyst, policy)
        messages.append(exec_msg)
        _signals_executed += 1
        print(f"  [AGENTE 3] Trade executado com sucesso")

    # --- Rejection rate summary ---
    if _signals_evaluated > 0:
        rejection_rate = ((_signals_rejected_analyst + _signals_rejected_risk) / _signals_evaluated) * 100
        print(f"\n  {'='*50}")
        print(f"  [AGENT] TAXA DE REJEICAO: {rejection_rate:.0f}% ({_signals_rejected_analyst + _signals_rejected_risk}/{_signals_evaluated})")
        print(f"    Avaliados: {_signals_evaluated} | Rejeitados analista: {_signals_rejected_analyst} | Rejeitados risco: {_signals_rejected_risk} | Executados: {_signals_executed}")
        print(f"  {'='*50}")

    return messages


# ============================================================
#  VALIDACAO SCALPING (chamado pelo scalping_trader)
# ============================================================

SCALPING_VALIDATION_PROMPT = """Voce e um validador rapido de trade de scalping.
Recebe dados de confluencia de 3 motores de sinal.
Responda SOMENTE com JSON: {"approved": true/false, "reason": "motivo curto"}
Aprove se a confluencia faz sentido. Rejeite se ha risco claro."""


def validate_scalping_signal(symbol, direction, score, reason, best_signal_source):
    """Quick Claude validation for borderline scalping signals (score 2/3)."""
    if not client:
        return False, "Claude indisponivel, trade rejeitado (fail-safe)"

    data_text = (
        f"Ativo: {symbol}\n"
        f"Direcao: {direction}\n"
        f"Confluencia: {score}/3\n"
        f"Motores ativos: {reason}\n"
        f"Motor principal: {best_signal_source}\n"
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            system=SCALPING_VALIDATION_PROMPT,
            messages=[{"role": "user", "content": data_text}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].strip()
        result = json.loads(text)
        return result.get("approved", True), result.get("reason", "")
    except Exception as e:
        print(f"  [SCALPING VALIDATION] Erro: {e}")
        return False, f"Fallback rejeitado (fail-safe): {e}"


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
