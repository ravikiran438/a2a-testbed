# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Failure-injection helpers applied to outgoing scenario messages.

Faults are scenario-declared and applied client-side so we don't have to
mutate the agent runtimes. Each fault kind takes the prepared HTTP
request and returns either:

- the unchanged request (NONE)
- a synthetic httpx.Response (DROP / HTTP_ERROR)
- a delay coroutine plus the unchanged request (DELAY)
- a mutated request (CORRUPT)
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Optional

import httpx

from a2a_testbed.core.types import Fault, FaultKind


class DroppedRequest(Exception):
    """Raised when a fault drops the request (no response produced)."""


async def apply_fault(
    fault: Optional[Fault],
    method: str,
    url: str,
    payload: dict,
    client: httpx.AsyncClient,
) -> httpx.Response:
    """Send (or simulate sending) a request with the configured fault applied.

    Returns the live or synthetic response. Raises ``DroppedRequest`` if
    the fault declares the message is silently lost.
    """
    if fault is None or fault.kind == FaultKind.NONE:
        return await client.request(method, url, json=payload)

    if fault.kind == FaultKind.DROP:
        raise DroppedRequest("fault: drop")

    if fault.kind == FaultKind.DELAY:
        await asyncio.sleep(max(0, fault.delay_ms) / 1000.0)
        return await client.request(method, url, json=payload)

    if fault.kind == FaultKind.CORRUPT:
        mutated = _corrupt_payload(payload, fault.corrupt_pattern)
        return await client.request(method, url, json=mutated)

    if fault.kind == FaultKind.HTTP_ERROR:
        return _synthetic_error(fault.http_status, url)

    raise ValueError(f"unknown fault kind: {fault.kind!r}")


def _synthetic_error(status: int, url: str) -> httpx.Response:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "error": {
                "code": -32000,
                "message": f"synthetic fault: HTTP {status}",
            },
        }
    )
    request = httpx.Request("POST", url)
    return httpx.Response(status_code=status, content=body.encode("utf-8"), request=request)


def _corrupt_payload(payload: dict, pattern: Optional[str]) -> dict:
    """Return a shallow-mutated copy of *payload* with a substring scrambled.

    If ``pattern`` is None, scramble a random text field in the message.
    """
    text = json.dumps(payload)
    if pattern and pattern in text:
        scrambled = "".join(random.sample(pattern, len(pattern)))
        text = text.replace(pattern, scrambled, 1)
    else:
        # Generic fallback: scramble the first message text part
        try:
            params = payload.get("params", {})
            message = params.get("message", {})
            parts = message.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    s = part["text"]
                    if s:
                        part["text"] = s[::-1]
                        return payload
        except (AttributeError, TypeError):
            pass
        text = text[::-1]
    return json.loads(text)
