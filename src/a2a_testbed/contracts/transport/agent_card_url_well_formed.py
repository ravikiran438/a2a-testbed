# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: AgentCard URLs are syntactically well-formed.

  Spec:    A2A 1.0 §4.4.1 (AgentCard schema)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Every URL on the AgentCard — top-level ``url``,
           ``documentationUrl``, ``iconUrl``, ``provider.url``, and
           each ``supportedInterfaces[*].url`` — MUST be a parseable
           absolute URL with a scheme and a host. Relative paths or
           string fragments are not interoperable: the client receives
           a card and dials the URL verbatim.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def _is_absolute_url(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return bool(parsed.scheme) and bool(parsed.netloc)


def make_agent_card_url_well_formed_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        offenders: list[str] = []

        # Top-level URL fields — only flagged when present.
        for field in ("url", "documentationUrl", "iconUrl"):
            if field in body and body[field] is not None:
                if not _is_absolute_url(body[field]):
                    offenders.append(
                        f"{field}={body[field]!r} is not an absolute URL"
                    )

        provider = body.get("provider") or {}
        if isinstance(provider, dict) and provider.get("url") is not None:
            if not _is_absolute_url(provider["url"]):
                offenders.append(
                    f"provider.url={provider['url']!r} is not an absolute URL"
                )

        for i, entry in enumerate(body.get("supportedInterfaces") or []):
            if not isinstance(entry, dict):
                continue
            if entry.get("url") is None:
                continue
            if not _is_absolute_url(entry["url"]):
                offenders.append(
                    f"supportedInterfaces[{i}].url={entry['url']!r} "
                    "is not an absolute URL"
                )

        assert not offenders, "; ".join(offenders)

    return Contract(
        id="transport.agent_card_url_well_formed",
        description=(
            "AgentCard URLs are absolute parseable URLs (§4.4.1)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
