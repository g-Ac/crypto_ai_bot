"""
Configuracao de logging para o sistema de scalping.

Cria loggers estruturados para cada modulo com output
em arquivo e console. Otimizado para Raspberry Pi
(rotacao de logs, tamanho limitado).
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from runtime_config import LOG_DIR, ensure_runtime_dirs

ensure_runtime_dirs()

_initialized = False


def setup_scalping_logging(level: int = logging.INFO) -> None:
    """
    Configura logging para todos os modulos de scalping.

    Cria um arquivo rotativo (max 5MB, 3 backups) para economizar
    espaco no Raspberry Pi.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    log_file = os.path.join(LOG_DIR, "scalping.log")

    # Formatter compacto
    fmt = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler com rotacao
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)

    # Console handler (menos verbose)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.WARNING)

    # Configurar todos os loggers de scalping
    for name in [
        "scalping",
        "scalping.data",
        "scalping.risk",
        "scalping.volume_breakout",
        "scalping.rsi_bb",
        "scalping.ema_crossover",
        "scalping.confluence",
        "scalping.trader",
    ]:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.propagate = False
