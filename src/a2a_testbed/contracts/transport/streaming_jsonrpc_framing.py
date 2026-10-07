# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: each SSE frame is a JSON-RPC response envelope.

Spec:    A2A 1.0 §9.4.2 (SendStreamingMessage, JSON-RPC binding)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  On the JSON-RPC binding every ``data:`` line of the event
         stream is a complete JSON-RPC 2.0 response —
         ``{"jsonrpc": "2.0", "id": <request id>, "result":
         <StreamResponse>}`` — not a bare StreamResponse (bare
         objects are the HTTP+JSON binding's framing, §11.7).
         Official SDK clients parse each frame as a JSON-RPC
         response and fail on bare payloads. The ``id`` MUST echo
         the request id so a client can correlate the stream.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    AgentProbe,
    stream_sse_events,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_streaming_jsonrpc_framing_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = streaming_skip_detail(probe.card)
        if skip:
            return skip
        request_id = "sse-framing-probe"
        frames = await stream_sse_events(
            transport,
            agent_url,
            probe.method("stream"),
            probe.send_params("count: 2 framing"),
            headers=probe.headers(),
            request_id=request_id,
        )
        assert frames, f"{probe.method('stream')} emitted no SSE events"
        offenders: list[str] = []
        for i, frame in enumerate(frames):
            if frame.get("jsonrpc") != "2.0":
                offenders.append(
                    f"frame[{i}] is not a JSON-RPC 2.0 response (keys {sorted(frame.keys())})"
                )
                continue
            if frame.get("id") != request_id:
                offenders.append(
                    f"frame[{i}].id={frame.get('id')!r} does not echo the request id {request_id!r}"
                )
            if ("result" in frame) == ("error" in frame):
                offenders.append(f"frame[{i}] must carry exactly one of result / error")
        assert not offenders, "; ".join(offenders[:5]) + (
            f" (+{len(offenders) - 5} more)" if len(offenders) > 5 else ""
        )
        return None

    return Contract(
        id="transport.streaming_jsonrpc_framing",
        description=("Each SSE frame is a JSON-RPC response echoing the request id (§9.4.2)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
