# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: JSON-RPC response carries exactly one of result or error.

  Spec:    JSON-RPC 2.0 §5 (Response Object)
  Source:  https://www.jsonrpc.org/specification#response_object
  Clause:  "Either the result member or error member MUST be included,
           but both members MUST NOT be included."
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport, WireMessage


def make_jsonrpc_result_xor_error_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        wire = WireMessage(
            sender_id="contract",
            receiver_id="agent",
            action_label="probe",
            text="xor probe",
            metadata={"request_id": "contract-xor-probe"},
        )
        payload = transport.encode_request(wire)
        url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
        body = json.loads(resp.text)
        has_result = "result" in body
        has_error = "error" in body
        assert has_result or has_error, (
            "response has neither 'result' nor 'error'; spec §5 requires one"
        )
        assert not (has_result and has_error), (
            "response has BOTH 'result' and 'error'; spec §5 forbids this"
        )

    return Contract(
        id="transport.jsonrpc_result_xor_error",
        description=(
            "JSON-RPC response carries exactly one of result/error per §5"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
