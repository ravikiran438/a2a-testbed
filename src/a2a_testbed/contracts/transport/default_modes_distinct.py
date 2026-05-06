# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: default input/output modes contain no duplicates.

  Spec:    A2A 1.0 §4.4.1 (AgentCard mode declarations)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  ``defaultInputModes`` and ``defaultOutputModes`` enumerate
           the media types the agent accepts / emits by default.
           Duplicates inflate the count without adding capability and
           suggest a card-generation bug; the lists are sets in spirit.
"""

from __future__ import annotations

import json
from collections import Counter

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def make_default_modes_distinct_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        offenders: list[str] = []
        for field in ("defaultInputModes", "defaultOutputModes"):
            modes = body.get(field)
            if not isinstance(modes, list):
                continue
            counts = Counter(m for m in modes if isinstance(m, str))
            dups = sorted(m for m, n in counts.items() if n > 1)
            if dups:
                offenders.append(f"{field} has duplicates: {dups}")
        assert not offenders, "; ".join(offenders)

    return Contract(
        id="transport.default_modes_distinct",
        description=(
            "defaultInputModes / defaultOutputModes contain no duplicate values (§4.4.1)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
