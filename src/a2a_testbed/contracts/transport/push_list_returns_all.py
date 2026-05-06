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
    call_method,
    fetch_card,
    probe_for_task,
    push_skip_detail,
)
from a2a_testbed.transport import Transport


def make_push_list_returns_all_contract(
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
        ids: list[str] = []
        for i in range(2):
            url = f"https://example.invalid/webhook/{uuid.uuid4().hex[:8]}-{i}"
            set_env = await call_method(
                transport,
                agent_url,
                "tasks/pushNotificationConfig/set",
                {"taskId": seed["id"], "pushNotificationConfig": {"url": url}},
            )
            if "error" in set_env and set_env.get("error", {}).get("code") == -32601:
                return "skipped — agent does not implement pushNotificationConfig/set"
            cfg = (set_env.get("result") or {}).get("pushNotificationConfig") or {}
            cfg_id = cfg.get("id")
            assert isinstance(cfg_id, str), "set did not return a config id"
            ids.append(cfg_id)

        list_env = await call_method(
            transport,
            agent_url,
            "tasks/pushNotificationConfig/list",
            {"taskId": seed["id"]},
        )
        if "error" in list_env and list_env.get("error", {}).get("code") == -32601:
            return "skipped — agent does not implement pushNotificationConfig/list"
        result = list_env.get("result")
        assert isinstance(result, dict), "list MUST return a result object"
        configs = result.get("pushNotificationConfigs")
        # Some agents key the array as `configs` instead; accept either.
        if configs is None and "configs" in result:
            configs = result["configs"]
        assert isinstance(configs, list), (
            "result.pushNotificationConfigs MUST be an array"
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
        description=(
            "pushNotificationConfig/list returns every stored config (§3.1.9)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
