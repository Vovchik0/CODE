#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Точка входа приложения Minecraft Load Tester.

Запуск::

    python main.py

Приложение открывает графический интерфейс (PyQt5 или PyQt4) для нагрузочного
тестирования СОБСТВЕННОГО Minecraft-сервера: проверки производительности,
стабильности и совместимости версий.

Биндинг Qt выбирается автоматически: сначала PyQt5, при его отсутствии --
PyQt4 (см. :mod:`mc_load_tester.qtcompat`).
"""

from __future__ import annotations

import sys

from mc_load_tester.qtcompat import QtWidgets, QT_API, exec_app
from mc_load_tester.gui import MainWindow
from mc_load_tester.logger import setup_logger


def main() -> int:
    """Инициализировать логгер, создать окно и запустить цикл событий Qt."""
    logger = setup_logger()
    logger.info("Запуск GUI на биндинге %s", QT_API)

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Minecraft Load Tester")

    window = MainWindow()
    window.show()

    return exec_app(app)


if __name__ == "__main__":
    sys.exit(main())
