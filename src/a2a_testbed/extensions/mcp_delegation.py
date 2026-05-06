# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""MCP delegation client.

For each registered (extension_uri → MCP server command, validator
tool name) tuple, the delegate spawns the server over stdio, calls the
named tool with the AgentCard's ``params`` payload, and parses the
response. The MCP servers our four protocols ship return JSON of the
form ``{"ok": true|false, ...}``, which we adapt into ``MCPFinding``
records that compose with the manifest validator's findings.

This module owns the moving parts so the testbed does not import
``acap`` / ``phala`` / ``nerve`` / ``pace`` directly: the MCP
subprocess is the integration point.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import httpx  # noqa: F401  (kept for symmetry with manifest validators)
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPFindingKind(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SERVER_UNAVAILABLE = "server_unavailable"
    TOOL_NOT_FOUND = "tool_not_found"
    DELEGATE_NOT_REGISTERED = "delegate_not_registered"


@dataclass(frozen=True)
class MCPFinding:
    kind: MCPFindingKind
    extension_uri: str
    detail: str = ""
    tool_name: Optional[str] = None
    raw_response: Optional[str] = None


@dataclass(frozen=True)
class MCPDelegate:
    """One protocol's MCP delegation entry.

    ``command`` is the argv list for spawning the MCP server; the
    server is expected to speak stdio and conform to the MCP spec.
    ``payload_validator_tool`` names the tool the testbed calls for
    AgentCard payload validation. ``payload_arg_name`` is the
    JSON-RPC argument name the tool expects (most of our tools use
    ``"ref"`` for service-descriptor payloads).
    """

    extension_uri: str
    command: tuple[str, ...]
    payload_validator_tool: str
    payload_arg_name: str = "ref"


class MCPDelegateRegistry:
    """Mutable registry of (URI → MCPDelegate) used by the CLI.

    The default registry seeds entries for the four protocols when
    they are importable on the system; otherwise it is empty and the
    user supplies entries explicitly via configuration.
    """

    def __init__(self) -> None:
        self._by_uri: dict[str, MCPDelegate] = {}

    def register(self, delegate: MCPDelegate) -> None:
        self._by_uri[delegate.extension_uri] = delegate

    def get(self, extension_uri: str) -> Optional[MCPDelegate]:
        return self._by_uri.get(extension_uri)

    def items(self) -> list[MCPDelegate]:
        return list(self._by_uri.values())


# Default MCP delegates for the four reference protocols. Each ships a
# tool that validates the AgentCard payload for its extension URI.
DEFAULT_MCP_DELEGATES: tuple[MCPDelegate, ...] = (
    MCPDelegate(
        extension_uri="https://ravikiran438.github.io/agent-consent-protocol/v1",
        command=(sys.executable, "-m", "acap.mcp_server"),
        payload_validator_tool="validate_usage_policy_ref",
        payload_arg_name="ref",
    ),
    MCPDelegate(
        extension_uri="https://ravikiran438.github.io/phala-protocol/v1",
        command=(sys.executable, "-m", "phala.mcp_server"),
        payload_validator_tool="validate_phala_service_ref",
        payload_arg_name="ref",
    ),
    MCPDelegate(
        extension_uri="https://ravikiran438.github.io/pratyahara-nerve/v1",
        command=(sys.executable, "-m", "nerve.mcp_server"),
        payload_validator_tool="validate_neural_posture_ref",
        payload_arg_name="ref",
    ),
    MCPDelegate(
        extension_uri="https://ravikiran438.github.io/sauvidya-pace/v1",
        command=(sys.executable, "-m", "pace.mcp_server"),
        payload_validator_tool="validate_accessibility_service_ref",
        payload_arg_name="ref",
    ),
)


def make_default_registry() -> MCPDelegateRegistry:
    """Build a registry pre-populated with the four reference delegates."""
    reg = MCPDelegateRegistry()
    for d in DEFAULT_MCP_DELEGATES:
        reg.register(d)
    return reg


class _MalformedToolResponse(Exception):
    """Raised when an MCP tool returns output that isn't ``{"ok": ..., ...}``.

    Distinct from an MCP transport error and from a validator
    rejection. Lets the caller surface SERVER_UNAVAILABLE rather than
    misclassifying a server crash as a validation failure.
    """

    def __init__(self, raw_text: str) -> None:
        super().__init__(
            "MCP tool returned non-JSON or unexpected payload: "
            + (raw_text[:200] or "(empty)")
        )
        self.raw_text = raw_text


async def _call_mcp_tool(
    delegate: MCPDelegate, payload: dict[str, Any]
) -> tuple[bool, str]:
    """Spawn the MCP server, call the validator tool, return (ok, raw_text).

    Raises on transport errors so the caller can surface
    SERVER_UNAVAILABLE rather than silently passing. Raises
    ``_MalformedToolResponse`` when the tool returns output that
    isn't a JSON object with an ``ok`` key — that condition is an
    operational failure (server crashed, returned plain text, etc.),
    NOT a legitimate validation rejection.
    """
    params = StdioServerParameters(
        command=delegate.command[0],
        args=list(delegate.command[1:]),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                delegate.payload_validator_tool,
                {delegate.payload_arg_name: payload},
            )
            text = ""
            if result.content:
                for c in result.content:
                    t = getattr(c, "text", None)
                    if t is not None:
                        text = t
                        break

            # MCP framework sets ``isError=True`` when the tool raised
            # an exception (e.g., Phala's ``_validate_primitive`` raises
            # ``ToolInvocationError`` on validation failure). That is a
            # legitimate validation rejection — surface it as ok=False
            # rather than as a malformed-response server error.
            if getattr(result, "isError", False):
                return False, text

            # Otherwise expect ``{"ok": ..., ...}`` — anything else is a
            # genuine operational failure.
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                raise _MalformedToolResponse(text)
            if not isinstance(parsed, dict) or "ok" not in parsed:
                raise _MalformedToolResponse(text)
            return bool(parsed["ok"]), text


def _extract_payload(entry: dict) -> Optional[dict]:
    if not isinstance(entry, dict):
        return None
    for key in ("params", "payload"):
        candidate = entry.get(key)
        if isinstance(candidate, dict):
            return candidate
    reserved = {"uri", "description", "required"}
    extra = {k: v for k, v in entry.items() if k not in reserved}
    return extra or None


async def delegate_validate_card(
    card: dict[str, Any],
    *,
    registry: MCPDelegateRegistry,
) -> list[MCPFinding]:
    """For each declared extension that has a registered delegate, call its
    MCP validator tool and produce a finding. Extensions without a
    registered delegate are skipped silently (the manifest validator
    has already covered them at the structural layer).
    """
    findings: list[MCPFinding] = []
    capabilities = card.get("capabilities") if isinstance(card, dict) else None
    if not isinstance(capabilities, dict):
        return findings
    extensions = capabilities.get("extensions") or []
    if not isinstance(extensions, list):
        return findings

    for entry in extensions:
        if not isinstance(entry, dict):
            continue
        uri = entry.get("uri")
        if not isinstance(uri, str) or not uri:
            continue

        delegate = registry.get(uri)
        if delegate is None:
            continue  # silent — manifest layer already handled it

        payload = _extract_payload(entry)
        if payload is None:
            findings.append(
                MCPFinding(
                    kind=MCPFindingKind.FAILED,
                    extension_uri=uri,
                    detail="extension declared but no payload to validate",
                    tool_name=delegate.payload_validator_tool,
                )
            )
            continue

        try:
            ok, raw = await _call_mcp_tool(delegate, payload)
        except FileNotFoundError as exc:
            findings.append(
                MCPFinding(
                    kind=MCPFindingKind.SERVER_UNAVAILABLE,
                    extension_uri=uri,
                    detail=(
                        f"MCP server command not found: {' '.join(delegate.command)} "
                        f"({exc.strerror})"
                    ),
                    tool_name=delegate.payload_validator_tool,
                )
            )
            continue
        except _MalformedToolResponse as exc:
            # Server returned non-conforming output: treat as an
            # operational failure (crash, plain-text dump, etc.), NOT
            # as a validation rejection. The caller should investigate
            # the server, not the AgentCard.
            findings.append(
                MCPFinding(
                    kind=MCPFindingKind.SERVER_UNAVAILABLE,
                    extension_uri=uri,
                    detail=str(exc),
                    tool_name=delegate.payload_validator_tool,
                    raw_response=exc.raw_text,
                )
            )
            continue
        except Exception as exc:
            findings.append(
                MCPFinding(
                    kind=MCPFindingKind.SERVER_UNAVAILABLE,
                    extension_uri=uri,
                    detail=f"MCP delegation failed: {type(exc).__name__}: {exc}",
                    tool_name=delegate.payload_validator_tool,
                )
            )
            continue

        findings.append(
            MCPFinding(
                kind=MCPFindingKind.PASSED if ok else MCPFindingKind.FAILED,
                extension_uri=uri,
                detail=f"{delegate.payload_validator_tool} returned ok={ok}",
                tool_name=delegate.payload_validator_tool,
                raw_response=raw,
            )
        )

    return findings
