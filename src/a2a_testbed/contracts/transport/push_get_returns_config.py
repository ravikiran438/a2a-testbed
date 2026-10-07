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
    METHOD_NOT_FOUND_CODE,
    AgentProbe,
    error_code,
    push_skip_detail,
)
from a2a_testbed.transport import Transport
from a2a_testbed.transport.dialect import push_get_params, push_set_params


def make_push_get_returns_config_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = push_skip_detail(probe.card)
        if skip:
            return skip
        seed = await probe.send_for_task()
        if seed is None:
            return "skipped — agent did not return a Task"
        client_url = "https://example.invalid/webhook/" + uuid.uuid4().hex[:8]
        set_env = await probe.call(
            "push_set", push_set_params(probe.dialect, seed["id"], url=client_url)
        )
        if error_code(set_env) == METHOD_NOT_FOUND_CODE:
            return f"skipped — agent does not implement {probe.method('push_set')} (-32601)"
        cfg_id = (probe.push_config_of(set_env.get("result")) or {}).get("id")
        assert isinstance(cfg_id, str), "set did not return a config id"
        get_env = await probe.call("push_get", push_get_params(probe.dialect, seed["id"], cfg_id))
        if error_code(get_env) == METHOD_NOT_FOUND_CODE:
            return f"skipped — agent does not implement {probe.method('push_get')} (-32601)"
        result = get_env.get("result")
        assert isinstance(result, dict), "get MUST return a result object"
        cfg = probe.push_config_of(result)
        assert cfg.get("id") == cfg_id, f"get returned id {cfg.get('id')!r}; expected {cfg_id!r}"
        assert cfg.get("url") == client_url, (
            f"get returned url {cfg.get('url')!r}; expected {client_url!r}"
        )
        return None

    return Contract(
        id="transport.push_get_returns_config",
        description=("pushNotificationConfig/get retrieves the stored config (§3.1.8)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
