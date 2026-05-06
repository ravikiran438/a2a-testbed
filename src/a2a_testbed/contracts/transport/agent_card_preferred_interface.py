# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: supportedInterfaces[0] is the preferred interface.

  Spec:    A2A 1.0 §8.3.1 (Multiple Transport Bindings)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  The first entry in ``supportedInterfaces`` represents the
           preferred interface — the one the agent would like clients
           to use when they have a choice. The contract verifies the
           preferred entry is well-formed (has both ``url`` and
           ``protocolBinding``) so a client following spec guidance
           can pick it deterministically without falling back.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def make_agent_card_preferred_interface_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        interfaces = body.get("supportedInterfaces")
        assert isinstance(interfaces, list) and interfaces, (
            "supportedInterfaces MUST be a non-empty array (§8.3.1)"
        )
        preferred = interfaces[0]
        assert isinstance(preferred, dict), (
            "supportedInterfaces[0] MUST be an object"
        )
        url = preferred.get("url")
        binding = preferred.get("protocolBinding")
        assert isinstance(url, str) and url, (
            "supportedInterfaces[0].url is REQUIRED on the preferred "
            "interface"
        )
        assert isinstance(binding, str) and binding, (
            "supportedInterfaces[0].protocolBinding is REQUIRED on the "
            "preferred interface"
        )

    return Contract(
        id="transport.agent_card_preferred_interface",
        description=(
            "supportedInterfaces[0] is well-formed preferred interface (§8.3.1)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
