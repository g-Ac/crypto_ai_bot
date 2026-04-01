"""
Scalping Trader -- modulo integrador que executa a estrategia completa.

Conecta confluencia + risk manager + gerenciamento de posicoes.
Chamado pelo main.py a cada ciclo de analise.

Fluxo:
1. Buscar dados OHLCV multi-timeframe
2. Executar confluencia (3 motores)
3. Avaliar risco (risk manager)
4. Abrir/gerenciar posicoes (paper mode)
5. Retornar mensagens para Telegram
"""
import logging
from datetime import datetime
from typing import List, Optional

import pandas as pd
import database as db

from config import SCALPING_INITIAL_CAPITAL
from signal_types import ConfluenceResult, RiskDecision, ScalpingConfig
from scalping_data import fetch_candles, add_scalping_indicators, clear_cache
from confluence import analyze as confluence_analyze
from risk_manager import (
    load_scalping_state, save_scalping_state,
    calculate_position_size,
    evaluate_risk, tick_cooldown, update_cooldown_on_close,
    is_in_cooldown,
)
from runtime_config import (
    SCALPING_AUDIT_ENABLED,
    SCALPING_DISABLE_AI_GATE,
    SCALPING_DISABLE_COOLDOWN,
    SCALPING_EXPERIMENTAL_FORCE_ENTRIES,
    SCALPING_FORCE_LEVERAGE,
    SCALPING_FORCE_POSITION_SIZE_PCT,
    SCALPING_IGNORE_RISK_FILTERS,
    SCALPING_MAX_POSITIONS_OVERRIDE,
)

logger = logging.getLogger("scalping.trader")

# Configuracao padrao
CONFIG = ScalpingConfig(initial_capital=float(SCALPING_INITIAL_CAPITAL))
if SCALPING_MAX_POSITIONS_OVERRIDE > 0:
    CONFIG.max_positions = SCALPING_MAX_POSITIONS_OVERRIDE


def _safe_round(value, digits=6):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _signal_to_dict(signal) -> dict:
    if signal is None:
        return {}
    return {
        "source": signal.source,
        "valid": bool(signal.valid),
        "direction": signal.direction.value,
        "strength": _safe_round(signal.strength, 4),
        "reason": signal.reason,
        "price": _safe_round(signal.price),
        "entry_price": _safe_round(signal.entry_price),
        "sl_price": _safe_round(signal.sl_price),
        "tp1_price": _safe_round(signal.tp1_price),
        "tp2_price": _safe_round(signal.tp2_price),
        "sl_distance_pct": _safe_round(signal.sl_distance_pct, 4),
        "rr_ratio": _safe_round(signal.rr_ratio, 4),
        "metadata": signal.metadata or {},
    }


def _confluence_to_dict(confluence: Optional[ConfluenceResult]) -> dict:
    if confluence is None:
        return {}
    return {
        "direction": confluence.direction.value,
        "score": confluence.score,
        "meets_threshold": bool(confluence.meets_threshold),
        "position_size_pct": _safe_round(confluence.position_size_pct, 2),
        "leverage": confluence.leverage,
        "reason": confluence.reason,
        "best_signal": _signal_to_dict(confluence.best_signal),
        "signals": [_signal_to_dict(item) for item in (confluence.signals or [])],
    }


def _risk_to_dict(risk: Optional[RiskDecision]) -> dict:
    if risk is None:
        return {}
    return {
        "approved": bool(risk.approved),
        "reason": risk.reason,
        "position_size_usd": _safe_round(risk.position_size_usd, 2),
        "sl_price": _safe_round(risk.sl_price),
        "tp1_price": _safe_round(risk.tp1_price),
        "tp2_price": _safe_round(risk.tp2_price),
        "leverage": risk.leverage,
        "risk_amount_usd": _safe_round(risk.risk_amount_usd, 2),
        "funding_rate": _safe_round(risk.funding_rate, 4),
        "atr_elevated": bool(risk.atr_elevated),
        "bb_bandwidth_low": bool(risk.bb_bandwidth_low),
        "in_cooldown": bool(risk.in_cooldown),
        "near_news_event": bool(risk.near_news_event),
    }


def _state_snapshot(state: Optional[dict]) -> dict:
    if not state:
        return {}
    positions = state.get("positions", {})
    cooldowns = state.get("cooldowns", {})
    return {
        "capital": _safe_round(state.get("capital"), 2),
        "total_trades": int(state.get("total_trades", 0)),
        "wins": int(state.get("wins", 0)),
        "losses": int(state.get("losses", 0)),
        "open_positions": len(positions),
        "open_symbols": sorted(positions.keys()),
        "cooldown_symbols": {
            symbol: item.get("candles_remaining", 0)
            for symbol, item in cooldowns.items()
        },
    }


