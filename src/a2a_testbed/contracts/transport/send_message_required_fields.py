# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: ``SendMessage`` rejects malformed messages.

Spec:    A2A 1.0 §3.1.1 (Send Message)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  Clients MUST provide ``message`` with ``role``,
         ``messageId``, and at least one part. Servers MUST reject
         messages missing these REQUIRED fields with a JSON-RPC
         error (typically ``-32602`` invalid params).
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import AgentProbe
from a2a_testbed.transport import Transport


def make_send_message_required_fields_contract(transport: Transport, agent_url: str) -> Contract:
    """Probe the agent with a malformed SendMessage (missing parts)
    and verify it returns an error response.
    """

    async def verify() -> None:
        # Construct a deliberately malformed request: message has no parts
        probe = await AgentProbe.create(transport, agent_url)
        message = probe.message("unused", message_id="m-1")
        del message["parts"]  # REQUIRED field deliberately omitted
        bad_payload = {
            "jsonrpc": "2.0",
            "id": "contract-bad-message",
            "method": probe.method("send"),
            "params": {"message": message},
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(probe.rpc_url, json=bad_payload, headers=probe.headers())
        assert resp.status_code in (200, 400), (
            f"unexpected HTTP status {resp.status_code} for malformed message"
        )
        body = json.loads(resp.text) if resp.text else {}
        # The spec mandates rejection. Either an explicit error in the
        # JSON-RPC envelope or a 4xx HTTP status is acceptable; what
        # MUST NOT happen is a successful "result" response.
        assert "result" not in body or "error" in body, (
            f"malformed {probe.method('send')} produced a result response; spec §3.1.1 "
            "requires REQUIRED fields to be enforced"
        )

    return Contract(
        id="transport.send_message_required_fields",
        description=("SendMessage rejects messages missing REQUIRED fields per A2A 1.0 §3.1.1"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
