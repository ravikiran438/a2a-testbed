# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: pushNotificationConfig/list returns every stored config.

Spec:    A2A 1.0 §3.1.9 (ListTaskPushNotificationConfig)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  After registering N push configs against a task,
         ``list`` MUST return all of them — the contract sets two,
         then asserts both ids appear in the listing.
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
from a2a_testbed.transport.dialect import push_list_params, push_set_params


def make_push_list_returns_all_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = push_skip_detail(probe.card)
        if skip:
            return skip
        seed = await probe.send_for_task()
        if seed is None:
            return "skipped — agent did not return a Task"
        ids: list[str] = []
        for i in range(2):
            url = f"https://example.invalid/webhook/{uuid.uuid4().hex[:8]}-{i}"
            set_env = await probe.call(
                "push_set", push_set_params(probe.dialect, seed["id"], url=url)
            )
            if error_code(set_env) == METHOD_NOT_FOUND_CODE:
                return f"skipped — agent does not implement {probe.method('push_set')} (-32601)"
            cfg_id = (probe.push_config_of(set_env.get("result")) or {}).get("id")
            assert isinstance(cfg_id, str), "set did not return a config id"
            ids.append(cfg_id)
        list_env = await probe.call("push_list", push_list_params(probe.dialect, seed["id"]))
        if error_code(list_env) == METHOD_NOT_FOUND_CODE:
            return f"skipped — agent does not implement {probe.method('push_list')} (-32601)"
        configs = probe.push_config_list_of(list_env.get("result"))
        assert isinstance(configs, list), (
            f"{probe.method('push_list')} MUST return the configs array "
            "(1.0: result.configs; 0.3: a bare array)"
        )
        listed_ids = {c.get("id") for c in configs if isinstance(c, dict)}
        for cid in ids:
            assert cid in listed_ids, (
                f"list omitted previously-set config id {cid!r}; "
                f"got {sorted(i for i in listed_ids if isinstance(i, str))}"
            )
        return None

    return Contract(
        id="transport.push_list_returns_all",
        description=("pushNotificationConfig/list returns every stored config (§3.1.9)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
