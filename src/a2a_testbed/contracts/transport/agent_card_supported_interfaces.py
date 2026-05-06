# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: each AgentCard interface declares URL and protocol binding.

  Spec:    A2A 1.0 §8.3.1 (Interface Declaration), §4.4.1 (AgentCard schema)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Each ``supportedInterfaces`` entry MUST declare a ``url``
           and a ``protocolBinding`` (e.g., ``"JSONRPC"``, ``"GRPC"``,
           ``"HTTP_JSON"``). Optional fields include ``protocolVersion``
           and ``tenant``.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


_KNOWN_BINDINGS = {"JSONRPC", "GRPC", "HTTP_JSON"}


def make_agent_card_supported_interfaces_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        interfaces = body.get("supportedInterfaces") or []
        assert len(interfaces) >= 1, (
            "supportedInterfaces MUST have at least one entry per §4.4.1"
        )

        for i, iface in enumerate(interfaces):
            assert isinstance(iface, dict), (
                f"supportedInterfaces[{i}] MUST be a JSON object"
            )
            assert iface.get("url"), (
                f"supportedInterfaces[{i}].url is REQUIRED per §8.3.1"
            )
            binding = iface.get("protocolBinding")
            assert binding, (
                f"supportedInterfaces[{i}].protocolBinding is REQUIRED per §8.3.1"
            )
            # Allow unknown bindings for forward-compatibility, but warn
            # against malformed values like 'http' or 'grpc' (lowercase).
            assert isinstance(binding, str) and binding == binding.upper(), (
                f"supportedInterfaces[{i}].protocolBinding={binding!r} "
                f"should be uppercase (recognized: {sorted(_KNOWN_BINDINGS)})"
            )

    return Contract(
        id="transport.agent_card_supported_interfaces",
        description=(
            "Every supportedInterfaces entry has url + protocolBinding "
            "per A2A 1.0 §8.3.1"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
