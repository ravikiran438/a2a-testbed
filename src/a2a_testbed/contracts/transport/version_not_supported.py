# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: an unsupported A2A-Version is rejected.

Spec:    A2A 1.0 §3.6.2 (Versioning — Server Responsibilities), §3.3.2
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  Agents MUST process requests using the semantics of the
         requested ``A2A-Version`` (matching Major.Minor). If the
         version is not supported by the interface, agents MUST
         return a ``VersionNotSupportedError`` (``-32009`` on the
         JSON-RPC binding, §5.4). Silently processing a request for a
         version the agent does not implement hides incompatibilities
         from clients that pinned a newer version. A2A 0.3 predates
         version negotiation, so 0.3 agents are skipped.
"""

from __future__ import annotations

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import AgentProbe, error_code
from a2a_testbed.transport import Transport
from a2a_testbed.transport.dialect import VERSION_HEADER

_EXPECTED_CODE = -32009
_UNSUPPORTED_VERSION = "99.0"


def make_version_not_supported_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        if probe.is_legacy:
            return "skipped — A2A 0.3 agent; version negotiation was introduced in 1.0"
        req = {
            "jsonrpc": "2.0",
            "id": "version-not-supported-probe",
            "method": probe.method("send"),
            "params": probe.send_params("version negotiation probe"),
        }
        headers = {**probe.headers(), VERSION_HEADER: _UNSUPPORTED_VERSION}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(probe.rpc_url, json=req, headers=headers)
        try:
            body = resp.json()
        except ValueError as exc:
            raise AssertionError(
                f"request with A2A-Version {_UNSUPPORTED_VERSION} returned non-JSON "
                f"(status {resp.status_code}); expected a JSON-RPC error envelope"
            ) from exc
        if isinstance(body, dict) and "result" in body and body.get("error") is None:
            raise AssertionError(
                f"agent processed a request for A2A-Version {_UNSUPPORTED_VERSION}; "
                "§3.6.2 requires VersionNotSupportedError (-32009)"
            )
        code = error_code(body)
        if code == _EXPECTED_CODE:
            return None
        message = (
            ((body or {}).get("error") or {}).get("message") if isinstance(body, dict) else None
        )
        return (
            f"agent refused A2A-Version {_UNSUPPORTED_VERSION} (good) but with code "
            f"{code} ({message or '?'}); spec mandates {_EXPECTED_CODE} "
            "(VersionNotSupportedError)"
        )

    return Contract(
        id="transport.version_not_supported",
        description=(
            "Requests for an unsupported A2A-Version return "
            "VersionNotSupportedError -32009 (§3.6.2)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
