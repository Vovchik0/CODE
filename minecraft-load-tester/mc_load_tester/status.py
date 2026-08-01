"""
status
======

Реализация **Server List Ping** -- лёгкого запроса статуса Minecraft-сервера
(состояние Login здесь не используется, реального подключения игрока не
происходит). Возвращает MOTD, версию, число игроков онлайн/максимум и задержку.

Полезно для быстрой проверки доступности и совместимости сервера **перед**
нагрузочным тестом, а также как отдельная функция «пинг» в интерфейсе.
"""

from __future__ import annotations

import json
import socket
import time

from .protocol import (
    MinecraftClient,
    ProtocolError,
    build_handshake,
    pack_varint,
)


def _extract_motd(description) -> str:
    """Извлечь текст MOTD из поля ``description`` (строка или chat-компонент)."""
    if isinstance(description, str):
        return description
    if isinstance(description, dict):
        parts = []
        if "text" in description and isinstance(description["text"], str):
            parts.append(description["text"])
        for extra in description.get("extra", []) or []:
            parts.append(_extract_motd(extra))
        return "".join(parts)
    return ""


def ping(host: str, port: int, protocol: int, timeout: float = 5.0) -> dict:
    """Запросить статус сервера (Server List Ping).

    :returns: словарь с полями ``online``, ``latency_ms``, ``version``,
        ``players_online``, ``players_max``, ``motd``, ``raw`` (полный JSON).
    :raises: сетевые ошибки / :class:`ProtocolError` при недоступности.
    """
    # Переиспользуем низкоуровневые методы чтения из MinecraftClient.
    client = MinecraftClient(host, port, protocol, timeout=timeout)
    start = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client.sock = sock

        # Handshake с next_state=1 (status), затем пустой Status Request (0x00).
        sock.sendall(build_handshake(protocol, host, port, next_state=1))
        sock.sendall(pack_varint(1) + pack_varint(0x00))

        length = client._read_varint()  # длина пакета ответа
        packet_id = client._read_varint()
        if packet_id != 0x00:
            raise ProtocolError("неожиданный пакет статуса: 0x%02x" % packet_id)
        json_len = client._read_varint()
        raw = client._recv_exact(json_len).decode("utf-8", errors="replace")
        latency_ms = (time.time() - start) * 1000.0
    finally:
        client.close()

    data = json.loads(raw)
    players = data.get("players", {}) or {}
    version = data.get("version", {}) or {}
    return {
        "online": True,
        "latency_ms": round(latency_ms, 1),
        "version": version.get("name", ""),
        "protocol": version.get("protocol"),
        "players_online": players.get("online", 0),
        "players_max": players.get("max", 0),
        "motd": _extract_motd(data.get("description", "")),
        "raw": data,
    }
