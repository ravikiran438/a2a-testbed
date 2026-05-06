# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: tasks/get returns the same Task by id.

  Spec:    A2A 1.0 §3.1.3 (GetTask)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Given a valid taskId previously returned by ``message/send``,
           ``tasks/get`` MUST return the corresponding Task object —
           same id, same contextId, status reflecting the current
           state. Lookup is the load-bearing primitive for every
           multi-turn flow.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    call_method,
    looks_like_task,
    probe_for_task,
)
from a2a_testbed.transport import Transport


def make_tasks_get_returns_task_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        seed = await probe_for_task(transport, agent_url)
        if seed is None:
            return "skipped — agent did not return a Task envelope"
        seed_id = seed["id"]
        envelope = await call_method(
            transport, agent_url, "tasks/get", {"id": seed_id}
        )
        if "error" in envelope and envelope.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement tasks/get (-32601)"
        result = envelope.get("result")
        assert looks_like_task(result), (
            f"tasks/get MUST return a Task object; got {type(result).__name__}"
        )
        assert result["id"] == seed_id, (  # type: ignore[index]
            f"tasks/get returned id {result['id']!r} but requested {seed_id!r}"  # type: ignore[index]
        )
        return None

    return Contract(
        id="transport.tasks_get_returns_task",
        description="tasks/get returns the Task identified by id (§3.1.3).",
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
