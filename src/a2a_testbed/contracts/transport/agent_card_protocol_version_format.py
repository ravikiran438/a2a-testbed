# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: supportedInterfaces[*].protocolVersion is Major.Minor.

  Spec:    A2A 1.0 §3.6 (Protocol Versioning), §8.3.1
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Patch version numbers SHOULD NOT be used in requests,
           responses and Agent Cards, and MUST not be considered
           when clients and servers negotiate protocol versions.
           Each ``supportedInterfaces[*]`` entry MAY declare a
           ``protocolVersion`` indicating which A2A revision that
           binding speaks; the value, when present, MUST be in
           ``<major>.<minor>`` form (e.g. ``"1.0"``), never with a
           patch suffix.
"""

from __future__ import annotations

import json
import re

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


# Major.Minor only.
_PROTOCOL_VERSION = re.compile(r"^\d+\.\d+$")


def make_agent_card_protocol_version_format_contract(
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
        body = json.loads(resp.text)
        interfaces = body.get("supportedInterfaces") or []
        if not isinstance(interfaces, list):
            return  # caught by the supported_interfaces shape contract
        offenders: list[str] = []
        for i, entry in enumerate(interfaces):
            if not isinstance(entry, dict):
                continue
            version = entry.get("protocolVersion")
            if version is None:
                continue  # OPTIONAL field; skip when absent
            if not isinstance(version, str):
                offenders.append(
                    f"supportedInterfaces[{i}].protocolVersion must be "
                    f"a string; got {type(version).__name__}"
                )
                continue
            if not _PROTOCOL_VERSION.match(version):
                offenders.append(
                    f"supportedInterfaces[{i}].protocolVersion "
                    f"{version!r} MUST match Major.Minor (e.g. '1.0'); "
                    "patch numbers SHOULD NOT appear (§3.6)"
                )
        assert not offenders, "; ".join(offenders)

    return Contract(
        id="transport.agent_card_protocol_version_format",
        description=(
            "supportedInterfaces[*].protocolVersion is Major.Minor (no patch) per §3.6"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
