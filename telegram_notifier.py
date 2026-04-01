"""
Telegram Notifier - envio de mensagens com HTML, retry e rate limiting.
"""
import os
import time
import threading
import requests
from collections import deque
from dotenv import load_dotenv
from runtime_config import ENABLE_TELEGRAM_NOTIFICATIONS, TELEGRAM_INSTANCE_TAG

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Rate limiting: max 25 msgs por segundo (Telegram limit = 30)
_msg_timestamps = deque(maxlen=25)
_send_lock = threading.Lock()

# Dedup circuit breaker alerts (evita spam)
_last_cb_alert = {}
CB_ALERT_COOLDOWN = 3600  # 1 hora entre alertas do mesmo circuit breaker


def _decorate_message(message: str) -> str:
    tag = TELEGRAM_INSTANCE_TAG.strip()
    if not tag:
        return message
    return f"<b>[{tag}]</b>\n{message}"


def _rate_limit():
    """Aguarda se necessario para respeitar rate limit do Telegram."""
    now = time.time()
    with _send_lock:
        # Remove timestamps mais velhos que 1 segundo
        while _msg_timestamps and now - _msg_timestamps[0] > 1.0:
            _msg_timestamps.popleft()
        if len(_msg_timestamps) >= 25:
            sleep_time = 1.0 - (now - _msg_timestamps[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
        _msg_timestamps.append(time.time())


def send_telegram_message(message: str, parse_mode: str = "HTML", silent: bool = False, retries: int = 3):
    """
    Envia mensagem para o Telegram com retry e rate limiting.

    Args:
        message: Texto da mensagem (suporta HTML)
        parse_mode: "HTML" ou "Markdown" (default: HTML)
        silent: Se True, envia sem notificacao sonora
        retries: Numero de tentativas em caso de falha
    """
    if not ENABLE_TELEGRAM_NOTIFICATIONS:
        print("[TELEGRAM] Notificacoes desabilitadas para esta instancia.")
        return False

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Token/chat_id nao configurados no .env")
        return False

    message = _decorate_message(message)

    _rate_limit()

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_notification": silent,
    }

    for attempt in range(retries):
        try:
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                return True
            elif response.status_code == 429:
                # Rate limited pelo Telegram
                retry_after = response.json().get("parameters", {}).get("retry_after", 5)
                print(f"[TELEGRAM] Rate limited, aguardando {retry_after}s...")
                time.sleep(retry_after)
                continue
            elif response.status_code == 400:
                # Possivel erro de parse HTML - tenta sem formatacao
                if parse_mode != "":
                    print(f"[TELEGRAM] Erro de parse, reenviando sem formatacao...")
                    payload["parse_mode"] = ""
                    continue
                print(f"[TELEGRAM] Erro 400: {response.text}")
                return False
            else:
                print(f"[TELEGRAM] HTTP {response.status_code}: {response.text}")
        except requests.exceptions.Timeout:
            print(f"[TELEGRAM] Timeout (tentativa {attempt + 1}/{retries})")
        except Exception as e:
            print(f"[TELEGRAM] Erro (tentativa {attempt + 1}/{retries}): {e}")

        if attempt < retries - 1:
            time.sleep(2 ** attempt)

    print(f"[TELEGRAM] Falha apos {retries} tentativas")
    return False


# ── MENSAGENS FORMATADAS ─────────────────────────────────────────────────────

def send_trade_alert(symbol: str, direction: str, entry: float, sl: float, tp: float,
                     system: str, extra: str = ""):
    """Envia alerta de trade formatado."""
    emoji = "\U0001f7e2" if direction.upper() in ("BUY", "LONG") else "\U0001f534"
    msg = (
        f"{emoji} <b>Novo Trade - {system}</b>\n"
        f"\n"
        f"<b>Par:</b> <code>{symbol}</code>\n"
        f"<b>Direcao:</b> {direction.upper()}\n"
        f"<b>Entrada:</b> <code>{entry:.6f}</code>\n"
        f"<b>Stop Loss:</b> <code>{sl:.6f}</code>\n"
        f"<b>Take Profit:</b> <code>{tp:.6f}</code>"
    )
    if extra:
        msg += f"\n{extra}"
    return send_telegram_message(msg)


def send_trade_close(symbol: str, pnl_pct: float, pnl_usd: float, reason: str,
                     system: str):
    """Envia alerta de fechamento de trade."""
    emoji = "\u2705" if pnl_pct >= 0 else "\u274c"
    msg = (
        f"{emoji} <b>Trade Fechado - {system}</b>\n"
        f"\n"
        f"<b>Par:</b> <code>{symbol}</code>\n"
        f"<b>P&amp;L:</b> <code>{pnl_pct:+.2f}%</code> (<code>${pnl_usd:+.2f}</code>)\n"
        f"<b>Motivo:</b> {reason}"
    )
    return send_telegram_message(msg)


def send_opportunity_alert(symbol: str, decision: str, opportunity_type: str,
                           dominant_side: str, confidence: int, priority: int,
                           interpretation: str = ""):
    """Envia alerta de oportunidade detectada."""
    msg = (
        f"\U0001f4ca <b>Oportunidade Detectada</b>\n"
        f"\n"
        f"<b>Par:</b> <code>{symbol}</code>\n"
        f"<b>Decisao:</b> {decision}\n"
        f"<b>Tipo:</b> {opportunity_type}\n"
        f"<b>Lado:</b> {dominant_side}\n"
        f"<b>Confianca:</b> <code>{confidence}/100</code>\n"
        f"<b>Priority:</b> <code>{priority}</code>"
    )
    if interpretation:
        msg = (
            f"\U0001f4ca <b>Oportunidade Detectada - {symbol}</b>\n"
            f"\n"
            f"{interpretation}\n"
            f"\n"
            f"<b>Decisao:</b> {decision} | <b>Tipo:</b> {opportunity_type}\n"
            f"<b>Lado:</b> {dominant_side} | <b>Confianca:</b> <code>{confidence}/100</code>\n"
            f"<b>Priority:</b> <code>{priority}</code>"
        )
    return send_telegram_message(msg)


def send_pump_alert(symbol: str, direction: str, price: float, volume_ratio: float,
                    change_1: float, change_3: float):
    """Envia alerta de pump/dump detectado."""
    emoji = "\U0001f680" if direction == "PUMP" else "\U0001f4c9"
    msg = (
        f"{emoji} <b>{direction} Detectado!</b>\n"
        f"\n"
        f"<b>Ativo:</b> <code>{symbol}</code>\n"
        f"<b>Preco:</b> <code>{price:.6f}</code>\n"
        f"<b>Volume:</b> <code>{volume_ratio}x</code> a media\n"
        f"<b>Var 1 candle:</b> <code>{change_1:+.2f}%</code>\n"
        f"<b>Var 3 candles:</b> <code>{change_3:+.2f}%</code>"
    )
    return send_telegram_message(msg)


def send_system_alert(title: str, message: str, critical: bool = False):
    """Envia alerta de sistema (crash, restart, circuit breaker)."""
    emoji = "\U0001f6a8" if critical else "\u26a0\ufe0f"
    msg = f"{emoji} <b>{title}</b>\n\n{message}"
    return send_telegram_message(msg, silent=not critical)


def send_circuit_breaker_alert(system: str, reason: str):
    """Envia alerta de circuit breaker com dedup (1x por hora por sistema)."""
    now = time.time()
    last = _last_cb_alert.get(system, 0)
    if now - last < CB_ALERT_COOLDOWN:
        return False

    _last_cb_alert[system] = now
    msg = (
        f"\U0001f6d1 <b>Circuit Breaker Ativado</b>\n"
        f"\n"
        f"<b>Sistema:</b> {system}\n"
        f"<b>Motivo:</b> {reason}\n"
        f"\n"
        f"Novas operacoes suspensas ate amanha."
    )
    return send_telegram_message(msg)


def send_daily_report_formatted(report_data: dict):
    """Envia relatorio diario formatado."""
    lines = [f"\U0001f4c8 <b>Relatorio Diario - {report_data['date']}</b>\n"]

    for sys_name, stats in report_data.get("systems", {}).items():
        wr = f"{(stats['wins'] / stats['count'] * 100):.0f}%" if stats["count"] > 0 else "N/A"
        emoji = "\u2705" if stats["pnl_usd"] >= 0 else "\u274c"
        lines.append(
            f"{emoji} <b>{sys_name}:</b> {stats['count']} trades | "
            f"<code>{stats['pnl_pct']:+.2f}%</code> (<code>${stats['pnl_usd']:+.2f}</code>) | "
            f"WR: {wr} | Capital: <code>${stats['capital']:.2f}</code>"
        )

    totals = report_data.get("totals", {})
    if totals:
        lines.append("")
        lines.append(
            f"\U0001f4b0 <b>Total:</b> {totals['count']} trades | "
            f"<code>${totals['pnl_usd']:+.2f}</code> | "
            f"W:{totals['wins']} L:{totals['losses']}"
        )

    positions = report_data.get("positions", [])
    if positions:
        lines.append(f"\n\U0001f4cd <b>Posicoes Abertas ({len(positions)}):</b>")
        for p in positions:
            lines.append(f"  {p}")

    return send_telegram_message("\n".join(lines))
