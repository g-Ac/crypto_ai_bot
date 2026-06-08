"""
Background WebSocket collector para liquidacoes reais da Binance Futures.

Conecta a wss://fstream.binance.com/ws/!forceOrder@arr e agrega
liquidacoes por simbolo numa janela rolante. Zero dependencias externas
(usa apenas stdlib: ssl, socket, struct, threading).

Uso:
    from liquidation_feed import init_feed, get_symbol_liquidations

    init_feed(["BTCUSDT", "ETHUSDT"])       # inicia thread em background
    data = get_symbol_liquidations("BTCUSDT")  # agrega janela de 15min
    # -> {"liquidation_vol_long": 12345.67, "liquidation_vol_short": 9876.54,
    #     "count": 42, "is_proxy": False}
"""
from __future__ import annotations

import base64
import json
import logging
import os
import socket
import ssl
import struct
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("liquidation_feed")

# ── Config ──────────────────────────────────────────────────────────────────
_WS_HOST = "fstream.binance.com"
_WS_PATH = "/ws/!forceOrder@arr"
_DEFAULT_WINDOW_MINUTES = 15
_RECONNECT_BASE_DELAY = 3
_RECONNECT_MAX_DELAY = 60
_PRUNE_INTERVAL = 60  # prune deques every 60s

# ── State ───────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_liquidations: dict[str, deque] = defaultdict(deque)
# Each entry: (utc_timestamp: float, side: str, notional: float)

_symbols: set[str] = set()
_window_minutes: int = _DEFAULT_WINDOW_MINUTES
_running = False
_connected = False
_stats = {"total_received": 0, "total_tracked": 0, "reconnects": 0, "last_event": 0.0}

# Sink opcional de persistencia. Se setado, e chamado a cada liquidacao com
# (event_ms, symbol, side, qty, price, notional). Aditivo e protegido —
# uma falha no sink NUNCA derruba o feed (ver _process_message).
_event_sink = None


def set_event_sink(fn) -> None:
    """Registra (ou remove, com None) um callback de persistencia. Opcional."""
    global _event_sink
    _event_sink = fn


def init_feed(symbols: list[str], window_minutes: int = _DEFAULT_WINDOW_MINUTES) -> None:
    """Inicia o collector em background (idempotente — chamar multiplas vezes e seguro)."""
    global _symbols, _window_minutes, _running

    _symbols = {s.upper() for s in symbols}
    _window_minutes = window_minutes

    if _running:
        logger.info("Liquidation feed ja esta rodando")
        return

    _running = True
    t = threading.Thread(target=_collector_loop, name="liq-feed", daemon=True)
    t.start()
    logger.info("Liquidation feed iniciado: %d simbolos, janela=%dmin", len(_symbols), window_minutes)


def stop_feed() -> None:
    """Sinaliza para o collector parar (para testes/shutdown)."""
    global _running
    _running = False


def get_symbol_liquidations(symbol: str, window_minutes: int | None = None) -> dict:
    """Retorna liquidacoes agregadas para um simbolo na janela rolante.

    Returns:
        {
            "liquidation_vol_long": float,
            "liquidation_vol_short": float,
            "count": int,
            "is_proxy": False,
        }
    """
    wm = window_minutes or _window_minutes
    cutoff = time.time() - (wm * 60)
    sym = symbol.upper()

    vol_long = 0.0
    vol_short = 0.0
    count = 0

    with _lock:
        entries = _liquidations.get(sym)
        if entries:
            # Prune old while we're here
            while entries and entries[0][0] < cutoff:
                entries.popleft()

            for ts, side, notional in entries:
                count += 1
                if side == "SELL":
                    vol_long += notional
                elif side == "BUY":
                    vol_short += notional

    return {
        "liquidation_vol_long": round(vol_long, 2),
        "liquidation_vol_short": round(vol_short, 2),
        "count": count,
        "is_proxy": False,
    }


def is_connected() -> bool:
    return _connected


def feed_stats() -> dict:
    """Retorna estatisticas do feed para diagnostico."""
    with _lock:
        symbols_with_data = {s: len(d) for s, d in _liquidations.items() if d}
    return {
        **_stats,
        "connected": _connected,
        "symbols_tracked": len(symbols_with_data),
        "entries_per_symbol": symbols_with_data,
    }


# ── Background Collector ────────────────────────────────────────────────────

def _collector_loop() -> None:
    global _connected
    delay = _RECONNECT_BASE_DELAY

    while _running:
        try:
            _run_websocket()
            delay = _RECONNECT_BASE_DELAY  # reset on clean exit
        except Exception as e:
            _connected = False
            _stats["reconnects"] += 1
            logger.warning("Liquidation feed desconectado: %s. Reconectando em %ds...", e, delay)
            time.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_DELAY)

    _connected = False
    logger.info("Liquidation feed encerrado")


