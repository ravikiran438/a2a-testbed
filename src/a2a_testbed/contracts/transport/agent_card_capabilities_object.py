# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: capabilities object is present and uses the
documented field names.

  Spec:    A2A 1.0 §4.4.1 (AgentCard schema), §3.3.4 (Capability validation)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  AgentCard.capabilities is REQUIRED; recognized booleans
           are ``streaming``, ``pushNotifications``, ``extendedAgentCard``;
           extensions array carries declared protocol extensions.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


_RECOGNIZED_BOOL_FIELDS = {
    "streaming",
    "pushNotifications",
    "extendedAgentCard",
}


def make_agent_card_capabilities_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        caps = body.get("capabilities")
        assert isinstance(caps, dict), (
            "capabilities MUST be a JSON object on the AgentCard "
            "(spec §4.4.1); got " + repr(type(caps))
        )

        # Every recognized boolean field, if present, is actually a bool
        for field in _RECOGNIZED_BOOL_FIELDS:
            if field in caps:
                assert isinstance(caps[field], bool), (
                    f"capabilities.{field} MUST be a boolean if present; "
                    f"got {type(caps[field]).__name__}"
                )

        # extensions array is well-formed if present
        extensions = caps.get("extensions")
        if extensions is not None:
            assert isinstance(extensions, list), (
                "capabilities.extensions MUST be a JSON array if present"
            )
            for i, ext in enumerate(extensions):
                assert isinstance(ext, dict), (
                    f"extensions[{i}] MUST be an object"
                )
                assert "uri" in ext and ext["uri"], (
                    f"extensions[{i}].uri is REQUIRED but missing/empty"
                )

    return Contract(
        id="transport.agent_card_capabilities_object",
        description=(
            "AgentCard.capabilities is a well-formed object per A2A 1.0 §4.4.1"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
