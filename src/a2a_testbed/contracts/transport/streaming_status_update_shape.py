# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: TaskStatusUpdateEvent carries taskId + status.

  Spec:    A2A 1.0 §4.1.6 (TaskStatusUpdateEvent)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Each ``statusUpdate`` SSE event MUST carry a ``taskId``
           (so the client can correlate to the right Task) and a
           ``status`` object with ``state`` (a TaskState enum value)
           and ``timestamp`` (ISO 8601 UTC). Without these, clients
           can't update their cached Task or order events.
"""

from __future__ import annotations

import re
import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    VALID_TASK_STATES,
    fetch_card,
    stream_sse_events,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


_TS_VALID = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def make_streaming_status_update_shape_contract(
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
                    "parts": [{"kind": "text", "text": "count: 1 status-shape"}],
                },
            },
        )
        for i, ev in enumerate(events):
            if not isinstance(ev, dict) or "statusUpdate" not in ev:
                continue
            su = ev["statusUpdate"]
            assert isinstance(su, dict), (
                f"event[{i}].statusUpdate MUST be an object"
            )
            task_id = su.get("taskId")
            assert isinstance(task_id, str) and task_id, (
                f"event[{i}].statusUpdate.taskId is REQUIRED"
            )
            status = su.get("status")
            assert isinstance(status, dict), (
                f"event[{i}].statusUpdate.status MUST be an object"
            )
            state = status.get("state")
            assert state in VALID_TASK_STATES, (
                f"event[{i}].statusUpdate.status.state {state!r} not in "
                f"recognized TaskState values"
            )
            ts = status.get("timestamp")
            assert isinstance(ts, str) and _TS_VALID.match(ts), (
                f"event[{i}].statusUpdate.status.timestamp MUST be ISO 8601 "
                f"UTC; got {ts!r}"
            )
        return None

    return Contract(
        id="transport.streaming_status_update_shape",
        description=(
            "TaskStatusUpdateEvent has taskId + status{state, timestamp} (§4.1.6)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
