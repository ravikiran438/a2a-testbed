# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: tasks/get on unknown id returns TaskNotFoundError.

  Spec:    A2A 1.0 §3.1.3 (GetTask), §9.5 (Errors)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Spec line 614: "Agents MUST return a TaskNotFoundError if
           the provided taskId does not correspond to an existing
           task." TaskNotFoundError carries JSON-RPC code -32001
           per §9.5 (line 1182).

           Strictness mirrors the capability contracts: a 200+result
           on a bogus id is a hard failure; any error is a soft
           pass (-32001 strict, others soft).
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    TASK_NOT_FOUND_CODE,
    call_method,
)
from a2a_testbed.transport import Transport


def make_tasks_get_not_found_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        bogus_id = str(uuid.uuid4())
        envelope = await call_method(
            transport, agent_url, "tasks/get", {"id": bogus_id}
        )
        if "error" in envelope and envelope.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement tasks/get (-32601)"
        if "result" in envelope and envelope.get("error") is None:
            raise AssertionError(
                f"tasks/get returned a result for bogus id {bogus_id!r}; "
                "spec mandates TaskNotFoundError (-32001)"
            )
        error = envelope.get("error") or {}
        code = error.get("code")
        if code == TASK_NOT_FOUND_CODE:
            return None
        return (
            f"agent rejected unknown taskId (good) but with code {code} "
            f"({error.get('message') or '?'}); spec mandates "
            f"{TASK_NOT_FOUND_CODE} (TaskNotFoundError)"
        )

    return Contract(
        id="transport.tasks_get_not_found",
        description=(
            "tasks/get on an unknown id returns TaskNotFoundError (§3.1.3 + §9.5)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
