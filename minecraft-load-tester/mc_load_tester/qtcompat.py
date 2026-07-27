"""
qtcompat
========

Слой совместимости Qt-биндингов. Позволяет приложению работать как на
**PyQt5**, так и на **PyQt4** без изменения остального кода.

Приоритет выбора биндинга: **PyQt5 -> PyQt4**. Таким образом, если PyQt4 не
установлен (что типично для современных систем), приложение запускается на
PyQt5.

Ключевое различие, которое скрывает этот модуль: в PyQt5 виджеты вынесены из
``QtGui`` в отдельный модуль ``QtWidgets``, а в PyQt4 они находятся в
``QtGui``. Модуль всегда экспортирует три объекта -- ``QtCore``, ``QtGui`` и
``QtWidgets`` -- поэтому остальной код может единообразно обращаться к виджетам
через ``QtWidgets`` независимо от версии биндинга.

Экспортируемые имена:

* ``QtCore``   -- модуль ядра Qt (сигналы, потоки, перечисления);
* ``QtGui``    -- графические примитивы (шрифты, цвета и т. п.);
* ``QtWidgets``-- виджеты (в PyQt4 указывает на ``QtGui``);
* ``QT_API``   -- строка ``"PyQt5"`` или ``"PyQt4"`` (для диагностики);
* ``exec_app`` -- запуск главного цикла приложения, совместимый с обеими версиями.
"""

from __future__ import annotations


QtCore = None
QtGui = None
QtWidgets = None
QT_API = None

try:
    # --- Предпочтительный вариант: PyQt5 ---
    from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore
    QT_API = "PyQt5"
except ImportError:
    try:
        # --- Запасной вариант: PyQt4 ---
        from PyQt4 import QtCore, QtGui  # type: ignore
        # В PyQt4 виджеты живут в QtGui -- делаем псевдоним, чтобы код,
        # написанный под QtWidgets, работал без изменений.
        QtWidgets = QtGui
        QT_API = "PyQt4"
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise ImportError(
            "Не найден ни PyQt5, ни PyQt4. Установите один из биндингов Qt:\n"
            "  PyQt5 (рекомендуется):  pip install PyQt5\n"
            "  PyQt4 (устаревший):     системный пакет python3-pyqt4"
        ) from exc


def exec_app(app):
    """Запустить главный цикл приложения (совместимо с PyQt4 и PyQt5).

    В PyQt6 метод ``exec_`` переименован в ``exec``; здесь поддерживаются оба
    варианта на случай будущего расширения.
    """
    if hasattr(app, "exec_"):
        return app.exec_()
    return app.exec()


__all__ = ["QtCore", "QtGui", "QtWidgets", "QT_API", "exec_app"]
