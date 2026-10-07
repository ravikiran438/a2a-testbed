# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: first SSE event of a stream carries the Task (or the Message).

Spec:    A2A 1.0 §3.1.2 (Send Streaming Message)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  Per the spec example (line 1376) the first SSE event of
         a streaming response carries the full Task envelope:
         ``data: {"task": {...}}``. Clients use this initial frame
         to learn the task id (so they can request follow-ups via
         ``GetTask`` / ``CancelTask`` later) and the contextId
         (so multi-turn flows can reuse the conversation handle).
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    AgentProbe,
    looks_like_task,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_streaming_first_event_is_task_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = streaming_skip_detail(probe.card)
        if skip:
            return skip
        events = await probe.stream("stream", probe.send_params("count: 1 first-event"))
        assert events, f"{probe.method('stream')} emitted no SSE events"
        first = events[0]
        if isinstance(first, dict) and isinstance(first.get("message"), dict):
            # Message-only stream (§3.1.2 pattern 1): exactly one Message.
            assert len(events) == 1, (
                f"message-only stream MUST contain exactly one Message and then "
                f"close (§3.1.2); got {len(events)} events"
            )
            return "message-only stream (agent answered with a Message, not a Task)"
        task = first.get("task") if isinstance(first, dict) else None
        assert looks_like_task(task), (
            'first SSE event MUST carry the Task (`{"task": {...}}`) or, for a '
            "message-only stream, the Message (§3.1.2); got "
            f"{list(first.keys()) if isinstance(first, dict) else type(first).__name__}"
        )
        return None

    return Contract(
        id="transport.streaming_first_event_is_task",
        description=("First SSE event carries the Task (or the sole Message) (§3.1.2)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
