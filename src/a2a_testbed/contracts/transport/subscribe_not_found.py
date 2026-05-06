# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: tasks/resubscribe on unknown id returns -32001.

  Spec:    A2A 1.0 §3.1.6 (SubscribeToTask), §9.5 (Errors)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Resubscribing to a Task id the agent doesn't have MUST
           return ``TaskNotFoundError`` (-32001) per §9.5. Same
           strict / soft-pass model as the other not-found contracts.
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    TASK_NOT_FOUND_CODE,
    call_method,
    fetch_card,
    streaming_skip_detail,
)
from a2a_testbed.transport import Transport


def make_subscribe_not_found_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        card = await fetch_card(transport, agent_url)
        skip = streaming_skip_detail(card)
        if skip:
            return skip
        bogus_id = str(uuid.uuid4())
        envelope = await call_method(
            transport, agent_url, "tasks/resubscribe", {"id": bogus_id}
        )
        if "error" in envelope and envelope.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement tasks/resubscribe (-32601)"
        if "result" in envelope and envelope.get("error") is None:
            raise AssertionError(
                f"tasks/resubscribe returned a result for bogus id {bogus_id!r}; "
                "spec mandates TaskNotFoundError (-32001)"
            )
        error = envelope.get("error") or {}
        code = error.get("code")
        if code == TASK_NOT_FOUND_CODE:
            return None
        return (
            f"agent rejected unknown taskId on resubscribe (good) but with "
            f"code {code} ({error.get('message') or '?'}); spec mandates "
            f"{TASK_NOT_FOUND_CODE}"
        )

    return Contract(
        id="transport.subscribe_not_found",
        description=(
            "tasks/resubscribe on unknown id returns TaskNotFoundError (§3.1.6 + §9.5)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
