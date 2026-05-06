# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: JSON serialization uses camelCase field names.

  Spec:    A2A 1.0 §5.5 (JSON Naming)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  All A2A bindings that emit JSON MUST use camelCase field
           names (e.g., ``messageId``, ``contextId``,
           ``defaultInputModes``), not snake_case from proto.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


# Snake-case field names that, if seen in the response, indicate a
# binding bug. These come from common A2A proto field names.
_FORBIDDEN_SNAKE_CASE = {
    "default_input_modes",
    "default_output_modes",
    "supported_interfaces",
    "security_schemes",
    "security_requirements",
    "documentation_url",
    "icon_url",
    "context_id",
    "task_id",
    "message_id",
    "artifact_id",
    "protocol_binding",
    "protocol_version",
}


def _walk_keys(obj):
    """Yield every dict key in a nested JSON object."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


def make_json_camel_case_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        offenders = sorted(
            k for k in _walk_keys(body) if k in _FORBIDDEN_SNAKE_CASE
        )
        assert not offenders, (
            f"AgentCard JSON contains snake_case fields: {offenders}; "
            f"spec §5.5 mandates camelCase"
        )

    return Contract(
        id="transport.json_camel_case",
        description="JSON field names are camelCase per A2A 1.0 §5.5",
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
