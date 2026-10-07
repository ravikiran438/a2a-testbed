# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: SubscribeToTask returns an SSE stream.

Spec:    A2A 1.0 §3.1.6 (SubscribeToTask)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  ``SubscribeToTask`` lets a client re-attach to an
         existing Task's event stream after a disconnect. The
         response MUST be ``Content-Type: text/event-stream`` —
         same wire shape as ``SendStreamingMessage`` per §3.1.2 — and
         replay (or attach to) the task's update stream.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    LONG_TASK_TEXT,
    TERMINAL_TASK_STATES,
    UNSUPPORTED_OPERATION_CODE,
    AgentProbe,
    error_code,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_subscribe_returns_stream_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = streaming_skip_detail(probe.card)
        if skip:
            return skip
        # SubscribeToTask only applies to tasks that are still running
        # (terminal tasks → UnsupportedOperationError, §3.1.6), so start
        # one that returns immediately and keeps working for a while.
        seed = await probe.send_for_task(text=LONG_TASK_TEXT, blocking=False)
        if seed is None:
            return "skipped — agent did not return a Task to subscribe to"
        if (seed.get("status") or {}).get("state") in TERMINAL_TASK_STATES:
            return (
                "skipped — task was already terminal when the send returned "
                "(agent ignored the non-blocking request); nothing to subscribe to"
            )
        req = {
            "jsonrpc": "2.0",
            "id": "resub-ctype",
            "method": probe.method("subscribe"),
            "params": {"id": seed["id"]},
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            async with client.stream(
                "POST",
                probe.rpc_url,
                json=req,
                headers=probe.headers(),
            ) as resp:
                ctype = resp.headers.get("content-type", "")
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    break
        if "text/event-stream" in ctype.lower():
            return None
        try:
            parsed = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            parsed = None
        if error_code(parsed) == UNSUPPORTED_OPERATION_CODE:
            return "skipped — task finished before the subscription was opened"
        # Some agents implement subscribe as JSON-only — that's a soft
        # pass since the method exists but its wire shape doesn't match
        # the spec.
        if "application/json" in ctype.lower():
            return (
                f"{probe.method('subscribe')} returned application/json, not "
                "text/event-stream; spec §3.1.6 mandates SSE per §3.1.2"
            )
        raise AssertionError(
            f"{probe.method('subscribe')} returned unexpected content-type {ctype!r}; "
            "expected text/event-stream"
        )

    return Contract(
        id="transport.subscribe_returns_stream",
        description=("SubscribeToTask returns Content-Type text/event-stream (§3.1.6)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
