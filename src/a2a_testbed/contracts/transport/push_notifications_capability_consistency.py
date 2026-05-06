# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: push notification ops are gated on the capability.

  Spec:    A2A 1.0 §3.5 (Push Notifications), §9.5 (Errors)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  If ``AgentCard.capabilities.pushNotifications`` is ``false``
           or not present, the push notification configuration
           operations (``tasks/pushNotificationConfig/set``, /get, /list,
           /delete) MUST return ``PushNotificationNotSupportedError``
           (code -32003). Strictness mirrors
           ``streaming_capability_consistency``: 200+result fails;
           any error passes (strict on -32003, soft on others).
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


_EXPECTED_CODE = -32003


def make_push_notifications_capability_consistency_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            card_resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
            assert card_resp.status_code == 200
            card_body = json.loads(card_resp.text)
            push = (card_body.get("capabilities") or {}).get(
                "pushNotifications"
            )
            if push is True:
                # Capability claimed; positive-case validation is roadmap.
                return "skipped — agent advertises pushNotifications=true"

            rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
            set_request = {
                "jsonrpc": "2.0",
                "id": "contract-push",
                "method": "tasks/pushNotificationConfig/set",
                "params": {
                    "taskId": "00000000-0000-0000-0000-000000000000",
                    "pushNotificationConfig": {
                        "url": "https://example.invalid/webhook",
                    },
                },
            }
            resp = await client.post(
                rpc_url,
                json=set_request,
                headers={"content-type": "application/json"},
            )

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
                "tasks/pushNotificationConfig/set returned a result; "
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
        description=(
            "Push config returns -32003 when pushNotifications=false (§3.5)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
