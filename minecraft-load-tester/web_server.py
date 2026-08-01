#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
web_server
==========

Веб-версия Minecraft Load Tester для управления с телефона (или любого
браузера). Сервер запускается на машине, где вы хотите генерировать нагрузку
(ПК, VPS или сам телефон через Termux), а тест управляется из браузера по
мобильному интерфейсу.

Реализация использует **только стандартную библиотеку Python** (без Flask и
прочих зависимостей) и переиспользует то же ядро теста
:class:`mc_load_tester.engine.LoadTestEngine`, что и десктопный GUI.

Запуск::

    python web_server.py                      # http://0.0.0.0:8000
    python web_server.py --port 8080
    python web_server.py --token МОЙ_СЕКРЕТ    # защита доступа токеном

После запуска откройте на телефоне ``http://<IP-компьютера>:8000``
(при токене -- ``…:8000/?token=МОЙ_СЕКРЕТ``). Компьютер и телефон должны быть в
одной сети.

HTTP API:

* ``GET  /``                    -- мобильная веб-страница;
* ``GET  /api/meta``            -- версии Minecraft и значения по умолчанию;
* ``POST /api/start``           -- запуск теста (JSON-конфигурация в теле);
* ``POST /api/stop``            -- остановка текущего теста;
* ``GET  /api/status?since=N``  -- статистика + новые строки журнала;
* ``GET  /api/report?format=json|csv`` -- скачать отчёт.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from mc_load_tester import logger as log_module
from mc_load_tester import reports
from mc_load_tester import status as status_module
from mc_load_tester import updater
from mc_load_tester.config import (
    MINECRAFT_VERSIONS,
    DEFAULT_VERSION,
    TestConfig,
    protocol_for,
)
from mc_load_tester.engine import LoadTestEngine

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_WEBAPP_DIR = os.path.join(_PROJECT_DIR, "webapp")
_MAX_LOG_LINES = 5000


