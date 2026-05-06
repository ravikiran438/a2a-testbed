# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: Task.status.timestamp is present and ISO 8601 UTC.

  Spec:    A2A 1.0 §3.4 (Task lifecycle), §5.6.1 (Timestamps)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  ``Task.status.timestamp`` records when the Task entered
           its current state. ListTasks ordering depends on this
           field (§3.1.4 sorts descending by timestamp), so it MUST
           be present and MUST be an ISO 8601 UTC string ending in
           'Z' per §5.6.1.
"""

from __future__ import annotations

import re

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import probe_for_task
from a2a_testbed.transport import Transport


_TS_VALID = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def make_task_status_timestamp_present_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        task = await probe_for_task(transport, agent_url)
        if task is None:
            return "skipped — agent did not return a Task envelope"
        ts = (task.get("status") or {}).get("timestamp")
        assert isinstance(ts, str) and ts, (
            "Task.status.timestamp is REQUIRED — ListTasks ordering depends on it"
        )
        assert _TS_VALID.match(ts), (
            f"Task.status.timestamp {ts!r} MUST be ISO 8601 UTC with 'Z' suffix"
        )
        return None

    return Contract(
        id="transport.task_status_timestamp_present",
        description=(
            "Task.status.timestamp is present and ISO 8601 UTC (§3.4 + §5.6.1)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
