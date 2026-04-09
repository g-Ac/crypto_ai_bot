"""
Sistema de Confluencia V2 -- combina os 3 motores de microestrutura.

Motores:
  M1: FundingEngine    (Funding Rate + L/S Ratio)
  M2: LiquidationEngine (Liquidation Cascade + OI Divergence)
  M3: BasisEngine       (Basis Spread + Session Timing)

Cada motor que confirma a mesma direcao = +1 ponto.
  - 1/3: nao operar
  - 2/3: 50% do tamanho maximo, alavancagem 3x
  - 3/3: 100% do tamanho maximo, alavancagem 5x

Sinais opostos entre motores = nao operar (mercado indeciso).

O regime gate controla quais motores rodam:
  TRENDING:   M1 + M2 + M3
  WEAK_TREND: M1 + M3
  VOLATILE:   M2
  RANGING:    M1 + M3
  CHOPPY:     NENHUM (nao operar)
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from signal_types import Direction, Signal, ConfluenceResult, ScalpingConfig
from funding_engine import FundingEngine
from liquidation_engine import LiquidationEngine
from basis_engine import BasisEngine
from execution_layer import calculate_levels, apply_to_signal

logger = logging.getLogger("scalping.confluence")

# Motor instances (stateless, safe to reuse)
_funding_engine = FundingEngine()
_liquidation_engine = LiquidationEngine()
_basis_engine = BasisEngine()

# Regime -> allowed motors
_REGIME_MOTORS: Dict[str, List[str]] = {
    "TRENDING":   ["M1", "M2", "M3"],
    "WEAK_TREND": ["M1", "M3"],
    "VOLATILE":   ["M2"],
    "RANGING":    ["M1", "M3"],
    "CHOPPY":     [],
    "UNKNOWN":    ["M1", "M3"],  # conservative default
}


def _select_best_signal(signals: List[Signal]) -> Optional[Signal]:
    """Seleciona o melhor sinal entre os validos (maior score, depois maior strength)."""
    valid = [s for s in signals if s.valid]
    if not valid:
        return None
    valid.sort(
        key=lambda s: (s.metadata.get("score_total", s.metadata.get("total_score", 0)), s.strength),
        reverse=True,
    )
    return valid[0]


def analyze(
    symbol: str,
    config: ScalpingConfig,
    market_data: Optional[Dict] = None,
    regime: str = "UNKNOWN",
    candles_5m: Optional[pd.DataFrame] = None,
    prev_basis_pct: Optional[float] = None,
) -> ConfluenceResult:
    """Executa motores permitidos pelo regime e calcula confluencia.

    Args:
        symbol: par de trading
        config: configuracao da estrategia
        market_data: retorno de collect_microstructure() (obrigatorio para V2)
        regime: regime de mercado do regime gate
        candles_5m: DataFrame OHLCV 5m para Motor 2 (VWAP/range)
        prev_basis_pct: basis anterior para Motor 3 (velocidade)

    Returns:
        ConfluenceResult com score 0-3, direcao e continuous_score
    """
    no_trade = ConfluenceResult(
        direction=Direction.NEUTRAL,
        score=0,
        meets_threshold=False,
        reason="Confluencia insuficiente",
    )

    # ── REGIME GATE ──────────────────────────────────────────────
    allowed = _REGIME_MOTORS.get(regime, _REGIME_MOTORS["UNKNOWN"])

    if not allowed:
        no_trade.reason = f"Regime {regime}: nenhum motor permitido"
        logger.info("CONFLUENCE %s: %s", symbol, no_trade.reason)
        return no_trade

    if market_data is None:
        no_trade.reason = "Microstructure data indisponivel"
        logger.warning("CONFLUENCE %s: %s", symbol, no_trade.reason)
        return no_trade

    # ── EXECUTAR MOTORES PERMITIDOS ──────────────────────────────
    signals: List[Signal] = []
    motor_labels = []

    if "M1" in allowed:
        sig_m1 = _funding_engine.analyze(symbol, market_data, regime)
        signals.append(sig_m1)
        motor_labels.append(
            f"M1={sig_m1.direction.value}({'OK' if sig_m1.valid else 'X'})"
        )
    else:
        motor_labels.append("M1=SKIP")

    if "M2" in allowed:
        sig_m2 = _liquidation_engine.analyze(symbol, market_data, regime, candles_5m)
        signals.append(sig_m2)
        motor_labels.append(
            f"M2={sig_m2.direction.value}({'OK' if sig_m2.valid else 'X'})"
        )
    else:
        motor_labels.append("M2=SKIP")

    if "M3" in allowed:
        sig_m3 = _basis_engine.analyze(symbol, market_data, regime, prev_basis_pct=prev_basis_pct)
        signals.append(sig_m3)
        motor_labels.append(
            f"M3={sig_m3.direction.value}({'OK' if sig_m3.valid else 'X'})"
        )
    else:
        motor_labels.append("M3=SKIP")

    logger.info("CONFLUENCE %s [%s]: %s", symbol, regime, " | ".join(motor_labels))

    valid_signals = [s for s in signals if s.valid]

    if not valid_signals:
        no_trade.signals = signals
        no_trade.reason = f"Nenhum motor gerou sinal valido ({regime})"
        logger.info("CONFLUENCE %s: %s", symbol, no_trade.reason)
        return no_trade

    # ── CONTAR SINAIS POR DIRECAO ────────────────────────────────
    long_count = sum(1 for s in valid_signals if s.direction == Direction.LONG)
    short_count = sum(1 for s in valid_signals if s.direction == Direction.SHORT)

    if long_count > 0 and short_count > 0:
        no_trade.signals = signals
        no_trade.reason = f"Sinais opostos: {long_count} LONG vs {short_count} SHORT (indeciso)"
        logger.warning("CONFLUENCE %s: %s", symbol, no_trade.reason)
        return no_trade

    if long_count > short_count:
        direction = Direction.LONG
        score = long_count
    elif short_count > long_count:
        direction = Direction.SHORT
        score = short_count
    else:
        no_trade.signals = signals
        no_trade.reason = "Sem direcao dominante"
        return no_trade

    # ── CONTINUOUS SCORE (media ponderada dos motores ativos) ────
    same_dir = [s for s in valid_signals if s.direction == direction]
    motor_scores = []
    for s in same_dir:
        ms = s.metadata.get("score_total", s.metadata.get("total_score", 0))
        motor_scores.append(ms)
    continuous_score = int(sum(motor_scores) / len(motor_scores)) if motor_scores else 0

    # ── SIZING ───────────────────────────────────────────────────
    best_signal = _select_best_signal(same_dir)
    n_motors = len(allowed)

    # Regra de confluencia adaptativa:
    #   3 motores ativos -> minimo 2 confirmacoes
    #   2 motores ativos -> minimo 2 confirmacoes
    #   1 motor  ativo   -> minimo 1, mas continuous_score >= 60
    if n_motors >= 2:
        min_confirmations = 2
    else:
        min_confirmations = 1

    if score < min_confirmations:
        no_trade.signals = signals
        no_trade.score = score
        no_trade.reason = (
            f"Confluencia {score}/{n_motors} - insuficiente "
            f"(minimo {min_confirmations})"
        )
        logger.info("CONFLUENCE %s: %s", symbol, no_trade.reason)
        return no_trade

    # Single-motor regime (e.g. VOLATILE): exigir score alto
    if n_motors == 1 and continuous_score < 60:
        no_trade.signals = signals
        no_trade.score = score
        no_trade.reason = (
            f"Motor unico ({regime}): continuous_score {continuous_score} < 60"
        )
        logger.info("CONFLUENCE %s: %s", symbol, no_trade.reason)
        return no_trade

    if score >= 3:
        position_size_pct = 100.0
        leverage = 5
        classification = "ALTO"
    elif score >= 2:
        position_size_pct = 50.0
        leverage = 3
        classification = "MEDIO"
    else:
        # Single motor with high score -> conservative sizing
        position_size_pct = 30.0
        leverage = 2
        classification = "SOLO"

    # Se chegou aqui, o trade passou pelo gate adaptativo (multi-motor
    # exige >= 2, single-motor exige >= 1 + continuous_score >= 60).
    meets_threshold = True

    # ── EXECUTION LAYER: calcular entry/SL/TP via ATR ───────────
    if best_signal is not None and candles_5m is not None:
        exec_plan = calculate_levels(
            signal=best_signal,
            candles_5m=candles_5m,
            direction=direction,
            score=continuous_score,
        )
        if exec_plan is not None:
            apply_to_signal(best_signal, exec_plan)
        else:
            logger.warning(
                "CONFLUENCE %s: execution layer falhou, best_signal sem niveis",
                symbol,
            )

    motor_status = " | ".join(motor_labels)
    reason = (
        f"Confluencia {classification} ({score}/{len(allowed)} {direction.value}) | "
        f"{motor_status} | "
        f"Cont.score: {continuous_score} | "
        f"Size: {position_size_pct:.0f}% | Leverage: {leverage}x"
    )

    logger.info("CONFLUENCE %s: %s", symbol, reason)

    return ConfluenceResult(
        direction=direction,
        score=score,
        meets_threshold=meets_threshold,
        signals=signals,
        position_size_pct=position_size_pct,
        leverage=leverage,
        reason=reason,
        best_signal=best_signal,
    )
