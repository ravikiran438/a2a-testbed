# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: tasks/list returns tasks sorted desc by timestamp.

  Spec:    A2A 1.0 §3.1.4 (ListTasks)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Spec line 262: "Implementations MUST return tasks sorted
           by their status timestamp time in descending order (most
           recently updated tasks first)." The contract creates two
           probe tasks back-to-back, then calls ``tasks/list`` and
           verifies the timestamps in the returned page are
           non-increasing.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    call_method,
    probe_for_task,
)
from a2a_testbed.transport import Transport


def make_tasks_list_sorted_desc_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        # Seed two tasks so list isn't trivially monotone with N=1.
        first = await probe_for_task(transport, agent_url)
        if first is None:
            return "skipped — agent did not return a Task envelope"
        await probe_for_task(transport, agent_url)

        envelope = await call_method(
            transport, agent_url, "tasks/list", {}
        )
        if "error" in envelope and envelope.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement tasks/list (-32601)"
        result = envelope.get("result")
        # Result shape varies (some agents wrap in {tasks: [...]} per
        # §3.1.4; others return the array directly). Accept both.
        if isinstance(result, dict):
            tasks = result.get("tasks")
        else:
            tasks = result
        assert isinstance(tasks, list), (
            "tasks/list result MUST contain a `tasks` array"
        )
        if len(tasks) < 2:
            return (
                f"only {len(tasks)} task(s) returned; can't verify sort "
                "order with fewer than two"
            )
        timestamps = []
        for i, t in enumerate(tasks):
            ts = (t.get("status") or {}).get("timestamp")
            assert isinstance(ts, str) and ts, (
                f"tasks/list[{i}].status.timestamp is REQUIRED for sort"
            )
            timestamps.append(ts)
        # ISO 8601 with Z suffix sorts lexicographically the same as
        # by absolute time. Verify non-increasing.
        for i in range(len(timestamps) - 1):
            assert timestamps[i] >= timestamps[i + 1], (
                f"tasks/list not sorted descending by timestamp at "
                f"index {i}: {timestamps[i]!r} < {timestamps[i + 1]!r}"
            )
        return None

    return Contract(
        id="transport.tasks_list_sorted_desc",
        description=(
            "tasks/list returns tasks sorted descending by status.timestamp (§3.1.4)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
