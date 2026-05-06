# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: TaskArtifactUpdateEvent carries taskId + artifact.

  Spec:    A2A 1.0 §4.1.7 (TaskArtifactUpdateEvent), §4.1.5 (Artifact)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Each ``artifactUpdate`` SSE event MUST carry a ``taskId``
           and an ``artifact`` object — the latter following the
           Artifact schema (artifactId + non-empty parts). Clients
           accumulate artifacts as the task streams; missing identity
           or empty parts make them unaddressable.
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


def make_streaming_artifact_update_shape_contract(
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
                    "parts": [{"kind": "text", "text": "count: 2 artifacts"}],
                },
            },
        )
        seen = 0
        for i, ev in enumerate(events):
            if not isinstance(ev, dict) or "artifactUpdate" not in ev:
                continue
            seen += 1
            au = ev["artifactUpdate"]
            assert isinstance(au, dict), (
                f"event[{i}].artifactUpdate MUST be an object"
            )
            assert isinstance(au.get("taskId"), str) and au["taskId"], (
                f"event[{i}].artifactUpdate.taskId is REQUIRED"
            )
            artifact = au.get("artifact")
            assert isinstance(artifact, dict), (
                f"event[{i}].artifactUpdate.artifact MUST be an object"
            )
            artifact_id = artifact.get("artifactId")
            assert isinstance(artifact_id, str) and artifact_id, (
                f"event[{i}].artifactUpdate.artifact.artifactId is REQUIRED"
            )
            parts = artifact.get("parts")
            assert isinstance(parts, list) and parts, (
                f"event[{i}].artifactUpdate.artifact.parts must be non-empty array"
            )
        if seen == 0:
            return (
                "agent streamed no artifactUpdate events for count=2 — "
                "skipping shape check (§4.1.7 only applies when emitted)"
            )
        return None

    return Contract(
        id="transport.streaming_artifact_update_shape",
        description=(
            "TaskArtifactUpdateEvent has taskId + Artifact (§4.1.7)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
