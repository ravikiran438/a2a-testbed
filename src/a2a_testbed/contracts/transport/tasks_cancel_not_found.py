# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: tasks/cancel on unknown id returns TaskNotFoundError.

  Spec:    A2A 1.0 §3.1.5 (CancelTask), §9.5 (Errors)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Cancellation of a non-existent task MUST return
           ``TaskNotFoundError`` (code -32001). Same strictness as
           ``tasks_get_not_found``: 200+result is a hard fail; -32001
           is a strict pass; other error codes are soft passes.
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    TASK_NOT_FOUND_CODE,
    call_method,
)
from a2a_testbed.transport import Transport


def make_tasks_cancel_not_found_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        bogus_id = str(uuid.uuid4())
        envelope = await call_method(
            transport, agent_url, "tasks/cancel", {"id": bogus_id}
        )
        if "error" in envelope and envelope.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement tasks/cancel (-32601)"
        if "result" in envelope and envelope.get("error") is None:
            raise AssertionError(
                f"tasks/cancel returned a result for bogus id {bogus_id!r}; "
                "spec mandates TaskNotFoundError (-32001)"
            )
        error = envelope.get("error") or {}
        code = error.get("code")
        if code == TASK_NOT_FOUND_CODE:
            return None
        return (
            f"agent rejected cancel of unknown id (good) but with code {code} "
            f"({error.get('message') or '?'}); spec mandates "
            f"{TASK_NOT_FOUND_CODE} (TaskNotFoundError)"
        )

    return Contract(
        id="transport.tasks_cancel_not_found",
        description=(
            "tasks/cancel on an unknown id returns TaskNotFoundError (§3.1.5 + §9.5)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