def _market_snapshot(df: Optional[pd.DataFrame]) -> dict:
    if df is None or len(df) < 2:
        return {}
    row = df.iloc[-2]
    snapshot = {}
    for key in [
        "time", "open", "high", "low", "close", "volume",
        "ema9", "ema20", "ema21", "ema50",
        "rsi", "bb_upper", "bb_lower", "bb_middle", "bb_bandwidth",
        "atr14", "volume_avg20", "body_ratio", "upper_wick", "lower_wick",
        "high_5", "low_5", "high_20", "low_20", "high_3", "low_3",
    ]:
        if key not in row:
            continue
        value = row[key]
        if hasattr(value, "isoformat"):
            snapshot[key] = value.isoformat()
        else:
            rounded = _safe_round(value, 6)
            if rounded is not None:
                snapshot[key] = rounded
            elif hasattr(value, "item"):
                try:
                    snapshot[key] = value.item()
                except Exception:
                    snapshot[key] = str(value)
            else:
                snapshot[key] = value
    return snapshot


def _record_scalping_audit(
    cycle_id: str,
    symbol: str,
    outcome: str,
    reason: str,
    opportunity_detected: bool,
    force_entry_applied: bool,
    ai_used: bool,
    ai_approved: bool,
    risk: Optional[RiskDecision],
    confluence: Optional[ConfluenceResult],
    state_before: Optional[dict],
    state_after: Optional[dict],
    market_context: Optional[dict] = None,
    execution: Optional[dict] = None,
) -> None:
    if not SCALPING_AUDIT_ENABLED:
        return

    details = {
        "config": {
            "initial_capital": _safe_round(CONFIG.initial_capital, 2),
            "max_positions": CONFIG.max_positions,
            "experimental_force_entries": SCALPING_EXPERIMENTAL_FORCE_ENTRIES,
            "ignore_risk_filters": SCALPING_IGNORE_RISK_FILTERS,
            "disable_ai_gate": SCALPING_DISABLE_AI_GATE,
            "disable_cooldown": SCALPING_DISABLE_COOLDOWN,
            "force_position_size_pct": _safe_round(SCALPING_FORCE_POSITION_SIZE_PCT, 2),
            "force_leverage": SCALPING_FORCE_LEVERAGE,
        },
        "confluence": _confluence_to_dict(confluence),
        "risk": _risk_to_dict(risk),
        "market": market_context or {},
        "state_before": state_before or {},
        "state_after": state_after or {},
        "execution": execution or {},
    }
    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cycle_id": cycle_id,
        "symbol": symbol,
        "outcome": outcome,
        "reason": reason,
        "opportunity_detected": opportunity_detected,
        "force_entry_enabled": SCALPING_EXPERIMENTAL_FORCE_ENTRIES,
        "force_entry_applied": force_entry_applied,
        "ai_used": ai_used,
        "ai_approved": ai_approved,
        "risk_approved": risk.approved if risk else False,
        "pnl_pct": execution.get("pnl_pct") if execution else None,
        "pnl_usd": execution.get("pnl_usd") if execution else None,
        "details_json": details,
    }
    try:
        db.insert_scalping_audit_log(payload)
    except Exception as exc:
        logger.warning("Falha ao persistir auditoria de scalping %s %s: %s", symbol, outcome, exc)


def _select_best_valid_signal(confluence: ConfluenceResult):
    valid_signals = [signal for signal in (confluence.signals or []) if signal.valid]
    if not valid_signals:
        return None
    valid_signals.sort(key=lambda item: (item.rr_ratio, item.strength), reverse=True)
    return valid_signals[0]


def _force_confluence_if_needed(confluence: ConfluenceResult) -> tuple[ConfluenceResult, bool]:
    if confluence.meets_threshold:
        return confluence, False

    best_signal = _select_best_valid_signal(confluence)
    if best_signal is None:
        return confluence, False

    matching_score = sum(
        1 for item in (confluence.signals or [])
        if item.valid and item.direction == best_signal.direction
    )
    forced = ConfluenceResult(
        direction=best_signal.direction,
        score=max(1, matching_score),
        meets_threshold=True,
        signals=confluence.signals,
        position_size_pct=max(1.0, float(SCALPING_FORCE_POSITION_SIZE_PCT)),
        leverage=SCALPING_FORCE_LEVERAGE,
        reason=(
            f"[FORCED] Entrada experimental liberada por {best_signal.source}. "
            f"Motivo original: {confluence.reason}"
        ),
        best_signal=best_signal,
    )
    return forced, True