# ---------------------------------------------------------------------------
# Менеджер теста (один активный тест на сервер)
# ---------------------------------------------------------------------------
class TestManager(object):
    """Хранит состояние текущего/последнего теста и управляет движком.

    Потокобезопасен: движок выполняется в фоновом потоке, а HTTP-обработчики
    читают состояние под общей блокировкой.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._engine = None
        self._thread = None
        self.running = False
        self.finished = False
        self.config = None            # type: TestConfig | None
        self.stats = {}
        self.log = []                 # список dict {time, level, message}

    def start(self, config: TestConfig) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("Тест уже выполняется")
            self.config = config
            self.stats = {}
            self.log = []
            self.finished = False
            self.running = True
            self._engine = LoadTestEngine(
                config, on_log=self._on_log, on_stats=self._on_stats
            )
            self._thread = threading.Thread(target=self._run, name="web-test", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            final = self._engine.run()
            with self._lock:
                self.stats = final
        finally:
            with self._lock:
                self.running = False
                self.finished = True

    def _on_log(self, level: str, message: str) -> None:
        with self._lock:
            self.log.append(
                {"time": time.strftime("%H:%M:%S"), "level": level, "message": message}
            )
            if len(self.log) > _MAX_LOG_LINES:
                self.log = self.log[-_MAX_LOG_LINES:]

    def _on_stats(self, snapshot: dict) -> None:
        with self._lock:
            self.stats = snapshot

    def stop(self) -> None:
        with self._lock:
            engine = self._engine
        if engine is not None:
            engine.stop()

    def status(self, since: int = 0) -> dict:
        with self._lock:
            since = max(0, min(since, len(self.log)))
            return {
                "running": self.running,
                "finished": self.finished,
                "stats": self.stats,
                "log": self.log[since:],
                "log_total": len(self.log),
                "config": self.config.to_dict() if self.config else None,
            }

    def report_payload(self):
        """Вернуть данные для формирования отчёта: (config, stats, log_lines)."""
        with self._lock:
            log_lines = [(item["level"], item["message"]) for item in self.log]
            config = self.config or TestConfig()
            return config, dict(self.stats), log_lines


MANAGER = TestManager()


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def _qt_available() -> bool:
    """Доступен ли какой-либо биндинг Qt (для отображения в интерфейсе)."""
    import importlib.util
    return bool(
        importlib.util.find_spec("PyQt5") or importlib.util.find_spec("PyQt4")
    )


def _config_from_dict(data: dict) -> TestConfig:
    """Построить :class:`TestConfig` из данных запроса с безопасными значениями."""
    return TestConfig(
        host=str(data.get("host", "127.0.0.1")).strip() or "127.0.0.1",
        port=int(data.get("port", 25565)),
        version=str(data.get("version", DEFAULT_VERSION)),
        client_count=max(1, int(data.get("client_count", 10))),
        connect_delay=max(0.0, float(data.get("connect_delay", 0.1))),
        hold_time=max(0.0, float(data.get("hold_time", 5.0))),
        nick_prefix=str(data.get("nick_prefix", "LoadBot")).strip(),
        ramp_up=bool(data.get("ramp_up", False)),
        ramp_steps=max(1, int(data.get("ramp_steps", 5))),
        ramp_interval=max(0.0, float(data.get("ramp_interval", 1.0))),
        max_concurrency=max(0, int(data.get("max_concurrency", 0))),
    )


def _local_ips() -> list:
    """Попытаться определить локальные IP-адреса для подсказки пользователю."""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


# ---------------------------------------------------------------------------
# HTTP-обработчик
# ---------------------------------------------------------------------------
def _restart_process():
    """Перезапустить процесс сервера с теми же аргументами (после обновления)."""
    def _do():
        time.sleep(0.6)  # дать HTTP-ответу уйти
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except OSError:
            pass
    threading.Thread(target=_do, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    #: токен доступа задаётся при запуске сервера (класс-атрибут)
    access_token = ""
    #: разрешено ли применять обновления через API (флаг --allow-update / --auto-update)
    allow_update = False

    server_version = "MinecraftLoadTester/1.0"

    # -- служебные ответы -------------------------------------------------
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body, content_type, status=200, download_name=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if download_name:
            self.send_header(
                "Content-Disposition", 'attachment; filename="%s"' % download_name
            )
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self, query) -> bool:
        """Проверить токен (если он задан на сервере)."""
        if not self.access_token:
            return True
        token = (query.get("token", [""])[0]) or self.headers.get("X-Auth-Token", "")
        return token == self.access_token

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- заглушаем стандартный шумный лог ---------------------------------
    def log_message(self, fmt, *args):
        pass

    # -- маршрутизация ----------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            return self._serve_page()

        # Статические ресурсы PWA (иконка, манифест, service worker).
        static_types = {
            "/manifest.webmanifest": "application/manifest+json; charset=utf-8",
            "/sw.js": "application/javascript; charset=utf-8",
            "/icon.svg": "image/svg+xml; charset=utf-8",
        }
        if path in static_types:
            return self._serve_static(os.path.basename(path), static_types[path])

        if path.startswith("/api/") and not self._authorized(query):
            return self._send_json({"error": "Требуется корректный токен доступа."}, 403)

        if path == "/api/meta":
            return self._send_json({
                "versions": [
                    {"label": label, "protocol": proto}
                    for label, proto in MINECRAFT_VERSIONS.items()
                ],
                "default_version": DEFAULT_VERSION,
                "qt_available": _qt_available(),
            })

        if path == "/api/status":
            since = 0
            try:
                since = int(query.get("since", ["0"])[0])
            except ValueError:
                since = 0
            return self._send_json(MANAGER.status(since))

        if path == "/api/report":
            return self._serve_report(query)

        if path == "/api/ping":
            return self._serve_ping(query)

        if path == "/api/version":
            fetch = query.get("check", ["0"])[0] in ("1", "true", "yes")
            info = updater.status(_PROJECT_DIR, fetch=fetch)
            info["allow_update"] = self.allow_update
            return self._send_json(info)

        return self._send_json({"error": "Не найдено"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.startswith("/api/") and not self._authorized(query):
            return self._send_json({"error": "Требуется корректный токен доступа."}, 403)

        if path == "/api/start":
            data = self._read_json_body()
            try:
                config = _config_from_dict(data)
            except (ValueError, TypeError) as exc:
                return self._send_json({"error": "Некорректные параметры: %s" % exc}, 400)
            try:
                MANAGER.start(config)
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 409)
            return self._send_json({"ok": True})

        if path == "/api/stop":
            MANAGER.stop()
            return self._send_json({"ok": True})

        if path == "/api/update":
            return self._serve_update()

        return self._send_json({"error": "Не найдено"}, 404)

    def _serve_update(self):
        if not self.allow_update:
            return self._send_json(
                {"ok": False, "error": "Обновление через API отключено. "
                 "Запустите сервер с --allow-update или --auto-update."}, 403)
        if MANAGER.running:
            return self._send_json(
                {"ok": False, "error": "Идёт тест -- остановите его перед обновлением."}, 409)
        result = updater.pull(_PROJECT_DIR)
        if result.get("updated"):
            # Изменения применены -> перезапускаем сервер, чтобы подхватить их.
            result["restarting"] = True
            self._send_json(result)
            _restart_process()
            return
        return self._send_json(result)

    # -- конкретные ресурсы ----------------------------------------------
    def _serve_page(self):
        index_path = os.path.join(_WEBAPP_DIR, "index.html")
        try:
            with open(index_path, "rb") as fh:
                body = fh.read()
        except (OSError, IOError):
            return self._send_bytes(b"index.html not found", "text/plain; charset=utf-8", 500)
        return self._send_bytes(body, "text/html; charset=utf-8")

    def _serve_static(self, filename, content_type):
        file_path = os.path.join(_WEBAPP_DIR, filename)
        try:
            with open(file_path, "rb") as fh:
                body = fh.read()
        except (OSError, IOError):
            return self._send_bytes(b"not found", "text/plain; charset=utf-8", 404)
        return self._send_bytes(body, content_type)

    def _serve_ping(self, query):
        host = (query.get("host", [""])[0] or "").strip()
        if not host:
            return self._send_json({"error": "Не указан адрес сервера."}, 400)
        try:
            port = int(query.get("port", ["25565"])[0])
        except ValueError:
            port = 25565
        version = query.get("version", [DEFAULT_VERSION])[0]
        protocol = protocol_for(version)
        try:
            result = status_module.ping(host, port, protocol, timeout=5.0)
            return self._send_json(result)
        except Exception as exc:  # недоступность/таймаут/ошибка протокола
            return self._send_json(
                {"online": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            )

    def _serve_report(self, query):
        fmt = (query.get("format", ["json"])[0] or "json").lower()
        config, stats, log_lines = MANAGER.report_payload()
        suffix = ".csv" if fmt == "csv" else ".json"
        name = "mc_load_report_%s%s" % (time.strftime("%Y%m%d_%H%M%S"), suffix)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.close()
        try:
            if fmt == "csv":
                reports.save_csv(tmp.name, config, stats, log_lines)
                ctype = "text/csv; charset=utf-8"
            else:
                reports.save_json(tmp.name, config, stats, log_lines)
                ctype = "application/json; charset=utf-8"
            with open(tmp.name, "rb") as fh:
                body = fh.read()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        return self._send_bytes(body, ctype, download_name=name)


# ---------------------------------------------------------------------------
# Фоновое авто-обновление
# ---------------------------------------------------------------------------
def _start_auto_update(interval_min: float, logger) -> None:
    """Периодически проверять обновления и применять их, когда тест не идёт."""
    interval = max(1.0, interval_min) * 60.0

    def loop():
        while True:
            time.sleep(interval)
            try:
                info = updater.status(_PROJECT_DIR, fetch=True)
                if info.get("update_available") and not MANAGER.running:
                    result = updater.pull(_PROJECT_DIR)
                    if result.get("updated"):
                        logger.info("Авто-обновление применено (%s) -- перезапуск сервера",
                                    result.get("commit"))
                        os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception:
                pass  # обновление не должно ронять сервер

    thread = threading.Thread(target=loop, name="auto-update", daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Веб-сервер Minecraft Load Tester (управление с телефона/браузера)."
    )
    parser.add_argument("--host", default="0.0.0.0",
                        help="Интерфейс для прослушивания (по умолчанию 0.0.0.0 -- все).")
    parser.add_argument("--port", type=int, default=8000,
                        help="Порт (по умолчанию 8000).")
    parser.add_argument("--token", default=os.environ.get("MC_LT_TOKEN", ""),
                        help="Необязательный токен доступа (или переменная MC_LT_TOKEN).")
    parser.add_argument("--allow-update", action="store_true",
                        help="Разрешить применять обновления через API/кнопку в интерфейсе.")
    parser.add_argument("--auto-update", type=float, default=0.0, metavar="МИН",
                        help="Автоматически проверять и применять обновления каждые N минут "
                             "(0 -- выключено; включает --allow-update).")
    args = parser.parse_args()

    logger = log_module.setup_logger()
    Handler.access_token = args.token
    Handler.allow_update = bool(args.allow_update or args.auto_update > 0)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True

    token_suffix = ("/?token=" + args.token) if args.token else "/"
    print("=" * 60)
    print(" Minecraft Load Tester -- веб-сервер запущен")
    print(" Локально:   http://127.0.0.1:%d%s" % (args.port, token_suffix))
    for ip in _local_ips():
        print(" В сети:     http://%s:%d%s   <- откройте на телефоне" % (ip, args.port, token_suffix))
    if not args.token:
        print(" ВНИМАНИЕ: доступ без токена. Для защиты используйте --token СЕКРЕТ")
    if args.auto_update > 0:
        print(" Авто-обновление: каждые %g мин (git pull + перезапуск, когда тест не идёт)"
              % args.auto_update)
    print(" Остановка: Ctrl+C")
    print("=" * 60)
    logger.info("Веб-сервер запущен на %s:%d", args.host, args.port)

    if args.auto_update > 0:
        _start_auto_update(args.auto_update, logger)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка сервера...")
        MANAGER.stop()
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
