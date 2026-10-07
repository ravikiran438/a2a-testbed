# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: extended card op is gated on the capability.

Spec:    A2A 1.0 §3.1.7 (Get Authenticated Extended Agent Card),
         §9.5 (Errors)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  If ``AgentCard.capabilities.extendedAgentCard`` is ``false``
         or not present, attempts to call ``GetExtendedAgentCard``
         (method ``agent/getAuthenticatedExtendedCard``) MUST return
         ``UnsupportedOperationError`` (code -32004). Strictness mirrors
         ``streaming_capability_consistency``: 200+result fails;
         any error passes (strict on -32004, soft on others).
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    AgentProbe,
)
from a2a_testbed.transport import Transport

_EXPECTED_CODE = -32004


def make_extended_card_capability_consistency_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        probe = await AgentProbe.create(transport, agent_url)
        assert probe.card, "card endpoint did not return a JSON AgentCard"
        # 1.0: capabilities.extendedAgentCard; 0.3 cards declared it as
        # top-level supportsAuthenticatedExtendedCard (converted in card_v1).
        if probe.capability("extendedAgentCard") is True:
            return "skipped — agent advertises extendedAgentCard=true"
        req = {
            "jsonrpc": "2.0",
            "id": "contract-extended-card",
            "method": probe.method("extended_card"),
            "params": {},
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(probe.rpc_url, json=req, headers=probe.headers())
        try:
            body = json.loads(resp.text)
        except json.JSONDecodeError:
            raise AssertionError(
                f"extendedAgentCard=false but extended card op returned "
                f"non-JSON (status {resp.status_code}); expected JSON-RPC error"
            )
        if "result" in body and body.get("error") is None:
            raise AssertionError(
                "agent advertises extendedAgentCard=false but "
                f"{probe.method('extended_card')} returned a result; "
                "per §3.1.7 it MUST return UnsupportedOperationError "
                "(-32004)"
            )
        error = body.get("error") or {}
        code = error.get("code")
        if code == _EXPECTED_CODE:
            return None
        return (
            f"capability honored — agent refused extended-card op as required "
            f"(§3.1.7), but returned code {code} ({error.get('message') or '?'}); "
            f"spec mandates {_EXPECTED_CODE} (UnsupportedOperationError)"
        )

    return Contract(
        id="transport.extended_card_capability_consistency",
        description=("Extended-card op returns -32004 when extendedAgentCard=false (§3.1.7)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
