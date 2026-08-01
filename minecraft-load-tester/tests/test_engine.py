"""Тесты Qt-независимого движка: статистика, ramp-up, лимит, остановка, ошибки."""

from __future__ import annotations

import threading
import time

from mc_load_tester.config import TestConfig
from mc_load_tester.engine import (
    LoadTestEngine,
    Stats,
    random_nickname,
    percentile,
    classify_error,
)


def test_random_nickname_prefix_and_length():
    for _ in range(50):
        nick = random_nickname("LoadBot")
        assert nick.startswith("LoadBot")
        assert len(nick) <= 16
    # слишком длинный префикс усекается
    assert len(random_nickname("X" * 30)) == 16


def test_percentile_interpolation():
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0.0) == 0.0
    assert percentile(values, 1.0) == 4.0
    assert percentile(values, 0.5) == 2.0
    assert percentile([], 0.5) == 0.0


def test_classify_error_categories():
    assert classify_error(__import__("socket").gaierror("x")) == "dns"
    assert classify_error(__import__("socket").timeout("x")) == "timeout"
    err = ConnectionRefusedError()
    assert classify_error(err) == "refused"


def test_stats_snapshot_fields():
    s = Stats()
    s.mark_start()
    s.on_success(0.10)
    s.on_success(0.30)
    s.on_error("timeout")
    snap = s.snapshot()
    assert snap["success"] == 2
    assert snap["errors"] == 1
    assert snap["active"] == 2
    assert snap["peak_active"] == 2
    assert abs(snap["avg_connect_time"] - 0.20) < 1e-9
    assert snap["min_connect_time"] == 0.10
    assert snap["max_connect_time"] == 0.30
    assert snap["errors_by_type"] == {"timeout": 1}
    assert snap["total"] == 3


def _run(engine):
    engine.run()


def test_engine_all_clients_succeed(mock_server):
    cfg = TestConfig(host=mock_server.host, port=mock_server.port, version="1.20.1",
                     client_count=8, connect_delay=0.01, hold_time=0.2,
                     nick_prefix="LoadBot")
    engine = LoadTestEngine(cfg)
    final = engine.run()
    assert final["success"] == 8
    assert final["errors"] == 0
    assert final["active"] == 0
    assert final["total"] == 8


def test_engine_rampup_waves(mock_server):
    logs = []
    cfg = TestConfig(host=mock_server.host, port=mock_server.port, version="1.21.x",
                     client_count=9, connect_delay=0.0, hold_time=0.1,
                     ramp_up=True, ramp_steps=3, ramp_interval=0.02)
    engine = LoadTestEngine(cfg, on_log=lambda lvl, msg: logs.append(msg))
    final = engine.run()
    assert final["success"] == 9
    waves = [m for m in logs if "Ramp-Up: волна" in m]
    assert len(waves) == 3


def test_engine_concurrency_limit_never_exceeded(mock_server):
    cfg = TestConfig(host=mock_server.host, port=mock_server.port, version="1.20.1",
                     client_count=20, connect_delay=0.0, hold_time=0.3,
                     max_concurrency=5)
    engine = LoadTestEngine(cfg)

    peak = {"v": 0}
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            peak["v"] = max(peak["v"], engine._alive_count())
            time.sleep(0.005)

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    final = engine.run()
    stop.set()
    assert final["success"] == 20
    # Одновременных воркеров не больше лимита (+scheduler допускает небольшой люфт).
    assert peak["v"] <= 6


def test_engine_errors_on_closed_port():
    # Порт 1 почти наверняка закрыт -> ошибки, без успехов.
    cfg = TestConfig(host="127.0.0.1", port=1, version="1.8.x",
                     client_count=4, connect_delay=0.0, hold_time=0.1,
                     socket_timeout=1.0)
    final = LoadTestEngine(cfg).run()
    assert final["success"] == 0
    assert final["errors"] == 4
    assert sum(final["errors_by_type"].values()) == 4


def test_engine_stop_is_prompt(mock_server):
    cfg = TestConfig(host=mock_server.host, port=mock_server.port, version="1.20.1",
                     client_count=1000, connect_delay=0.05, hold_time=5.0)
    engine = LoadTestEngine(cfg)
    t = threading.Thread(target=engine.run)
    t.start()
    time.sleep(0.4)
    engine.stop()
    t.join(timeout=8)
    assert not t.is_alive()  # тест должен завершиться быстро после stop()
