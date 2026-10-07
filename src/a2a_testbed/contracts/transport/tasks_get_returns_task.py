# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: GetTask returns the same Task by id.

Spec:    A2A 1.0 §3.1.3 (GetTask)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  Given a valid taskId previously returned by ``SendMessage``,
         ``GetTask`` MUST return the corresponding Task object —
         same id, same contextId, status reflecting the current
         state. Lookup is the load-bearing primitive for every
         multi-turn flow.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    METHOD_NOT_FOUND_CODE,
    AgentProbe,
    error_code,
    looks_like_task,
)
from a2a_testbed.transport import Transport


def make_tasks_get_returns_task_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        seed = await probe.send_for_task()
        if seed is None:
            return "skipped — agent did not return a Task envelope"
        seed_id = seed["id"]
        envelope = await probe.call("get", {"id": seed_id})
        if error_code(envelope) == METHOD_NOT_FOUND_CODE:
            return f"skipped — agent does not implement {probe.method('get')} (-32601)"
        result = probe.task_of(envelope.get("result"))
        assert looks_like_task(result), (
            f"{probe.method('get')} MUST return a Task object; got {type(result).__name__}"
        )
        assert result["id"] == seed_id, (  # type: ignore[index]
            f"{probe.method('get')} returned id {result['id']!r} but requested {seed_id!r}"  # type: ignore[index]
        )
        return None

    return Contract(
        id="transport.tasks_get_returns_task",
        description="GetTask returns the Task identified by id (§3.1.3).",
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
