# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: tasks/cancel transitions the task to CANCELED.

  Spec:    A2A 1.0 §3.1.5 (CancelTask)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  ``tasks/cancel`` requests cancellation of an in-flight
           Task. After a successful response, the Task's
           ``status.state`` is ``TASK_STATE_CANCELED`` (or remains
           in a terminal state — spec line 496 notes cancellation
           is idempotent and a duplicate may return TaskNotFoundError
           if the task was already canceled and purged).
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    TERMINAL_TASK_STATES,
    call_method,
    looks_like_task,
    probe_for_task,
)
from a2a_testbed.transport import Transport


def make_tasks_cancel_sets_canceled_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        seed = await probe_for_task(transport, agent_url)
        if seed is None:
            return "skipped — agent did not return a Task envelope"
        envelope = await call_method(
            transport, agent_url, "tasks/cancel", {"id": seed["id"]}
        )
        if "error" in envelope:
            err = envelope["error"] or {}
            code = err.get("code")
            if code == -32601:
                return "skipped — agent does not implement tasks/cancel (-32601)"
            # Idempotency / already-terminal cases the spec allows.
            if code == -32001:
                return (
                    "agent returned TaskNotFoundError on cancel — "
                    "permitted when task is already canceled and purged "
                    "(spec line 496); cannot verify state transition"
                )
            raise AssertionError(
                f"tasks/cancel failed with code {code} "
                f"({err.get('message') or '?'})"
            )
        result = envelope.get("result")
        assert looks_like_task(result), (
            f"tasks/cancel result MUST be the updated Task; got {type(result).__name__}"
        )
        state = (result.get("status") or {}).get("state")  # type: ignore[union-attr]
        # CANCELED is the spec-mandated post-cancel state. Other
        # terminal states are accepted (the task may have completed
        # or failed before the cancel arrived) — that's a benign
        # race the spec doesn't forbid; flag as a soft pass.
        if state == "TASK_STATE_CANCELED":
            return None
        if state in TERMINAL_TASK_STATES:
            return (
                f"task ended in {state} rather than TASK_STATE_CANCELED "
                "— accepted (cancel may have arrived after completion) "
                "but the canonical post-cancel state is TASK_STATE_CANCELED"
            )
        raise AssertionError(
            f"after tasks/cancel, Task.status.state is {state!r}; "
            "expected TASK_STATE_CANCELED (or another terminal state)"
        )

    return Contract(
        id="transport.tasks_cancel_sets_canceled",
        description=(
            "tasks/cancel transitions the task to TASK_STATE_CANCELED (§3.1.5)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
