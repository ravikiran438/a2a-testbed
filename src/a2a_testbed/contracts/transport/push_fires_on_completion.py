# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: agent fires push notification on task completion.

Spec:    A2A 1.0 §3.5 (Push Notifications)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  When a Task completes (or transitions to any terminal
         state) AND the client has registered a push config for
         that task, the agent MUST POST the Task to the registered
         url. Without delivery, push is decorative.

         Mechanism: configure the agent to push to our hosted
         receiver, drive a fresh task to completion, poll the
         receiver for the captured webhook. Override the receiver
         via ``A2A_TESTBED_PUSH_RECEIVER`` env var.
"""

from __future__ import annotations

import asyncio
import json

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    METHOD_NOT_FOUND_CODE,
    TERMINAL_TASK_STATES,
    AgentProbe,
    error_code,
    fresh_token,
    push_receiver_base,
    push_skip_detail,
    read_received_hooks,
    webhook_task_id,
)
from a2a_testbed.transport import Transport
from a2a_testbed.transport.dialect import push_set_params


def make_push_fires_on_completion_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        skip = push_skip_detail(probe.card)
        if skip:
            return skip
        token = fresh_token()
        webhook_url = f"{push_receiver_base().rstrip('/')}/webhook/{token}"
        # Async path: the agent must return BEFORE the task completes
        # so we can register the push config in time. A non-blocking
        # send (1.0 returnImmediately / 0.3 blocking=false) asks the
        # agent to return the task in WORKING/SUBMITTED state and
        # finish in the background. Agents that don't honor it
        # complete synchronously and we can't reliably win the race;
        # the contract reports "skipped" in that case.
        fresh_task = await probe.send_for_task(blocking=False)
        if fresh_task is None:
            return "skipped — agent did not return a Task for a non-blocking send"
        if fresh_task.get("status", {}).get("state") in TERMINAL_TASK_STATES:
            return (
                "skipped — agent ignored the non-blocking request (task already "
                "in terminal state on response); cannot reliably register "
                "push config in time to receive the webhook"
            )
        set_env = await probe.call(
            "push_set", push_set_params(probe.dialect, fresh_task["id"], url=webhook_url)
        )
        if error_code(set_env) == METHOD_NOT_FOUND_CODE:
            return f"skipped — agent does not implement {probe.method('push_set')} (-32601)"
        # Poll the receiver. The agent may push before or after the
        # task completes; allow a few seconds.
        deadline = 5.0  # seconds
        interval = 0.25
        elapsed = 0.0
        hooks: list = []
        while elapsed < deadline:
            hooks = await read_received_hooks(token)
            if hooks:
                break
            await asyncio.sleep(interval)
            elapsed += interval
        assert hooks, (
            f"no webhook fired within {deadline}s after task completion; "
            f"agent advertises pushNotifications=true but did not deliver "
            f"to {webhook_url}"
        )
        # Sanity: payload should reference the task id we set the
        # config against. 1.0 posts a StreamResponse (§4.3.3); 0.3
        # posted the bare Task.
        first = hooks[0]
        body = first.get("body", "") if isinstance(first, dict) else ""
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        if webhook_task_id(probe.dialect, payload) != fresh_task["id"]:
            return (
                f"webhook delivered (good) but payload didn't carry the "
                f"task id; received body {body[:120]!r}"
            )
        return None

    return Contract(
        id="transport.push_fires_on_completion",
        description=("Agent POSTs the Task to a registered push URL on completion (§3.5)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