def _force_risk_approval(
    state: dict,
    confluence: ConfluenceResult,
    blocked_risk: RiskDecision,
) -> RiskDecision:
    best = confluence.best_signal
    capital = float(state.get("capital", CONFIG.initial_capital))
    leverage = max(1, SCALPING_FORCE_LEVERAGE)
    position_size = calculate_position_size(
        capital=capital,
        risk_pct=CONFIG.max_risk_pct,
        entry_price=best.entry_price,
        sl_price=best.sl_price,
        leverage=leverage,
    )
    position_size *= max(1.0, float(SCALPING_FORCE_POSITION_SIZE_PCT)) / 100.0
    if position_size <= 0:
        position_size = round(max(capital * 0.1, 10.0), 2)

    return RiskDecision(
        approved=True,
        reason=f"[FORCED] Risco bypassado. Motivo original: {blocked_risk.reason}",
        position_size_usd=round(position_size, 2),
        sl_price=best.sl_price,
        tp1_price=best.tp1_price,
        tp2_price=best.tp2_price,
        leverage=leverage,
        risk_amount_usd=round(capital * (CONFIG.max_risk_pct / 100), 2),
        funding_rate=blocked_risk.funding_rate,
        atr_elevated=blocked_risk.atr_elevated,
        bb_bandwidth_low=blocked_risk.bb_bandwidth_low,
        in_cooldown=blocked_risk.in_cooldown,
        near_news_event=blocked_risk.near_news_event,
    )


def _record_scalping_decision(
    cycle_id: str,
    symbol: str,
    outcome: str,
    reason: str = "",
    confluence: Optional[ConfluenceResult] = None,
    ai_used: bool = False,
    ai_approved: bool = False,
    risk: Optional[RiskDecision] = None,
) -> None:
    """Persiste o resultado final do funil do scalping para comparacao entre instancias."""
    best_signal = confluence.best_signal if confluence else None
    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cycle_id": cycle_id,
        "symbol": symbol,
        "outcome": outcome,
        "reason": reason,
        "confluence_score": confluence.score if confluence else None,
        "confluence_direction": confluence.direction.value if confluence else None,
        "best_signal_source": best_signal.source if best_signal else None,
        "ai_used": ai_used,
        "ai_approved": ai_approved,
        "risk_approved": risk.approved if risk else False,
        "rr_ratio": best_signal.rr_ratio if best_signal else None,
        "sl_distance_pct": best_signal.sl_distance_pct if best_signal else None,
    }
    try:
        db.insert_scalping_decision(payload)
    except Exception as exc:
        logger.warning("Falha ao persistir decisao de scalping %s %s: %s", symbol, outcome, exc)


# ============================================================
#  GERENCIAMENTO DE POSICOES
# ============================================================

