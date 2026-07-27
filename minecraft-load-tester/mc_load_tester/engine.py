"""
engine
======

Ядро нагрузочного теста **без зависимости от Qt**. Именно этот модуль выполняет
всю сетевую работу и оркестрацию потоков; и десктопный GUI (PyQt5/PyQt4), и
веб-сервер используют один и тот же движок, обмениваясь с ним данными через
простые callback-функции.

Архитектура потоков:

* :class:`LoadTestEngine.run` -- «дирижёр»: запускает клиентов по расписанию
  (задержка между подключениями + режим Ramp-Up), периодически публикует
  статистику и строки журнала через callback-и. Метод блокирующий, поэтому
  вызывающая сторона обычно запускает его в отдельном потоке.
* Каждое подключение выполняется в отдельном обычном ``threading.Thread``.
  Воркеры не вызывают callback-и напрямую: они складывают события в
  потокобезопасную очередь и обновляют общий :class:`Stats` под блокировкой.
  Дирижёр разбирает очередь и уже из своего потока вызывает ``on_log`` -- так
  callback-и всегда вызываются из одного потока (что важно, например, для
  безопасной эмиссии Qt-сигналов в обёртке).
"""

from __future__ import annotations

import queue
import random
import socket
import string
import threading
import time

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
        """Вернуть согласованный снимок статистики (для GUI, веб-UI и отчётов)."""
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
# Движок нагрузочного теста (Qt-независимый)
# ---------------------------------------------------------------------------
class LoadTestEngine(object):
    """Оркестратор нагрузочного теста.

    :param config: параметры теста.
    :param on_log: callback ``(level, message)`` для событий журнала (опц.).
    :param on_stats: callback ``(snapshot: dict)`` для обновления статистики (опц.).

    Callback-и вызываются только из потока, в котором выполняется :meth:`run`.
    """

    def __init__(self, config: TestConfig, on_log=None, on_stats=None):
        self.config = config
        self.stats = Stats()
        self._stop_event = threading.Event()
        self._events: "queue.Queue" = queue.Queue()
        self._workers: list = []
        self._logger = log_module.setup_logger()
        self._on_log = on_log
        self._on_stats = on_stats

    # -- управление -------------------------------------------------------
    def stop(self) -> None:
        """Запросить остановку теста (прерывает запуск и удержание соединений)."""
        self._stop_event.set()

    def is_stopped(self) -> bool:
        """Была ли запрошена остановка."""
        return self._stop_event.is_set()

    # -- служебные --------------------------------------------------------
    def _emit_log(self, level: str, message: str) -> None:
        """Положить событие в очередь и продублировать в файловый лог."""
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

    def _drain_events(self) -> None:
        """Передать накопленные события журнала в callback ``on_log``."""
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "log" and self._on_log is not None:
                _, level, message = event
                self._on_log(level, message)

    def _emit_stats(self) -> None:
        if self._on_stats is not None:
            self._on_stats(self.stats.snapshot())

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
            client.hold(self.config.hold_time, stop_check=self.is_stopped)
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
            while launched < total and not self.is_stopped():
                wave_no += 1
                wave_size = min(per_wave, total - launched)
                self._emit_log(
                    log_module.LEVEL_INFO,
                    "Ramp-Up: волна %d -- запуск %d клиент(ов)" % (wave_no, wave_size),
                )
                for _ in range(wave_size):
                    if self.is_stopped():
                        break
                    launched += 1
                    self._launch_client(launched)
                    self._sleep_interruptible(self.config.connect_delay)
                if launched < total and not self.is_stopped():
                    self._sleep_interruptible(self.config.ramp_interval)
        else:
            # Обычный режим: клиенты стартуют по одному с фиксированной паузой.
            for index in range(1, total + 1):
                if self.is_stopped():
                    break
                self._launch_client(index)
                self._sleep_interruptible(self.config.connect_delay)

    def _sleep_interruptible(self, seconds: float) -> None:
        """Пауза, которая прерывается при запросе остановки."""
        if seconds <= 0:
            return
        deadline = time.time() + seconds
        while time.time() < deadline and not self.is_stopped():
            time.sleep(min(0.05, max(0.0, deadline - time.time())))

    # -- основной блокирующий цикл ---------------------------------------
    def run(self) -> dict:
        """Выполнить тест целиком. Блокирующий метод.

        :returns: финальный снимок статистики.
        """
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
        while True:
            self._drain_events()

            now = time.time()
            if now - last_stats >= 0.2:
                self._emit_stats()
                last_stats = now

            scheduler_done = not scheduler.is_alive()
            workers_alive = any(w.is_alive() for w in self._workers)
            if scheduler_done and not workers_alive:
                break

            time.sleep(0.05)

        # Финальный разбор очереди и завершающая статистика.
        self._drain_events()
        self.stats.mark_end()

        final = self.stats.snapshot()
        self._emit_stats()
        self._emit_log(
            log_module.LEVEL_INFO,
            "Тест завершён. Успешно: %d, ошибок: %d, время: %.1f c"
            % (final["success"], final["errors"], final["elapsed"]),
        )
        self._drain_events()
        return final
