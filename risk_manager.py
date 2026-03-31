"""
Risk Manager para a estrategia de scalping.

Responsabilidades:
- Position sizing baseado em 2% de risco do capital
- Cooldown de 3 candles no TF de entrada apos fechar posicao
- Verificacao de funding rate antes de abrir posicao
- Verificacao de ATR elevado (> 50% vs media)
- Verificacao de BB bandwidth global no 15m (< 1.2% = nao operar)
- Distancia maxima de SL por abordagem
"""
import json
import os
import tempfile
import logging
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd
import requests

from signal_types import (
    Direction, ConfluenceResult, RiskDecision, ScalpingConfig,
)
from scalping_data import get_funding_rate
from news_filter import is_near_news_event

logger = logging.getLogger("scalping.risk")

# Arquivo de estado do scalping trader
SCALPING_STATE_FILE = "scalping_state.json"


# ============================================================
#  STATE MANAGEMENT
# ============================================================

def load_scalping_state() -> dict:
    """Carrega o estado do scalping trader do disco."""
    if not os.path.exists(SCALPING_STATE_FILE):
        return {
            "capital": 10000.0,
            "positions": {},
            "cooldowns": {},       # symbol -> {"last_close_time": iso, "candles_remaining": int}
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl_usd": 0.0,
            "history": [],
        }
    with open(SCALPING_STATE_FILE, "r") as f:
        return json.load(f)


def save_scalping_state(state: dict) -> None:
    """Salva o estado do scalping trader no disco de forma atomica."""
    data = json.dumps(state, indent=2, default=str)
    dir_name = os.path.dirname(os.path.abspath(SCALPING_STATE_FILE))
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as f:
        f.write(data)
        tmp_path = f.name
    os.replace(tmp_path, SCALPING_STATE_FILE)


# ============================================================
#  COOLDOWN MANAGEMENT
# ============================================================

def update_cooldown_on_close(state: dict, symbol: str, config: ScalpingConfig) -> None:
    """Registra cooldown apos fechar posicao em um par."""
    state.setdefault("cooldowns", {})[symbol] = {
        "last_close_time": datetime.now().isoformat(),
        "candles_remaining": config.cooldown_candles,
    }
    logger.info(
        "COOLDOWN ativado: %s - %d candles restantes",
        symbol, config.cooldown_candles
    )


def tick_cooldown(state: dict, symbol: str) -> None:
    """Decrementa o contador de cooldown em 1 candle. Chamar a cada candle fechado."""
    cooldowns = state.get("cooldowns", {})
    if symbol in cooldowns:
        cooldowns[symbol]["candles_remaining"] -= 1
        if cooldowns[symbol]["candles_remaining"] <= 0:
            del cooldowns[symbol]
            logger.info("COOLDOWN expirado: %s", symbol)


def is_in_cooldown(state: dict, symbol: str) -> bool:
    """Verifica se o par esta em cooldown."""
    cooldowns = state.get("cooldowns", {})
    if symbol not in cooldowns:
        return False
    return cooldowns[symbol].get("candles_remaining", 0) > 0


# ============================================================
#  RISK CHECKS
# ============================================================

def check_atr_elevated(df_15m: pd.DataFrame, threshold_pct: float = 50.0) -> bool:
    """
    Verifica se o ATR atual esta elevado em relacao a media de 20 periodos.

    Retorna True se ATR subiu > threshold_pct% vs media.
    """
    if df_15m is None or "atr14" not in df_15m.columns or len(df_15m) < 21:
        return False

    current_atr = df_15m["atr14"].iloc[-2]  # ultimo candle fechado
    atr_mean_20 = df_15m["atr14"].iloc[-22:-2].mean()

    if atr_mean_20 == 0:
        return False

    elevation_pct = ((current_atr - atr_mean_20) / atr_mean_20) * 100

    if elevation_pct > threshold_pct:
        logger.warning(
            "ATR elevado: atual=%.6f, media_20=%.6f, elevacao=%.1f%%",
            current_atr, atr_mean_20, elevation_pct
        )
        return True

    return False


