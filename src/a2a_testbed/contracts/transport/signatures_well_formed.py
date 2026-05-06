# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: AgentCard signatures (when present) are well-formed JWS.

  Spec:    A2A 1.0 §4.4 (AgentCard.signatures), §13 (Authentication)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  ``signatures`` is an OPTIONAL array of detached JWS
           signatures over the canonical AgentCard form. Each entry
           follows RFC 7515 JSON Serialization shape: ``protected``
           (base64url-encoded protected header) and ``signature``
           (base64url-encoded signature). The ``header`` (unprotected)
           object is optional but, when present, MUST be an object.
           Clients verify provenance by re-canonicalizing the card
           and matching the signature; a malformed entry can't be
           verified and silently masks tampering.
"""

from __future__ import annotations

import json
import re

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


# Base64url alphabet (RFC 4648 §5): A-Z, a-z, 0-9, -, _, with optional
# trailing '=' padding. JWS entries strip padding, so make it optional.
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+=*$")


def make_signatures_well_formed_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
        assert resp.status_code == 200
        body = json.loads(resp.text)
        signatures = body.get("signatures")
        if signatures is None:
            return  # OPTIONAL; nothing to validate
        assert isinstance(signatures, list), (
            f"signatures MUST be an array when present; got {type(signatures).__name__}"
        )
        offenders: list[str] = []
        for i, sig in enumerate(signatures):
            if not isinstance(sig, dict):
                offenders.append(f"signatures[{i}] is not an object")
                continue
            protected = sig.get("protected")
            signature = sig.get("signature")
            if not (isinstance(protected, str) and _BASE64URL.match(protected)):
                offenders.append(
                    f"signatures[{i}].protected MUST be a base64url string"
                )
            if not (isinstance(signature, str) and _BASE64URL.match(signature)):
                offenders.append(
                    f"signatures[{i}].signature MUST be a base64url string"
                )
            header = sig.get("header")
            if header is not None and not isinstance(header, dict):
                offenders.append(
                    f"signatures[{i}].header MUST be an object when present"
                )
        assert not offenders, "; ".join(offenders)

    return Contract(
        id="transport.signatures_well_formed",
        description=(
            "AgentCard.signatures (when present) are well-formed JWS entries (§4.4 + §13)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
