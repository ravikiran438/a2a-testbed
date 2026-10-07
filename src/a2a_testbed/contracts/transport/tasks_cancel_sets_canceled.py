# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: CancelTask transitions the task to CANCELED.

Spec:    A2A 1.0 §3.1.5 (CancelTask)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  ``CancelTask`` requests cancellation of an in-flight
         Task. After a successful response, the Task's
         ``status.state`` is ``TASK_STATE_CANCELED`` (or remains
         in a terminal state — spec line 496 notes cancellation
         is idempotent and a duplicate may return TaskNotFoundError
         if the task was already canceled and purged).
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    LONG_TASK_TEXT,
    METHOD_NOT_FOUND_CODE,
    TASK_NOT_CANCELABLE_CODE,
    TASK_NOT_FOUND_CODE,
    TERMINAL_TASK_STATES,
    AgentProbe,
    looks_like_task,
)
from a2a_testbed.transport import Transport


def make_tasks_cancel_sets_canceled_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        # Cancel a task that is still running: a completed task is not
        # cancelable (TaskNotCancelableError, §3.1.5), so ask the agent
        # to return immediately and give it enough work to still be busy.
        seed = await probe.send_for_task(text=LONG_TASK_TEXT, blocking=False)
        if seed is None:
            return "skipped — agent did not return a Task envelope"
        if (seed.get("status") or {}).get("state") in TERMINAL_TASK_STATES:
            return (
                "skipped — task was already terminal when the send returned "
                "(agent ignored the non-blocking request); nothing to cancel"
            )
        envelope = await probe.call("cancel", {"id": seed["id"]})
        if "error" in envelope:
            err = envelope["error"] or {}
            code = err.get("code")
            if code == METHOD_NOT_FOUND_CODE:
                return f"skipped — agent does not implement {probe.method('cancel')} (-32601)"
            if code == TASK_NOT_CANCELABLE_CODE:
                return (
                    "agent returned TaskNotCancelableError — permitted when the "
                    "task finished before the cancel arrived (§3.1.5); cannot "
                    "verify the state transition"
                )
            # Idempotency / already-terminal cases the spec allows.
            if code == TASK_NOT_FOUND_CODE:
                return (
                    "agent returned TaskNotFoundError on cancel — "
                    "permitted when task is already canceled and purged "
                    "(spec line 496); cannot verify state transition"
                )
            raise AssertionError(
                f"{probe.method('cancel')} failed with code {code} ({err.get('message') or '?'})"
            )
        result = probe.task_of(envelope.get("result"))
        assert looks_like_task(result), (
            f"{probe.method('cancel')} result MUST be the updated Task; got {type(result).__name__}"
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
            f"after {probe.method('cancel')}, Task.status.state is {state!r}; "
            "expected TASK_STATE_CANCELED (or another terminal state)"
        )

    return Contract(
        id="transport.tasks_cancel_sets_canceled",
        description=("CancelTask transitions a running task to TASK_STATE_CANCELED (§3.1.5)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
