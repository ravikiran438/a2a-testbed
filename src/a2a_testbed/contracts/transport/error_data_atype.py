# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: error.data entries carry @type per ProtoJSON.

  Spec:    A2A 1.0 §3.3.2 (Error Handling)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  When a JSON-RPC error response carries ``error.data``, the
           field is an array of typed objects. Each object MUST
           include a ``@type`` key per the ProtoJSON ``Any``
           representation (e.g. ``type.googleapis.com/lf.a2a.v1.X``).
           Clients dispatch on ``@type`` to extract structured
           context; missing ``@type`` keys leave clients unable to
           parse the data and silently drop the diagnostic.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def make_error_data_atype_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        # Trigger a known error: malformed `message/send` (no params).
        # Most A2A agents respond with -32602 (invalid params); the
        # specific code doesn't matter for this contract — only the
        # data array shape does.
        rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": "error-data-probe",
                    "method": "message/send",
                    "params": {},
                },
                headers={"content-type": "application/json"},
            )
        try:
            body = json.loads(resp.text)
        except json.JSONDecodeError:
            return  # not JSON; covered by other contracts
        error = (body.get("error") or {}) if isinstance(body, dict) else {}
        data = error.get("data")
        if data is None:
            return  # OPTIONAL field; nothing to validate
        assert isinstance(data, list), (
            f"error.data MUST be an array when present; got {type(data).__name__}"
        )
        offenders: list[str] = []
        for i, entry in enumerate(data):
            if not isinstance(entry, dict):
                offenders.append(f"error.data[{i}] is not an object")
                continue
            atype = entry.get("@type")
            if not isinstance(atype, str) or not atype:
                offenders.append(
                    f"error.data[{i}] missing required '@type' key (§3.3.2)"
                )
        assert not offenders, "; ".join(offenders)

    return Contract(
        id="transport.error_data_atype",
        description=(
            "error.data[*] entries carry @type per ProtoJSON Any (§3.3.2)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