def _check_open_positions(state: dict, symbol: str, df_1m: Optional[pd.DataFrame]) -> List[str]:
    """
    Verifica posicoes abertas do scalping para SL/TP hits.

    Gerencia TP parcial (TP1 = 50% da posicao) e trailing SL apos TP1.
    """
    messages = []
    positions = state.get("positions", {})

    if symbol not in positions:
        return messages

    pos = positions[symbol]
    state_before = _state_snapshot(state)
    entry_price = pos["entry_price"]
    sl_price = pos["sl_price"]
    tp1_price = pos["tp1_price"]
    tp2_price = pos["tp2_price"]
    direction = pos["direction"]
    tp1_hit = pos.get("tp1_hit", False)

    # Pegar preco atual
    if df_1m is not None and len(df_1m) > 0:
        current_price = df_1m["close"].iloc[-1]
        current_high = df_1m["high"].iloc[-1]
        current_low = df_1m["low"].iloc[-1]
    else:
        return messages

    # Atualizar SL para breakeven se TP1 ja foi atingido
    if tp1_hit:
        sl_price = entry_price  # SL no breakeven

    # Verificar hits
    # Slippage no fill: SL executa ligeiramente pior, TP ligeiramente pior
    slip = entry_price * (CONFIG.slippage_pct / 100)
    hit = None
    exit_price = current_price

    if direction == "LONG":
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # SL hit -- fill simulado abaixo do SL (slippage contra)
        if current_low <= sl_price:
            hit = "stop_loss"
            exit_price = sl_price - slip
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100

        # TP2 hit -- fill simulado abaixo do TP (slippage contra)
        elif current_high >= tp2_price:
            hit = "take_profit_2"
            exit_price = tp2_price - slip
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100

        # TP1 hit (parcial)
        elif not tp1_hit and current_high >= tp1_price:
            tp1_fill = tp1_price - slip
            pos["tp1_hit"] = True
            pos["sl_price"] = entry_price  # Mover SL para breakeven
            pos["tp1_pnl_pct"] = ((tp1_fill - entry_price) / entry_price) * 100
            realized_pnl = pos["tp1_pnl_pct"] * (pos["position_size_usd"] * 0.5 / 100)
            state["capital"] += realized_pnl
            positions[symbol] = pos

            messages.append(
                f"[SCALPING] TP1 atingido: {symbol} {direction}\n"
                f"Fechado 50% @ {tp1_fill:.4f} (slip) | P&L parcial: {pos['tp1_pnl_pct']:+.2f}%\n"
                f"SL movido para breakeven ({entry_price:.4f})"
            )
            logger.info(
                "TP1 %s: fechado 50%% @ %.4f (slip), SL -> breakeven",
                symbol, tp1_fill
            )
            _record_scalping_audit(
                cycle_id=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                symbol=symbol,
                outcome="tp1_partial",
                reason="TP1 parcial atingido e SL movido para breakeven",
                opportunity_detected=True,
                force_entry_applied=bool(pos.get("forced_entry", False)),
                ai_used=False,
                ai_approved=True,
                risk=None,
                confluence=None,
                state_before=state_before,
                state_after=_state_snapshot(state),
                market_context={"tf_1m": _market_snapshot(df_1m)},
                execution={
                    "direction": direction,
                    "entry_price": _safe_round(entry_price),
                    "exit_price": _safe_round(tp1_fill),
                    "pnl_pct": _safe_round(pos["tp1_pnl_pct"], 4),
                    "pnl_usd": _safe_round(realized_pnl, 2),
                    "position_entry_time": pos.get("entry_time"),
                },
            )
            return messages  # Nao fechar completamente ainda

    else:  # SHORT
        pnl_pct = ((entry_price - current_price) / entry_price) * 100

        # SL hit -- fill simulado acima do SL (slippage contra)
        if current_high >= sl_price:
            hit = "stop_loss"
            exit_price = sl_price + slip
            pnl_pct = ((entry_price - exit_price) / entry_price) * 100

        # TP2 hit -- fill simulado acima do TP (slippage contra)
        elif current_low <= tp2_price:
            hit = "take_profit_2"
            exit_price = tp2_price + slip
            pnl_pct = ((entry_price - exit_price) / entry_price) * 100

        elif not tp1_hit and current_low <= tp1_price:
            tp1_fill = tp1_price + slip
            pos["tp1_hit"] = True
            pos["sl_price"] = entry_price
            pos["tp1_pnl_pct"] = ((entry_price - tp1_fill) / entry_price) * 100
            realized_pnl = pos["tp1_pnl_pct"] * (pos["position_size_usd"] * 0.5 / 100)
            state["capital"] += realized_pnl
            positions[symbol] = pos

            messages.append(
                f"[SCALPING] TP1 atingido: {symbol} {direction}\n"
                f"Fechado 50% @ {tp1_fill:.4f} (slip) | P&L parcial: {pos['tp1_pnl_pct']:+.2f}%\n"
                f"SL movido para breakeven ({entry_price:.4f})"
            )
            logger.info(
                "TP1 %s: fechado 50%% @ %.4f (slip), SL -> breakeven",
                symbol, tp1_fill
            )
            _record_scalping_audit(
                cycle_id=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                symbol=symbol,
                outcome="tp1_partial",
                reason="TP1 parcial atingido e SL movido para breakeven",
                opportunity_detected=True,
                force_entry_applied=bool(pos.get("forced_entry", False)),
                ai_used=False,
                ai_approved=True,
                risk=None,
                confluence=None,
                state_before=state_before,
                state_after=_state_snapshot(state),
                market_context={"tf_1m": _market_snapshot(df_1m)},
                execution={
                    "direction": direction,
                    "entry_price": _safe_round(entry_price),
                    "exit_price": _safe_round(tp1_fill),
                    "pnl_pct": _safe_round(pos["tp1_pnl_pct"], 4),
                    "pnl_usd": _safe_round(realized_pnl, 2),
                    "position_entry_time": pos.get("entry_time"),
                },
            )
            return messages

    # Fechar posicao completa
    if hit:
        # Ajustar PnL se TP1 ja foi atingido (50% restante)
        remaining_pct = 0.5 if tp1_hit else 1.0
        pnl_usd = pnl_pct * (pos["position_size_usd"] * remaining_pct / 100)

        state["capital"] += pnl_usd
        state["total_pnl_usd"] = state.get("total_pnl_usd", 0.0) + pnl_usd
        state["total_trades"] += 1

        if pnl_pct > 0 or (tp1_hit and hit == "stop_loss"):
            # Se TP1 foi atingido e SL bateu no breakeven, ainda e win parcial
            if tp1_hit and hit == "stop_loss":
                state["wins"] += 1  # TP1 foi lucro, SL no breakeven = win
            elif pnl_pct > 0:
                state["wins"] += 1
            else:
                state["losses"] += 1
        else:
            state["losses"] += 1

        # Registrar cooldown
        if not SCALPING_DISABLE_COOLDOWN:
            update_cooldown_on_close(state, symbol, CONFIG)

        # Historico
        state.setdefault("history", []).append({
            "symbol": symbol,
            "direction": direction,
            "pnl_pct": round(pnl_pct, 2),
            "exit_reason": hit,
            "timestamp": datetime.now().isoformat(),
        })
        state["history"] = state["history"][-20:]

        # Log no banco
        trade = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            "type": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "sl_price": pos["sl_price"],
            "tp_price": tp2_price,
            "position_size_usd": pos.get("position_size_usd"),
            "leverage": pos.get("leverage"),
            "confluence_score": pos.get("confluence_score"),
            "source": pos.get("source"),
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usd": round(pnl_usd, 2),
            "exit_reason": hit,
            "capital_after": round(state["capital"], 2),
        }
        try:
            db.insert_scalping_trade(trade)
        except Exception as db_err:
            logger.error(
                "ERRO DB insert_scalping_trade (trade NAO salvo no banco): %s | trade_data=%s",
                db_err, trade,
            )

        wr = (state["wins"] / state["total_trades"]) * 100 if state["total_trades"] > 0 else 0

        tp1_note = " (TP1 ja realizado)" if tp1_hit else ""
        messages.append(
            f"[SCALPING] {direction} fechado: {symbol}{tp1_note}\n"
            f"Entrada: {entry_price:.4f} | Saida: {exit_price:.4f}\n"
            f"P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
            f"Motivo: {hit}\n"
            f"Capital: ${state['capital']:.2f} | Trades: {state['total_trades']} | WR: {wr:.1f}%"
        )

        logger.info(
            "FECHADO %s %s: exit=%.4f reason=%s pnl=%.2f%% capital=$%.2f",
            symbol, direction, exit_price, hit, pnl_pct, state["capital"]
        )

        # Remover posicao
        del positions[symbol]

        _record_scalping_audit(
            cycle_id=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            symbol=symbol,
            outcome=f"closed_{hit}",
            reason=f"Posicao encerrada por {hit}",
            opportunity_detected=True,
            force_entry_applied=bool(pos.get("forced_entry", False)),
            ai_used=False,
            ai_approved=True,
            risk=None,
            confluence=None,
            state_before=state_before,
            state_after=_state_snapshot(state),
            market_context={"tf_1m": _market_snapshot(df_1m)},
            execution={
                "direction": direction,
                "entry_price": _safe_round(entry_price),
                "exit_price": _safe_round(exit_price),
                "pnl_pct": _safe_round(pnl_pct, 4),
                "pnl_usd": _safe_round(pnl_usd, 2),
                "exit_reason": hit,
                "tp1_hit_before_close": tp1_hit,
                "position_entry_time": pos.get("entry_time"),
            },
        )

    return messages


