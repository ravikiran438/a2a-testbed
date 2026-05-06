# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: production interface URLs use encrypted transport.

  Spec:    A2A 1.0 §7.1 (Transport-Level Security)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Production deployments MUST use encrypted communication
           (HTTPS for HTTP-based bindings, TLS for gRPC). For A2A
           bindings JSONRPC and REST this means each
           ``supportedInterfaces[*].url`` starts with ``https://``;
           gRPC bindings declare TLS via the binding's own URL scheme.
           Localhost / 127.0.0.1 / ::1 development URLs are exempt;
           the contract treats them as non-production.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_local(url: str) -> bool:
    """Return True for loopback URLs, which are exempt from the HTTPS rule."""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    return host in _LOCAL_HOSTS


def make_agent_card_https_urls_contract(
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
        if not isinstance(interfaces, list):
            return  # caught by the supported_interfaces shape contract
        offenders: list[str] = []
        for i, entry in enumerate(interfaces):
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            binding = entry.get("protocolBinding") or "?"
            if not isinstance(url, str) or not url:
                continue
            if _is_local(url):
                continue
            scheme = urlparse(url).scheme.lower()
            if binding.upper() == "GRPC":
                # gRPC TLS is declared via the binding's own scheme;
                # don't enforce HTTPS string match.
                continue
            if scheme not in {"https", "wss"}:
                offenders.append(
                    f"supportedInterfaces[{i}] ({binding}) url {url!r} "
                    f"uses {scheme!r}; production MUST use https/wss"
                )
        assert not offenders, "; ".join(offenders)

    return Contract(
        id="transport.agent_card_https_urls",
        description=(
            "Non-loopback supportedInterfaces URLs use HTTPS/WSS per §7.1"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
