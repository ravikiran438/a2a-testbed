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
from a2a_testbed.transport import Transport


_EXPECTED_CODE = -32004


def make_extended_card_capability_consistency_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            card_resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
            assert card_resp.status_code == 200
            card_body = json.loads(card_resp.text)
            extended = (card_body.get("capabilities") or {}).get(
                "extendedAgentCard"
            )
            if extended is True:
                return "skipped — agent advertises extendedAgentCard=true"

            rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
            req = {
                "jsonrpc": "2.0",
                "id": "contract-extended-card",
                "method": "agent/getAuthenticatedExtendedCard",
                "params": {},
            }
            resp = await client.post(
                rpc_url,
                json=req,
                headers={"content-type": "application/json"},
            )

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
                "agent/getAuthenticatedExtendedCard returned a result; "
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
        description=(
            "Extended-card op returns -32004 when extendedAgentCard=false (§3.1.7)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
