# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: the agent serves the protocol version its card advertises.

Spec:    A2A 1.0 §3.6.2 (Versioning — Server Responsibilities), §9.1, §8.3.1
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  An AgentCard interface declares ``protocolBinding`` and
         ``protocolVersion``; agents MUST process requests using the
         semantics of the requested version, and the JSON-RPC
         binding names its methods in PascalCase (``SendMessage``,
         ``GetTask``, …). A card that advertises ``JSONRPC`` /
         ``1.0`` while the endpoint only answers the pre-1.0
         slash-style names (``message/send``) breaks every 1.0
         client at the first call with MethodNotFound — the drift
         reported against this testbed's own reference agent in
         a2aproject/A2A#1826. This contract sends the version's
         canonical send method (with ``A2A-Version`` for 1.0) and,
         on MethodNotFound, checks whether the legacy name works to
         name the mismatch precisely.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    METHOD_NOT_FOUND_CODE,
    AgentProbe,
    call_method,
    error_code,
)
from a2a_testbed.transport import Transport
from a2a_testbed.transport import dialect as d

_VERSION_NOT_SUPPORTED_CODE = -32009


def make_advertised_version_served_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        assert probe.card, "card endpoint did not return a JSON AgentCard"
        envelope = await probe.call("send", probe.send_params("version probe"))
        code = error_code(envelope)
        advertised = probe.dialect.value
        if code == METHOD_NOT_FOUND_CODE:
            other = d.Dialect.V0_3 if probe.dialect is d.Dialect.V1_0 else d.Dialect.V1_0
            alt = await call_method(
                transport,
                agent_url,
                d.method(other, "send"),
                d.send_params(other, d.text_message(other, "version probe")),
                headers=d.request_headers(other),
            )
            if "result" in alt and error_code(alt) is None:
                raise AssertionError(
                    f"AgentCard advertises A2A {advertised} (JSONRPC) but the agent "
                    f"returned MethodNotFound for {probe.method('send')!r} and only "
                    f"answers the A2A {other.value} name {d.method(other, 'send')!r}; "
                    f"either serve the A2A {advertised} method names or advertise "
                    f"protocolVersion {other.value!r} (§3.6.2, §9.1)"
                )
            raise AssertionError(
                f"AgentCard advertises A2A {advertised} (JSONRPC) but the agent "
                f"returned MethodNotFound for {probe.method('send')!r} (§9.1)"
            )
        if code == _VERSION_NOT_SUPPORTED_CODE:
            raise AssertionError(
                f"agent rejected A2A-Version {advertised} with VersionNotSupportedError "
                "although its AgentCard advertises that version (§3.6.2)"
            )
        assert envelope, f"{probe.method('send')} did not return a JSON-RPC envelope"
        return f"agent serves A2A {advertised} as advertised ({probe.method('send')})"

    return Contract(
        id="transport.advertised_version_served",
        description=(
            "Agent answers the JSON-RPC method names of the protocolVersion "
            "its AgentCard advertises (§3.6.2, §9.1)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
