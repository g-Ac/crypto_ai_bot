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

from signal_types import ConfluenceResult, RiskDecision, ScalpingConfig
from scalping_data import fetch_candles, add_scalping_indicators, clear_cache
from confluence import analyze as confluence_analyze
from risk_manager import (
    load_scalping_state, save_scalping_state,
    evaluate_risk, tick_cooldown, update_cooldown_on_close,
    is_in_cooldown,
)

logger = logging.getLogger("scalping.trader")

# Configuracao padrao
CONFIG = ScalpingConfig()


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
            return messages

    # Fechar posicao completa
    if hit:
        # Ajustar PnL se TP1 ja foi atingido (50% restante)
        remaining_pct = 0.5 if tp1_hit else 1.0
        pnl_usd = pnl_pct * (pos["position_size_usd"] * remaining_pct / 100)

        state["capital"] += pnl_usd
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
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usd": round(pnl_usd, 2),
            "exit_reason": hit,
            "capital_after": round(state["capital"], 2),
        }
        try:
            db.insert_paper_trade(trade)
        except Exception as db_err:
            logger.error(
                "ERRO DB insert_paper_trade (trade NAO salvo no banco): %s | trade_data=%s",
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

    return messages


def _open_position(
    state: dict,
    symbol: str,
    confluence: ConfluenceResult,
    risk: RiskDecision,
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
    }

    # Log no banco
    trade = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "type": direction,
        "entry_price": best.entry_price,
        "sl_price": risk.sl_price,
        "tp_price": risk.tp2_price,
        "position_size_usd": risk.position_size_usd,
        "exit_price": None,
        "pnl_pct": None,
        "pnl_usd": 0,
        "exit_reason": "open",
        "analyst_confidence": int(best.strength * 100),
        "capital_after": state["capital"],
    }
    try:
        db.insert_agent_trade(trade)
    except Exception as db_err:
        logger.error(
            "ERRO DB insert_agent_trade (trade NAO salvo no banco): %s | trade_data=%s",
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

def process_scalping(symbols: list) -> List[str]:
    """
    Executa um ciclo completo da estrategia de scalping.

    1. Verifica posicoes abertas (SL/TP)
    2. Atualiza cooldowns
    3. Busca dados e roda confluencia
    4. Avalia risco e abre posicoes

    Retorna lista de mensagens para o Telegram.
    """
    messages = []
    state = load_scalping_state()

    # Limpar cache de candles para dados frescos
    clear_cache()

    # Pre-buscar dados 15m (compartilhado por todos os pares para economizar API calls)
    df_15m_cache = {}

    for symbol in symbols:
        try:
            # ---- PASSO 1: Verificar posicoes abertas ----
            df_1m = fetch_candles(symbol, "1m", 10)
            pos_msgs = _check_open_positions(state, symbol, df_1m)
            messages.extend(pos_msgs)

            # ---- PASSO 2: Tick cooldown ----
            tick_cooldown(state, symbol)

            # ---- PASSO 3: Se ja tem posicao ou em cooldown, pular ----
            if symbol in state.get("positions", {}):
                continue

            if is_in_cooldown(state, symbol):
                cooldown_info = state.get("cooldowns", {}).get(symbol, {})
                remaining = cooldown_info.get("candles_remaining", 0)
                logger.info("SCALPING %s: em cooldown (%d candles)", symbol, remaining)
                continue

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

            # ---- PASSO 5: Confluencia ----
            confluence = confluence_analyze(symbol, CONFIG, df_3m=df_3m, df_5m=df_5m, df_15m=df_15m)

            if not confluence.meets_threshold:
                logger.info(
                    "SCALPING %s: confluencia %d/3 - %s",
                    symbol, confluence.score, confluence.reason
                )
                continue

            # ---- PASSO 6: Risk Manager ----
            risk = evaluate_risk(confluence, symbol, CONFIG, df_15m=df_15m)

            if not risk.approved:
                logger.info("SCALPING %s: risco rejeitou - %s", symbol, risk.reason)
                messages.append(
                    f"[SCALPING] {symbol} bloqueado pelo risco: {risk.reason}"
                )
                continue

            # ---- PASSO 7: Abrir posicao ----
            open_msg = _open_position(state, symbol, confluence, risk)
            messages.append(open_msg)

        except Exception as e:
            logger.error("Erro ao processar scalping %s: %s", symbol, e, exc_info=True)
            messages.append(f"[SCALPING] Erro em {symbol}: {e}")

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
