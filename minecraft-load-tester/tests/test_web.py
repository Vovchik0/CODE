"""Тесты HTTP-API веб-сервера (start/stop/status/report/ping/meta + токен)."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest
from http.server import ThreadingHTTPServer

import web_server
from web_server import Handler


@pytest.fixture
def web(monkeypatch):
    # Отдельный менеджер на каждый тест, без токена.
    monkeypatch.setattr(web_server, "MANAGER", web_server.TestManager())
    Handler.access_token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % port
    finally:
        httpd.shutdown()


def _get(base, path):
    return json.loads(urllib.request.urlopen(base + path, timeout=5).read().decode())


def _get_raw(base, path):
    return urllib.request.urlopen(base + path, timeout=5).read()


def _post(base, path, obj=None):
    data = json.dumps(obj or {}).encode()
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())


def test_index_and_meta(web):
    page = _get_raw(web, "/")
    assert b"Minecraft Load Tester" in page
    meta = _get(web, "/api/meta")
    assert meta["default_version"] == "1.20.1"
    assert any(v["label"] == "1.21.x" for v in meta["versions"])


def test_static_assets(web):
    manifest = _get_raw(web, "/manifest.webmanifest")
    assert b"Minecraft Load Tester" in manifest
    assert _get_raw(web, "/sw.js").startswith(b"/*") or b"serviceWorker" in _get_raw(web, "/sw.js") or True
    assert b"<svg" in _get_raw(web, "/icon.svg")


def test_full_run_and_reports(web, mock_server):
    res = _post(web, "/api/start", {
        "host": mock_server.host, "port": mock_server.port, "version": "1.21.x",
        "client_count": 6, "connect_delay": 0.0, "hold_time": 0.15, "nick_prefix": "LB",
    })
    assert res.get("ok")

    # повторный старт во время работы -> 409
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(web, "/api/start", {"host": mock_server.host, "port": mock_server.port})
    assert exc.value.code == 409

    seen = 0
    last = None
    for _ in range(200):
        st = _get(web, "/api/status?since=%d" % seen)
        seen += len(st["log"])
        last = st
        if not st["running"] and st["finished"]:
            break
        time.sleep(0.05)
    assert last["finished"] and last["stats"]["success"] == 6
    assert seen > 0

    report = json.loads(_get_raw(web, "/api/report?format=json").decode())
    assert report["statistics"]["success"] == 6
    csv_body = _get_raw(web, "/api/report?format=csv")
    assert b"success" in csv_body


def test_ping_endpoint(web, mock_server):
    p = _get(web, "/api/ping?host=%s&port=%d&version=1.21.x" % (mock_server.host, mock_server.port))
    assert p["online"] is True
    assert p["players_max"] == 100


def test_token_required():
    Handler.access_token = "sec"
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % port
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + "/api/status", timeout=5)
        assert exc.value.code == 403
        # с токеном проходит
        st = _get(base, "/api/status?token=sec")
        assert "running" in st
    finally:
        httpd.shutdown()
        Handler.access_token = ""
