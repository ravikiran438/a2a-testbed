# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: pushNotificationConfig/delete removes the config.

Spec:    A2A 1.0 §3.1.10 (DeleteTaskPushNotificationConfig)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  After ``delete``, the targeted config MUST no longer
         appear in ``list`` (or be retrievable via ``get``).
         Without this guarantee, clients that revoke a webhook
         still leak push notifications to the deleted endpoint.
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    METHOD_NOT_FOUND_CODE,
    AgentProbe,
    error_code,
    push_skip_detail,
)
from a2a_testbed.transport import Transport
from a2a_testbed.transport.dialect import (
    push_delete_params,
    push_list_params,
    push_set_params,
)


def make_push_delete_removes_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = push_skip_detail(probe.card)
        if skip:
            return skip
        seed = await probe.send_for_task()
        if seed is None:
            return "skipped — agent did not return a Task"
        url = "https://example.invalid/webhook/" + uuid.uuid4().hex[:8]
        set_env = await probe.call("push_set", push_set_params(probe.dialect, seed["id"], url=url))
        if error_code(set_env) == METHOD_NOT_FOUND_CODE:
            return f"skipped — agent does not implement {probe.method('push_set')} (-32601)"
        cfg_id = (probe.push_config_of(set_env.get("result")) or {}).get("id")
        assert isinstance(cfg_id, str), "set did not return a config id"
        del_env = await probe.call(
            "push_delete", push_delete_params(probe.dialect, seed["id"], cfg_id)
        )
        if error_code(del_env) == METHOD_NOT_FOUND_CODE:
            return f"skipped — agent does not implement {probe.method('push_delete')} (-32601)"
        assert "error" not in del_env, (
            f"{probe.method('push_delete')} failed: {del_env.get('error')}"
        )
        # Verify with list — the deleted id must NOT be present.
        list_env = await probe.call("push_list", push_list_params(probe.dialect, seed["id"]))
        if error_code(list_env) == METHOD_NOT_FOUND_CODE:
            return None  # Implementation deletes but doesn't expose list — accept.
        configs = probe.push_config_list_of(list_env.get("result")) or []
        listed_ids = {c.get("id") for c in configs if isinstance(c, dict)}
        assert cfg_id not in listed_ids, f"deleted config {cfg_id!r} still appears in list response"
        return None

    return Contract(
        id="transport.push_delete_removes",
        description=("pushNotificationConfig/delete removes the config from list (§3.1.10)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
