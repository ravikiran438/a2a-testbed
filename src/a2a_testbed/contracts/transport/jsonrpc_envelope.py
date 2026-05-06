# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: agent's RPC endpoint returns a well-formed
JSON-RPC 2.0 response to a ``message/send`` request.

  Spec:    A2A 1.0 §3.1.1 (Send Message), §9.3 (JSON-RPC envelope),
           plus JSON-RPC 2.0 §5
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  ``message/send`` is the canonical A2A method (§3.1.1); per
           §9.3 every JSON-RPC request/response uses the JSON-RPC 2.0
           envelope; per JSON-RPC §5 every response carries
           ``jsonrpc: "2.0"``, the same ``id`` as the request, and
           exactly one of ``result`` or ``error``.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport, WireMessage


def make_jsonrpc_envelope_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        wire = WireMessage(
            sender_id="contract",
            receiver_id="agent",
            action_label="probe",
            text="probe: contract test",
            metadata={"request_id": "contract-probe"},
        )
        payload = transport.encode_request(wire)
        url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
        assert resp.status_code == 200, (
            f"RPC returned {resp.status_code}, expected 200"
        )
        try:
            body = json.loads(resp.text)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"RPC body is not JSON: {exc}")
        assert body.get("jsonrpc") == "2.0", "missing/invalid jsonrpc field"
        assert "id" in body, "RPC response missing id"
        assert "result" in body or "error" in body, (
            "RPC response must carry either result or error"
        )

    return Contract(
        id="transport.jsonrpc_envelope",
        description=(
            "POST to RPC endpoint returns a well-formed JSON-RPC 2.0 envelope."
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
