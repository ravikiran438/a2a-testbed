# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: Task.history (when present) is a Message array.

  Spec:    A2A 1.0 §4.1.1 (Task), §4.1.4 (Message)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  ``Task.history`` is an OPTIONAL array tracking the sequence
           of messages exchanged within the Task. Each entry MUST be
           a Message object — at minimum carrying ``role`` ("user" or
           "agent") and ``parts`` (a non-empty array of Part objects).
           Malformed entries break multi-turn replay because clients
           reconstruct conversational state by walking history.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import probe_for_task
from a2a_testbed.transport import Transport


_RECOGNIZED_ROLES = {"user", "agent", "ROLE_USER", "ROLE_AGENT"}


def make_task_history_shape_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        task = await probe_for_task(transport, agent_url)
        if task is None:
            return "skipped — agent did not return a Task envelope"
        history = task.get("history")
        if history is None:
            return None  # OPTIONAL field
        assert isinstance(history, list), (
            "Task.history MUST be an array when present"
        )
        for i, msg in enumerate(history):
            assert isinstance(msg, dict), (
                f"Task.history[{i}] MUST be a Message object"
            )
            role = msg.get("role")
            assert isinstance(role, str) and role in _RECOGNIZED_ROLES, (
                f"Task.history[{i}].role {role!r} not in recognized values "
                f"{sorted(_RECOGNIZED_ROLES)}"
            )
            parts = msg.get("parts")
            assert isinstance(parts, list) and parts, (
                f"Task.history[{i}].parts MUST be a non-empty array"
            )
        return None

    return Contract(
        id="transport.task_history_shape",
        description=(
            "Task.history (when present) is a well-formed Message array (§4.1.1 + §4.1.4)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
