# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: JSON-RPC responses always carry ``jsonrpc: "2.0"``.

  Spec:    JSON-RPC 2.0 §5 + A2A 1.0 §9.3
  Source:  https://www.jsonrpc.org/specification#response_object
           docs/specification.md §9.3 (LF AI & Data A2A repo)
  Clause:  Every JSON-RPC response object MUST include the member
           ``jsonrpc`` with the exact string value ``"2.0"``.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport, WireMessage


def make_jsonrpc_version_field_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        wire = WireMessage(
            sender_id="contract",
            receiver_id="agent",
            action_label="probe",
            text="version-field probe",
            metadata={"request_id": "contract-version-probe"},
        )
        payload = transport.encode_request(wire)
        url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
        assert resp.status_code == 200
        body = json.loads(resp.text)
        assert "jsonrpc" in body, (
            "response missing required 'jsonrpc' member (JSON-RPC 2.0 §5)"
        )
        assert body["jsonrpc"] == "2.0", (
            f"response jsonrpc={body['jsonrpc']!r}, expected exactly \"2.0\""
        )

    return Contract(
        id="transport.jsonrpc_version_field",
        description="JSON-RPC response carries jsonrpc=\"2.0\" per spec §5",
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
