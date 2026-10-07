# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: ListTasks returns tasks sorted desc by timestamp.

Spec:    A2A 1.0 §3.1.4 (ListTasks)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  Spec line 262: "Implementations MUST return tasks sorted
         by their status timestamp time in descending order (most
         recently updated tasks first)." The contract creates two
         probe tasks back-to-back, then calls ``ListTasks`` and
         verifies the timestamps in the returned page are
         non-increasing.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    METHOD_NOT_FOUND_CODE,
    AgentProbe,
    error_code,
)
from a2a_testbed.transport import Transport


def make_tasks_list_sorted_desc_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        # Seed two tasks so list isn't trivially monotone with N=1.
        first = await probe.send_for_task()
        if first is None:
            return "skipped — agent did not return a Task envelope"
        await probe.send_for_task()
        envelope = await probe.call("list", {})
        if error_code(envelope) == METHOD_NOT_FOUND_CODE:
            if probe.is_legacy:
                return "skipped — A2A 0.3 defines no task-list method (tasks/list → -32601)"
            return f"skipped — agent does not implement {probe.method('list')} (-32601)"
        result = envelope.get("result")
        # 1.0 wraps the array as {tasks: [...]} (§3.1.4); pre-1.0
        # agents sometimes returned the array directly. Accept both.
        tasks = result.get("tasks") if isinstance(result, dict) else result
        assert isinstance(tasks, list), (
            f"{probe.method('list')} result MUST contain a `tasks` array"
        )
        tasks = [probe.task_of(t) for t in tasks]
        if len(tasks) < 2:
            return (
                f"only {len(tasks)} task(s) returned; can't verify sort order with fewer than two"
            )
        timestamps = []
        for i, t in enumerate(tasks):
            ts = (t.get("status") or {}).get("timestamp")
            assert isinstance(ts, str) and ts, (
                f"{probe.method('list')}[{i}].status.timestamp is REQUIRED for sort"
            )
            timestamps.append(ts)
        # ISO 8601 with Z suffix sorts lexicographically the same as
        # by absolute time. Verify non-increasing.
        for i in range(len(timestamps) - 1):
            assert timestamps[i] >= timestamps[i + 1], (
                f"{probe.method('list')} not sorted descending by timestamp at "
                f"index {i}: {timestamps[i]!r} < {timestamps[i + 1]!r}"
            )
        return None

    return Contract(
        id="transport.tasks_list_sorted_desc",
        description=("ListTasks returns tasks sorted descending by status.timestamp (§3.1.4)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
