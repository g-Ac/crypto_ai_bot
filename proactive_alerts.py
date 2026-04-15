"""
Alertas proativos — detecta problemas antes que se agravem.

Checks executados a cada ciclo do main loop (5 min):
  1. Drawdown warning: perda diaria >= 3% em qualquer sistema
  2. Zero trades 24h: nenhum trade (scalping + pump) em 24 horas
  3. Erros repetidos: >= 5 decisoes com blocked_by='error' na ultima hora

Dedup in-memory com cooldown por tipo de alerta (mesmo padrao de
telegram_notifier._last_cb_alert).
"""
import logging
import time
from datetime import date

import database as db
from daily_report import calc_daily_stats, _get_current_capital
from config import (
    SCALPING_INITIAL_CAPITAL,
    PUMP_INITIAL_CAPITAL,
)
from telegram_notifier import send_system_alert

logger = logging.getLogger("proactive_alerts")

# Cooldowns (segundos)
_DRAWDOWN_COOLDOWN = 7200    # 2h
_ZERO_TRADES_COOLDOWN = 43200  # 12h
_ERRORS_COOLDOWN = 3600       # 1h

# Thresholds
DRAWDOWN_WARNING_PCT = 3.0    # alerta se perda >= 3%
ERROR_COUNT_THRESHOLD = 5     # >= 5 erros/hora

# Dedup state (in-memory, resets on restart — ok para alertas)
_last_alert: dict[str, float] = {}


def _cooldown_ok(key: str, cooldown: float) -> bool:
    """Retorna True se o cooldown para esta chave ja expirou.

    NAO grava o timestamp — o caller deve chamar _mark_sent() apos
    confirmar que o alerta foi entregue.
    """
    now = time.time()
    last = _last_alert.get(key, 0)
    return (now - last) >= cooldown


def _mark_sent(key: str):
    """Grava timestamp de envio apos confirmacao de entrega."""
    _last_alert[key] = time.time()


def _check_drawdown():
    """Alerta se algum sistema perdeu >= 3% hoje."""
    systems = {
        "scalping": ("scalping_trades", SCALPING_INITIAL_CAPITAL),
        "pump": ("pump_trades", PUMP_INITIAL_CAPITAL),
    }
    for system, (table, initial_capital) in systems.items():
        try:
            trades = db.get_trades_today(table)
            stats = calc_daily_stats(trades)
            if stats["count"] == 0:
                continue

            current_capital = _get_current_capital(system)
            reference = max(initial_capital, current_capital)
            if reference <= 0:
                reference = initial_capital

            loss_pct = (stats["pnl_usd"] / reference) * 100
            if loss_pct <= -DRAWDOWN_WARNING_PCT:
                key = f"drawdown_{system}"
                if _cooldown_ok(key, _DRAWDOWN_COOLDOWN):
                    sent = send_system_alert(
                        "Drawdown Warning",
                        f"{system.title()}: perda de {loss_pct:.2f}% hoje "
                        f"(${stats['pnl_usd']:+.2f}). "
                        f"Limite circuit breaker: -5%.",
                    )
                    if sent is not False:
                        _mark_sent(key)
                    logger.warning(
                        "DRAWDOWN_WARNING %s: %.2f%% ($%.2f)",
                        system, loss_pct, stats["pnl_usd"],
                    )
        except Exception as e:
            logger.error("Erro no check de drawdown (%s): %s", system, e)


def _check_zero_trades():
    """Alerta se nenhum trade (scalping + pump) nas ultimas 24h."""
    try:
        conn = db._get_conn()
        try:
            scalping_count = conn.execute(
                "SELECT COUNT(*) FROM scalping_trades "
                "WHERE timestamp > datetime('now', '-24 hours')"
            ).fetchone()[0]
            pump_count = conn.execute(
                "SELECT COUNT(*) FROM pump_trades "
                "WHERE timestamp > datetime('now', '-24 hours')"
            ).fetchone()[0]
        finally:
            conn.close()

        if scalping_count == 0 and pump_count == 0:
            if _cooldown_ok("zero_trades_24h", _ZERO_TRADES_COOLDOWN):
                sent = send_system_alert(
                    "Zero Trades",
                    "Nenhum trade (scalping + pump) nas ultimas 24h. "
                    "Verificar se o bot esta operando corretamente.",
                )
                if sent is not False:
                    _mark_sent("zero_trades_24h")
                logger.warning("ZERO_TRADES: 0 trades nas ultimas 24h")
    except Exception as e:
        logger.error("Erro no check de zero trades: %s", e)


def _check_repeated_errors():
    """Alerta se >= 5 decisoes com blocked_by='error' na ultima hora."""
    try:
        conn = db._get_conn()
        try:
            error_count = conn.execute(
                "SELECT COUNT(*) FROM scalping_decisions "
                "WHERE blocked_by = 'error' "
                "AND timestamp > datetime('now', '-1 hour')"
            ).fetchone()[0]
        finally:
            conn.close()

        if error_count >= ERROR_COUNT_THRESHOLD:
            if _cooldown_ok("repeated_errors", _ERRORS_COOLDOWN):
                sent = send_system_alert(
                    "Erros Repetidos",
                    f"{error_count} decisoes com erro na ultima hora. "
                    f"Verificar logs do bot.",
                    critical=True,
                )
                if sent is not False:
                    _mark_sent("repeated_errors")
                logger.warning("REPEATED_ERRORS: %d erros na ultima hora", error_count)
    except Exception as e:
        logger.error("Erro no check de erros repetidos: %s", e)


def check_proactive_alerts():
    """Executa todos os checks proativos. Chamado no fim de cada ciclo."""
    _check_drawdown()
    _check_zero_trades()
    _check_repeated_errors()