def _open_position(
    state: dict,
    symbol: str,
    confluence: ConfluenceResult,
    risk: RiskDecision,
    force_entry_applied: bool = False,
) -> str:
    """Abre uma nova posicao de scalping."""
    direction = confluence.direction.value
    best = confluence.best_signal

    positions = state.setdefault("positions", {})
    positions[symbol] = {
        "direction": direction,
        "entry_price": best.entry_price,
        "entry_time": datetime.now().isoformat(),
        "sl_price": risk.sl_price,
        "tp1_price": risk.tp1_price,
        "tp2_price": risk.tp2_price,
        "position_size_usd": risk.position_size_usd,
        "leverage": risk.leverage,
        "confluence_score": confluence.score,
        "source": best.source,
        "tp1_hit": False,
        "forced_entry": bool(force_entry_applied),
    }

    # Log no banco
    trade = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "type": direction,
        "entry_price": best.entry_price,
        "exit_price": None,
        "sl_price": risk.sl_price,
        "tp_price": risk.tp2_price,
        "position_size_usd": risk.position_size_usd,
        "leverage": risk.leverage,
        "confluence_score": confluence.score,
        "source": best.source,
        "pnl_pct": None,
        "pnl_usd": 0,
        "exit_reason": "open",
        "capital_after": state["capital"],
    }
    try:
        db.insert_scalping_trade(trade)
    except Exception as db_err:
        logger.error(
            "ERRO DB insert_scalping_trade (trade NAO salvo no banco): %s | trade_data=%s",
            db_err, trade,
        )

    msg = (
        f"[SCALPING] {direction} aberto: {symbol}\n"
        f"Confluencia: {confluence.score}/3 ({confluence.reason})\n"
        f"Entrada: {best.entry_price:.4f}\n"
        f"SL: {risk.sl_price:.4f} ({best.sl_distance_pct:.2f}%)\n"
        f"TP1: {risk.tp1_price:.4f} | TP2: {risk.tp2_price:.4f}\n"
        f"Size: ${risk.position_size_usd:.2f} | Lev: {risk.leverage}x\n"
        f"Motor principal: {best.source} | RR: {best.rr_ratio:.1f}\n"
        f"Capital: ${state['capital']:.2f}"
    )

    logger.info(
        "ABERTO %s %s: entry=%.4f sl=%.4f tp1=%.4f tp2=%.4f size=$%.2f lev=%dx",
        symbol, direction, best.entry_price, risk.sl_price,
        risk.tp1_price, risk.tp2_price, risk.position_size_usd, risk.leverage
    )

    return msg


