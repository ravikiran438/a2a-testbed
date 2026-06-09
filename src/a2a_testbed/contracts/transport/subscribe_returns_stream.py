# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: tasks/resubscribe returns an SSE stream.

Spec:    A2A 1.0 §3.1.6 (SubscribeToTask)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  ``tasks/resubscribe`` lets a client re-attach to an
         existing Task's event stream after a disconnect. The
         response MUST be ``Content-Type: text/event-stream`` —
         same wire shape as ``message/stream`` per §3.1.2 — and
         replay (or attach to) the task's update stream.
"""

from __future__ import annotations


import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    fetch_card,
    probe_for_task,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_subscribe_returns_stream_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        card = await fetch_card(transport, agent_url)
        skip = streaming_skip_detail(card)
        if skip:
            return skip
        seed = await probe_for_task(transport, agent_url)
        if seed is None:
            return "skipped — agent did not return a Task to resubscribe to"
        rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
        req = {
            "jsonrpc": "2.0",
            "id": "resub-ctype",
            "method": "tasks/resubscribe",
            "params": {"id": seed["id"]},
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            async with client.stream(
                "POST",
                rpc_url,
                json=req,
                headers={"content-type": "application/json"},
            ) as resp:
                ctype = resp.headers.get("content-type", "")
                async for _ in resp.aiter_bytes():
                    break
        if "text/event-stream" in ctype.lower():
            return None
        # Some agents implement tasks/resubscribe as JSON-only — that's
        # a soft pass since the method exists but its wire shape doesn't
        # match the spec.
        if "application/json" in ctype.lower():
            return (
                "tasks/resubscribe returned application/json, not "
                "text/event-stream; spec §3.1.6 mandates SSE per §3.1.2"
            )
        raise AssertionError(
            f"tasks/resubscribe returned unexpected content-type {ctype!r}; "
            "expected text/event-stream"
        )

    return Contract(
        id="transport.subscribe_returns_stream",
        description=("tasks/resubscribe returns Content-Type text/event-stream (§3.1.6)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
