# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: pushNotificationConfig/set returns the stored config.

  Spec:    A2A 1.0 §3.1.7 (CreateTaskPushNotificationConfig)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Setting a push notification config MUST return the stored
           record under the response's
           ``pushNotificationConfig`` key, including the assigned
           ``id`` and the ``url`` the client supplied. Without that
           echo the client can't address the config later
           (get/list/delete operations key on id).
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


def make_push_set_persists_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        card = await fetch_card(transport, agent_url)
        skip = push_skip_detail(card)
        if skip:
            return skip
        seed = await probe_for_task(transport, agent_url)
        if seed is None:
            return "skipped — agent did not return a Task to attach config to"
        client_url = "https://example.invalid/webhook/" + uuid.uuid4().hex[:8]
        envelope = await call_method(
            transport,
            agent_url,
            "tasks/pushNotificationConfig/set",
            {
                "taskId": seed["id"],
                "pushNotificationConfig": {"url": client_url},
            },
        )
        if "error" in envelope and envelope.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement pushNotificationConfig/set"
        result = envelope.get("result")
        assert isinstance(result, dict), (
            f"set MUST return a result object; got {type(result).__name__}"
        )
        cfg = result.get("pushNotificationConfig")
        assert isinstance(cfg, dict), (
            "result.pushNotificationConfig MUST be present"
        )
        assert cfg.get("url") == client_url, (
            f"set returned url {cfg.get('url')!r}; expected {client_url!r}"
        )
        cfg_id = cfg.get("id")
        assert isinstance(cfg_id, str) and cfg_id, (
            "result.pushNotificationConfig.id MUST be assigned (non-empty string)"
        )
        return None

    return Contract(
        id="transport.push_set_persists",
        description=(
            "pushNotificationConfig/set returns the stored config with id (§3.1.7)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
