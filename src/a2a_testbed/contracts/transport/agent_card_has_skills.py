# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: each AgentCard skill carries the REQUIRED
attributes (id, name, description, ≥1 tag).

  Spec:    A2A 1.0 §4.4.1 (AgentCard schema)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Each AgentSkill MUST include ``id``, ``name``,
           ``description``, and at least one entry in ``tags``.
"""

from __future__ import annotations

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def make_agent_card_skill_attributes_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        card = transport.parse_card_text(resp.text)
        skills = list(getattr(card, "skills", []) or [])
        assert skills, "AgentCard MUST have ≥1 skill (already covered by required-fields contract)"

        for i, skill in enumerate(skills):
            sid = getattr(skill, "id", None)
            sname = getattr(skill, "name", None)
            sdesc = getattr(skill, "description", None)
            stags = list(getattr(skill, "tags", []) or [])
            assert sid, f"skill[{i}].id is REQUIRED but missing/empty"
            assert sname, f"skill[{i}].name is REQUIRED but missing/empty"
            assert sdesc, f"skill[{i}].description is REQUIRED but missing/empty"
            assert len(stags) >= 1, (
                f"skill[{i}].tags MUST have ≥1 entry"
            )

        # Skill ids are unique within an agent (implicit invariant)
        seen_ids = [getattr(s, "id", "") for s in skills]
        assert len(seen_ids) == len(set(seen_ids)), (
            f"skill ids MUST be unique within an agent; saw duplicates in {seen_ids}"
        )

    return Contract(
        id="transport.agent_card_skill_attributes",
        description=(
            "Every AgentCard skill carries id/name/description/≥1 tag "
            "per A2A 1.0 §4.4.1, with unique skill ids"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
