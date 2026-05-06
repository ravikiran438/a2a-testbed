# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: extension URIs are absolute HTTPS URLs.

  Spec:    A2A 1.0 §4.4.4 (Extensions)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Each ``capabilities.extensions[*].uri`` identifies the
           extension's published manifest. The convention requires a
           dereferenceable URL — clients fetch ``<uri>/manifest.json``
           to discover the schema. Relative paths or non-HTTP schemes
           prevent that lookup, so each URI MUST be an absolute
           ``http://`` or ``https://`` URL.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


def make_extensions_uri_absolute_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        extensions = (body.get("capabilities") or {}).get("extensions") or []
        if not isinstance(extensions, list):
            return  # caught by the capabilities-shape contract
        offenders: list[str] = []
        for i, ext in enumerate(extensions):
            uri = ext.get("uri") if isinstance(ext, dict) else None
            if not isinstance(uri, str) or not uri:
                continue  # caught elsewhere
            parsed = urlparse(uri)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                offenders.append(
                    f"extensions[{i}].uri {uri!r} is not an absolute http(s) URL"
                )
        assert not offenders, "; ".join(offenders)

    return Contract(
        id="transport.extensions_uri_absolute",
        description=(
            "capabilities.extensions[*].uri values are absolute HTTP(S) URLs (§4.4.4)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
