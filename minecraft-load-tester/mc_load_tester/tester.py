"""
tester
======

Qt-обёртка над Qt-независимым движком :class:`~mc_load_tester.engine.LoadTestEngine`.

Класс :class:`LoadTester` -- это :class:`QThread`, который выполняет тест в
отдельном потоке (не блокируя графический интерфейс) и транслирует события
движка в Qt-сигналы. Вся реальная логика (сеть, потоки, статистика, ramp-up)
находится в :mod:`mc_load_tester.engine` и переиспользуется веб-версией.

Для обратной совместимости имена :func:`random_nickname` и :class:`Stats`
реэкспортируются из движка.
"""

from __future__ import annotations

from .qtcompat import QtCore
from .config import TestConfig
from .engine import LoadTestEngine, Stats, random_nickname  # noqa: F401  (реэкспорт)


class LoadTester(QtCore.QThread):
    """Управляющий поток нагрузочного теста.

    Сигналы (подключаются в GUI):

    * ``log_message(str, str)``  -- (уровень, текст) для цветного журнала;
    * ``stats_updated(dict)``    -- снимок статистики (см. :meth:`Stats.snapshot`);
    * ``finished_test(dict)``    -- финальный снимок статистики по завершении.
    """

    log_message = QtCore.pyqtSignal(str, str)
    stats_updated = QtCore.pyqtSignal(dict)
    finished_test = QtCore.pyqtSignal(dict)

    def __init__(self, config: TestConfig, parent=None):
        super(LoadTester, self).__init__(parent)
        self.config = config
        # Движок вызывает callback-и из потока run() -- то есть из этого
        # QThread. Эмиссия Qt-сигналов из потока QThread безопасна: Qt сам
        # доставляет их в главный поток GUI через очередь.
        self._engine = LoadTestEngine(
            config,
            on_log=lambda level, message: self.log_message.emit(level, message),
            on_stats=lambda snapshot: self.stats_updated.emit(snapshot),
        )
        #: доступ к статистике теста (тот же объект, что и в движке)
        self.stats = self._engine.stats

    def stop(self) -> None:
        """Запросить остановку теста."""
        self._engine.stop()

    def run(self) -> None:
        """Точка входа потока: выполнить тест и сообщить о завершении."""
        final = self._engine.run()
        self.finished_test.emit(final)
