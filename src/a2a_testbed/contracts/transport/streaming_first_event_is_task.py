# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: first SSE event of message/stream carries the Task.

  Spec:    A2A 1.0 §3.1.2 (Send Streaming Message)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Per the spec example (line 1376) the first SSE event of
           a streaming response carries the full Task envelope:
           ``data: {"task": {...}}``. Clients use this initial frame
           to learn the task id (so they can request follow-ups via
           ``tasks/get`` / ``tasks/cancel`` later) and the contextId
           (so multi-turn flows can reuse the conversation handle).
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    fetch_card,
    looks_like_task,
    stream_sse_events,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_streaming_first_event_is_task_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        card = await fetch_card(transport, agent_url)
        skip = streaming_skip_detail(card)
        if skip:
            return skip
        events = await stream_sse_events(
            transport,
            agent_url,
            "message/stream",
            {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "user",
                    "parts": [{"kind": "text", "text": "count: 1 first-event"}],
                },
            },
        )
        assert events, "message/stream emitted no SSE events"
        first = events[0]
        # The spec example wraps the Task under a `task` key.
        task = first.get("task") if isinstance(first, dict) else None
        assert looks_like_task(task), (
            "first SSE event MUST carry the Task envelope as "
            f"`{{\"task\": {{...}}}}` (§3.1.2); got {list(first.keys()) if isinstance(first, dict) else type(first).__name__}"
        )
        return None

    return Contract(
        id="transport.streaming_first_event_is_task",
        description=(
            "First SSE event of message/stream carries the Task envelope (§3.1.2)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
