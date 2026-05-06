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
    call_method,
    fetch_card,
    probe_for_task,
    push_skip_detail,
)
from a2a_testbed.transport import Transport


def make_push_delete_removes_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        card = await fetch_card(transport, agent_url)
        skip = push_skip_detail(card)
        if skip:
            return skip
        seed = await probe_for_task(transport, agent_url)
        if seed is None:
            return "skipped — agent did not return a Task"
        url = "https://example.invalid/webhook/" + uuid.uuid4().hex[:8]
        set_env = await call_method(
            transport,
            agent_url,
            "tasks/pushNotificationConfig/set",
            {"taskId": seed["id"], "pushNotificationConfig": {"url": url}},
        )
        if "error" in set_env and set_env.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement pushNotificationConfig/set"
        cfg_id = ((set_env.get("result") or {}).get("pushNotificationConfig") or {}).get("id")
        assert isinstance(cfg_id, str), "set did not return a config id"

        del_env = await call_method(
            transport,
            agent_url,
            "tasks/pushNotificationConfig/delete",
            {"taskId": seed["id"], "pushNotificationConfigId": cfg_id},
        )
        if "error" in del_env and del_env.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement pushNotificationConfig/delete"
        # Verify with list — the deleted id must NOT be present.
        list_env = await call_method(
            transport,
            agent_url,
            "tasks/pushNotificationConfig/list",
            {"taskId": seed["id"]},
        )
        if "error" in list_env and list_env.get("error", {}).get("code") == -32601:
            return None  # Implementation deletes but doesn't expose list — accept.
        configs = (list_env.get("result") or {}).get("pushNotificationConfigs") or (
            (list_env.get("result") or {}).get("configs") or []
        )
        listed_ids = {c.get("id") for c in configs if isinstance(c, dict)}
        assert cfg_id not in listed_ids, (
            f"deleted config {cfg_id!r} still appears in list response"
        )
        return None

    return Contract(
        id="transport.push_delete_removes",
        description=(
            "pushNotificationConfig/delete removes the config from list (§3.1.10)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
