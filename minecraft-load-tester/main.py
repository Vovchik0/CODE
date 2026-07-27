#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Точка входа приложения Minecraft Load Tester.

Запуск::

    python main.py

Приложение открывает графический интерфейс (PyQt4) для нагрузочного
тестирования СОБСТВЕННОГО Minecraft-сервера: проверки производительности,
стабильности и совместимости версий.
"""

from __future__ import annotations

import sys

from PyQt4 import QtGui

from mc_load_tester.gui import MainWindow
from mc_load_tester.logger import setup_logger


def main() -> int:
    """Инициализировать логгер, создать окно и запустить цикл событий Qt."""
    setup_logger()

    app = QtGui.QApplication(sys.argv)
    app.setApplicationName("Minecraft Load Tester")

    window = MainWindow()
    window.show()

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
