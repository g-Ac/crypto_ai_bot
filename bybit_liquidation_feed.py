"""
Background WebSocket collector de liquidacoes reais da Bybit (linear perp).

Conecta a wss://stream.bybit.com/v5/public/linear, assina allLiquidation.<sym>
e entrega cada liquidacao via callback (set_event_sink). Mesma interface do
liquidation_feed (Binance), pra reuso por scripts/liquidation_collector.py.

Usado porque o WS de futuros da Binance (fstream) e bloqueado neste Pi
(ver memoria binance_futures_ws_blocked). Zero dependencias externas (stdlib).

side entregue = lado da ORDEM de liquidacao reportado pela Bybit (BUY/SELL,
maiusculo). A interpretacao long/short fica na analise.
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

logger = logging.getLogger("bybit_liquidation_feed")

_WS_HOST = "stream.bybit.com"
_WS_PORT = 443
_WS_PATH = "/v5/public/linear"
_PING_INTERVAL = 20            # Bybit espera ping app-level periodico
_READ_TIMEOUT = 15
_RECONNECT_BASE_DELAY = 3
_RECONNECT_MAX_DELAY = 60

_symbols: list[str] = []
_running = False
_connected = False
_event_sink = None
_stats = {"total_received": 0, "total_liq": 0, "reconnects": 0, "last_event": 0.0}


def set_event_sink(fn) -> None:
    """Registra (ou remove com None) o callback de persistencia."""
    global _event_sink
    _event_sink = fn


def init_feed(symbols) -> None:
    """Inicia o collector em background (idempotente)."""
    global _symbols, _running
    _symbols = [s.upper() for s in symbols]
    if _running:
        logger.info("Bybit liquidation feed ja rodando")
        return
    _running = True
    t = threading.Thread(target=_collector_loop, name="bybit-liq-feed", daemon=True)
    t.start()
    logger.info("Bybit liquidation feed iniciado: %d simbolos", len(_symbols))


def stop_feed() -> None:
    global _running
    _running = False


def is_connected() -> bool:
    return _connected


def feed_stats() -> dict:
    return {**_stats, "connected": _connected, "symbols": len(_symbols)}


def _collector_loop() -> None:
    global _connected
    delay = _RECONNECT_BASE_DELAY
    while _running:
        try:
            _run_websocket()
            delay = _RECONNECT_BASE_DELAY
        except Exception as e:
            _connected = False
            _stats["reconnects"] += 1
            logger.warning("Bybit feed desconectado: %s. Reconectando em %ds...", e, delay)
            time.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_DELAY)
    _connected = False
    logger.info("Bybit liquidation feed encerrado")


def _run_websocket() -> None:
    global _connected
    sock = socket.create_connection((_WS_HOST, _WS_PORT), timeout=30)
    ctx = ssl.create_default_context()
    ws = ctx.wrap_socket(sock, server_hostname=_WS_HOST)
    ws.settimeout(_READ_TIMEOUT)
    try:
        leftover = _do_handshake(ws)
        _connected = True
        logger.info("Bybit feed conectado a %s%s", _WS_HOST, _WS_PATH)

        args = [f"allLiquidation.{s}" for s in _symbols]
        _send_text(ws, json.dumps({"op": "subscribe", "args": args}))

        buf = bytearray(leftover)
        last_ping = time.time()
        while _running:
            try:
                opcode, data = _read_frame(ws, buf)
            except socket.timeout:
                _send_text(ws, json.dumps({"op": "ping"}))
                last_ping = time.time()
                continue
            if opcode == 1:
                _process_message(data)
            elif opcode == 9:
                _send_pong(ws, data)
            elif opcode == 8:
                logger.info("Bybit fechou a conexao WebSocket")
                break
            if time.time() - last_ping > _PING_INTERVAL:
                _send_text(ws, json.dumps({"op": "ping"}))
                last_ping = time.time()
    finally:
        _connected = False
        try:
            ws.close()
        except Exception:
            pass


def _do_handshake(ws) -> bytes:
    """Handshake WebSocket. Retorna bytes do 1o frame que vieram junto (leftover)."""
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
    header, _, leftover = resp.partition(b"\r\n\r\n")
    if b"101" not in header.split(b"\r\n")[0]:
        raise ConnectionError(f"Handshake falhou: {header[:200]!r}")
    return leftover


def _read_frame(ws, buf: bytearray):
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
        offset += 4
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
    mask_key = os.urandom(4)
    masked = bytearray(len(payload))
    for i in range(len(payload)):
        masked[i] = payload[i] ^ mask_key[i % 4]
    header = bytearray()
    header.append(0x80 | opcode)
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack(">Q", length))
    header.extend(mask_key)
    ws.send(bytes(header) + bytes(masked))


def _send_text(ws, text: str) -> None:
    _send_frame(ws, 0x1, text.encode())


def _send_pong(ws, data: bytes) -> None:
    _send_frame(ws, 0xA, data)


def _process_message(data: bytes) -> None:
    """Processa uma mensagem do WS. So liquidacoes (allLiquidation) viram eventos."""
    try:
        msg = json.loads(data.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    _stats["total_received"] += 1

    topic = msg.get("topic", "")
    if not topic.startswith("allLiquidation"):
        return  # ack de subscribe, pong, etc.

    for item in msg.get("data", []) or []:
        try:
            symbol = item["s"]
            side = str(item["S"]).upper()
            qty = float(item["v"])
            price = float(item["p"])
            event_ms = int(item.get("T") or msg.get("ts") or time.time() * 1000)
        except (KeyError, ValueError, TypeError):
            continue
        if qty <= 0 or price <= 0:
            continue
        notional = qty * price
        _stats["total_liq"] += 1
        _stats["last_event"] = time.time()
        if _event_sink is not None:
            try:
                _event_sink(event_ms, symbol, side, qty, price, notional)
            except Exception:
                logger.exception("bybit event_sink falhou (ignorado)")