# ============================================================
#  LOOP PRINCIPAL
# ============================================================

def process_scalping(symbols: list, open_new: bool = True) -> List[str]:
    """
    Executa um ciclo completo da estrategia de scalping.

    1. Verifica posicoes abertas (SL/TP)
    2. Atualiza cooldowns
    3. Busca dados e roda confluencia (se open_new=True)
    4. Avalia risco e abre posicoes (se open_new=True)

    Retorna lista de mensagens para o Telegram.
    """
    messages = []
    state = load_scalping_state()
    cycle_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Limpar cache de candles para dados frescos
    clear_cache()

    # Pre-buscar dados 15m (compartilhado por todos os pares para economizar API calls)
    df_15m_cache = {}

    for symbol in symbols:
        try:
            state_before = _state_snapshot(state)

            # ---- PASSO 1: Verificar posicoes abertas ----
            df_1m = fetch_candles(symbol, "1m", 10)
            pos_msgs = _check_open_positions(state, symbol, df_1m)
            messages.extend(pos_msgs)

            # Se circuit breaker ativo, apenas gerenciar posicoes
            if not open_new:
                save_scalping_state(state)
                continue

            # ---- PASSO 2: Tick cooldown ----
            tick_cooldown(state, symbol)

            # ---- PASSO 3: Se ja tem posicao ou em cooldown, pular ----
            if symbol in state.get("positions", {}):
                _record_scalping_decision(
                    cycle_id=cycle_id,
                    symbol=symbol,
                    outcome="in_position",
                    reason="Ja existe posicao aberta no simbolo",
                )
                _record_scalping_audit(
                    cycle_id=cycle_id,
                    symbol=symbol,
                    outcome="in_position",
                    reason="Ja existe posicao aberta no simbolo",
                    opportunity_detected=True,
                    force_entry_applied=False,
                    ai_used=False,
                    ai_approved=False,
                    risk=None,
                    confluence=None,
                    state_before=state_before,
                    state_after=_state_snapshot(state),
                    market_context={"tf_1m": _market_snapshot(df_1m)},
                )
                continue

            cooldown_active = is_in_cooldown(state, symbol)
            if cooldown_active and not SCALPING_DISABLE_COOLDOWN:
                cooldown_info = state.get("cooldowns", {}).get(symbol, {})
                remaining = cooldown_info.get("candles_remaining", 0)
                logger.info("SCALPING %s: em cooldown (%d candles)", symbol, remaining)
                _record_scalping_decision(
                    cycle_id=cycle_id,
                    symbol=symbol,
                    outcome="cooldown",
                    reason=f"Cooldown ativo: {remaining} candles restantes",
                )
                _record_scalping_audit(
                    cycle_id=cycle_id,
                    symbol=symbol,
                    outcome="cooldown",
                    reason=f"Cooldown ativo: {remaining} candles restantes",
                    opportunity_detected=False,
                    force_entry_applied=False,
                    ai_used=False,
                    ai_approved=False,
                    risk=None,
                    confluence=None,
                    state_before=state_before,
                    state_after=_state_snapshot(state),
                    market_context={"tf_1m": _market_snapshot(df_1m)},
                )
                continue
            if cooldown_active and SCALPING_DISABLE_COOLDOWN:
                cooldown_info = state.get("cooldowns", {}).get(symbol, {})
                remaining = cooldown_info.get("candles_remaining", 0)
                logger.warning(
                    "SCALPING %s: cooldown ignorado por modo experimental (%d candles)",
                    symbol, remaining,
                )

            # ---- PASSO 4: Buscar dados multi-timeframe ----
            df_3m = fetch_candles(symbol, "3m", 100)
            if df_3m is not None:
                df_3m = add_scalping_indicators(df_3m)

            df_5m = fetch_candles(symbol, "5m", 100)
            if df_5m is not None:
                df_5m = add_scalping_indicators(df_5m)

            if symbol not in df_15m_cache:
                df_15m = fetch_candles(symbol, "15m", 100)
                if df_15m is not None:
                    df_15m = add_scalping_indicators(df_15m)
                df_15m_cache[symbol] = df_15m
            else:
                df_15m = df_15m_cache[symbol]

            market_context = {
                "tf_1m": _market_snapshot(df_1m),
                "tf_3m": _market_snapshot(df_3m),
                "tf_5m": _market_snapshot(df_5m),
                "tf_15m": _market_snapshot(df_15m),
            }

            # ---- PASSO 5: Confluencia ----
            confluence = confluence_analyze(symbol, CONFIG, df_3m=df_3m, df_5m=df_5m, df_15m=df_15m)
            force_entry_applied = False
            opportunity_detected = any(item.valid for item in (confluence.signals or []))

            if not confluence.meets_threshold:
                if SCALPING_EXPERIMENTAL_FORCE_ENTRIES:
                    confluence, force_entry_applied = _force_confluence_if_needed(confluence)
                    if force_entry_applied:
                        logger.warning(
                            "SCALPING %s: confluencia liberada por modo experimental - %s",
                            symbol, confluence.reason,
                        )
                        messages.append(
                            f"[SCALPING][V2] {symbol} liberado em modo experimental: {confluence.reason}"
                        )
                    else:
                        logger.info(
                            "SCALPING %s: confluencia %d/3 - %s",
                            symbol, confluence.score, confluence.reason
                        )
                        _record_scalping_decision(
                            cycle_id=cycle_id,
                            symbol=symbol,
                            outcome="confluence_block",
                            reason=confluence.reason,
                            confluence=confluence,
                        )
                        _record_scalping_audit(
                            cycle_id=cycle_id,
                            symbol=symbol,
                            outcome="confluence_block",
                            reason=confluence.reason,
                            opportunity_detected=opportunity_detected,
                            force_entry_applied=False,
                            ai_used=False,
                            ai_approved=False,
                            risk=None,
                            confluence=confluence,
                            state_before=state_before,
                            state_after=_state_snapshot(state),
                            market_context=market_context,
                        )
                        continue
                else:
                    logger.info(
                        "SCALPING %s: confluencia %d/3 - %s",
                        symbol, confluence.score, confluence.reason
                    )
                    _record_scalping_decision(
                        cycle_id=cycle_id,
                        symbol=symbol,
                        outcome="confluence_block",
                        reason=confluence.reason,
                        confluence=confluence,
                    )
                    _record_scalping_audit(
                        cycle_id=cycle_id,
                        symbol=symbol,
                        outcome="confluence_block",
                        reason=confluence.reason,
                        opportunity_detected=opportunity_detected,
                        force_entry_applied=False,
                        ai_used=False,
                        ai_approved=False,
                        risk=None,
                        confluence=confluence,
                        state_before=state_before,
                        state_after=_state_snapshot(state),
                        market_context=market_context,
                    )
                    continue

            # ---- PASSO 5.5: Claude validation para confluencia borderline (2/3) ----
            ai_used = False
            ai_approved = False
            if confluence.score == 2 and not SCALPING_DISABLE_AI_GATE:
                ai_used = True
                try:
                    from trade_agents import validate_scalping_signal
                    approved, val_reason = validate_scalping_signal(
                        symbol,
                        confluence.direction.value,
                        confluence.score,
                        confluence.reason,
                        confluence.best_signal.source if confluence.best_signal else "unknown",
                    )
                    if not approved:
                        ai_approved = False
                        logger.info("SCALPING %s: Claude rejeitou (2/3) - %s", symbol, val_reason)
                        messages.append(f"[SCALPING] {symbol} rejeitado por Claude: {val_reason}")
                        _record_scalping_decision(
                            cycle_id=cycle_id,
                            symbol=symbol,
                            outcome="ai_rejected",
                            reason=val_reason,
                            confluence=confluence,
                            ai_used=ai_used,
                            ai_approved=ai_approved,
                        )
                        _record_scalping_audit(
                            cycle_id=cycle_id,
                            symbol=symbol,
                            outcome="ai_rejected",
                            reason=val_reason,
                            opportunity_detected=opportunity_detected,
                            force_entry_applied=force_entry_applied,
                            ai_used=ai_used,
                            ai_approved=ai_approved,
                            risk=None,
                            confluence=confluence,
                            state_before=state_before,
                            state_after=_state_snapshot(state),
                            market_context=market_context,
                        )
                        continue
                    ai_approved = True
                    logger.info("SCALPING %s: Claude aprovou (2/3) - %s", symbol, val_reason)
                except Exception as val_err:
                    ai_approved = True
                    logger.warning("SCALPING %s: erro na validacao Claude, prosseguindo: %s", symbol, val_err)
            elif confluence.score == 2 and SCALPING_DISABLE_AI_GATE:
                ai_approved = True
                logger.warning("SCALPING %s: gate de IA ignorado por modo experimental", symbol)

            # ---- PASSO 6: Risk Manager ----
            risk = evaluate_risk(confluence, symbol, CONFIG, df_15m=df_15m, state=state)

            if not risk.approved:
                if SCALPING_IGNORE_RISK_FILTERS and confluence.best_signal is not None:
                    blocked_reason = risk.reason
                    risk = _force_risk_approval(state, confluence, risk)
                    force_entry_applied = True
                    logger.warning(
                        "SCALPING %s: risco bypassado por modo experimental - %s",
                        symbol, blocked_reason,
                    )
                    messages.append(
                        f"[SCALPING][V2] {symbol} entrou apesar do risco: {blocked_reason}"
                    )
                else:
                    logger.info("SCALPING %s: risco rejeitou - %s", symbol, risk.reason)
                    messages.append(
                        f"[SCALPING] {symbol} bloqueado pelo risco: {risk.reason}"
                    )
                    _record_scalping_decision(
                        cycle_id=cycle_id,
                        symbol=symbol,
                        outcome="risk_blocked",
                        reason=risk.reason,
                        confluence=confluence,
                        ai_used=ai_used,
                        ai_approved=ai_approved,
                        risk=risk,
                    )
                    _record_scalping_audit(
                        cycle_id=cycle_id,
                        symbol=symbol,
                        outcome="risk_blocked",
                        reason=risk.reason,
                        opportunity_detected=opportunity_detected,
                        force_entry_applied=force_entry_applied,
                        ai_used=ai_used,
                        ai_approved=ai_approved,
                        risk=risk,
                        confluence=confluence,
                        state_before=state_before,
                        state_after=_state_snapshot(state),
                        market_context=market_context,
                    )
                    continue

            # ---- PASSO 7: Abrir posicao ----
            open_msg = _open_position(
                state,
                symbol,
                confluence,
                risk,
                force_entry_applied=force_entry_applied,
            )
            messages.append(open_msg)
            _record_scalping_decision(
                cycle_id=cycle_id,
                symbol=symbol,
                outcome="opened",
                reason="Trade aberto com sucesso",
                confluence=confluence,
                ai_used=ai_used,
                ai_approved=ai_approved,
                risk=risk,
            )
            _record_scalping_audit(
                cycle_id=cycle_id,
                symbol=symbol,
                outcome="opened",
                reason="Trade aberto com sucesso",
                opportunity_detected=opportunity_detected,
                force_entry_applied=force_entry_applied,
                ai_used=ai_used,
                ai_approved=ai_approved,
                risk=risk,
                confluence=confluence,
                state_before=state_before,
                state_after=_state_snapshot(state),
                market_context=market_context,
                execution={
                    "direction": confluence.direction.value,
                    "entry_price": _safe_round(confluence.best_signal.entry_price),
                    "sl_price": _safe_round(risk.sl_price),
                    "tp1_price": _safe_round(risk.tp1_price),
                    "tp2_price": _safe_round(risk.tp2_price),
                    "position_size_usd": _safe_round(risk.position_size_usd, 2),
                    "leverage": risk.leverage,
                    "source": confluence.best_signal.source if confluence.best_signal else "",
                },
            )

        except Exception as e:
            logger.error("Erro ao processar scalping %s: %s", symbol, e, exc_info=True)
            messages.append(f"[SCALPING] Erro em {symbol}: {e}")
            _record_scalping_decision(
                cycle_id=cycle_id,
                symbol=symbol,
                outcome="error",
                reason=str(e),
            )
            _record_scalping_audit(
                cycle_id=cycle_id,
                symbol=symbol,
                outcome="error",
                reason=str(e),
                opportunity_detected=False,
                force_entry_applied=False,
                ai_used=False,
                ai_approved=False,
                risk=None,
                confluence=None,
                state_before=state_before if "state_before" in locals() else {},
                state_after=_state_snapshot(state),
                market_context={},
            )

    # Salvar estado
    save_scalping_state(state)

    return messages


