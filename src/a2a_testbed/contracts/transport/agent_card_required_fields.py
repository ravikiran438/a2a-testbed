# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: AgentCard carries every REQUIRED field.

  Spec:    A2A 1.0 §4.4.1 (AgentCard schema), §8.1 (discovery)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  AgentCard MUST include: ``name``, ``description``, ``version``,
           ``supportedInterfaces`` (≥1 entry), ``capabilities``,
           ``defaultInputModes`` (≥1), ``defaultOutputModes`` (≥1),
           ``skills`` (≥1).
"""

from __future__ import annotations

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def make_agent_card_required_fields_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200, (
            f"card endpoint returned {resp.status_code}, expected 200"
        )
        card = transport.parse_card_text(resp.text)

        # Required scalar fields
        assert getattr(card, "name", None), "name is REQUIRED but missing/empty"
        assert getattr(card, "description", None), (
            "description is REQUIRED but missing/empty"
        )
        assert getattr(card, "version", None), (
            "version is REQUIRED but missing/empty"
        )

        # Required collections
        interfaces = list(getattr(card, "supported_interfaces", []) or [])
        assert len(interfaces) >= 1, (
            "supportedInterfaces MUST have ≥1 entry"
        )

        skills = list(getattr(card, "skills", []) or [])
        assert len(skills) >= 1, "skills MUST have ≥1 entry"

        input_modes = list(getattr(card, "default_input_modes", []) or [])
        assert len(input_modes) >= 1, "defaultInputModes MUST have ≥1 entry"

        output_modes = list(getattr(card, "default_output_modes", []) or [])
        assert len(output_modes) >= 1, "defaultOutputModes MUST have ≥1 entry"

        # capabilities object must be present (it MAY be empty but the field exists)
        assert card.HasField("capabilities"), (
            "capabilities object is REQUIRED on the AgentCard"
        )

    return Contract(
        id="transport.agent_card_required_fields",
        description=(
            "AgentCard carries every REQUIRED field per A2A 1.0 §4.4.1 + §8.1"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
