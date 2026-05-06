# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: Task.status.state is a recognized TaskState enum.

  Spec:    A2A 1.0 §4.1.3 (TaskState), §5.5 (ProtoJSON enum encoding)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  ``Task.status.state`` MUST be a string drawn from the
           TaskState enum: TASK_STATE_SUBMITTED, TASK_STATE_WORKING,
           TASK_STATE_INPUT_REQUIRED, TASK_STATE_COMPLETED,
           TASK_STATE_CANCELED, TASK_STATE_FAILED, TASK_STATE_REJECTED,
           TASK_STATE_AUTH_REQUIRED, or TASK_STATE_UNSPECIFIED.
           ProtoJSON serializes enums by their full SCREAMING_SNAKE_CASE
           name (§5.5 line 1215); lowercase or truncated values
           ("completed", "working") are non-conformant.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    VALID_TASK_STATES,
    probe_for_task,
)
from a2a_testbed.transport import Transport


def make_task_status_state_enum_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        task = await probe_for_task(transport, agent_url)
        if task is None:
            return "skipped — agent did not return a Task envelope"
        state = (task.get("status") or {}).get("state")
        assert isinstance(state, str) and state, (
            "Task.status.state MUST be a non-empty string"
        )
        assert state in VALID_TASK_STATES, (
            f"Task.status.state {state!r} is not a recognized TaskState "
            "enum value; ProtoJSON requires SCREAMING_SNAKE_CASE form "
            f"(e.g. TASK_STATE_COMPLETED). Recognized values: "
            f"{sorted(VALID_TASK_STATES)}"
        )
        return None

    return Contract(
        id="transport.task_status_state_enum",
        description=(
            "Task.status.state is a recognized TaskState enum value (§4.1.3 + §5.5)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
