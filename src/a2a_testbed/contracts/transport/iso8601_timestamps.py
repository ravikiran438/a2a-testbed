# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: response timestamps are ISO 8601 UTC with 'Z' suffix.

  Spec:    A2A 1.0 §5.6.1 (Timestamps)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Timestamps MUST NOT include timezone offsets other than 'Z'
           (all times are UTC). The on-the-wire form is therefore an
           RFC 3339 / ISO 8601 string ending in 'Z':
           ``2026-04-23T13:54:31Z`` or ``2026-04-23T13:54:31.123Z``.
           Numeric epoch values, naive timestamps, and offset suffixes
           (``+05:30``, ``-08:00``) are non-conformant.
"""

from __future__ import annotations

import json
import re

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport, WireMessage


# Heuristic: anything that starts with YYYY-MM-DDThh:mm we treat as a
# timestamp candidate. Forces a Z suffix (after optional fractional
# seconds). Other strings are ignored — we don't try to flag every
# non-timestamp string.
_TS_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
_TS_VALID = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _walk_strings(node: object) -> list[tuple[str, str]]:
    """Yield (path, value) for every string in a JSON-like tree."""
    out: list[tuple[str, str]] = []

    def visit(n: object, path: str) -> None:
        if isinstance(n, dict):
            for k, v in n.items():
                visit(v, f"{path}.{k}" if path else str(k))
        elif isinstance(n, list):
            for i, v in enumerate(n):
                visit(v, f"{path}[{i}]")
        elif isinstance(n, str):
            out.append((path or "<root>", n))

    visit(node, "")
    return out


def make_iso8601_timestamps_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        # Drive a vanilla send; whatever the agent emits (Message or
        # Task) gets walked for timestamp-looking strings.
        rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
        wire = WireMessage(
            sender_id="contract-prober",
            receiver_id="agent",
            action_label="ping",
            text="iso8601-probe",
            metadata={"request_id": "contract", "message_id": "contract"},
        )
        payload = transport.encode_request(wire)
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                rpc_url, json=payload, headers={"content-type": "application/json"}
            )
        # Even error responses ship JSON-RPC envelopes; we walk the body
        # regardless of status code to catch error.data timestamps.
        try:
            body = json.loads(resp.text)
        except json.JSONDecodeError:
            return  # not JSON; nothing to validate

        offenders: list[str] = []
        for path, value in _walk_strings(body):
            if not _TS_LIKE.match(value):
                continue  # not timestamp-shaped
            if not _TS_VALID.match(value):
                offenders.append(f"{path}={value!r}")

        assert not offenders, (
            f"timestamps MUST be ISO 8601 UTC with 'Z' suffix (§5.6.1); "
            f"non-conformant values: {'; '.join(offenders)}"
        )

    return Contract(
        id="transport.iso8601_timestamps",
        description=(
            "Response timestamps end with 'Z' (UTC) per A2A 1.0 §5.6.1"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
