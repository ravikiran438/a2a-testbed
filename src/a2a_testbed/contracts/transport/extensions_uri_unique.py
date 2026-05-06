# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: extension URIs are unique within the AgentCard.

  Spec:    A2A 1.0 §4.4.4 (Extensions)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  ``capabilities.extensions[*].uri`` is the protocol identifier
           clients route on. Two entries with the same URI are
           ambiguous — clients can't tell which one's payload to honor
           when validation flags a discrepancy — so URIs MUST be unique
           within a single card.
"""

from __future__ import annotations

import json
from collections import Counter

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def make_extensions_uri_unique_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        extensions = (body.get("capabilities") or {}).get("extensions") or []
        if not isinstance(extensions, list):
            return
        uris = [
            e.get("uri")
            for e in extensions
            if isinstance(e, dict) and isinstance(e.get("uri"), str) and e.get("uri")
        ]
        duplicates = sorted(u for u, n in Counter(uris).items() if n > 1)
        assert not duplicates, (
            f"duplicate extension URIs on AgentCard: {duplicates} "
            "— each capabilities.extensions[*].uri MUST be unique (§4.4.4)"
        )

    return Contract(
        id="transport.extensions_uri_unique",
        description=(
            "capabilities.extensions[*].uri values are unique within the card (§4.4.4)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
