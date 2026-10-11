# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""MCP delegation client.

An extension protocol can ship an MCP server whose tools check its
semantics. The testbed never imports a protocol: it spawns that server
over stdio and calls tools on it. Which server serves which extension
URI is configuration (``MCPDelegate`` entries loaded from a delegates
file, a scenario's ``mcp_delegates:`` block or ``--mcp-delegates``), so
a new protocol needs a config entry, not a testbed change.

Two callers:

- ``delegate_validate_card`` calls each delegate's optional
  ``card_validator_tool`` with an AgentCard extension's ``params``.
- ``call_extension_tool`` / ``check_extension_expectation`` call any
  tool with arbitrary arguments, for scenario ``expect.extensions``.

Tools are expected to answer ``{"ok": true|false, ...}`` as JSON text.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union

import yaml
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
    """One extension's MCP server.

    ``command`` is the argv that starts the server (stdio transport);
    a ``{python}`` element is replaced by the running interpreter.
    ``card_validator_tool`` is the tool ``delegate_validate_card`` calls
    with an AgentCard extension's ``params`` (under ``card_arg_name``);
    leave it unset for a server that is only used for scenario checks.
    ``env`` adds environment variables for the server process.
    """

    extension_uri: str
    command: tuple[str, ...]
    card_validator_tool: Optional[str] = None
    card_arg_name: str = "ref"
    env: Mapping[str, str] = field(default_factory=dict)

    # Old attribute names, readable for code that inspected delegates.
    # (Construct with card_validator_tool= / card_arg_name=.)
    @property
    def payload_validator_tool(self) -> Optional[str]:
        return self.card_validator_tool

    @property
    def payload_arg_name(self) -> str:
        return self.card_arg_name

    def argv(self) -> list[str]:
        return [sys.executable if part == "{python}" else part for part in self.command]


class MCPDelegateRegistry:
    """Mutable registry of (URI → MCPDelegate)."""

    def __init__(self, delegates: Iterable[MCPDelegate] = ()) -> None:
        self._by_uri: dict[str, MCPDelegate] = {}
        for delegate in delegates:
            self.register(delegate)

    def register(self, delegate: MCPDelegate) -> None:
        self._by_uri[delegate.extension_uri] = delegate

    def get(self, extension_uri: str) -> Optional[MCPDelegate]:
        return self._by_uri.get(extension_uri)

    def items(self) -> list[MCPDelegate]:
        return list(self._by_uri.values())

    def merged(self, other: "MCPDelegateRegistry") -> "MCPDelegateRegistry":
        """A new registry: these entries, overridden by ``other``'s."""
        return MCPDelegateRegistry([*self.items(), *other.items()])

    def __len__(self) -> int:
        return len(self._by_uri)


class DelegateConfigError(ValueError):
    """A delegates file or block is malformed."""


def _resolve_command(command: list[str], base_dir: Optional[Path]) -> list[str]:
    """Resolve relative file paths in ``command`` against ``base_dir`` (the
    directory of the file that declared the delegate), so a delegates
    file works from any working directory. Bare program names and
    options are left alone; only elements that exist relative to
    ``base_dir`` change."""
    if base_dir is None:
        return command
    out = []
    for part in command:
        if part.startswith("-") or part == "{python}" or os.path.isabs(part) or "/" not in part:
            out.append(part)
            continue
        candidate = (base_dir / part).resolve()
        out.append(str(candidate) if candidate.exists() else part)
    return out


def parse_delegates(
    data: Any, *, source: str = "mcp_delegates", base_dir: Optional[Path] = None
) -> MCPDelegateRegistry:
    """Build a registry from config data.

    Accepts ``{"delegates": [...]}`` (a delegates file) or a bare list of
    entries (a scenario's inline block). Each entry::

        uri: https://example.org/my-extension/v1      # required
        command: [my-extension-mcp]                    # required (list or string)
        card_validator_tool: validate_service_ref      # optional
        card_arg_name: ref                             # optional, default "ref"
        env: {LOG_LEVEL: warning}                      # optional
    """
    entries = data.get("delegates") if isinstance(data, Mapping) else data
    if entries is None:
        return MCPDelegateRegistry()
    if not isinstance(entries, list):
        raise DelegateConfigError(f"{source}: expected a list of delegates")
    registry = MCPDelegateRegistry()
    for i, entry in enumerate(entries):
        where = f"{source}[{i}]"
        if not isinstance(entry, Mapping):
            raise DelegateConfigError(f"{where}: each delegate must be a mapping")
        unknown = set(entry) - {"uri", "command", "card_validator_tool", "card_arg_name", "env"}
        if unknown:
            raise DelegateConfigError(f"{where}: unknown field(s) {sorted(unknown)}")
        uri = entry.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            raise DelegateConfigError(f"{where}: 'uri' is required")
        command = entry.get("command")
        if isinstance(command, str):
            command = shlex.split(command)
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise DelegateConfigError(f"{where} ({uri}): 'command' must be a non-empty list")
        tool = entry.get("card_validator_tool")
        if tool is not None and not isinstance(tool, str):
            raise DelegateConfigError(f"{where} ({uri}): 'card_validator_tool' must be a string")
        env = entry.get("env") or {}
        if not isinstance(env, Mapping):
            raise DelegateConfigError(f"{where} ({uri}): 'env' must be a mapping")
        if registry.get(uri.strip()) is not None:
            raise DelegateConfigError(f"{where}: {uri} is configured twice")
        registry.register(
            MCPDelegate(
                extension_uri=uri.strip(),
                command=tuple(_resolve_command(list(command), base_dir)),
                card_validator_tool=tool,
                card_arg_name=str(entry.get("card_arg_name") or "ref"),
                env={str(k): str(v) for k, v in env.items()},
            )
        )
    return registry


def load_delegates(path: Union[str, Path]) -> MCPDelegateRegistry:
    """Load a delegates file (YAML or JSON)."""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DelegateConfigError(f"cannot read MCP delegates file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise DelegateConfigError(f"{path}: invalid YAML: {exc}") from exc
    return parse_delegates(data, source=str(path), base_dir=path.resolve().parent)


class _MalformedToolResponse(Exception):
    """Raised when an MCP tool returns output that isn't ``{"ok": ..., ...}``.

    Distinct from an MCP transport error and from a validator
    rejection. Lets the caller surface SERVER_UNAVAILABLE rather than
    misclassifying a server crash as a validation failure.
    """

    def __init__(self, raw_text: str) -> None:
        super().__init__(
            "MCP tool returned non-JSON or unexpected payload: " + (raw_text[:200] or "(empty)")
        )
        self.raw_text = raw_text


class ToolOutcome(str, Enum):
    """What one MCP tool call said.

    - ``ok``        — the tool answered ``{"ok": true, ...}``.
    - ``violation`` — the tool answered ``{"ok": false, ...}``: it ran
      the check and the check failed.
    - ``rejected``  — the server flagged the call as an error
      (``isError``): typically invalid arguments, or a protocol that
      signals a failed check by raising.
    """

    OK = "ok"
    VIOLATION = "violation"
    REJECTED = "rejected"


class ToolNotFound(Exception):
    """The delegate's server does not offer the requested tool."""

    def __init__(self, tool: str, available: list[str]) -> None:
        listed = ", ".join(sorted(available)) or "(none)"
        super().__init__(f"tool {tool!r} not offered by the server; it offers: {listed}")
        self.tool = tool
        self.available = available


def _server_params(delegate: MCPDelegate) -> StdioServerParameters:
    argv = delegate.argv()
    if shutil.which(argv[0]) is None and not os.path.exists(argv[0]):
        raise FileNotFoundError(2, "command not found", argv[0])
    env = {**os.environ, **delegate.env} if delegate.env else None
    return StdioServerParameters(command=argv[0], args=argv[1:], env=env)


def _first_text(result: Any) -> str:
    for content in getattr(result, "content", None) or []:
        text = getattr(content, "text", None)
        if text is not None:
            return text
    return ""


def _is_error(result: Any) -> bool:
    # SDK 1.x names it isError; SDK 2.x models expose is_error.
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


# Upper bound on one tool call, server start-up included.
DEFAULT_TOOL_TIMEOUT_S = 60.0


def describe_error(exc: BaseException) -> str:
    """One line for an MCP failure, unwrapping task-group exception groups."""
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(describe_error(e) for e in exc.exceptions)
    if isinstance(exc, TimeoutError):
        return "no answer within the time limit"
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


async def call_extension_tool(
    delegate: MCPDelegate,
    tool: str,
    arguments: Mapping[str, Any],
    *,
    check_tool_exists: bool = True,
    timeout: Optional[float] = DEFAULT_TOOL_TIMEOUT_S,
) -> tuple[ToolOutcome, str]:
    return await asyncio.wait_for(
        _call_extension_tool(delegate, tool, arguments, check_tool_exists=check_tool_exists),
        timeout=timeout,
    )


async def _call_extension_tool(
    delegate: MCPDelegate,
    tool: str,
    arguments: Mapping[str, Any],
    *,
    check_tool_exists: bool,
) -> tuple[ToolOutcome, str]:
    """Start the delegate's server, call ``tool`` and classify the answer.

    Raises ``FileNotFoundError`` when the server command is missing,
    ``ToolNotFound`` when the server does not list the tool, and
    ``_MalformedToolResponse`` when a non-error answer is not a JSON
    object with an ``ok`` key. Transport failures propagate.
    """
    # Decide inside the session, raise after it closes: an exception
    # raised inside the stdio client's task group would surface wrapped
    # in an ExceptionGroup.
    names: list[str] = []
    result: Any = None
    async with stdio_client(_server_params(delegate)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if check_tool_exists:
                listed = await session.list_tools()
                names = [t.name for t in getattr(listed, "tools", None) or []]
            if not check_tool_exists or tool in names:
                result = await session.call_tool(tool, dict(arguments))
    if result is None:
        raise ToolNotFound(tool, names)
    return _classify(result)


def _classify(result: Any) -> tuple[ToolOutcome, str]:
    text = _first_text(result)
    if _is_error(result):
        return ToolOutcome.REJECTED, text
    if not hasattr(result, "content"):
        # SDK 2.x can answer with an input-required or other non-tool
        # result; nothing we can judge.
        raise _MalformedToolResponse(f"{type(result).__name__}: {text}")
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        raise _MalformedToolResponse(text)
    if not isinstance(parsed, dict) or "ok" not in parsed:
        raise _MalformedToolResponse(text)
    if parsed["ok"] is True:
        return ToolOutcome.OK, text
    if parsed["ok"] is False:
        return ToolOutcome.VIOLATION, text
    # null / "true" / 1: not a verdict, and must not satisfy "violation".
    raise _MalformedToolResponse(text)


async def _call_mcp_tool(delegate: MCPDelegate, payload: dict[str, Any]) -> tuple[bool, str]:
    """Card validation: call ``card_validator_tool`` with the payload.

    A server-flagged error counts as a failed validation (some
    protocols raise on an invalid payload), as before.
    """
    assert delegate.card_validator_tool is not None
    outcome, text = await call_extension_tool(
        delegate,
        delegate.card_validator_tool,
        {delegate.card_arg_name: payload},
        check_tool_exists=False,
    )
    return outcome is ToolOutcome.OK, text


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
        if delegate is None or not delegate.card_validator_tool:
            continue  # silent — manifest layer already handled it

        payload = _extract_payload(entry)
        if payload is None:
            findings.append(
                MCPFinding(
                    kind=MCPFindingKind.FAILED,
                    extension_uri=uri,
                    detail="extension declared but no payload to validate",
                    tool_name=delegate.card_validator_tool,
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
                        f"MCP server command not found: {' '.join(delegate.argv())} "
                        f"({exc.strerror})"
                    ),
                    tool_name=delegate.card_validator_tool,
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
                    tool_name=delegate.card_validator_tool,
                    raw_response=exc.raw_text,
                )
            )
            continue
        except Exception as exc:
            findings.append(
                MCPFinding(
                    kind=MCPFindingKind.SERVER_UNAVAILABLE,
                    extension_uri=uri,
                    detail=f"MCP delegation failed: {describe_error(exc)}",
                    tool_name=delegate.card_validator_tool,
                )
            )
            continue

        findings.append(
            MCPFinding(
                kind=MCPFindingKind.PASSED if ok else MCPFindingKind.FAILED,
                extension_uri=uri,
                detail=f"{delegate.card_validator_tool} returned ok={ok}",
                tool_name=delegate.card_validator_tool,
                raw_response=raw,
            )
        )

    return findings
