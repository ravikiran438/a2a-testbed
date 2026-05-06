# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: every skill on the AgentCard has a unique id.

  Spec:    A2A 1.0 §4.4.1 (AgentCardSkill)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Each ``AgentCardSkill.id`` is a stable identifier the client
           uses to invoke the skill. Duplicate ids would make the
           identifier ambiguous, so they MUST be unique within a card.
"""

from __future__ import annotations

import json
from collections import Counter

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def make_agent_card_skill_id_unique_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        skills = body.get("skills") or []
        if not isinstance(skills, list):
            return  # caught by the skill_attributes shape contract
        ids = [s.get("id") for s in skills if isinstance(s, dict)]
        ids = [i for i in ids if isinstance(i, str) and i]
        counts = Counter(ids)
        duplicates = [i for i, n in counts.items() if n > 1]
        assert not duplicates, (
            f"duplicate skill ids on AgentCard: {sorted(duplicates)} "
            f"— each skill.id MUST be unique within the card (§4.4.1)"
        )

    return Contract(
        id="transport.agent_card_skill_id_unique",
        description=(
            "AgentCard.skills[*].id values are unique within the card (§4.4.1)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
