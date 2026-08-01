"""Тесты низкоуровневого кодирования протокола Minecraft."""

from __future__ import annotations

import struct

import pytest

from mc_load_tester.protocol import (
    pack_varint,
    pack_string,
    build_handshake,
    build_login_start,
)


@pytest.mark.parametrize("value,expected", [
    (0, b"\x00"),
    (1, b"\x01"),
    (127, b"\x7f"),
    (128, b"\x80\x01"),
    (255, b"\xff\x01"),
    (25565, b"\xdd\xc7\x01"),
    (2097151, b"\xff\xff\x7f"),
])
def test_pack_varint(value, expected):
    assert pack_varint(value) == expected


def test_pack_string_prefixes_length():
    assert pack_string("Bob") == b"\x03Bob"
    # Многобайтовые символы: длина считается в байтах UTF-8.
    encoded = pack_string("Ы")
    assert encoded[0] == 2 and encoded[1:] == "Ы".encode("utf-8")


def test_build_handshake_structure():
    pkt = build_handshake(763, "localhost", 25565, next_state=2)
    assert pkt[0] == len(pkt) - 1          # первый байт -- длина тела
    body = pkt[1:]
    assert body[0] == 0x00                 # packet id
    assert body.endswith(b"\x02")          # next_state = 2
    # порт как big-endian unsigned short присутствует в теле
    assert struct.pack(">H", 25565) in body


@pytest.mark.parametrize("protocol,has_uuid_flag,has_uuid", [
    (47, False, False),     # 1.8 -- только имя
    (340, False, False),    # 1.12.2
    (758, False, False),    # 1.18.2
    (762, True, True),      # 1.19.4 -- флаг + UUID
    (763, True, True),      # 1.20.1
    (765, False, True),     # 1.20.4 -- UUID без флага
    (767, False, True),     # 1.21
])
def test_login_start_length_by_protocol(protocol, has_uuid_flag, has_uuid):
    pkt = build_login_start("Bob", protocol)
    body = pkt[1:]
    base = 1 + 1 + 3  # id + strlen + "Bob"
    expected = base + (1 if has_uuid_flag else 0) + (16 if has_uuid else 0)
    assert len(body) == expected
    assert body[0] == 0x00
