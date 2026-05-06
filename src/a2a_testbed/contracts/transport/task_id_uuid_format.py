# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: Task.id is a server-generated UUID.

  Spec:    A2A 1.0 §3.4 (Task lifecycle), §4.1.1 (Task)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  ``Task.id`` is the server-generated identifier clients use
           to reference a Task across subsequent calls
           (``tasks/get``, ``tasks/cancel``, multi-turn follow-ups).
           The spec uses UUIDs throughout its examples; the value
           MUST be a non-empty string and SHOULD parse as a UUID so
           IDs collide globally rather than per-server.
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import probe_for_task
from a2a_testbed.transport import Transport


def make_task_id_uuid_format_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        task = await probe_for_task(transport, agent_url)
        if task is None:
            return "skipped — agent did not return a Task envelope"
        task_id = task.get("id")
        assert isinstance(task_id, str) and task_id, (
            "Task.id MUST be a non-empty string"
        )
        try:
            uuid.UUID(task_id)
        except ValueError:
            raise AssertionError(
                f"Task.id {task_id!r} is not a valid UUID; spec examples "
                "use UUIDs and global uniqueness is the load-bearing property"
            )
        return None

    return Contract(
        id="transport.task_id_uuid_format",
        description="Task.id is a server-generated UUID (§3.4 + §4.1.1).",
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
