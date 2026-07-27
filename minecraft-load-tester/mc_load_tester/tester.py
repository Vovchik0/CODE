"""
tester
======

Ядро нагрузочного теста. Класс :class:`LoadTester` -- это :class:`QThread`,
который управляет пулом подключений к серверу, не блокируя графический
интерфейс.

Архитектура потоков:

* :class:`LoadTester` (QThread) -- «дирижёр»: запускает клиентов по расписанию
  (с учётом задержки между подключениями и режима Ramp-Up), периодически
  публикует статистику и раскрашенные строки журнала через сигналы Qt.
* Каждое подключение выполняется в отдельном обычном ``threading.Thread``
  (рабочем воркере). Воркеры не трогают Qt напрямую: они складывают события в
  потокобезопасную очередь и обновляют общий объект :class:`Stats` под
  блокировкой. Дирижёр разбирает очередь и уже из своего потока эмитит сигналы.

Такой подход исключает эмиссию Qt-сигналов из десятков сторонних потоков и
делает обновление GUI безопасным.
"""

from __future__ import annotations

import queue
import random
import socket
import string
import threading
import time

from PyQt4 import QtCore

from . import logger as log_module
from .config import TestConfig
from .protocol import MinecraftClient, ProtocolError


# ---------------------------------------------------------------------------
# Генерация никнеймов
# ---------------------------------------------------------------------------
_NICK_ALPHABET = string.ascii_letters + string.digits + "_"


def random_nickname(prefix: str = "", max_length: int = 16) -> str:
    """Сгенерировать случайный ник, начинающийся с ``prefix``.

    Длина ника ограничена ``max_length`` (16 -- лимит Minecraft). Если префикс
    длиннее лимита, он усекается.

    :param prefix: префикс ника (например, ``"LoadBot"``).
    :param max_length: максимальная длина результата.
    """
    prefix = (prefix or "")[:max_length]
    remaining = max_length - len(prefix)
    if remaining <= 0:
        return prefix
    suffix = "".join(random.choice(_NICK_ALPHABET) for _ in range(remaining))
    return prefix + suffix


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------
class Stats(object):
    """Потокобезопасный контейнер агрегированной статистики теста."""

    def __init__(self):
        self._lock = threading.Lock()
        self.success = 0            # успешно вошедшие клиенты
        self.errors = 0            # клиенты, завершившиеся ошибкой
        self.active = 0            # клиенты с открытым соединением сейчас
        self.total_connect_time = 0.0  # сумма времён подключения (для среднего)
        self.start_time = 0.0
        self.end_time = 0.0

    def mark_start(self) -> None:
        with self._lock:
            self.start_time = time.time()
            self.end_time = 0.0

    def mark_end(self) -> None:
        with self._lock:
            self.end_time = time.time()

    def on_success(self, connect_time: float) -> None:
        with self._lock:
            self.success += 1
            self.active += 1
            self.total_connect_time += connect_time

    def on_error(self) -> None:
        with self._lock:
            self.errors += 1

    def on_disconnect(self) -> None:
        with self._lock:
            if self.active > 0:
                self.active -= 1

    def snapshot(self) -> dict:
        """Вернуть согласованный снимок статистики (для GUI и отчётов)."""
        with self._lock:
            avg = (self.total_connect_time / self.success) if self.success else 0.0
            end = self.end_time or time.time()
            elapsed = (end - self.start_time) if self.start_time else 0.0
            return {
                "success": self.success,
                "errors": self.errors,
                "active": self.active,
                "avg_connect_time": avg,
                "elapsed": elapsed,
                "total": self.success + self.errors,
            }


