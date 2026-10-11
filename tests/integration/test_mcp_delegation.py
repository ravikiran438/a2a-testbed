# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""MCP delegation of AgentCard extension checks.

Delegates come from configuration (here, the shipped example
``examples/mcp-delegates.yaml``); the testbed knows no protocol. The
real-server tests spawn the protocol's MCP server over stdio and run
only when its console script is installed. The negative path: a
malformed payload yields a ``failed`` finding, not a crash.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from a2a_testbed.extensions import (
    DelegateConfigError,
    MCPDelegate,
    MCPDelegateRegistry,
    MCPFindingKind,
    delegate_validate_card,
    load_delegates,
    parse_delegates,
)

EXAMPLE_DELEGATES = Path(__file__).resolve().parents[2] / "examples" / "mcp-delegates.yaml"
PHALA_URI = "https://ravikiran438.github.io/phala-protocol/v1"
ACAP_URI = "https://ravikiran438.github.io/agent-consent-protocol/v1"


def _only(uri: str) -> MCPDelegateRegistry:
    delegate = load_delegates(EXAMPLE_DELEGATES).get(uri)
    assert delegate is not None, uri
    return MCPDelegateRegistry([delegate])


def _installed(uri: str) -> bool:
    delegate = load_delegates(EXAMPLE_DELEGATES).get(uri)
    return delegate is not None and shutil.which(delegate.argv()[0]) is not None


def _phala_card(*, broken: bool = False) -> dict:
    params = {
        "version": "1.0.0",
        "outcome_endpoint": "https://x/o",
        "satisfaction_endpoint": "https://x/s",
        "belief_update_endpoint": "https://x/b",
        "weight_keys": ["k"],
        "learning_rate": 0.05,
        "weight_bounds": {"min": -1.0, "max": 1.0},
    }
    if broken:
        del params["belief_update_endpoint"]
    return {
        "name": "demo",
        "capabilities": {
            "extensions": [
                {
                    "uri": PHALA_URI,
                    "params": params,
                }
            ]
        },
    }


@pytest.mark.skipif(not _installed(PHALA_URI), reason="phala-mcp not installed")
def test_phala_mcp_delegation_passes_for_valid_card():
    findings = asyncio.run(delegate_validate_card(_phala_card(), registry=_only(PHALA_URI)))
    assert len(findings) == 1, [f.detail for f in findings]
    assert findings[0].kind == MCPFindingKind.PASSED, findings[0].detail
    assert findings[0].tool_name == "validate_phala_service_ref"


@pytest.mark.skipif(not _installed(PHALA_URI), reason="phala-mcp not installed")
def test_phala_mcp_delegation_fails_for_broken_card():
    findings = asyncio.run(
        delegate_validate_card(_phala_card(broken=True), registry=_only(PHALA_URI))
    )
    assert len(findings) == 1
    assert findings[0].kind == MCPFindingKind.FAILED


def test_unregistered_uri_is_silently_skipped():
    """Extensions without a configured delegate produce no MCP findings;
    the manifest layer is responsible for those."""
    findings = asyncio.run(delegate_validate_card(_phala_card(), registry=MCPDelegateRegistry()))
    assert findings == []


def test_delegate_without_card_tool_is_skipped_for_card_validation():
    reg = MCPDelegateRegistry([MCPDelegate(PHALA_URI, ("no-such-binary",))])
    assert asyncio.run(delegate_validate_card(_phala_card(), registry=reg)) == []


def test_missing_server_is_reported_unavailable():
    reg = MCPDelegateRegistry(
        [MCPDelegate(PHALA_URI, ("no-such-binary",), card_validator_tool="validate")]
    )
    findings = asyncio.run(delegate_validate_card(_phala_card(), registry=reg))
    assert findings[0].kind == MCPFindingKind.SERVER_UNAVAILABLE


