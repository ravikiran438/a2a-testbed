# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: unknown JSON-RPC method returns code -32601.

  Spec:    JSON-RPC 2.0 §5.1 (reserved error codes)
           plus A2A 1.0 §9 (JSON-RPC binding adopts JSON-RPC error semantics)
  Source:  https://www.jsonrpc.org/specification#error_object
           docs/specification.md §9 (LF AI & Data A2A repo)
  Clause:  If the requested method does not exist or is not available,
           the server MUST return a JSON-RPC error with
           ``error.code = -32601``.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def make_method_not_found_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        bogus = {
            "jsonrpc": "2.0",
            "id": "contract-probe-mnf",
            "method": "no/such/method/exists/anywhere",
            "params": {},
        }
        url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=bogus)
        body = json.loads(resp.text)
        assert "error" in body, "unknown method MUST produce an error response"
        assert body["error"].get("code") == -32601, (
            f"expected error.code = -32601 (method not found); got "
            f"{body['error'].get('code')}"
        )

    return Contract(
        id="transport.method_not_found",
        description=(
            "Unknown JSON-RPC method returns -32601 per JSON-RPC 2.0 §5.1"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