# ---------------------------------------------------------------------------
# Дирижёр нагрузочного теста
# ---------------------------------------------------------------------------
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
        self.stats = Stats()
        self._stop_event = threading.Event()
        self._events: "queue.Queue" = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._logger = log_module.setup_logger()

    # -- управление -------------------------------------------------------
    def stop(self) -> None:
        """Запросить остановку теста (прерывает запуск и удержание соединений)."""
        self._stop_event.set()

    def _stopped(self) -> bool:
        return self._stop_event.is_set()

    def _emit_log(self, level: str, message: str) -> None:
        """Положить сообщение в очередь и продублировать в файловый лог."""
        self._events.put(("log", level, message))
        try:
            if level == log_module.LEVEL_ERROR:
                self._logger.error(message)
            elif level == log_module.LEVEL_WARNING:
                self._logger.warning(message)
            else:
                self._logger.info(message)
        except Exception:
            pass

    # -- рабочий воркер (обычный поток) ----------------------------------
    def _worker(self, index: int, username: str) -> None:
        """Жизненный цикл одного тестового клиента."""
        client = MinecraftClient(
            self.config.host,
            self.config.port,
            self.config.protocol,
            timeout=self.config.socket_timeout,
        )
        try:
            connect_time = client.login(username)
            self.stats.on_success(connect_time)
            self._emit_log(
                log_module.LEVEL_SUCCESS,
                "Клиент #%d (%s) подключён за %.3f c" % (index, username, connect_time),
            )
            # Удерживаем соединение, реагируя на запрос остановки.
            client.hold(self.config.hold_time, stop_check=self._stopped)
        except (socket.timeout,) as exc:
            self.stats.on_error()
            self._emit_log(
                log_module.LEVEL_ERROR,
                "Клиент #%d (%s): таймаут подключения (%s)" % (index, username, exc),
            )
        except (socket.error, ProtocolError, OSError) as exc:
            self.stats.on_error()
            self._emit_log(
                log_module.LEVEL_ERROR,
                "Клиент #%d (%s): ошибка -- %s" % (index, username, exc),
            )
        finally:
            was_connected = client.sock is not None
            client.close()
            if was_connected:
                self.stats.on_disconnect()

    # -- расписание запуска ----------------------------------------------
    def _launch_client(self, index: int) -> None:
        username = random_nickname(self.config.nick_prefix)
        thread = threading.Thread(
            target=self._worker, args=(index, username), name="mc-client-%d" % index
        )
        thread.daemon = True
        thread.start()
        self._workers.append(thread)

    def _run_schedule(self) -> None:
        """Запустить всех клиентов согласно настройкам (delay + ramp-up)."""
        total = self.config.client_count

        if self.config.ramp_up and self.config.ramp_steps > 1:
            # Делим клиентов на волны и наращиваем нагрузку постепенно.
            steps = max(1, self.config.ramp_steps)
            per_wave = max(1, (total + steps - 1) // steps)
            launched = 0
            wave_no = 0
            while launched < total and not self._stopped():
                wave_no += 1
                wave_size = min(per_wave, total - launched)
                self._emit_log(
                    log_module.LEVEL_INFO,
                    "Ramp-Up: волна %d -- запуск %d клиент(ов)" % (wave_no, wave_size),
                )
                for _ in range(wave_size):
                    if self._stopped():
                        break
                    launched += 1
                    self._launch_client(launched)
                    self._sleep_interruptible(self.config.connect_delay)
                if launched < total and not self._stopped():
                    self._sleep_interruptible(self.config.ramp_interval)
        else:
            # Обычный режим: клиенты стартуют по одному с фиксированной паузой.
            for index in range(1, total + 1):
                if self._stopped():
                    break
                self._launch_client(index)
                self._sleep_interruptible(self.config.connect_delay)

    def _sleep_interruptible(self, seconds: float) -> None:
        """Пауза, которая прерывается при запросе остановки."""
        if seconds <= 0:
            return
        deadline = time.time() + seconds
        while time.time() < deadline and not self._stopped():
            time.sleep(min(0.05, max(0.0, deadline - time.time())))

    # -- основной цикл QThread -------------------------------------------
    def run(self) -> None:
        """Точка входа потока: запуск клиентов, публикация статистики, финал."""
        self.stats.mark_start()
        cfg = self.config
        self._emit_log(
            log_module.LEVEL_INFO,
            "Старт теста: %s:%d, версия %s (протокол %d), клиентов: %d"
            % (cfg.host, cfg.port, cfg.version, cfg.protocol, cfg.client_count),
        )

        # Планировщик запуска работает в отдельном потоке, чтобы основной цикл
        # мог параллельно разбирать очередь событий и обновлять статистику.
        scheduler = threading.Thread(target=self._run_schedule, name="mc-scheduler")
        scheduler.daemon = True
        scheduler.start()

        last_stats = 0.0
        # Крутимся, пока планировщик работает или живы воркеры (и нет остановки).
        while True:
            self._drain_events()

            now = time.time()
            if now - last_stats >= 0.2:
                self.stats_updated.emit(self.stats.snapshot())
                last_stats = now

            scheduler_done = not scheduler.is_alive()
            workers_alive = any(w.is_alive() for w in self._workers)
            if scheduler_done and not workers_alive:
                break
            if self._stopped() and scheduler_done and not workers_alive:
                break

            self.msleep(50)

        # Небольшая пауза на закрытие сокетов и финальный разбор очереди.
        self._drain_events()
        self.stats.mark_end()

        final = self.stats.snapshot()
        self.stats_updated.emit(final)
        self._emit_log(
            log_module.LEVEL_INFO,
            "Тест завершён. Успешно: %d, ошибок: %d, время: %.1f c"
            % (final["success"], final["errors"], final["elapsed"]),
        )
        self._drain_events()
        self.finished_test.emit(final)

    def _drain_events(self) -> None:
        """Переложить накопленные события из очереди в Qt-сигналы."""
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "log":
                _, level, message = event
                self.log_message.emit(level, message)
