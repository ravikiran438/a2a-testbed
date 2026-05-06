# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: A2A-specific JSON-RPC error codes are in the
reserved range -32001..-32099.

  Spec:    A2A 1.0 §9.5 (Error Code Mapping for JSON-RPC binding)
           plus JSON-RPC 2.0 §5.1 (Error object)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  A2A error types map to JSON-RPC error codes in the range
           ``-32001`` to ``-32099``. Standard JSON-RPC reserved codes
           (-32700, -32600, -32601, -32602, -32603) keep their JSON-RPC
           meanings.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


_VALID_RESERVED = {
    -32700,  # parse error
    -32600,  # invalid request
    -32601,  # method not found
    -32602,  # invalid params
    -32603,  # internal error
}


def make_jsonrpc_error_code_range_contract(
    transport: Transport, agent_url: str
) -> Contract:
    """Probe the agent with a method it doesn't implement and verify
    the error code is either a JSON-RPC standard code or in the A2A
    reserved range.
    """

    async def verify() -> None:
        bogus = {
            "jsonrpc": "2.0",
            "id": "contract-probe",
            "method": "method/that/definitely/does/not/exist",
            "params": {},
        }
        url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=bogus)
        assert resp.status_code == 200, (
            f"RPC returned {resp.status_code} for unknown method; expected 200"
        )
        body = json.loads(resp.text)
        assert "error" in body, (
            "unknown method MUST produce a JSON-RPC error response"
        )
        code = body["error"].get("code")
        assert isinstance(code, int), "error.code MUST be an integer"
        in_a2a_range = -32099 <= code <= -32001
        in_jsonrpc_reserved = code in _VALID_RESERVED
        assert in_a2a_range or in_jsonrpc_reserved, (
            f"error.code={code} is not in A2A reserved range "
            f"(-32099..-32001) and not a JSON-RPC standard reserved code "
            f"({sorted(_VALID_RESERVED)})"
        )

    return Contract(
        id="transport.jsonrpc_error_code_range",
        description=(
            "Error codes from the agent are in the JSON-RPC reserved set "
            "or the A2A range (-32099..-32001) per A2A 1.0 §9.5"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