def _run_websocket() -> None:
    global _connected

    sock = socket.create_connection((_WS_HOST, 443), timeout=30)
    ctx = ssl.create_default_context()
    ws = ctx.wrap_socket(sock, server_hostname=_WS_HOST)
    ws.settimeout(30)  # read timeout for ping detection

    try:
        _do_handshake(ws)
        _connected = True
        logger.info("Liquidation feed conectado a %s%s", _WS_HOST, _WS_PATH)

        buf = bytearray()
        last_prune = time.time()

        while _running:
            try:
                opcode, data = _read_frame(ws, buf)
            except socket.timeout:
                # No data in 30s — send ping to keep alive
                _send_ping(ws)
                continue

            if opcode == 1:  # text frame
                _process_message(data)
            elif opcode == 9:  # ping
                _send_pong(ws, data)
            elif opcode == 8:  # close
                logger.info("Servidor fechou conexao WebSocket")
                break

            # Periodic prune
            now = time.time()
            if now - last_prune > _PRUNE_INTERVAL:
                _prune_old_entries()
                last_prune = now
    finally:
        _connected = False
        try:
            ws.close()
        except Exception:
            pass


def _do_handshake(ws) -> None:
    """Realiza WebSocket handshake HTTP/1.1 Upgrade."""
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {_WS_PATH} HTTP/1.1\r\n"
        f"Host: {_WS_HOST}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    ws.send(request.encode())

    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = ws.recv(4096)
        if not chunk:
            raise ConnectionError("Conexao fechada durante handshake")
        resp += chunk

    header = resp.split(b"\r\n\r\n")[0].decode()
    if "101" not in header:
        raise ConnectionError(f"Handshake falhou: {header[:200]}")

    # Push leftover bytes back into the buffer is handled by caller


def _read_frame(ws, buf: bytearray) -> tuple[int, bytes]:
    """Le um frame WebSocket completo. Retorna (opcode, payload)."""
    def _ensure(n):
        while len(buf) < n:
            chunk = ws.recv(4096)
            if not chunk:
                raise ConnectionError("Conexao fechada")
            buf.extend(chunk)

    _ensure(2)
    b0, b1 = buf[0], buf[1]
    opcode = b0 & 0x0F
    masked = b1 & 0x80
    length = b1 & 0x7F
    offset = 2

    if length == 126:
        _ensure(4)
        length = struct.unpack(">H", buf[2:4])[0]
        offset = 4
    elif length == 127:
        _ensure(10)
        length = struct.unpack(">Q", buf[2:10])[0]
        offset = 10

    if masked:
        offset += 4  # skip mask key (server frames shouldn't be masked, but handle it)

    _ensure(offset + length)

    if masked:
        mask_key = buf[offset - 4:offset]
        payload = bytearray(buf[offset:offset + length])
        for i in range(length):
            payload[i] ^= mask_key[i % 4]
        data = bytes(payload)
    else:
        data = bytes(buf[offset:offset + length])

    del buf[:offset + length]
    return opcode, data


def _send_frame(ws, opcode: int, payload: bytes = b"") -> None:
    """Envia um frame WebSocket mascarado (client -> server deve ser mascarado)."""
    mask_key = os.urandom(4)
    masked = bytearray(len(payload))
    for i in range(len(payload)):
        masked[i] = payload[i] ^ mask_key[i % 4]

    header = bytearray()
    header.append(0x80 | opcode)  # FIN + opcode

    length = len(payload)
    if length < 126:
        header.append(0x80 | length)  # masked bit + length
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack(">Q", length))

    header.extend(mask_key)
    ws.send(bytes(header) + bytes(masked))


def _send_ping(ws) -> None:
    _send_frame(ws, 0x9)


def _send_pong(ws, data: bytes) -> None:
    _send_frame(ws, 0xA, data)


def _process_message(data: bytes) -> None:
    """Processa um evento de liquidacao do stream."""
    try:
        msg = json.loads(data.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    order = msg.get("o", {})
    symbol = order.get("s", "")
    _stats["total_received"] += 1

    # Filtrar por simbolos que nos interessam
    if symbol not in _symbols:
        return

    side = order.get("S", "")  # BUY = short liq, SELL = long liq
    qty = float(order.get("q", 0))
    price = float(order.get("ap", order.get("p", 0)))

    if qty <= 0 or price <= 0:
        return

    notional = qty * price
    now = time.time()
    event_ms = int(order.get("T") or msg.get("E") or now * 1000)
    _stats["total_tracked"] += 1
    _stats["last_event"] = now

    with _lock:
        _liquidations[symbol].append((now, side, notional))

    # Persistencia opcional (evento-cru). Protegido: nunca derruba o feed.
    if _event_sink is not None:
        try:
            _event_sink(event_ms, symbol, side, qty, price, notional)
        except Exception:
            logger.exception("liquidation event_sink falhou (ignorado)")


def _prune_old_entries() -> None:
    """Remove entradas mais antigas que 2x a janela (margem de seguranca)."""
    cutoff = time.time() - (_window_minutes * 60 * 2)
    with _lock:
        for sym in list(_liquidations.keys()):
            dq = _liquidations[sym]
            while dq and dq[0][0] < cutoff:
                dq.popleft()
            if not dq:
                del _liquidations[sym]
