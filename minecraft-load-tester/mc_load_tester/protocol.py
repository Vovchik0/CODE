"""
protocol
========

Минимальная реализация клиентской стороны сетевого протокола Minecraft
(Java Edition), достаточная для нагрузочного тестирования собственного
сервера.

Реализованы:

* кодирование ``VarInt`` и строк с префиксом длины;
* сборка пакета **Handshake** (переход в состояние Login);
* сборка пакета **Login Start** с учётом различий между версиями протокола;
* класс :class:`MinecraftClient`, выполняющий TCP-подключение, отправку
  handshake + login start и чтение первого ответа сервера.

Замечания по совместимости версий Login Start:

* протокол ``<= 758`` (1.8 .. 1.18.2)  -- только имя игрока;
* протокол ``759 .. 763`` (1.19 .. 1.20.1) -- имя + флаг наличия UUID + UUID;
* протокол ``>= 764`` (1.20.2+, 1.20.4, 1.21) -- имя + обязательный UUID.

Этого достаточно, чтобы сервер начал процедуру входа (или прислал ответ:
disconnect / encryption request / set compression / login success). Любой
корректный ответ считается признаком доступности сервера.
"""

from __future__ import annotations

import socket
import struct
import time
import uuid


# ---------------------------------------------------------------------------
# Низкоуровневое кодирование
# ---------------------------------------------------------------------------
def pack_varint(value: int) -> bytes:
    """Закодировать целое число в формат VarInt (Minecraft).

    :param value: неотрицательное целое (в протоколе значения положительны).
    :returns: последовательность байтов VarInt.
    """
    out = bytearray()
    # Работаем с 32-битным беззнаковым представлением.
    value &= 0xFFFFFFFF
    while True:
        temp = value & 0x7F
        value >>= 7
        if value:
            out.append(temp | 0x80)
        else:
            out.append(temp)
            break
    return bytes(out)


def pack_string(text: str) -> bytes:
    """Закодировать строку: VarInt(длина в байтах UTF-8) + сами байты."""
    encoded = text.encode("utf-8")
    return pack_varint(len(encoded)) + encoded


def pack_ushort(value: int) -> bytes:
    """Закодировать беззнаковое 16-битное число (big-endian) -- порт сервера."""
    return struct.pack(">H", value & 0xFFFF)


def _frame(packet_body: bytes) -> bytes:
    """Обернуть тело пакета префиксом длины (несжатый формат)."""
    return pack_varint(len(packet_body)) + packet_body


# ---------------------------------------------------------------------------
# Сборка конкретных пакетов
# ---------------------------------------------------------------------------
def build_handshake(protocol: int, host: str, port: int, next_state: int = 2) -> bytes:
    """Собрать пакет Handshake (0x00). ``next_state=2`` -- переход к Login."""
    body = (
        pack_varint(0x00)
        + pack_varint(protocol)
        + pack_string(host)
        + pack_ushort(port)
        + pack_varint(next_state)
    )
    return _frame(body)


def build_login_start(username: str, protocol: int) -> bytes:
    """Собрать пакет Login Start (0x00) с учётом версии протокола.

    :param username: ник игрока (<= 16 символов).
    :param protocol: номер протокола выбранной версии.
    """
    body = pack_varint(0x00) + pack_string(username)

    if protocol <= 758:
        # 1.8 .. 1.18.2 -- достаточно имени.
        pass
    elif protocol <= 763:
        # 1.19 .. 1.20.1 -- необязательный UUID (передаём флаг True + UUID).
        body += b"\x01" + uuid.uuid4().bytes
    else:
        # 1.20.2+ (764, 765, 767, ...) -- обязательный UUID без флага.
        body += uuid.uuid4().bytes

    return _frame(body)


# ---------------------------------------------------------------------------
# Клиент
# ---------------------------------------------------------------------------
class ProtocolError(Exception):
    """Ошибка при разборе ответа сервера."""


class MinecraftClient(object):
    """Простой тестовый клиент Minecraft (только процедура входа).

    Экземпляр рассчитан на одно подключение. Типичный жизненный цикл::

        client = MinecraftClient(host, port, protocol, timeout)
        connect_time = client.login(username)   # установить соединение
        client.hold(seconds)                     # удерживать соединение
        client.close()                           # закрыть
    """

    def __init__(self, host: str, port: int, protocol: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.timeout = timeout
        self.sock: socket.socket | None = None
        #: время (сек), затраченное на установку соединения и первый ответ
        self.connect_time: float = 0.0

    # -- внутренние помощники --------------------------------------------
    def _recv_exact(self, n: int) -> bytes:
        """Прочитать ровно ``n`` байт из сокета или бросить исключение."""
        assert self.sock is not None
        chunks = []
        remaining = n
        while remaining > 0:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise ProtocolError("соединение закрыто сервером")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_varint(self) -> int:
        """Прочитать VarInt из сокета."""
        num = 0
        for i in range(5):
            byte = self._recv_exact(1)[0]
            num |= (byte & 0x7F) << (7 * i)
            if not (byte & 0x80):
                return num
        raise ProtocolError("VarInt слишком длинный")

    # -- публичный интерфейс ---------------------------------------------
    def login(self, username: str) -> float:
        """Подключиться к серверу и выполнить handshake + login start.

        После отправки login start пытается прочитать первый пакет ответа
        сервера (login success / disconnect / encryption request / set
        compression) -- этого достаточно, чтобы подтвердить обработку входа.

        :param username: ник тестового клиента.
        :returns: время установки соединения в секундах.
        :raises: :class:`socket.error`, :class:`socket.timeout`,
            :class:`ProtocolError` при проблемах подключения.
        """
        start = time.time()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))
        # Отключаем алгоритм Нейгла -- пакеты уходят немедленно.
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        self.sock.sendall(build_handshake(self.protocol, self.host, self.port))
        self.sock.sendall(build_login_start(username, self.protocol))

        # Читаем первый ответ (длина + тело). Разбирать содержимое не нужно:
        # сам факт ответа подтверждает, что сервер обработал вход.
        length = self._read_varint()
        if length > 0:
            self._recv_exact(min(length, 32 * 1024))

        self.connect_time = time.time() - start
        return self.connect_time

    def hold(self, seconds: float, stop_check=None) -> None:
        """Удерживать соединение открытым заданное время.

        :param seconds: сколько секунд держать соединение.
        :param stop_check: необязательный вызываемый объект; если он вернёт
            ``True``, удержание прерывается досрочно (для быстрой остановки).
        """
        deadline = time.time() + seconds
        while time.time() < deadline:
            if stop_check is not None and stop_check():
                break
            time.sleep(min(0.2, max(0.0, deadline - time.time())))

    def close(self) -> None:
        """Аккуратно закрыть сокет (ошибки игнорируются)."""
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except (OSError, socket.error):
                pass
            try:
                self.sock.close()
            except (OSError, socket.error):
                pass
            self.sock = None
