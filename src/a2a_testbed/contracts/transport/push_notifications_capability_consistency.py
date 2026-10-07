# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: push notification ops are gated on the capability.

Spec:    A2A 1.0 §3.5 (Push Notifications), §9.5 (Errors)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  If ``AgentCard.capabilities.pushNotifications`` is ``false``
         or not present, the push notification configuration
         operations (``{Create,Get,List,Delete}TaskPushNotificationConfig``;
         ``tasks/pushNotificationConfig/*`` in 0.3) MUST return
         ``PushNotificationNotSupportedError``
         (code -32003). Strictness mirrors
         ``streaming_capability_consistency``: 200+result fails;
         any error passes (strict on -32003, soft on others).
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    AgentProbe,
)
from a2a_testbed.transport import Transport
from a2a_testbed.transport.dialect import push_set_params

_EXPECTED_CODE = -32003


def make_push_notifications_capability_consistency_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        probe = await AgentProbe.create(transport, agent_url)
        assert probe.card, "card endpoint did not return a JSON AgentCard"
        if probe.capability("pushNotifications") is True:
            # Capability claimed; the push_* contracts cover the positive case.
            return "skipped — agent advertises pushNotifications=true"
        set_request = {
            "jsonrpc": "2.0",
            "id": "contract-push",
            "method": probe.method("push_set"),
            "params": push_set_params(
                probe.dialect,
                "00000000-0000-0000-0000-000000000000",
                url="https://example.invalid/webhook",
            ),
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(probe.rpc_url, json=set_request, headers=probe.headers())
        try:
            body = json.loads(resp.text)
        except json.JSONDecodeError:
            raise AssertionError(
                f"pushNotifications=false but set returned non-JSON "
                f"(status {resp.status_code}); expected JSON-RPC error per §9.5"
            )
        if "result" in body and body.get("error") is None:
            raise AssertionError(
                "agent advertises pushNotifications=false but "
                f"{probe.method('push_set')} returned a result; "
                "per §3.5 it MUST return PushNotificationNotSupportedError "
                "(-32003)"
            )
        error = body.get("error") or {}
        code = error.get("code")
        if code == _EXPECTED_CODE:
            return None
        return (
            f"capability honored — agent refused push config as required "
            f"(§3.5), but returned code {code} ({error.get('message') or '?'}); "
            f"spec mandates {_EXPECTED_CODE} (PushNotificationNotSupportedError)"
        )

    return Contract(
        id="transport.push_notifications_capability_consistency",
        description=("Push config returns -32003 when pushNotifications=false (§3.5)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
