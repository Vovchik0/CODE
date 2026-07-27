"""
logger
======

Настройка журналирования для приложения. Логи пишутся одновременно:

* в ротационный файл ``minecraft_load_tester.log`` (для последующего анализа);
* в стандартный поток (полезно при запуске из консоли).

GUI подписывается на события журнала не через :mod:`logging`, а через
потокобезопасную очередь событий тестера — так проще раскрашивать строки по
уровню. Тем не менее модуль предоставляет общий логгер, чтобы вся логика
писала в единый файл.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler


#: Уровни, используемые в цветном журнале GUI.
LEVEL_SUCCESS = "SUCCESS"
LEVEL_INFO = "INFO"
LEVEL_WARNING = "WARNING"
LEVEL_ERROR = "ERROR"

#: Соответствие уровней журнала цветам (HEX) для тёмной темы GUI.
LEVEL_COLORS = {
    LEVEL_SUCCESS: "#4caf50",
    LEVEL_INFO: "#64b5f6",
    LEVEL_WARNING: "#ffb74d",
    LEVEL_ERROR: "#ef5350",
}

_DEFAULT_LOG_FILE = "minecraft_load_tester.log"
_configured = False


def setup_logger(
    name: str = "mc_load_tester",
    log_file: str = _DEFAULT_LOG_FILE,
    level: int = logging.INFO,
) -> logging.Logger:
    """Создать (единожды) и вернуть настроенный логгер приложения.

    :param name: имя логгера.
    :param log_file: путь к файлу журнала (ротация по 1 МБ, 3 копии).
    :param level: минимальный уровень логирования.
    :returns: готовый к использованию :class:`logging.Logger`.
    """
    global _configured
    logger = logging.getLogger(name)

    if _configured:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Файловый обработчик с ротацией.
    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except (OSError, IOError):
        # Если каталог недоступен для записи -- не роняем приложение.
        pass

    # Потоковый обработчик (консоль).
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    _configured = True
    return logger


def color_for(level: str) -> str:
    """Вернуть HEX-цвет для уровня журнала (по умолчанию -- INFO)."""
    return LEVEL_COLORS.get(level, LEVEL_COLORS[LEVEL_INFO])


def default_log_path() -> str:
    """Абсолютный путь к файлу журнала по умолчанию."""
    return os.path.abspath(_DEFAULT_LOG_FILE)