def check_bb_bandwidth_low(df_15m: pd.DataFrame, min_bandwidth_pct: float = 1.2) -> bool:
    """
    Verifica se o BB bandwidth no 15m esta abaixo do minimo.

    Retorna True se bandwidth < min_bandwidth_pct% (mercado lateral, nao operar).
    """
    if df_15m is None or "bb_bandwidth" not in df_15m.columns or len(df_15m) < 2:
        return False

    # bb_bandwidth da lib ta retorna como fator, converter para %
    bandwidth = df_15m["bb_bandwidth"].iloc[-2]
    bb_middle = df_15m["bb_middle"].iloc[-2]

    if bb_middle == 0:
        return False

    # bandwidth ja e (upper - lower) / middle, converter para %
    bandwidth_pct = bandwidth * 100

    if bandwidth_pct < min_bandwidth_pct:
        logger.warning(
            "BB bandwidth 15m baixo: %.2f%% < %.2f%% minimo",
            bandwidth_pct, min_bandwidth_pct
        )
        return True

    return False


def check_funding_rate(
    symbol: str,
    direction: Direction,
    threshold: float = 0.05,
) -> tuple:
    """
    Verifica funding rate e retorna (rate, should_reduce, should_skip).

    Se |funding| > threshold e direcao contra o funding:
    - Reduzir tamanho em 50%
    Se |funding| > threshold * 2: pular trade.
    """
    rate = get_funding_rate(symbol)

    if rate is None:
        logger.info("Funding rate indisponivel para %s, prosseguindo", symbol)
        return 0.0, False, False

    abs_rate = abs(rate)

    if abs_rate <= threshold:
        return rate, False, False

    # Funding positivo alto = longs pagam shorts
    # Se estamos LONG com funding positivo alto: contra nos
    against_us = (
        (direction == Direction.LONG and rate > 0) or
        (direction == Direction.SHORT and rate < 0)
    )

    if not against_us:
        logger.info(
            "Funding rate %.4f%% a favor da direcao %s", rate, direction.value
        )
        return rate, False, False

    if abs_rate > threshold * 2:
        logger.warning(
            "SKIP: Funding rate %.4f%% muito alto contra %s",
            rate, direction.value
        )
        return rate, False, True

    logger.warning(
        "REDUZIR: Funding rate %.4f%% contra %s, reduzindo posicao 50%%",
        rate, direction.value
    )
    return rate, True, False


# ============================================================
#  POSITION SIZING
# ============================================================

def calculate_position_size(
    capital: float,
    risk_pct: float,
    entry_price: float,
    sl_price: float,
    leverage: int = 1,
) -> float:
    """
    Calcula tamanho da posicao baseado em risco fixo de 2% do capital.

    Formula: position_size = (capital * risk_pct / 100) / (|entry - sl| / entry)
    Ajustado pela alavancagem.
    """
    if entry_price == 0 or sl_price == 0:
        return 0.0

    sl_distance_pct = abs(entry_price - sl_price) / entry_price
    if sl_distance_pct == 0:
        return 0.0

    risk_amount = capital * (risk_pct / 100)
    position_size_usd = risk_amount / sl_distance_pct

    # Com alavancagem, a margem necessaria e menor
    margin_required = position_size_usd / leverage

    # Nao pode exceder o capital disponivel
    max_margin = capital * 0.5  # no maximo 50% do capital em margem
    if margin_required > max_margin:
        position_size_usd = max_margin * leverage

    logger.info(
        "Position size: $%.2f (risco: $%.2f, SL dist: %.2f%%, alavancagem: %dx)",
        position_size_usd, risk_amount, sl_distance_pct * 100, leverage
    )

    return round(position_size_usd, 2)


# ============================================================
#  CAPITAL VERIFICATION
# ============================================================

BINANCE_FUTURES_BALANCE_URL = "https://fapi.binance.com/fapi/v2/balance"


