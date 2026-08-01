"""
engine
======

Ядро нагрузочного теста **без зависимости от Qt**. Именно этот модуль выполняет
всю сетевую работу и оркестрацию потоков; и десктопный GUI (PyQt5/PyQt4), и
веб-сервер используют один и тот же движок, обмениваясь с ним данными через
простые callback-функции.

Архитектура потоков:

* :meth:`LoadTestEngine.run` -- «дирижёр»: запускает клиентов по расписанию
  (задержка между подключениями + Ramp-Up), с ограничением одновременных
  соединений (``max_concurrency``), периодически публикует статистику и строки
  журнала через callback-и. Метод блокирующий -- обычно вызывается в отдельном
  потоке.
* Каждое подключение выполняется в отдельном ``threading.Thread``. Воркеры не
  вызывают callback-и напрямую: они складывают события в потокобезопасную
  очередь и обновляют общий :class:`Stats` под блокировкой. Дирижёр разбирает
  очередь и вызывает ``on_log`` из своего потока -- так callback-и всегда
  приходят из одного потока (важно, например, для безопасной эмиссии
  Qt-сигналов в обёртке).
"""

from __future__ import annotations

import errno
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
    """
    prefix = (prefix or "")[:max_length]
    remaining = max_length - len(prefix)
    if remaining <= 0:
        return prefix
    suffix = "".join(random.choice(_NICK_ALPHABET) for _ in range(remaining))
    return prefix + suffix


# ---------------------------------------------------------------------------
# Классификация ошибок и перцентили
# ---------------------------------------------------------------------------
def classify_error(exc: BaseException) -> str:
    """Определить категорию ошибки подключения (для наглядной статистики)."""
    if isinstance(exc, socket.gaierror):
        return "dns"
    if isinstance(exc, ProtocolError):
        return "protocol"
    # Встроенные подклассы OSError надёжнее, чем errno (кроссплатформенно).
    if isinstance(exc, ConnectionRefusedError):
        return "refused"
    if isinstance(exc, ConnectionResetError):
        return "reset"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, OSError):
        code = getattr(exc, "errno", None)
        if code == errno.ECONNREFUSED:
            return "refused"
        if code in (errno.ECONNRESET, errno.EPIPE):
            return "reset"
        if code in (errno.ETIMEDOUT,):
            return "timeout"
        if code in (errno.ENETUNREACH, errno.EHOSTUNREACH):
            return "unreachable"
        return "other"
    return "other"


def percentile(sorted_values: list, q: float) -> float:
    """Линейно-интерполированный перцентиль ``q`` (0..1) для отсортированного списка."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = q * (len(sorted_values) - 1)
    low = int(idx)
    high = min(low + 1, len(sorted_values) - 1)
    frac = idx - low
    return sorted_values[low] * (1.0 - frac) + sorted_values[high] * frac


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------
class Stats(object):
    """Потокобезопасный контейнер агрегированной статистики теста.

    Помимо счётчиков хранит все времена подключений (для перцентилей) и разбивку
    ошибок по категориям.
    """

    #: предел числа хранимых замеров времени (защита от роста памяти)
    MAX_SAMPLES = 200000

    def __init__(self):
        self._lock = threading.Lock()
        self.success = 0
        self.errors = 0
        self.active = 0
        self.peak_active = 0
        self.total_connect_time = 0.0
        self.connect_times = []          # список времён подключения (сек)
        self.errors_by_type = {}         # категория -> количество
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
            if self.active > self.peak_active:
                self.peak_active = self.active
            self.total_connect_time += connect_time
            if len(self.connect_times) < self.MAX_SAMPLES:
                self.connect_times.append(connect_time)

    def on_error(self, category: str = "other") -> None:
        with self._lock:
            self.errors += 1
            self.errors_by_type[category] = self.errors_by_type.get(category, 0) + 1

    def on_disconnect(self) -> None:
        with self._lock:
            if self.active > 0:
                self.active -= 1

    def snapshot(self) -> dict:
        """Согласованный снимок статистики (для GUI, веб-UI и отчётов)."""
        with self._lock:
            times = sorted(self.connect_times)
            success = self.success
            avg = (self.total_connect_time / success) if success else 0.0
            end = self.end_time or time.time()
            elapsed = (end - self.start_time) if self.start_time else 0.0
            rps = (success / elapsed) if elapsed > 0 else 0.0
            return {
                "success": success,
                "errors": self.errors,
                "active": self.active,
                "peak_active": self.peak_active,
                "avg_connect_time": avg,
                "min_connect_time": times[0] if times else 0.0,
                "max_connect_time": times[-1] if times else 0.0,
                "p50_connect_time": percentile(times, 0.50),
                "p95_connect_time": percentile(times, 0.95),
                "p99_connect_time": percentile(times, 0.99),
                "elapsed": elapsed,
                "rps": rps,
                "total": success + self.errors,
                "errors_by_type": dict(self.errors_by_type),
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
        self._logger = log_module.setup_logger()
        self._on_log = on_log
        self._on_stats = on_stats

        # Ограничение одновременных соединений (0 -- без ограничения).
        limit = max(0, int(getattr(config, "max_concurrency", 0)))
        self._semaphore = threading.BoundedSemaphore(limit) if limit > 0 else None

        # Счётчики живых воркеров (вместо неограниченно растущего списка потоков).
        self._counter_lock = threading.Lock()
        self._spawned = 0
        self._finished = 0

    # -- управление -------------------------------------------------------
    def stop(self) -> None:
        """Запросить остановку теста (прерывает запуск и удержание соединений)."""
        self._stop_event.set()

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    # -- служебные --------------------------------------------------------
    def _emit_log(self, level: str, message: str) -> None:
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

    def _acquire_slot(self) -> bool:
        """Занять слот параллелизма, прерываясь при остановке. False -- если стоп."""
        if self._semaphore is None:
            return not self.is_stopped()
        while not self.is_stopped():
            if self._semaphore.acquire(timeout=0.1):
                return True
        return False

    def _release_slot(self) -> None:
        if self._semaphore is not None:
            try:
                self._semaphore.release()
            except ValueError:
                pass

    # -- рабочий воркер (обычный поток) ----------------------------------
    def _worker(self, index: int, username: str) -> None:
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
            client.hold(self.config.hold_time, stop_check=self.is_stopped)
        except Exception as exc:  # классифицируем и учитываем любую ошибку соединения
            category = classify_error(exc)
            self.stats.on_error(category)
            self._emit_log(
                log_module.LEVEL_ERROR,
                "Клиент #%d (%s): ошибка [%s] -- %s" % (index, username, category, exc),
            )
        finally:
            was_connected = client.sock is not None
            client.close()
            if was_connected:
                self.stats.on_disconnect()
            self._release_slot()
            with self._counter_lock:
                self._finished += 1

    def _alive_count(self) -> int:
        with self._counter_lock:
            return self._spawned - self._finished

    # -- расписание запуска ----------------------------------------------
    def _launch_client(self, index: int) -> None:
        username = random_nickname(self.config.nick_prefix)
        thread = threading.Thread(
            target=self._worker, args=(index, username), name="mc-client-%d" % index
        )
        thread.daemon = True
        with self._counter_lock:
            self._spawned += 1
        thread.start()

    def _run_schedule(self) -> None:
        total = self.config.client_count

        if self.config.ramp_up and self.config.ramp_steps > 1:
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
                    if not self._acquire_slot():
                        return
                    launched += 1
                    self._launch_client(launched)
                    self._sleep_interruptible(self.config.connect_delay)
                if launched < total and not self.is_stopped():
                    self._sleep_interruptible(self.config.ramp_interval)
        else:
            index = 0
            while index < total and not self.is_stopped():
                if not self._acquire_slot():
                    return
                index += 1
                self._launch_client(index)
                self._sleep_interruptible(self.config.connect_delay)

    def _sleep_interruptible(self, seconds: float) -> None:
        if seconds <= 0:
            return
        deadline = time.time() + seconds
        while time.time() < deadline and not self.is_stopped():
            time.sleep(min(0.05, max(0.0, deadline - time.time())))

    # -- основной блокирующий цикл ---------------------------------------
    def run(self) -> dict:
        """Выполнить тест целиком. Блокирующий метод. Возвращает финальную статистику."""
        self.stats.mark_start()
        cfg = self.config
        limit_txt = ("лимит %d" % cfg.max_concurrency) if getattr(cfg, "max_concurrency", 0) else "без лимита"
        self._emit_log(
            log_module.LEVEL_INFO,
            "Старт теста: %s:%d, версия %s (протокол %d), клиентов: %d (%s одновременно)"
            % (cfg.host, cfg.port, cfg.version, cfg.protocol, cfg.client_count, limit_txt),
        )

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

            if not scheduler.is_alive() and self._alive_count() <= 0:
                break

            time.sleep(0.05)

        self._drain_events()
        self.stats.mark_end()

        final = self.stats.snapshot()
        self._emit_stats()
        self._emit_log(
            log_module.LEVEL_INFO,
            "Тест завершён. Успешно: %d, ошибок: %d, пик: %d, время: %.1f c, ~%.1f подкл/с"
            % (final["success"], final["errors"], final["peak_active"],
               final["elapsed"], final["rps"]),
        )
        self._drain_events()
        return final
