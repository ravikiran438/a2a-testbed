# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""MCP delegation: deeper semantic validation than static manifest checks.

A protocol's published manifest constrains the **shape** of a card's
``capabilities.extensions[].params`` payload via JSON Schema. That's
fast and offline-friendly, but it can't enforce semantic invariants
that only the protocol implementation knows (cross-field constraints,
wire-format rules, lookup-table consistency).

For those, the protocol ships its own MCP server with validator tools
(e.g. ``validate_phala_service_ref``). The testbed delegates: it
spawns the protocol's MCP server over stdio, calls the relevant
validator tool with the payload, and surfaces the structured result
as a finding.

Both layers compose: manifest validation runs first (cheap, offline);
MCP delegation is the second-tier deeper check that requires the
protocol's installed MCP server.
"""

from a2a_testbed.extensions.mcp_delegation import (
    DEFAULT_MCP_DELEGATES,
    MCPDelegate,
    MCPDelegateRegistry,
    MCPFinding,
    MCPFindingKind,
    delegate_validate_card,
    make_default_registry,
)


__all__ = [
    "DEFAULT_MCP_DELEGATES",
    "MCPDelegate",
    "MCPDelegateRegistry",
    "MCPFinding",
    "MCPFindingKind",
    "delegate_validate_card",
    "make_default_registry",
]