def fetch_exchange_balance(api_key: str, api_secret: str) -> Optional[float]:
    """
    Busca saldo USDT da carteira de futuros na Binance.

    Requer autenticacao HMAC. Retorna None em caso de erro.
    Preparado para uso futuro com chaves reais.
    """
    import hmac
    import hashlib
    import time

    try:
        timestamp = int(time.time() * 1000)
        query_string = f"timestamp={timestamp}"
        signature = hmac.new(
            api_secret.encode(), query_string.encode(), hashlib.sha256
        ).hexdigest()

        headers = {"X-MBX-APIKEY": api_key}
        params = {"timestamp": timestamp, "signature": signature}

        resp = requests.get(
            BINANCE_FUTURES_BALANCE_URL,
            headers=headers,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()

        for asset in resp.json():
            if asset.get("asset") == "USDT":
                return float(asset.get("availableBalance", 0))

        logger.warning("USDT nao encontrado no retorno da API de balance")
        return None
    except Exception as e:
        logger.error("Erro ao buscar saldo da exchange: %s", e)
        return None


def check_capital_sufficient(
    state: dict,
    config: ScalpingConfig,
) -> Tuple[bool, float, str]:
    """
    Verifica se o capital e suficiente para operar.

    Em paper_mode, usa o capital interno do state.
    Em modo real, tenta buscar o saldo da exchange (futuro).

    Retorna (ok, capital_atual, motivo).
    """
    capital = state.get("capital", config.initial_capital)

    if not config.paper_mode:
        # Modo real: buscar saldo da exchange
        # Requer API keys configuradas via env vars
        api_key = os.environ.get("BINANCE_API_KEY", "")
        api_secret = os.environ.get("BINANCE_API_SECRET", "")

        if api_key and api_secret:
            exchange_balance = fetch_exchange_balance(api_key, api_secret)
            if exchange_balance is not None:
                capital = exchange_balance
                logger.info("Saldo exchange USDT: $%.2f", capital)
            else:
                logger.warning(
                    "Nao foi possivel obter saldo da exchange, usando capital interno: $%.2f",
                    capital,
                )
        else:
            logger.warning(
                "API keys nao configuradas para modo real, usando capital interno: $%.2f",
                capital,
            )

    if capital < config.min_capital:
        reason = (
            f"Capital insuficiente: ${capital:.2f} < "
            f"minimo ${config.min_capital:.2f}"
        )
        logger.warning("BLOQUEADO: %s", reason)
        return False, capital, reason

    return True, capital, ""


# ============================================================
#  MAIN RISK EVALUATION
# ============================================================

def evaluate_risk(
    confluence: ConfluenceResult,
    symbol: str,
    config: ScalpingConfig,
    df_15m: Optional[pd.DataFrame] = None,
) -> RiskDecision:
    """
    Avaliacao completa de risco para uma oportunidade de scalping.

    Verifica todas as condicoes do risk manager:
    0. Capital minimo
    1. Confluencia minima (score >= 2)
    2. Cooldown por par
    3. Maximo de posicoes
    4. Ja tem posicao no mesmo par
    5. Filtro de noticias/eventos economicos
    6. BB bandwidth global 15m
    7. ATR elevado
    8. Funding rate
    9. Distancia maxima SL
    10. RR minimo
    11. Position sizing
    """
    state = load_scalping_state()

    # 0. Verificacao de capital minimo
    capital_ok, capital, capital_reason = check_capital_sufficient(state, config)
    if not capital_ok:
        return RiskDecision(approved=False, reason=capital_reason)

    # 1. Confluencia minima
    if not confluence.meets_threshold:
        return RiskDecision(
            approved=False,
            reason=f"Confluencia insuficiente: {confluence.score}/3 (minimo: {config.min_confluence_score})"
        )

    direction = confluence.direction
    best_signal = confluence.best_signal

    if best_signal is None or direction == Direction.NEUTRAL:
        return RiskDecision(
            approved=False,
            reason="Sem sinal valido ou direcao neutra"
        )

    # 2. Cooldown
    if is_in_cooldown(state, symbol):
        cooldown_info = state["cooldowns"].get(symbol, {})
        remaining = cooldown_info.get("candles_remaining", 0)
        return RiskDecision(
            approved=False,
            reason=f"Cooldown ativo: {remaining} candles restantes para {symbol}",
            in_cooldown=True
        )

    # 3. Maximo de posicoes
    open_positions = len(state.get("positions", {}))
    if open_positions >= config.max_positions:
        return RiskDecision(
            approved=False,
            reason=f"Maximo de {config.max_positions} posicoes atingido ({open_positions} abertas)"
        )

    # 4. Ja tem posicao no mesmo par
    if symbol in state.get("positions", {}):
        return RiskDecision(
            approved=False,
            reason=f"Ja existe posicao aberta em {symbol}"
        )

    # 5. Filtro de noticias/eventos economicos
    if config.news_filter_enabled:
        near_news, news_reason = is_near_news_event(
            minutes_before=config.news_minutes_before,
            minutes_after=config.news_minutes_after,
        )
        if near_news:
            return RiskDecision(
                approved=False,
                reason=f"Bloqueado por evento economico: {news_reason}",
                near_news_event=True
            )

    # 6. BB bandwidth global 15m
    bb_low = False
    if df_15m is not None:
        bb_low = check_bb_bandwidth_low(df_15m, config.bb_bandwidth_min_15m)
        if bb_low:
            return RiskDecision(
                approved=False,
                reason=f"BB bandwidth 15m abaixo de {config.bb_bandwidth_min_15m}% - mercado lateral",
                bb_bandwidth_low=True
            )

    # 7. ATR elevado
    atr_elevated = False
    if df_15m is not None:
        atr_elevated = check_atr_elevated(df_15m, config.atr_elevation_threshold)
        if atr_elevated:
            return RiskDecision(
                approved=False,
                reason="ATR elevado > 50% vs media 20 periodos - volatilidade excessiva",
                atr_elevated=True
            )

    # 8. Funding rate
    funding_rate, should_reduce, should_skip = check_funding_rate(
        symbol, direction, config.funding_rate_threshold
    )
    if should_skip:
        return RiskDecision(
            approved=False,
            reason=f"Funding rate muito alto ({funding_rate:.4f}%) contra direcao {direction.value}",
            funding_rate=funding_rate
        )

    # 9. Verificar distancia maxima do SL
    sl_price = best_signal.sl_price
    entry_price = best_signal.entry_price
    sl_distance_pct = best_signal.sl_distance_pct

    max_sl_map = {
        "volume_breakout": config.max_sl_volume_breakout,
        "rsi_bb_reversal": config.max_sl_rsi_bb,
        "ema_crossover": config.max_sl_ema_crossover,
    }
    max_sl = max_sl_map.get(best_signal.source, 0.8)

    if sl_distance_pct > max_sl:
        return RiskDecision(
            approved=False,
            reason=(
                f"SL muito distante: {sl_distance_pct:.2f}% > "
                f"maximo {max_sl:.1f}% para {best_signal.source}"
            )
        )

    # 10. Verificar RR minimo
    min_rr_map = {
        "volume_breakout": config.min_rr_volume_breakout,
        "rsi_bb_reversal": config.min_rr_rsi_bb,
        "ema_crossover": config.min_rr_ema_crossover,
    }
    min_rr = min_rr_map.get(best_signal.source, 1.5)

    if best_signal.rr_ratio < min_rr:
        return RiskDecision(
            approved=False,
            reason=(
                f"RR insuficiente: {best_signal.rr_ratio:.2f} < "
                f"minimo {min_rr:.1f} para {best_signal.source}"
            )
        )

    # 11. Position sizing
    leverage = confluence.leverage
    position_size_pct = confluence.position_size_pct

    position_size = calculate_position_size(
        capital=capital,
        risk_pct=config.max_risk_pct,
        entry_price=entry_price,
        sl_price=sl_price,
        leverage=leverage,
    )

    # Ajustar pelo % de confluencia (50% ou 100%)
    position_size = position_size * (position_size_pct / 100)

    # Reduzir por funding rate se necessario
    if should_reduce:
        position_size *= (1 - config.funding_rate_reduce_pct / 100)
        logger.warning(
            "Posicao reduzida por funding rate: $%.2f (-%d%%)",
            position_size, int(config.funding_rate_reduce_pct)
        )

    risk_amount = capital * (config.max_risk_pct / 100) * (position_size_pct / 100)

    logger.info(
        "APROVADO: %s %s | Size: $%.2f | SL: %.6f | Leverage: %dx | RR: %.2f",
        direction.value, symbol, position_size, sl_price, leverage,
        best_signal.rr_ratio
    )

    return RiskDecision(
        approved=True,
        reason=f"Trade aprovado: {direction.value} {symbol} | Confluencia {confluence.score}/3",
        position_size_usd=position_size,
        sl_price=sl_price,
        tp1_price=best_signal.tp1_price,
        tp2_price=best_signal.tp2_price,
        leverage=leverage,
        risk_amount_usd=round(risk_amount, 2),
        funding_rate=funding_rate,
        atr_elevated=atr_elevated,
        bb_bandwidth_low=bb_low,
        in_cooldown=False,
    )
