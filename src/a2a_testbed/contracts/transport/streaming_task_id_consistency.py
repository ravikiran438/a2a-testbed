# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: every SSE event references the same taskId.

  Spec:    A2A 1.0 §3.1.2 (Send Streaming Message)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  All update events in a single message/stream response
           describe the same Task. The initial ``task`` event
           establishes the id; every subsequent ``statusUpdate`` /
           ``artifactUpdate`` MUST carry the matching ``taskId``.
           Drift means the agent multiplexed multiple Tasks onto
           one stream, which clients can't disentangle.
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    fetch_card,
    stream_sse_events,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_streaming_task_id_consistency_contract(
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
                    "parts": [{"kind": "text", "text": "count: 2 id-consistency"}],
                },
            },
        )
        assert events, "message/stream emitted no SSE events"
        first = events[0]
        task_id = ((first.get("task") or {}).get("id")) if isinstance(first, dict) else None
        assert isinstance(task_id, str) and task_id, (
            "first event must carry the Task envelope with a `task.id` to anchor consistency"
        )
        offenders: list[str] = []
        for i, ev in enumerate(events[1:], start=1):
            payload = (ev.get("statusUpdate") or ev.get("artifactUpdate")) if isinstance(ev, dict) else None
            if not isinstance(payload, dict):
                continue
            seen_id = payload.get("taskId")
            if seen_id != task_id:
                offenders.append(
                    f"event[{i}].taskId={seen_id!r} differs from initial task.id={task_id!r}"
                )
        assert not offenders, "; ".join(offenders)
        return None

    return Contract(
        id="transport.streaming_task_id_consistency",
        description=(
            "All SSE events in one stream reference the same taskId (§3.1.2)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
