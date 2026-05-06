# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: pushNotificationConfig/get retrieves the stored config.

  Spec:    A2A 1.0 §3.1.8 (GetTaskPushNotificationConfig)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Given a (taskId, pushNotificationConfigId) pair previously
           returned by ``set``, ``get`` MUST return the same config
           — ``id`` matching, ``url`` matching what was stored.
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


def make_push_get_returns_config_contract(
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
        client_url = "https://example.invalid/webhook/" + uuid.uuid4().hex[:8]
        set_env = await call_method(
            transport,
            agent_url,
            "tasks/pushNotificationConfig/set",
            {"taskId": seed["id"], "pushNotificationConfig": {"url": client_url}},
        )
        if "error" in set_env and set_env.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement pushNotificationConfig/set"
        cfg_id = ((set_env.get("result") or {}).get("pushNotificationConfig") or {}).get("id")
        assert isinstance(cfg_id, str), "set did not return a config id"
        get_env = await call_method(
            transport,
            agent_url,
            "tasks/pushNotificationConfig/get",
            {"taskId": seed["id"], "pushNotificationConfigId": cfg_id},
        )
        if "error" in get_env and get_env.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement pushNotificationConfig/get"
        result = get_env.get("result")
        assert isinstance(result, dict), "get MUST return a result object"
        cfg = result.get("pushNotificationConfig")
        assert isinstance(cfg, dict), "result.pushNotificationConfig MUST be present"
        assert cfg.get("id") == cfg_id, (
            f"get returned id {cfg.get('id')!r}; expected {cfg_id!r}"
        )
        assert cfg.get("url") == client_url, (
            f"get returned url {cfg.get('url')!r}; expected {client_url!r}"
        )
        return None

    return Contract(
        id="transport.push_get_returns_config",
        description=(
            "pushNotificationConfig/get retrieves the stored config (§3.1.8)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
