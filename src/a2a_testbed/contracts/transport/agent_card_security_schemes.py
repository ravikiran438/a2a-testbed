# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: declared security schemes use recognized types.

  Spec:    A2A 1.0 §7.3 (Authentication and Authorization)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  When the AgentCard declares ``securitySchemes``, each entry
           identifies an authentication mechanism the client uses to
           talk to the agent. The recognized scheme types follow the
           OpenAPI 3.0 SecurityScheme object: ``apiKey``, ``http``,
           ``oauth2``, ``openIdConnect``, ``mutualTLS``. Unknown
           values mean clients can't pick a credential strategy and
           silently fall back to anonymous, defeating the declaration.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


_RECOGNIZED_TYPES = {"apiKey", "http", "oauth2", "openIdConnect", "mutualTLS"}


def make_agent_card_security_schemes_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        schemes = body.get("securitySchemes")
        if schemes is None:
            return  # OPTIONAL field; nothing to validate
        assert isinstance(schemes, dict), (
            "securitySchemes MUST be an object keyed by scheme name "
            f"if present; got {type(schemes).__name__}"
        )
        for name, spec in schemes.items():
            assert isinstance(spec, dict), (
                f"securitySchemes[{name!r}] MUST be an object"
            )
            kind = spec.get("type")
            assert kind in _RECOGNIZED_TYPES, (
                f"securitySchemes[{name!r}].type {kind!r} is not a "
                f"recognized OpenAPI scheme; expected one of "
                f"{sorted(_RECOGNIZED_TYPES)}"
            )

    return Contract(
        id="transport.agent_card_security_schemes",
        description=(
            "Declared securitySchemes use recognized OpenAPI types per §7.3"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
