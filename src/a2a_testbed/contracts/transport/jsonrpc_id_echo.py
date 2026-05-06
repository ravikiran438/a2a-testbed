# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: JSON-RPC response echoes the request's id.

  Spec:    A2A 1.0 §9.3 + JSON-RPC 2.0 §5
  Source:  docs/specification.md (LF AI & Data A2A repo) + jsonrpc.org
  Clause:  Every JSON-RPC response MUST carry the same ``id`` value as
           the request that produced it. Per JSON-RPC §5: "The Server
           MUST reply with the same value of id, member."
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport, WireMessage


def make_jsonrpc_id_echo_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        request_id = "contract-echo-id-test-12345"
        wire = WireMessage(
            sender_id="contract",
            receiver_id="agent",
            action_label="probe",
            text="probe id echo",
            metadata={"request_id": request_id},
        )
        payload = transport.encode_request(wire)
        url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
        assert resp.status_code == 200
        body = json.loads(resp.text)
        assert body.get("id") == request_id, (
            f"response id={body.get('id')!r} does not match request id "
            f"={request_id!r}; JSON-RPC 2.0 §5 mandates exact echo"
        )

    return Contract(
        id="transport.jsonrpc_id_echo",
        description="JSON-RPC response echoes request id per JSON-RPC 2.0 §5",
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
