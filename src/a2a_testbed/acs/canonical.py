# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Shape testbed wire exchanges into ACS canonical policy input.

This is the seam that makes ACS usable at the A2A inter-agent layer.
The testbed already taps every request/response pair as a
``WireExchange`` (see ``core/observer.py``); this module turns one of
those into the snapshot an ACS policy evaluates, and resolves the
``policy_target`` / ``tool_name_from`` paths declared in a manifest.

Wire-seam → intervention-point mapping
--------------------------------------
- ``input``           : the inbound JSON-RPC request before the receiver acts
- ``output``          : the response before it leaves the receiver
- ``pre_tool_call``   : an A2A handoff, with the *remote agent as the tool*
                        (tool name = receiver id, args = request params)
- ``post_tool_call``  : the handoff result re-entering the caller's context
- ``agent_startup``   : a synthetic snapshot built from an AgentCard
- ``agent_shutdown``  : a synthetic end-of-session snapshot

Version-agnostic by construction: snapshots are derived from the wire
bodies as-is and never branch on the A2A protocol version. The same
manifest yields the same verdict whether the handoff used A2A 1.0, 0.3,
or a non-A2A transport.
"""

from __future__ import annotations

from typing import Any, Optional

from a2a_testbed.acs.types import CanonicalInput, InterventionPoint, ToolDecl
from a2a_testbed.core.observer import WireExchange


# Sentinel distinguishing "path resolved to None" from "path absent".
_MISSING = object()


def resolve_path(data: Any, path: str) -> Any:
    """Resolve a small JSONPath-lite ``$.a.b.c`` (or ``a.b.c``) path.

    Supports dotted keys and integer list indices. Returns ``_MISSING``
    when any segment is absent so callers can distinguish absence from a
    present ``None`` value. Deliberately tiny — no third-party JSONPath
    dependency, no expression evaluation.
    """
    if path in ("", "$", "$."):
        return data
    cleaned = path[2:] if path.startswith("$.") else path
    cleaned = cleaned.lstrip("$.")
    cur = data
    for seg in cleaned.split("."):
        if seg == "":
            continue
        if isinstance(cur, dict):
            if seg not in cur:
                return _MISSING
            cur = cur[seg]
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(seg)]
            except (ValueError, IndexError):
                return _MISSING
        else:
            return _MISSING
    return cur


def path_present(value: Any) -> bool:
    """True when ``resolve_path`` found a value (even a falsy one)."""
    return value is not _MISSING


def snapshot_for(
    point: InterventionPoint,
    exchange: WireExchange,
    *,
    tools: Optional[dict[str, ToolDecl]] = None,
) -> dict[str, Any]:
    """Build the host snapshot for ``point`` from one wire exchange.

    The snapshot is the broader context an ACS policy may read. We keep
    the raw wire bodies available under ``request`` / ``response`` and
    add intervention-point-specific projections so manifests can target
    a stable path regardless of transport quirks.
    """
    req = exchange.request_body or {}
    resp = exchange.response_body or {}
    params = req.get("params", {}) if isinstance(req, dict) else {}

    snap: dict[str, Any] = {
        "receiver": exchange.receiver_id,
        "request": req,
        "response": resp,
        "extras": dict(exchange.extras),
    }

    if point == InterventionPoint.INPUT:
        snap["input"] = {"method": req.get("method"), "params": params}
    elif point == InterventionPoint.OUTPUT:
        snap["output"] = resp.get("result", resp)
    elif point in (InterventionPoint.PRE_TOOL_CALL, InterventionPoint.POST_TOOL_CALL):
        # A2A-handoff-as-tool: the remote agent is the tool.
        tool_call = {
            "name": exchange.receiver_id,
            "method": req.get("method"),
            "args": params,
        }
        if point == InterventionPoint.POST_TOOL_CALL:
            tool_call["result"] = resp.get("result", resp)
        snap["tool_call"] = tool_call

    return snap


def tool_metadata(
    name: Optional[str], tools: Optional[dict[str, ToolDecl]]
) -> Optional[dict[str, Any]]:
    """Project a declared tool's metadata into the canonical ``tool`` block."""
    if not name or not tools:
        return None
    decl = tools.get(name)
    if decl is None:
        return None
    return {
        "name": decl.id,
        "clearance": decl.clearance,
        "security_labels": list(decl.security_labels),
    }


def build_canonical_input(
    point: InterventionPoint,
    snapshot: dict[str, Any],
    *,
    policy_target_path: str = "$",
    policy_target_kind: str = "snapshot",
    tool_name_from: Optional[str] = None,
    tools: Optional[dict[str, ToolDecl]] = None,
    annotations: Optional[dict[str, Any]] = None,
) -> CanonicalInput:
    """Assemble the ACS canonical input from a snapshot + manifest paths."""
    raw_target = resolve_path(snapshot, policy_target_path)
    target_value = None if raw_target is _MISSING else raw_target

    tool_name = None
    if tool_name_from:
        resolved = resolve_path(snapshot, tool_name_from)
        if resolved is not _MISSING:
            tool_name = resolved

    return CanonicalInput(
        intervention_point=point,
        policy_target={
            "kind": policy_target_kind,
            "path": policy_target_path,
            "value": target_value,
        },
        snapshot=snapshot,
        annotations=dict(annotations or {}),
        tool=tool_metadata(tool_name, tools),
    )
