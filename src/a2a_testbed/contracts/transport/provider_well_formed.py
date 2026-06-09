# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: AgentCard.provider is well-formed when present.

Spec:    A2A 1.0 §4.4.1 (AgentCardProvider)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  ``provider`` is OPTIONAL on the AgentCard. When present,
         it identifies the operator running the agent: the
         ``organization`` field is the human-readable provider name
         and ``url`` (when present) MUST be an absolute URL to the
         provider's site. A provider object with neither field
         contributes no information and is non-conformant.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def make_provider_well_formed_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(agent_url.rstrip("/") + transport.card_endpoint_path())
        assert resp.status_code == 200
        body = json.loads(resp.text)
        provider = body.get("provider")
        if provider is None:
            return  # OPTIONAL field; nothing to validate
        assert isinstance(provider, dict), (
            f"provider MUST be a JSON object when present; got {type(provider).__name__}"
        )
        org = provider.get("organization")
        url = provider.get("url")
        assert isinstance(org, str) and org, (
            "provider.organization is REQUIRED when provider is present"
        )
        if url is not None:
            assert isinstance(url, str) and url, (
                "provider.url must be a non-empty string when present"
            )
            parsed = urlparse(url)
            assert parsed.scheme and parsed.netloc, f"provider.url {url!r} MUST be an absolute URL"

    return Contract(
        id="transport.provider_well_formed",
        description=(
            "AgentCard.provider object (when present) carries organization + valid URL (§4.4.1)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
