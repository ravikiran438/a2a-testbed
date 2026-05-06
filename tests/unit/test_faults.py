# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for core/faults.py — failure injection helpers."""

from __future__ import annotations

import json

import httpx
import pytest

from a2a_testbed.core.faults import DroppedRequest, apply_fault
from a2a_testbed.core.types import Fault, FaultKind


def _payload() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "m1",
                "role": "user",
                "parts": [{"kind": "text", "text": "hello"}],
            }
        },
    }


@pytest.mark.asyncio
async def test_no_fault_passes_through():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"echo": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await apply_fault(None, "POST", "http://x/y", _payload(), client)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_drop_raises_dropped():
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(DroppedRequest):
            await apply_fault(
                Fault(kind=FaultKind.DROP), "POST", "http://x/y", _payload(), client
            )


@pytest.mark.asyncio
async def test_http_error_returns_synthetic():
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await apply_fault(
            Fault(kind=FaultKind.HTTP_ERROR, http_status=503),
            "POST", "http://x/y", _payload(), client,
        )
    assert resp.status_code == 503
    body = json.loads(resp.text)
    assert "synthetic fault" in body["error"]["message"]


@pytest.mark.asyncio
async def test_delay_still_returns_response():
    received = []
    async def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"ok": True})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await apply_fault(
            Fault(kind=FaultKind.DELAY, delay_ms=10),
            "POST", "http://x/y", _payload(), client,
        )
    assert resp.status_code == 200
    assert len(received) == 1


@pytest.mark.asyncio
async def test_corrupt_mutates_payload():
    captured_bodies: list[bytes] = []
    async def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(request.content)
        return httpx.Response(200, json={"ok": True})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await apply_fault(
            Fault(kind=FaultKind.CORRUPT, corrupt_pattern="hello"),
            "POST", "http://x/y", _payload(), client,
        )
    sent = json.loads(captured_bodies[0].decode("utf-8"))
    text_part = sent["params"]["message"]["parts"][0]["text"]
    assert text_part != "hello"
