# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: SendStreamingMessage returns Content-Type text/event-stream.

Spec:    A2A 1.0 §3.1.2 (Send Streaming Message)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  When ``capabilities.streaming`` is true, ``SendStreamingMessage``
         MUST stream Server-Sent Events back to the caller. The
         response carries ``Content-Type: text/event-stream`` per
         the SSE spec — clients dispatch on this header to switch
         into streaming mode rather than buffering a single JSON
         response.
"""

from __future__ import annotations

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    AgentProbe,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_streaming_response_content_type_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = streaming_skip_detail(probe.card)
        if skip:
            return skip
        req = {
            "jsonrpc": "2.0",
            "id": "stream-ctype",
            "method": probe.method("stream"),
            "params": probe.send_params("count: 1 ctype-probe"),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            async with client.stream(
                "POST",
                probe.rpc_url,
                json=req,
                headers=probe.headers(),
            ) as resp:
                ctype = resp.headers.get("content-type", "")
                # Drain so the connection is reusable.
                async for _ in resp.aiter_bytes():
                    break
        assert "text/event-stream" in ctype.lower(), (
            f"{probe.method('stream')} MUST return text/event-stream content-type "
            f"per §3.1.2; got {ctype!r}"
        )
        return None

    return Contract(
        id="transport.streaming_response_content_type",
        description=("SendStreamingMessage returns Content-Type text/event-stream (§3.1.2)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
