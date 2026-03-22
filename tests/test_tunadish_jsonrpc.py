"""Tests for tunadish JSON-RPC 2.0 response support."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tunapi.tunadish.transport import TunadishTransport

pytestmark = pytest.mark.anyio


class FakeWs:
    def __init__(self):
        self.sent: list[dict[str, Any]] = []

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    def last(self) -> dict[str, Any]:
        return self.sent[-1]


class TestJsonRpcResponse:
    async def test_send_response(self):
        ws = FakeWs()
        t = TunadishTransport(ws)
        await t._send_response("req-1", {"data": "hello"})
        msg = ws.last()
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == "req-1"
        assert msg["result"] == {"data": "hello"}
        assert "error" not in msg

    async def test_send_error(self):
        ws = FakeWs()
        t = TunadishTransport(ws)
        await t._send_error("req-2", -32601, "Method not found")
        msg = ws.last()
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == "req-2"
        assert msg["error"]["code"] == -32601
        assert msg["error"]["message"] == "Method not found"
        assert "result" not in msg

    async def test_notification_without_rpc_id(self):
        ws = FakeWs()
        t = TunadishTransport(ws)
        await t._send_notification("project.list.result", {"projects": []})
        msg = ws.last()
        assert msg["method"] == "project.list.result"
        assert msg["params"] == {"projects": []}
        assert "jsonrpc" not in msg

    async def test_notification_with_rpc_id_becomes_response(self):
        ws = FakeWs()
        t = TunadishTransport(ws)
        t.set_rpc_id("req-3")
        await t._send_notification("project.list.result", {"projects": ["a"]})
        msg = ws.last()
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == "req-3"
        assert msg["result"] == {"projects": ["a"]}
        assert "method" not in msg

    async def test_rpc_id_consumed_after_one_notification(self):
        ws = FakeWs()
        t = TunadishTransport(ws)
        t.set_rpc_id("req-4")
        await t._send_notification("first.result", {"ok": True})
        # Second notification should be normal (rpc_id consumed)
        await t._send_notification("message.new", {"text": "hi"})
        msg = ws.last()
        assert msg["method"] == "message.new"
        assert "jsonrpc" not in msg

    async def test_rpc_id_with_error_in_params(self):
        ws = FakeWs()
        t = TunadishTransport(ws)
        t.set_rpc_id("req-5")
        await t._send_notification("some.result", {"error": "no project"})
        msg = ws.last()
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == "req-5"
        assert msg["error"]["code"] == -32000
        assert msg["error"]["message"] == "no project"

    async def test_rpc_id_integer(self):
        ws = FakeWs()
        t = TunadishTransport(ws)
        t.set_rpc_id(42)
        await t._send_notification("test.result", {"value": 1})
        msg = ws.last()
        assert msg["id"] == 42
        assert msg["jsonrpc"] == "2.0"
