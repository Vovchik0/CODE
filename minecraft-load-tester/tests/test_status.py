"""Тесты Server List Ping."""

from __future__ import annotations

import pytest

from mc_load_tester import status


def test_ping_returns_server_info(mock_server):
    result = status.ping(mock_server.host, mock_server.port, 767, timeout=3.0)
    assert result["online"] is True
    assert result["players_online"] == 3
    assert result["players_max"] == 100
    assert result["version"] == "MockMC 1.21"
    assert "Mock" in result["motd"] and "Server" in result["motd"]
    assert result["latency_ms"] >= 0


def test_ping_unreachable_raises():
    with pytest.raises(Exception):
        status.ping("127.0.0.1", 1, 767, timeout=1.0)
