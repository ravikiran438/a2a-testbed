# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: SubscribeToTask first event reflects current state.

Spec:    A2A 1.0 §3.1.6 (SubscribeToTask)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  When a client subscribes, the agent's first SSE event
         MUST carry the current Task (A2A 1.0 §3.1.6: "The operation
         MUST return a Task object as the first event"); A2A 0.3
         agents may instead lead with a ``statusUpdate`` reflecting
         the latest known ``status.state``. Without it the client can't reconcile
         its cached view with what the agent currently believes.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    LONG_TASK_TEXT,
    TERMINAL_TASK_STATES,
    UNSUPPORTED_OPERATION_CODE,
    AgentProbe,
    SseFormatError,
    looks_like_task,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_subscribe_replays_state_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = streaming_skip_detail(probe.card)
        if skip:
            return skip
        # SubscribeToTask only applies to tasks that are still running
        # (terminal tasks → UnsupportedOperationError, §3.1.6), so start
        # one that returns immediately and keeps working for a while.
        seed = await probe.send_for_task(text=LONG_TASK_TEXT, blocking=False)
        if seed is None:
            return "skipped — agent did not return a Task to subscribe to"
        if (seed.get("status") or {}).get("state") in TERMINAL_TASK_STATES:
            return (
                "skipped — task was already terminal when the send returned "
                "(agent ignored the non-blocking request); nothing to subscribe to"
            )
        try:
            events = await probe.stream("subscribe", {"id": seed["id"]})
        except SseFormatError as exc:
            if exc.error_code == UNSUPPORTED_OPERATION_CODE:
                return "skipped — task finished before the subscription was opened"
            return f"skipped — {probe.method('subscribe')} did not return SSE"
        assert events, f"{probe.method('subscribe')} emitted no events"
        first = events[0]
        # Either a Task envelope or a statusUpdate that names the seed.
        task_env = first.get("task") if isinstance(first, dict) else None
        if looks_like_task(task_env):
            assert task_env["id"] == seed["id"], (
                f"first event task.id {task_env['id']!r} ≠ subscribed id {seed['id']!r}"
            )
            return None
        status_update = first.get("statusUpdate") if isinstance(first, dict) else None
        # 1.0 §3.1.6: "The operation MUST return a Task object as the first
        # event"; 0.3 agents could lead with a status update.
        if isinstance(status_update, dict) and probe.is_legacy:
            assert status_update.get("taskId") == seed["id"], (
                "first statusUpdate.taskId ≠ subscribed id"
            )
            return None
        raise AssertionError(
            f"first {probe.method('subscribe')} event MUST carry the Task (§3.1.6); "
            f"keys={list(first.keys()) if isinstance(first, dict) else type(first).__name__}"
        )

    return Contract(
        id="transport.subscribe_replays_state",
        description=("SubscribeToTask first event reflects the subscribed task's state (§3.1.6)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
