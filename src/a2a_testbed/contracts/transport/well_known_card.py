# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: well-known agent card endpoint is reachable
and returns valid card JSON.

  Spec:    A2A 1.0 §8.2 (Agent Card Discovery)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Agents MUST make an Agent Card available at the well-known
           URI ``https://{domain}/.well-known/agent-card.json`` per
           RFC 8615, retrievable via HTTP GET, parseable against the
           AgentCard schema.
"""

from __future__ import annotations

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.core.loader import AgentCardLoadError
from a2a_testbed.transport import Transport


def make_well_known_card_contract(transport: Transport, agent_url: str) -> Contract:
    """Build a contract that verifies one agent's well-known endpoint."""

    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(agent_url.rstrip("/") + transport.card_endpoint_path())
        assert resp.status_code == 200, (
            f"well-known card endpoint returned {resp.status_code}, expected 200"
        )
        try:
            card = transport.parse_card_text(resp.text)
        except (AgentCardLoadError, Exception) as exc:
            raise AssertionError(f"card body did not parse as a valid {transport.name} card: {exc}")
        # Minimal sanity check: card has a name field
        assert getattr(card, "name", None), "card.name is missing or empty"

    return Contract(
        id="transport.well_known_card",
        description="GET /<card-path> returns 200 and a parseable card.",
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
