"""
config
======

Хранит справочник поддерживаемых версий Minecraft с соответствующими
номерами сетевого протокола, а также структуру :class:`TestConfig`,
описывающую параметры одного запуска нагрузочного теста.

Номера протоколов соответствуют официальным значениям из wiki.vg
(Protocol Version Numbers) и используются в handshake-пакете.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Поддерживаемые версии Minecraft -> номер протокола
# ---------------------------------------------------------------------------
# Порядок сохраняется (Python 3.7+), поэтому выпадающий список в GUI
# формируется прямо из ключей этого словаря.
MINECRAFT_VERSIONS = {
    "1.8.x":  47,
    "1.12.2": 340,
    "1.16.5": 754,
    "1.18.2": 758,
    "1.19.4": 762,
    "1.20.1": 763,
    "1.20.4": 765,
    "1.21.x": 767,
}

#: Версия, выбранная в выпадающем списке по умолчанию.
DEFAULT_VERSION = "1.20.1"


def protocol_for(version: str) -> int:
    """Вернуть номер протокола для человекочитаемой версии.

    :param version: строка-ключ из :data:`MINECRAFT_VERSIONS`.
    :returns: номер протокола; при неизвестной версии возвращается протокол
        версии по умолчанию, чтобы приложение не падало.
    """
    return MINECRAFT_VERSIONS.get(version, MINECRAFT_VERSIONS[DEFAULT_VERSION])


class TestConfig(object):
    """Параметры одного запуска нагрузочного теста.

    Простой контейнер значений (без внешних зависимостей вроде dataclasses),
    что упрощает совместимость и сериализацию. Значения заполняются из полей
    ввода GUI и передаются в :class:`~mc_load_tester.tester.LoadTester`.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 25565,
        version: str = DEFAULT_VERSION,
        client_count: int = 10,
        connect_delay: float = 0.1,
        hold_time: float = 5.0,
        nick_prefix: str = "LoadBot",
        ramp_up: bool = False,
        ramp_steps: int = 5,
        ramp_interval: float = 1.0,
        socket_timeout: float = 5.0,
    ):
        self.host = host
        self.port = int(port)
        self.version = version
        self.client_count = int(client_count)
        #: пауза (сек) между стартом соседних клиентов
        self.connect_delay = float(connect_delay)
        #: сколько секунд держать соединение открытым после логина
        self.hold_time = float(hold_time)
        self.nick_prefix = nick_prefix
        #: включить постепенное наращивание нагрузки (Ramp-Up)
        self.ramp_up = bool(ramp_up)
        #: количество «волн» при включённом ramp-up
        self.ramp_steps = int(ramp_steps)
        #: пауза (сек) между волнами ramp-up
        self.ramp_interval = float(ramp_interval)
        #: таймаут сокета на установку соединения / чтение
        self.socket_timeout = float(socket_timeout)

    @property
    def protocol(self) -> int:
        """Номер протокола, соответствующий выбранной версии."""
        return protocol_for(self.version)

    def to_dict(self) -> dict:
        """Сериализовать конфигурацию в словарь (для отчётов JSON)."""
        return {
            "host": self.host,
            "port": self.port,
            "version": self.version,
            "protocol": self.protocol,
            "client_count": self.client_count,
            "connect_delay": self.connect_delay,
            "hold_time": self.hold_time,
            "nick_prefix": self.nick_prefix,
            "ramp_up": self.ramp_up,
            "ramp_steps": self.ramp_steps,
            "ramp_interval": self.ramp_interval,
            "socket_timeout": self.socket_timeout,
        }
