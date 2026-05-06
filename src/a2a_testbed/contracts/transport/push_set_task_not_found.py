# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: pushNotificationConfig/set on unknown taskId fails.

  Spec:    A2A 1.0 §3.1.7 (CreateTaskPushNotificationConfig), §9.5
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Setting a push config against a non-existent taskId MUST
           return ``TaskNotFoundError`` (-32001). Same strict /
           soft-pass model as the other not-found contracts.
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    TASK_NOT_FOUND_CODE,
    call_method,
    fetch_card,
    push_skip_detail,
)
from a2a_testbed.transport import Transport


def make_push_set_task_not_found_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        card = await fetch_card(transport, agent_url)
        skip = push_skip_detail(card)
        if skip:
            return skip
        bogus = str(uuid.uuid4())
        envelope = await call_method(
            transport,
            agent_url,
            "tasks/pushNotificationConfig/set",
            {
                "taskId": bogus,
                "pushNotificationConfig": {
                    "url": "https://example.invalid/webhook",
                },
            },
        )
        if "error" in envelope and envelope.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement pushNotificationConfig/set"
        if "result" in envelope and envelope.get("error") is None:
            raise AssertionError(
                f"set returned a result for bogus taskId {bogus!r}; spec "
                "mandates TaskNotFoundError (-32001)"
            )
        error = envelope.get("error") or {}
        code = error.get("code")
        if code == TASK_NOT_FOUND_CODE:
            return None
        return (
            f"agent rejected unknown taskId on push set (good) but with "
            f"code {code} ({error.get('message') or '?'}); spec mandates "
            f"{TASK_NOT_FOUND_CODE}"
        )

    return Contract(
        id="transport.push_set_task_not_found",
        description=(
            "pushNotificationConfig/set on unknown taskId returns -32001 (§3.1.7)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