def test_example_config_parses_and_names_card_validators():
    registry = load_delegates(EXAMPLE_DELEGATES)
    assert len(registry) >= 1
    for delegate in registry.items():
        assert delegate.command and delegate.card_validator_tool


@pytest.mark.parametrize(
    "data, match",
    [
        ({"delegates": {"uri": "x"}}, "list"),
        ([{"command": ["x"]}], "uri"),
        ([{"uri": "u", "command": []}], "command"),
        ([{"uri": "u", "command": ["x"], "tool": "t"}], "unknown field"),
        ([{"uri": "u", "command": ["x"]}, {"uri": "u", "command": ["y"]}], "twice"),
    ],
)
def test_malformed_delegate_config_is_rejected(data, match):
    with pytest.raises(DelegateConfigError, match=match):
        parse_delegates(data)


def test_command_string_and_python_placeholder():
    reg = parse_delegates([{"uri": "u", "command": "{python} -m some.server"}])
    assert reg.get("u").argv() == [sys.executable, "-m", "some.server"]


def _acap_card(*, broken: bool = False) -> dict:
    params = {
        "version": "1.0.0",
        "document_uri": "https://callee.example.com/.well-known/usage-policy.json",
        "document_hash": "sha256:" + "a" * 64,
        "effective_date": "2026-04-01T00:00:00Z",
        "acceptance_required": False,
        "natural_language_uri": "https://callee.example.com/terms",
    }
    if broken:
        params["acceptance_required"] = True
        # acceptance_endpoint deliberately omitted — should fail V-3-style coherence.
    return {
        "name": "demo",
        "capabilities": {
            "extensions": [
                {
                    "uri": ACAP_URI,
                    "params": params,
                }
            ]
        },
    }


@pytest.mark.skipif(not _installed(ACAP_URI), reason="acap-mcp not installed")
def test_acap_mcp_delegation_passes_for_valid_card():
    findings = asyncio.run(delegate_validate_card(_acap_card(), registry=_only(ACAP_URI)))
    assert len(findings) == 1, [f.detail for f in findings]
    assert findings[0].kind == MCPFindingKind.PASSED, findings[0].detail


@pytest.mark.skipif(not _installed(ACAP_URI), reason="acap-mcp not installed")
def test_acap_mcp_delegation_fails_when_acceptance_endpoint_missing():
    findings = asyncio.run(
        delegate_validate_card(_acap_card(broken=True), registry=_only(ACAP_URI))
    )
    assert findings[0].kind == MCPFindingKind.FAILED
    assert "acceptance_endpoint" in findings[0].detail.lower() or (
        "acceptance_endpoint" in (findings[0].raw_response or "").lower()
    )


FAKE_SERVER = Path(__file__).resolve().parents[1] / "oracles" / "fake_mcp_server.py"


def _env_value(delegate: MCPDelegate, name: str):
    import json

    from a2a_testbed.extensions import call_extension_tool

    _, raw = asyncio.run(call_extension_tool(delegate, "env", {"name": name}))
    return json.loads(raw)["value"]


def test_server_inherits_the_parent_environment(monkeypatch):
    """Without `env:`, the server still sees the parent's variables (proxy
    settings above all), not the MCP SDK's minimal default set."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("A2A_TESTBED_PROBE", "inherited")
    plain = MCPDelegate("u", ("{python}", str(FAKE_SERVER)))
    assert _env_value(plain, "HTTPS_PROXY") == "http://proxy.example:3128"
    assert _env_value(plain, "A2A_TESTBED_PROBE") == "inherited"


def test_delegate_env_overrides_the_parent(monkeypatch):
    monkeypatch.setenv("A2A_TESTBED_PROBE", "inherited")
    delegate = MCPDelegate(
        "u", ("{python}", str(FAKE_SERVER)), env={"A2A_TESTBED_PROBE": "override"}
    )
    assert _env_value(delegate, "A2A_TESTBED_PROBE") == "override"
