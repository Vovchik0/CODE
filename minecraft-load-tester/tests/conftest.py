"""
conftest
========

Общие фикстуры для тестов: лёгкий мок Minecraft-сервера на TCP, который
принимает handshake + login/status и отвечает корректно оформленным пакетом.
Позволяет тестировать движок и веб-API без настоящего сервера.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from mc_load_tester.protocol import pack_varint, pack_string


def _read_varint(sock):
    num = 0
    for i in range(5):
        b = sock.recv(1)
        if not b:
            raise ConnectionError
        val = b[0]
        num |= (val & 0x7F) << (7 * i)
        if not (val & 0x80):
            break
    return num


class MockMinecraftServer(object):
    """Минимальный TCP-сервер, имитирующий приём входа и статуса."""

    def __init__(self, hold=0.3):
        self.hold = hold
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(200)
        self.host, self.port = self._sock.getsockname()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _serve(self):
        self._sock.settimeout(0.3)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            conn.settimeout(3)
            # Читаем handshake, чтобы узнать next_state.
            length = _read_varint(conn)
            data = b""
            while len(data) < length:
                chunk = conn.recv(length - len(data))
                if not chunk:
                    return
                data += chunk
            next_state = data[-1]  # последний байт handshake -- next_state

            if next_state == 1:
                # Status: читаем запрос и отвечаем JSON.
                conn.recv(64)
                payload = json.dumps({
                    "version": {"name": "MockMC 1.21", "protocol": 767},
                    "players": {"online": 3, "max": 100},
                    "description": {"text": "Mock ", "extra": [{"text": "Server"}]},
                }).encode("utf-8")
                body = pack_varint(0x00) + pack_string(payload.decode("utf-8"))
                conn.sendall(pack_varint(len(body)) + body)
            else:
                # Login: читаем login start и отвечаем «disconnect»-подобным пакетом.
                conn.recv(256)
                body = pack_varint(0x00) + pack_string('{"text":"ok"}')
                conn.sendall(pack_varint(len(body)) + body)
                time.sleep(self.hold)
        except (OSError, ConnectionError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass


@pytest.fixture
def mock_server():
    server = MockMinecraftServer(hold=0.2).start()
    try:
        yield server
    finally:
        server.stop()