def get_scalping_status() -> str:
    """Retorna status atual do scalping trader."""
    state = load_scalping_state()
    capital = state.get("capital", CONFIG.initial_capital)
    total = state.get("total_trades", 0)
    wins = state.get("wins", 0)
    losses = state.get("losses", 0)
    wr = (wins / total) * 100 if total > 0 else 0
    ret = ((capital - CONFIG.initial_capital) / CONFIG.initial_capital) * 100

    lines = [
        f"[SCALPING] Capital: ${capital:.2f} ({ret:+.2f}%)",
        f"[SCALPING] Trades: {total} | W:{wins} L:{losses} | WR: {wr:.1f}%",
    ]

    positions = state.get("positions", {})
    if positions:
        lines.append(f"[SCALPING] Posicoes: {len(positions)}/{CONFIG.max_positions}")
        for sym, pos in positions.items():
            tp1_note = " [TP1 OK]" if pos.get("tp1_hit") else ""
            lines.append(
                f"  {sym}: {pos['direction']} @ {pos['entry_price']:.4f} | "
                f"SL: {pos['sl_price']:.4f} | TP1: {pos['tp1_price']:.4f} | "
                f"TP2: {pos['tp2_price']:.4f} | Lev: {pos.get('leverage', 1)}x{tp1_note}"
            )
    else:
        lines.append("[SCALPING] Sem posicoes abertas")

    cooldowns = state.get("cooldowns", {})
    if cooldowns:
        cd_strs = [f"{s}({v.get('candles_remaining', 0)}c)" for s, v in cooldowns.items()]
        lines.append(f"[SCALPING] Cooldowns: {', '.join(cd_strs)}")

    return "\n".join(lines)
