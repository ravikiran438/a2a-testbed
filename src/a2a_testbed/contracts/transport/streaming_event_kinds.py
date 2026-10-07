# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: SSE events carry one of the documented update kinds.

Spec:    A2A 1.0 §3.1.2 (Send Streaming Message), §4.1.6/§4.1.7
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  Beyond the initial Task envelope, every SSE event from
         ``SendStreamingMessage`` carries either a ``statusUpdate``
         (TaskStatusUpdateEvent) or an ``artifactUpdate``
         (TaskArtifactUpdateEvent). Both are documented in the
         spec example (line 1376–1382). Events with neither key
         — or with arbitrary payloads — break clients that
         dispatch on the wrapping field.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    AgentProbe,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport

# StreamResponse oneof members (A2A 1.0 §3.2.3).
_RECOGNIZED_KEYS = {"task", "message", "statusUpdate", "artifactUpdate"}


def make_streaming_event_kinds_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = streaming_skip_detail(probe.card)
        if skip:
            return skip
        events = await probe.stream("stream", probe.send_params("count: 2 kinds"))
        assert events, f"{probe.method('stream')} emitted no SSE events"
        offenders: list[str] = []
        for i, ev in enumerate(events):
            if not isinstance(ev, dict):
                offenders.append(f"event[{i}] is not an object")
                continue
            if "error" in ev:
                offenders.append(f"event[{i}] is a JSON-RPC error: {ev['error']}")
                continue
            keys = set(ev.keys())
            if len(keys & _RECOGNIZED_KEYS) != 1:
                offenders.append(
                    f"event[{i}] has keys {sorted(keys)}; expected exactly one of "
                    f"{sorted(_RECOGNIZED_KEYS)}"
                )
        assert not offenders, "; ".join(offenders)
        return None

    return Contract(
        id="transport.streaming_event_kinds",
        description=(
            "SSE events carry one StreamResponse member: task / message / "
            "statusUpdate / artifactUpdate (§3.1.2)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
