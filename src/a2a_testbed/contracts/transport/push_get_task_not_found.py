# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: pushNotificationConfig/get on unknown taskId fails.

Spec:    A2A 1.0 §3.1.8 (GetTaskPushNotificationConfig), §9.5
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  Fetching a push config for a non-existent taskId MUST
         return ``TaskNotFoundError`` (-32001).
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    METHOD_NOT_FOUND_CODE,
    TASK_NOT_FOUND_CODE,
    AgentProbe,
    error_code,
    push_skip_detail,
)
from a2a_testbed.transport import Transport
from a2a_testbed.transport.dialect import push_get_params


def make_push_get_task_not_found_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = push_skip_detail(probe.card)
        if skip:
            return skip
        bogus_task = str(uuid.uuid4())
        bogus_cfg = str(uuid.uuid4())
        envelope = await probe.call(
            "push_get", push_get_params(probe.dialect, bogus_task, bogus_cfg)
        )
        if error_code(envelope) == METHOD_NOT_FOUND_CODE:
            return f"skipped — agent does not implement {probe.method('push_get')} (-32601)"
        if "result" in envelope and envelope.get("error") is None:
            raise AssertionError(
                f"get returned a result for bogus taskId {bogus_task!r}; "
                "spec mandates TaskNotFoundError (-32001)"
            )
        error = envelope.get("error") or {}
        code = error.get("code")
        if code == TASK_NOT_FOUND_CODE:
            return None
        return (
            f"agent rejected unknown taskId on push get (good) but with "
            f"code {code} ({error.get('message') or '?'}); spec mandates "
            f"{TASK_NOT_FOUND_CODE}"
        )

    return Contract(
        id="transport.push_get_task_not_found",
        description=("pushNotificationConfig/get on unknown taskId returns -32001 (§3.1.8)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
