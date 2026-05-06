# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: SSE stream closes after a terminal-state event.

  Spec:    A2A 1.0 §3.1.2 (Send Streaming Message), §4.1.3 (TaskState)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Once a Task reaches a terminal state (TASK_STATE_COMPLETED,
           CANCELED, FAILED, or REJECTED), no further state changes
           are possible — so the SSE stream closes after the
           statusUpdate carrying the terminal state. Clients that
           keep listening after a terminal state would block forever;
           the spec's stream-close semantics are what unblocks them.
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    TERMINAL_TASK_STATES,
    fetch_card,
    stream_sse_events,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_streaming_terminal_state_closes_contract(
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
                    "parts": [{"kind": "text", "text": "count: 1 terminal"}],
                },
            },
        )
        assert events, "message/stream emitted no SSE events"
        # Find the last status update.
        last_status = None
        last_index = -1
        for i, ev in enumerate(events):
            if isinstance(ev, dict) and "statusUpdate" in ev:
                last_status = ev["statusUpdate"]
                last_index = i
        assert last_status is not None, (
            "stream emitted no terminal statusUpdate event; client cannot "
            "tell when the task ended"
        )
        state = (last_status.get("status") or {}).get("state")
        assert state in TERMINAL_TASK_STATES, (
            f"last statusUpdate carries non-terminal state {state!r}; spec "
            "requires the stream to close on a terminal-state event"
        )
        # Last event in the stream MUST be the terminal status; no
        # straggler events after.
        assert last_index == len(events) - 1, (
            f"agent emitted {len(events) - last_index - 1} event(s) after "
            "the terminal statusUpdate — stream should have closed"
        )
        return None

    return Contract(
        id="transport.streaming_terminal_state_closes",
        description=(
            "SSE stream closes after a terminal-state statusUpdate (§3.1.2 + §4.1.3)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
