# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: tasks/resubscribe first event reflects current state.

  Spec:    A2A 1.0 §3.1.6 (SubscribeToTask)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  When a client resubscribes, the agent's first SSE event
           MUST carry the current Task state — either as a full
           ``task`` envelope (matching §3.1.2 initial-event shape)
           or a ``statusUpdate`` reflecting the latest known
           ``status.state``. Without it the client can't reconcile
           its cached view with what the agent currently believes.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    fetch_card,
    looks_like_task,
    probe_for_task,
    stream_sse_events,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_subscribe_replays_state_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        card = await fetch_card(transport, agent_url)
        skip = streaming_skip_detail(card)
        if skip:
            return skip
        seed = await probe_for_task(transport, agent_url)
        if seed is None:
            return "skipped — agent did not return a Task to resubscribe to"
        try:
            events = await stream_sse_events(
                transport,
                agent_url,
                "tasks/resubscribe",
                {"id": seed["id"]},
            )
        except AssertionError:
            return "skipped — tasks/resubscribe did not return SSE"
        assert events, "tasks/resubscribe emitted no events"
        first = events[0]
        # Either a Task envelope or a statusUpdate that names the seed.
        task_env = first.get("task") if isinstance(first, dict) else None
        if looks_like_task(task_env):
            assert task_env["id"] == seed["id"], (
                f"first event task.id {task_env['id']!r} ≠ subscribed id {seed['id']!r}"
            )
            return None
        status_update = first.get("statusUpdate") if isinstance(first, dict) else None
        if isinstance(status_update, dict):
            assert status_update.get("taskId") == seed["id"], (
                f"first statusUpdate.taskId ≠ subscribed id"
            )
            return None
        raise AssertionError(
            "first tasks/resubscribe event carries neither `task` nor "
            f"`statusUpdate`; keys={list(first.keys()) if isinstance(first, dict) else type(first).__name__}"
        )

    return Contract(
        id="transport.subscribe_replays_state",
        description=(
            "tasks/resubscribe first event reflects the subscribed task's state (§3.1.6)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
